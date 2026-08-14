import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from app.alipay_service import (
    activate_subscription as alipay_activate_subscription,
    create_pending_subscription,
    create_subscription_checkout,
    find_pending_subscription,
    reconcile_pending_subscription,
    verify_webhook_signature,
)
from app.amap_cache import SQLiteAmapCache
from app.amap_client import AmapAPIClient
from app.amap_tool import AmapTool
from app.auth_middleware import get_current_user_id, require_current_user_id
from app.database import engine as default_engine, init_db, session_scope
from app.feed_ranking import SORT_RECOMMEND, post_min_distance_meters
from app.generation import GenerationService
from app.image_polish_tasks import ImagePolishTaskService
from app.jimeng_service import get_jimeng_service
from app.models import GenerationLog, GenerationRequest, Post, PostInteraction, SearchLog, Subscription
from app.polished_images import latest_polished_by_original_url, save_polished_image
from app.post_export import build_post_export_zip
from app.rate_limiter import RateLimiter
from app.repositories import PostRepository
from app.route_match import route_groups_payload
from app.schemas import (
    GenerateRequest,
    ImagePolishRequest,
    InteractionRequest,
    LocationSuggestRequest,
    PostExportRequest,
    SubscriptionCreateRequest,
)
from app.search import search_posts
from app.security_headers import SecurityHeadersMiddleware
from app.subscription_service import (
    check_polish_eligibility,
    subscription_status_payload,
)
from app.tags import get_hot_tags

logger = logging.getLogger(__name__)

# In-memory rate limiter (per-worker; sufficient for single-worker preview/production uvicorn).
_rate_limiter = RateLimiter()

# Allowed CORS origins - read from env so preview and production can differ.
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or [
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://localhost:5173",
]

# Maximum query/prompt lengths to prevent DB bloat and abuse.
_MAX_QUERY_LENGTH = 200
_MAX_GENERATE_QUERY_LENGTH = 1000


def create_app(db_engine: Engine = default_engine) -> FastAPI:
    init_db(db_engine)

    app = FastAPI(title="CityCity API")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    repo = PostRepository(db_engine)
    generation_service = GenerationService(db_engine)
    image_polish_service = ImagePolishTaskService(db_engine)
    app.state.db_engine = db_engine
    app.state.image_polish_service = image_polish_service

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/posts")
    def list_posts(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=50),
        user_id: str | None = None,
        sort: str = Query(SORT_RECOMMEND),
        lat: float | None = None,
        lng: float | None = None,
        tag: str | None = None,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        from app.feed_ranking import VALID_SORTS

        safe_sort = sort if sort in VALID_SORTS else SORT_RECOMMEND
        # Prefer JWT user_id for authenticated visitors; fall back to query param
        # for anonymous browsing interactions.
        effective_user_id = auth_user_id or user_id
        result = repo.list_posts(
            page=page,
            page_size=page_size,
            sort=safe_sort,
            user_lat=lat,
            user_lng=lng,
            tag=tag,
        )
        payload = _page_payload(result, effective_user_id, repo, user_lat=lat, user_lng=lng)
        payload["sort"] = safe_sort
        if tag and tag.strip():
            payload["tag"] = tag.strip()
        return payload

    @app.get("/api/search")
    def search(
        request: Request,
        query: str | None = None,
        tag: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=50),
        user_id: str | None = None,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.allow(f"search:{client_ip}", limit=30, window_seconds=60):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        if query and len(query) > _MAX_QUERY_LENGTH:
            raise HTTPException(status_code=400, detail=f"查询词过长（最多{_MAX_QUERY_LENGTH}字符）")
        effective_user_id = auth_user_id or user_id
        result = search_posts(db_engine, query=query, tag=tag, page=page, page_size=page_size)
        normalized_query = (query or "").strip()
        if normalized_query:
            truncated_query = normalized_query[:_MAX_QUERY_LENGTH]
            with session_scope(db_engine) as session:
                session.add(
                    SearchLog(
                        user_id=effective_user_id,
                        query=truncated_query,
                        result_count=result.total,
                    )
                )
        return _page_payload(result, effective_user_id, repo)

    @app.get("/api/tags/hot")
    def hot_tags(limit: int = Query(12, ge=1, le=30)):
        return {"items": get_hot_tags(db_engine, limit=limit)}

    @app.post("/api/locations/suggest")
    async def suggest_locations(
        request: LocationSuggestRequest,
        http_request: Request,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        client_ip = http_request.client.host if http_request.client else "unknown"
        rate_key = f"loc:{auth_user_id or client_ip}"
        if not _rate_limiter.allow(rate_key, limit=20, window_seconds=60):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        if not (request.query and request.query.strip()) and (
            request.lat is None or request.lng is None
        ):
            raise HTTPException(status_code=400, detail="query or coordinates are required")
        if request.query and len(request.query) > 100:
            raise HTTPException(status_code=400, detail="查询词过长")
        cache = SQLiteAmapCache(db_engine)
        amap_tool = AmapTool(AmapAPIClient(cache=cache))
        location = None
        if request.lat is not None and request.lng is not None:
            location = f"{request.lng},{request.lat}"
        items = await amap_tool.suggest_locations(query=request.query, location=location)
        return {"items": items}

    @app.get("/api/posts/{post_id}")
    def get_post(
        post_id: int,
        user_id: str | None = None,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        post = repo.get_post(post_id)
        if post is None or post.status != "published":
            raise HTTPException(status_code=404, detail="post not found")
        effective_user_id = auth_user_id or user_id
        return _post_payload(post, _interaction_for(repo, post.id, effective_user_id))

    @app.post("/api/posts/{post_id}/like")
    def toggle_like(
        post_id: int,
        request: InteractionRequest,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        # Prefer JWT-authenticated user_id; fall back to client-supplied id for
        # anonymous interactions. Prevents impersonation of logged-in users.
        effective_user_id = auth_user_id or request.user_id
        try:
            is_liked, like_count = repo.toggle_like(post_id, effective_user_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="post not found")
        return {"success": True, "is_liked": is_liked, "like_count": like_count}

    @app.post("/api/posts/{post_id}/favorite")
    def toggle_favorite(
        post_id: int,
        request: InteractionRequest,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        effective_user_id = auth_user_id or request.user_id
        try:
            is_favorited, favorite_count = repo.toggle_favorite(post_id, effective_user_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="post not found")
        return {"success": True, "is_favorited": is_favorited, "favorite_count": favorite_count}

    @app.post("/api/posts/{post_id}/export")
    async def export_post(
        post_id: int,
        request: PostExportRequest,
        http_request: Request,
    ):
        client_ip = http_request.client.host if http_request.client else "unknown"
        if not _rate_limiter.allow(f"export:{client_ip}", limit=10, window_seconds=60):
            raise HTTPException(status_code=429, detail="导出过于频繁，请稍后再试")
        from urllib.parse import quote
        from app.post_export import is_safe_image_url

        post = repo.get_post(post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="post not found")
        # Validate all image URLs to prevent SSRF (server-side fetch of
        # internal/cloud-metadata URLs).
        if request.image_urls:
            for url in request.image_urls:
                if not is_safe_image_url(url):
                    raise HTTPException(
                        status_code=400,
                        detail=f"不支持的图片地址: {url[:180]}",
                    )
        zip_bytes, filename = await build_post_export_zip(post, request)
        encoded_filename = quote(filename)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"post-{post_id}.zip\"; filename*=UTF-8''{encoded_filename}"
                )
            },
        )

    @app.post("/api/images/polish")
    async def polish_image(
        request: ImagePolishRequest,
        background_tasks: BackgroundTasks,
        http_request: Request,
        user_id: str = Depends(require_current_user_id),
    ):
        if not _rate_limiter.allow(f"polish:{user_id}", limit=10, window_seconds=300):
            raise HTTPException(status_code=429, detail="润色请求过于频繁，请稍后再试")
        if len(request.prompt) > 1000:
            raise HTTPException(status_code=400, detail="润色提示词过长（最多1000字符）")
        # Cache hits are always free - viewing existing polished images
        # doesn't consume the free quota.
        cached = image_polish_service.find_cached(request)
        if cached:
            return {
                "status": "success",
                "polished_image_url": cached.polished_url,
                "cached": True,
            }

        # Subscription gating: 2 free uses, then require active subscription.
        # Only enforce for NEW polish tasks (not cache hits).
        eligibility = check_polish_eligibility(db_engine, user_id)
        if not eligibility.allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "subscription_required",
                    "message": "免费润色次数已用完，请订阅后继续使用",
                    "free_used": eligibility.free_used,
                    "free_limit": eligibility.free_limit,
                    "has_active_subscription": eligibility.has_active_subscription,
                },
            )

        response = image_polish_service.start(request, user_id=user_id)
        if response.get("status") == "success" or response.get("status") in {"pending", "running"} and response.get(
            "polish_request_id"
        ):
            request_id = response.get("polish_request_id")
            if response.get("status") == "pending" and isinstance(request_id, int):
                jimeng = getattr(app.state, "jimeng_service", None) or get_jimeng_service()
                if not jimeng.is_configured:
                    image_polish_service.mark_failed(request_id, "图片润色服务未配置")
                    raise HTTPException(status_code=503, detail="图片润色服务未配置")
                background_tasks.add_task(image_polish_service.run, request_id, jimeng)
            return response
        raise HTTPException(status_code=500, detail="图片润色任务创建失败")

    @app.get("/api/images/polish/{request_id}")
    def get_polish_status(request_id: int):
        row = image_polish_service.get(request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="polish request not found")
        return image_polish_service.payload(row)

    @app.post("/api/images/polish-sync")
    async def polish_image_sync(
        request: ImagePolishRequest,
        user_id: str = Depends(require_current_user_id),
    ):
        eligibility = check_polish_eligibility(db_engine, user_id)
        if not eligibility.allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "subscription_required",
                    "message": "免费润色次数已用完，请订阅后继续使用",
                    "free_used": eligibility.free_used,
                    "free_limit": eligibility.free_limit,
                    "has_active_subscription": eligibility.has_active_subscription,
                },
            )
        jimeng = getattr(app.state, "jimeng_service", None) or get_jimeng_service()
        if not jimeng.is_configured:
            raise HTTPException(status_code=503, detail="图片润色服务未配置")
        polished_url = await jimeng.polish_image(image_url=request.image_url, prompt=request.prompt)
        if not polished_url:
            raise HTTPException(status_code=502, detail="图片润色失败，请重试")
        save_polished_image(
            db_engine,
            post_id=request.post_id,
            original_url=request.image_url,
            prompt=request.prompt,
            polished_url=polished_url,
            user_id=user_id,
        )
        if not eligibility.has_active_subscription:
            from app.subscription_service import increment_polish_usage
            increment_polish_usage(db_engine, user_id)
        return {"polished_image_url": polished_url}

    @app.get("/api/posts/{post_id}/polished-images")
    def get_polished_images(post_id: int):
        latest = latest_polished_by_original_url(db_engine, post_id)
        return {
            "items": [
                {
                    "original_url": original_url,
                    "polished_url": record.polished_url,
                    "prompt": record.prompt,
                    "created_at": _isoformat_utc(record.created_at),
                }
                for original_url, record in latest.items()
            ]
        }

    @app.post("/api/generate", status_code=202)
    def generate(
        request: GenerateRequest,
        http_request: Request,
        background_tasks: BackgroundTasks,
        auth_user_id: str | None = Depends(get_current_user_id),
    ):
        client_ip = http_request.client.host if http_request.client else "unknown"
        rate_key = f"generate:{auth_user_id or client_ip}"
        if not _rate_limiter.allow(rate_key, limit=5, window_seconds=300):
            raise HTTPException(status_code=429, detail="生成请求过于频繁，请稍后再试")
        if not request.query.strip():
            raise HTTPException(status_code=400, detail="query is required")
        if len(request.query) > _MAX_GENERATE_QUERY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"查询词过长（最多{_MAX_GENERATE_QUERY_LENGTH}字符）",
            )
        generation_request_id = generation_service.create_generation_request(request)
        background_tasks.add_task(generation_service.run_generation_job, generation_request_id, request)
        return {"generation_request_id": generation_request_id, "status": "running"}

    @app.get("/api/generation-requests/{request_id}")
    def get_generation_request(
        request_id: int,
        after_log_id: int | None = Query(None, ge=0),
        log_limit: int = Query(200, ge=1, le=500),
    ):
        return _generation_request_status(db_engine, request_id, after_log_id=after_log_id, log_limit=log_limit)

    @app.get("/api/generation-logs")
    def generation_logs(
        limit: int = Query(100, ge=1, le=500),
        generation_request_id: int | None = None,
    ):
        return {"items": _generation_log_items(db_engine, generation_request_id, limit)}

    # ---- Auth + subscription ----

    @app.get("/api/auth/me")
    def auth_me(user_id: str | None = Depends(get_current_user_id)):
        if not user_id:
            return {"authenticated": False}
        from app.subscription_service import ensure_user
        ensure_user(db_engine, user_id)
        return {
            "authenticated": True,
            "user_id": user_id,
            "subscription": subscription_status_payload(db_engine, user_id),
        }

    @app.post("/api/subscriptions/create")
    def create_subscription(
        _request: SubscriptionCreateRequest,
        user_id: str = Depends(require_current_user_id),
    ):
        from app.subscription_service import get_subscription_price_cents
        price_cents = get_subscription_price_cents()
        try:
            result = create_subscription_checkout(user_id, price_cents=price_cents)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        out_trade_no = result["out_trade_no"]
        # Record pending subscription so webhook can match
        create_pending_subscription(db_engine, user_id=user_id, out_trade_no=out_trade_no)
        return {
            "out_trade_no": out_trade_no,
            "checkout_url": result["checkout_url"],
            "total_amount": result["total_amount"],
            "price_cents": price_cents,
        }

    @app.get("/api/subscriptions/status")
    def subscription_status(
        user_id: str = Depends(require_current_user_id),
        reconcile: str | None = Query(
            default=None,
            description="out_trade_no to actively reconcile against Alipay before returning status",
        ),
    ):
        # PagePay confirmation cannot rely on the async webhook alone (it may be
        # blocked/lost). When the frontend polls with the order it just created,
        # actively query Alipay and activate on success as a fallback.
        if reconcile:
            try:
                pending = find_pending_subscription(db_engine, reconcile)
                # Only the owner of the order may trigger its reconciliation, so
                # one user can never activate/probe another user's order.
                if pending is not None and pending.user_id == user_id:
                    reconcile_pending_subscription(db_engine, reconcile)
            except Exception:
                logger.exception(
                    "subscription reconcile failed for out_trade_no=%s", reconcile
                )
        return subscription_status_payload(db_engine, user_id)

    @app.post("/api/webhooks/alipay")
    async def alipay_webhook(request: Request):
        """Alipay async payment notification.

        Form-encoded body. Verify RSA2 signature, then activate subscription.
        Respond plain text 'success' or 'fail'.
        """
        form = await request.form()
        params = {k: str(v) for k, v in form.items() if v}
        # Public key from env. If not configured, REJECT the webhook entirely -
        # accepting unsigned notifications lets attackers forge payments.
        alipay_public_key_pem = os.environ.get("ALIPAY_PUBLIC_KEY", "").strip()
        if not alipay_public_key_pem:
            logger.error("ALIPAY_PUBLIC_KEY not configured - rejecting Alipay webhook")
            return Response(content="fail", media_type="text/plain")
        if not verify_webhook_signature(params, _wrap_public_key_pem(alipay_public_key_pem)):
            logger.warning(
                "Alipay webhook signature verification failed for out_trade_no=%s",
                params.get("out_trade_no", ""),
            )
            return Response(content="fail", media_type="text/plain")

        trade_status = params.get("trade_status", "")
        out_trade_no = params.get("out_trade_no", "")
        alipay_trade_no = params.get("trade_no", "")

        if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"} and out_trade_no:
            # Idempotency: skip if this out_trade_no is already active.
            existing = find_pending_subscription(db_engine, out_trade_no)
            if existing and existing.status == "active":
                logger.info("Alipay webhook: out_trade_no=%s already active, skipping", out_trade_no)
                return Response(content="success", media_type="text/plain")
            try:
                alipay_activate_subscription(
                    db_engine,
                    user_id=_resolve_user_for_out_trade_no(db_engine, out_trade_no),
                    out_trade_no=out_trade_no,
                    alipay_trade_no=alipay_trade_no,
                )
            except Exception:
                logger.exception(
                    "Alipay webhook: activation failed for out_trade_no=%s",
                    out_trade_no,
                )
                return Response(content="fail", media_type="text/plain")

        return Response(content="success", media_type="text/plain")

    # ---- Static frontend serving (production single-container) ----
    # Serve the built React app from frontend/dist. In preview, the Haven
    # sandbox handles this separately; this block is for production deploys
    # where the backend container is the only server.
    _FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", "/app/frontend/dist"))
    if _FRONTEND_DIST.is_dir():
        index_html = _FRONTEND_DIST / "index.html"
        assets_dir = _FRONTEND_DIST / "assets"

        # Serve Vite-built JS/CSS chunks at /assets/*
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Serve other static files at root (favicon, logo, etc.)
        def _serve_static_file(filename: str):
            file_path = _FRONTEND_DIST / filename
            if file_path.is_file():
                return FileResponse(str(file_path))
            raise HTTPException(status_code=404)

        # Known static files served at root
        for static_name in ("brand-logo.png", "favicon.ico", "vite.svg"):
            static_path = _FRONTEND_DIST / static_name
            if static_path.is_file():
                app.get(f"/{static_name}", name=f"static_{static_name}")(lambda fn=static_name: _serve_static_file(fn))

        # SPA fallback: any non-API path returns index.html
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Don't intercept API routes (they're registered above and take priority)
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            # Try to serve a matching static file first (e.g. /brand-logo.png)
            candidate = _FRONTEND_DIST / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # Otherwise return index.html for client-side routing
            if index_html.is_file():
                return FileResponse(str(index_html))
            raise HTTPException(status_code=404)

    return app


def _wrap_public_key_pem(raw: str) -> str:
    raw = raw.strip()
    if "BEGIN" in raw:
        return raw
    body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"


def _resolve_user_for_out_trade_no(db_engine: Engine, out_trade_no: str) -> str:
    """Find the user_id associated with a pending subscription by out_trade_no."""
    from app.alipay_service import find_pending_subscription
    sub = find_pending_subscription(db_engine, out_trade_no)
    if sub is None or not sub.user_id:
        raise ValueError(f"no pending subscription for out_trade_no={out_trade_no}")
    return sub.user_id


def _page_payload(
    result: Any,
    user_id: str | None,
    repo: PostRepository,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
) -> dict[str, Any]:
    post_ids = [post.id for post in result.items]
    interactions = repo.get_interactions_batch(post_ids, user_id)
    return {
        "items": [
            _post_payload(
                post,
                interactions.get(post.id),
                user_lat=user_lat,
                user_lng=user_lng,
            )
            for post in result.items
        ],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "has_more": result.page * result.page_size < result.total,
    }


def _isoformat_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _post_payload(
    post: Post,
    interaction: PostInteraction | None = None,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
) -> dict[str, Any]:
    places = []
    if hasattr(post, "places") and post.places:
        places = [
            {
                "name": p.name,
                "address": p.address,
                "lat": p.lat,
                "lng": p.lng,
                "category": p.category,
                "rating": p.rating,
                "amap_poi_id": p.amap_poi_id,
                "method_order": p.method_order,
                "method_title": p.method_title,
            }
            for p in sorted(post.places, key=lambda x: (x.method_order, x.step_order))
            if p.lat and p.lng
        ]

    route_groups = _generated_route_groups(places) if post.source_type == "user_generated" else []
    if not route_groups:
        route_groups = route_groups_payload(post.content, places) if places else []
    author = _author_payload(post.source_type, getattr(post, "author_user_id", None))
    distance_meters = None
    if user_lat is not None and user_lng is not None and hasattr(post, "places") and post.places:
        distance_meters = post_min_distance_meters(post.places, user_lat, user_lng)

    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "tags": _loads_list(post.tags_json),
        "images": _loads_list(post.images_json),
        "cover_image": post.cover_image,
        "source_query": post.source_query,
        "source_type": post.source_type,
        "like_count": post.like_count,
        "favorite_count": post.favorite_count,
        "view_count": post.view_count,
        "is_liked": bool(interaction and interaction.liked),
        "is_favorited": bool(interaction and interaction.favorited),
        "created_at": _isoformat_utc(post.created_at),
        "author": author,
        "places": places,
        "route_groups": route_groups,
        "distance_meters": distance_meters,
    }


def _interaction_for(repo: PostRepository, post_id: int, user_id: str | None) -> PostInteraction | None:
    if not user_id:
        return None
    return repo.get_interaction(post_id, user_id)


def _loads_list(raw: str) -> list[Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _loads_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _generated_route_groups(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for place in places:
        order = int(place.get("method_order") or 0)
        if order <= 0:
            continue
        buckets.setdefault(order, []).append(place)
    groups: list[dict[str, Any]] = []
    for order in sorted(buckets):
        group_places = sorted(buckets[order], key=lambda item: int(item.get("step_order") or 0))
        title = str(group_places[0].get("method_title") or f"玩法{order}")
        groups.append(
            {
                "section_index": order,
                "section_label": f"玩法{_cn_order(order)}",
                "title": title,
                "places": group_places,
            }
        )
    return groups


def _cn_order(order: int) -> str:
    numerals = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
    return numerals.get(order, str(order))


def _generation_request_status(
    db_engine: Engine,
    request_id: int,
    *,
    after_log_id: int | None = None,
    log_limit: int = 200,
) -> dict[str, Any]:
    from app.database import session_scope

    with session_scope(db_engine) as session:
        generation_request = session.get(GenerationRequest, request_id)
        if generation_request is None:
            raise HTTPException(status_code=404, detail="generation request not found")
        logs = _generation_log_items(
            db_engine,
            request_id,
            log_limit,
            ascending=True,
            after_log_id=after_log_id,
        )
        return {
            "generation_request_id": generation_request.id,
            "status": generation_request.status,
            "post_id": generation_request.result_post_id,
            "error_message": generation_request.error_message,
            "logs": logs,
        }


def _generation_log_items(
    db_engine: Engine,
    generation_request_id: int | None,
    limit: int,
    *,
    ascending: bool = False,
    after_log_id: int | None = None,
) -> list[dict[str, Any]]:
    from app.database import session_scope

    with session_scope(db_engine) as session:
        query = session.query(GenerationLog)
        if generation_request_id is not None:
            query = query.where(GenerationLog.generation_request_id == generation_request_id)
        if after_log_id is not None:
            query = query.where(GenerationLog.id > after_log_id)
        order = GenerationLog.id.asc() if ascending else GenerationLog.id.desc()
        rows = query.order_by(order).limit(limit).all()
        if not ascending:
            rows = list(reversed(rows))
        return [
            {
                "id": row.id,
                "generation_request_id": row.generation_request_id,
                "stage": row.stage,
                "level": row.level,
                "message": row.message,
                "payload": _loads_json(row.payload_json),
                "created_at": _isoformat_utc(row.created_at),
            }
            for row in rows
        ]


def _author_payload(source_type: str, user_id: str | None = None) -> dict[str, Any]:
    if source_type == "user_generated":
        seed = user_id or "user"
        suffix = seed.replace("web_", "")[:6] if seed else "用户"
        return {
            "name": f"用户{suffix}",
            "avatar_text": suffix[:1].upper() if suffix else "我",
            "avatar_url": None,
            "type": "user",
            "id": seed,
        }
    return {
        "name": "上海City不City",
        "avatar_text": "城",
        "avatar_url": "/brand-logo.png",
        "type": "platform",
        "id": "platform",
    }


app = create_app()

