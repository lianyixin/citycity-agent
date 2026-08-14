import json
import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from app.agent_models import DiscoveryRequest, PlayMethod, PlayStep, POICategory, POIInfo
from app.amap_cache import SQLiteAmapCache
from app.amap_client import AmapAPIClient
from app.amap_tool import AmapTool
from app.database import session_scope
from app.deepseek_client import DeepSeekClient
from app.models import GenerationLog, GenerationRequest, GeneratedPlayMethod, Place, Post
from app.play_discovery_workflow import PlayDiscoveryWorkflow
from app.schemas import GenerateRequest
from app.xhs_content import XHSContentGenerator


@dataclass(frozen=True)
class GeneratedPost:
    post_id: int
    post_ids: list[int]
    generation_request_id: int


MIN_XHS_CANDIDATES = 6
MAX_XHS_CANDIDATES = 8
TECHNICAL_LOG_REPLACEMENTS = (
    ("Plan + Execute", "路线探索"),
    ("PlannerAgent", ""),
    ("ExecuteAgent", ""),
    ("Planner", ""),
    ("Execute Agent", ""),
    ("Execute", ""),
    ("Agent", ""),
)
USER_LOG_SUPPRESSED_PHRASES = ("延展出", "正在查找", "玩法发现", "路线探索")
USER_LOG_SUPPRESSED_STAGES = frozenset({"discovery", "workflow"})


def _default_city() -> str:
    return os.getenv("DEFAULT_CITY", "上海").strip() or "上海"


def _default_coordinates() -> tuple[float, float]:
    return (
        float(os.getenv("DEFAULT_CITY_LAT", "31.2304")),
        float(os.getenv("DEFAULT_CITY_LNG", "121.4737")),
    )


class GenerationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def generate(self, request: GenerateRequest) -> GeneratedPost:
        import asyncio

        return asyncio.run(self.generate_async(request))

    def create_generation_request(self, request: GenerateRequest) -> int:
        with session_scope(self.engine) as session:
            generation_request = GenerationRequest(
                user_id=request.user_id,
                query=request.query,
                location_text=request.location_text,
                location_lat=request.location_lat,
                location_lng=request.location_lng,
                time_context=request.time_context,
                companion_type=request.companion_type,
                preference_tags_json=json.dumps(request.preference_tags, ensure_ascii=False),
                status="pending",
            )
            session.add(generation_request)
            session.flush()
            return generation_request.id

    def run_generation_job(self, generation_request_id: int, request: GenerateRequest) -> None:
        import asyncio

        asyncio.run(self._run_generation_job_async(generation_request_id, request))

    async def generate_async(self, request: GenerateRequest) -> GeneratedPost | None:
        generation_request_id = self.create_generation_request(request)
        return await self._run_generation_job_async(generation_request_id, request)

    async def _run_generation_job_async(self, generation_request_id: int, request: GenerateRequest) -> GeneratedPost | None:
        self._set_request_status(generation_request_id, "running")
        try:
            request, methods, card = await self._build_generated_card(generation_request_id, request)
        except Exception as exc:
            # A generation failure (e.g. no candidate routes, map/LLM error) must
            # mark the request as failed. Do NOT persist a fallback post: a fake
            # note published to the content stream would hide the real failure and
            # pollute the feed with an empty/placeholder itinerary.
            error_message = str(exc)
            self._log(generation_request_id, "error", error_message, level="error")
            self._set_request_status(generation_request_id, "failed", error_message=error_message)
            return None

        return self._persist_generated_post(
            generation_request_id,
            request,
            methods,
            card,
            source_type="user_generated",
            author_user_id=request.user_id,
        )

    async def _build_generated_card(
        self,
        generation_request_id: int,
        request: GenerateRequest,
    ) -> tuple[GenerateRequest, list[PlayMethod], dict[str, Any]]:
        self._log(generation_request_id, "request", "已接收生成请求，开始执行", {"query": request.query})
        request = await self._resolve_location(request, generation_request_id)
        methods = await self._discover_play_methods(request, generation_request_id)
        self._log(
            generation_request_id,
            "discovery",
            f"玩法发现完成，共 {len(methods)} 条候选路线",
            [_method_log(method) for method in methods],
        )
        self._log(generation_request_id, "candidate_filter", "正在筛选并去重小红书候选路线…")
        methods = filter_candidate_methods_for_xhs(methods)
        self._log(
            generation_request_id,
            "candidate_filter",
            f"候选筛选完成，保留 {len(methods)} 条（附近模式={_nearby_intent(request.query)}）",
            [_method_log(method) for method in methods],
        )
        self._log(generation_request_id, "xhs", "正在调用 LLM 撰写小红书正文与配图…")
        card = await self._generate_xhs_card(request, methods, generation_request_id)
        methods = _selected_methods_from_card(methods, card)
        self._log(
            generation_request_id,
            "selection",
            f"已选定 {len(methods)} 条路线写入笔记",
            [_method_log(method) for method in methods],
        )
        self._log(generation_request_id, "xhs", f"小红书正文生成完成：{card.get('title')}")
        if not card.get("title") or not card.get("content") or not card.get("images"):
            raise RuntimeError("生成结果不完整，未发布")
        return request, methods, card

    def _persist_generated_post(
        self,
        generation_request_id: int,
        request: GenerateRequest,
        methods: list[PlayMethod],
        card: dict[str, Any],
        *,
        source_type: str,
        author_user_id: str,
    ) -> GeneratedPost:
        with session_scope(self.engine) as session:
            generation_request = session.get(GenerationRequest, generation_request_id)
            post = Post(
                title=card["title"],
                content=card["content"],
                tags_json=json.dumps(card["tags"], ensure_ascii=False),
                images_json=json.dumps(card["images"], ensure_ascii=False),
                cover_image=card["images"][0] if card["images"] else None,
                source_query=request.query,
                source_type=source_type,
                author_user_id=author_user_id,
                status="published",
            )
            session.add(post)
            session.flush()

            for method_index, method in enumerate(methods, start=1):
                session.add(
                    GeneratedPlayMethod(
                        post_id=post.id,
                        generation_request_id=generation_request_id,
                        method_json=method.model_dump_json(),
                    )
                )
                for step in method.steps:
                    session.add(
                        Place(
                            post_id=post.id,
                            name=step.poi.name,
                            address=step.poi.address,
                            lat=step.poi.latitude,
                            lng=step.poi.longitude,
                            category=step.poi.category.value,
                            rating=step.poi.rating,
                            image_urls_json=json.dumps(step.poi.photos[:2], ensure_ascii=False),
                            amap_poi_id=step.poi.amap_poi_id,
                            step_order=step.step_number,
                            method_order=method_index,
                            method_title=method.title,
                        )
                    )

            if generation_request:
                generation_request.status = "success"
                generation_request.result_post_id = post.id
                generation_request.error_message = None
            self._log(generation_request_id, "persist", "笔记已保存到内容流", {"post_id": post.id})
            return GeneratedPost(post_id=post.id, post_ids=[post.id], generation_request_id=generation_request_id)

    def _set_request_status(
        self,
        generation_request_id: int,
        status: str,
        *,
        error_message: str | None = None,
        result_post_id: int | None = None,
    ) -> None:
        with session_scope(self.engine) as session:
            generation_request = session.get(GenerationRequest, generation_request_id)
            if not generation_request:
                return
            generation_request.status = status
            if error_message is not None:
                generation_request.error_message = error_message
            if result_post_id is not None:
                generation_request.result_post_id = result_post_id

    async def _discover_play_methods(self, request: GenerateRequest, generation_request_id: int) -> list[PlayMethod]:
        def log_callback(stage: str, message: str) -> None:
            self._log(generation_request_id, stage, message)

        cache = SQLiteAmapCache(self.engine)
        amap_client = AmapAPIClient(cache=cache)
        workflow = PlayDiscoveryWorkflow(
            AmapTool(amap_client),
            DeepSeekClient(),
            max_rounds=3,
            log_callback=log_callback,
        )
        self._log(generation_request_id, "discovery", "启动 Plan + Execute 玩法发现…")
        discovery = await workflow.run(_to_discovery_request(request), log_callback=log_callback)
        if not discovery.success:
            raise RuntimeError(f"玩法发现失败：{discovery.message}")
        if not discovery.play_methods:
            raise RuntimeError("未找到符合条件的候选路线，请换个关键词或出发地重试")
        return discovery.play_methods

    async def _generate_xhs_card(
        self,
        request: GenerateRequest,
        methods: list[PlayMethod],
        generation_request_id: int,
    ) -> dict:
        generator = XHSContentGenerator(DeepSeekClient())
        try:
            return await generator.generate_multi_route_note(request.query, methods, request.location_text)
        except Exception as exc:
            self._log(
                generation_request_id,
                "xhs",
                f"多路线生成失败，改用单路线生成器重试：{exc}",
                level="warning",
            )
            return await generator.generate(request.query, methods, request.location_text)

    async def _resolve_location(self, request: GenerateRequest, generation_request_id: int) -> GenerateRequest:
        if request.location_lat is not None and request.location_lng is not None:
            if request.location_text:
                self._log(
                    generation_request_id,
                    "location",
                    "使用用户提供的出发坐标",
                    {"lat": request.location_lat, "lng": request.location_lng, "location_text": request.location_text},
                )
                return request
            cache = SQLiteAmapCache(self.engine)
            client = AmapAPIClient(cache=cache)
            location = f"{request.location_lng},{request.location_lat}"
            response = await client.reverse_geocode(location)
            name = _reverse_geocode_name(response.data)
            if name:
                self._log(
                    generation_request_id,
                    "location",
                    "逆地理编码坐标为出发地名称",
                    {"lat": request.location_lat, "lng": request.location_lng, "location_text": name},
                )
                return request.model_copy(update={"location_text": name})
            self._log(
                generation_request_id,
                "location",
                "使用坐标作为出发地（未能解析地名）",
                {"lat": request.location_lat, "lng": request.location_lng},
            )
            return request
        if not request.location_text:
            default_city = _default_city()
            default_lat, default_lng = _default_coordinates()
            self._log(
                generation_request_id,
                "location",
                f"未提供坐标或地名，使用{default_city}默认出发地",
                {"lat": default_lat, "lng": default_lng, "location_text": default_city},
            )
            return request.model_copy(
                update={"location_lat": default_lat, "location_lng": default_lng, "location_text": default_city}
            )

        cache = SQLiteAmapCache(self.engine)
        client = AmapAPIClient(cache=cache)
        response = await client.geocode(request.location_text, city=_default_city())
        geocodes = response.data.get("geocodes", []) if isinstance(response.data, dict) else []
        if not geocodes:
            self._log(generation_request_id, "location", "地名解析未返回结果", {"location_text": request.location_text}, level="warning")
            return request
        lng, lat = _parse_location(geocodes[0].get("location"))
        if not lat or not lng:
            return request
        self._log(generation_request_id, "location", "已将地名解析为坐标", {"location_text": request.location_text, "lat": lat, "lng": lng})
        return request.model_copy(update={"location_lat": lat, "location_lng": lng})

    def _log(
        self,
        generation_request_id: int | None,
        stage: str,
        message: str,
        payload: Any | None = None,
        level: str = "info",
    ) -> None:
        if level == "error":
            sanitized_stage, sanitized_message = stage, message.strip()
        else:
            sanitized = _sanitize_generation_log(stage, message)
            if sanitized is None:
                return
            sanitized_stage, sanitized_message = sanitized
        try:
            with session_scope(self.engine) as session:
                session.add(
                    GenerationLog(
                        generation_request_id=generation_request_id,
                        stage=sanitized_stage,
                        level=level,
                        message=sanitized_message,
                        payload_json=json.dumps(payload, ensure_ascii=False, default=str) if payload is not None else None,
                    )
                )
        except Exception:
            pass


def _should_publish_user_log(stage: str, message: str) -> bool:
    if stage in USER_LOG_SUPPRESSED_STAGES:
        return False
    return not any(phrase in message for phrase in USER_LOG_SUPPRESSED_PHRASES)


def _publish_user_log(stage: str, message: str) -> tuple[str, str] | None:
    if not _should_publish_user_log(stage, message):
        return None
    return stage, message


def _sanitize_generation_log(stage: str, message: str) -> tuple[str, str] | None:
    sanitized = message.strip()
    sanitized = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", sanitized)

    if sanitized == "workflow:start":
        return _publish_user_log("workflow", "正在启动路线探索")

    round_execute_match = re.fullmatch(r"workflow:round:(\d+):execute", sanitized)
    if round_execute_match:
        return _publish_user_log("workflow", f"第 {round_execute_match.group(1)} 轮：正在查找并筛选地点")

    round_plan_match = re.fullmatch(r"workflow:round:(\d+):recursive_planning:(\d+)", sanitized)
    if round_plan_match:
        return _publish_user_log("workflow", f"第 {round_plan_match.group(1)} 轮：正在补充下一跳玩法")

    if sanitized.startswith("workflow:"):
        return _publish_user_log("workflow", "正在推进路线探索")

    search_match = re.search(r"\bsearching:\s*(.+?)(?:,\s*location=|,\s*radius=|$)", sanitized)
    if search_match:
        query = search_match.group(1).strip().strip(",")
        return _publish_user_log("search", f"正在查找：{query}" if query else "正在查找合适地点")

    selected_match = re.search(r"\bselected\s+(.+?)\s+for\s+(.+)$", sanitized)
    if selected_match:
        poi_name = selected_match.group(1).strip()
        route_name = selected_match.group(2).strip()
        return _publish_user_log("search", f"已找到地点：{poi_name}（{route_name}）")

    no_poi_match = re.search(r"\bno suitable POI for\s+(.+)$", sanitized)
    if no_poi_match:
        return _publish_user_log("search", f"暂未找到合适地点：{no_poi_match.group(1).strip()}")

    completed_match = re.search(r"\bcompleted\s+(\d+)\s+paths\b", sanitized)
    if completed_match:
        return _publish_user_log("workflow", f"已整理 {completed_match.group(1)} 条候选路线")

    expanded_match = re.search(r"\bexpanded from\s+(.+?)\s+to\s+(.+)$", sanitized)
    if expanded_match:
        return _publish_user_log(
            "discovery",
            f"从 {expanded_match.group(1).strip()} 延展出：{expanded_match.group(2).strip()}",
        )

    created_match = re.search(r"created\s+(\d+)\s+root plans", sanitized)
    if created_match:
        return _publish_user_log("discovery", f"已生成 {created_match.group(1)} 个初始玩法方向")

    sanitized = re.sub(r",?\s*location=[^,，\s]+(?:,[^,，\s]+)?", "", sanitized)
    sanitized = re.sub(r",?\s*radius=\d+", "", sanitized)
    for source, target in TECHNICAL_LOG_REPLACEMENTS:
        sanitized = sanitized.replace(source, target)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = sanitized.replace("启动 路线探索 玩法发现", "正在探索玩法路线")
    sanitized = sanitized.replace("开始 路线探索 玩法发现", "正在探索玩法路线")
    sanitized = sanitized.replace("正在搜索并筛选 POI", "正在查找并筛选地点")
    sanitized = sanitized.replace(" 已规划 ", "已规划")
    sanitized = sanitized.strip(" ·-:")

    if stage in {"planner", "execute", "agent"}:
        stage = "discovery"
    return _publish_user_log(stage, sanitized or "正在处理生成进度")


def _build_fallback_card(request: GenerateRequest) -> dict:
    default_city = _default_city()
    location = (request.location_text or default_city).strip()
    time_context = (request.time_context or "最近").strip()
    companion = (request.companion_type or "朋友").strip()
    preferences = [tag.strip() for tag in request.preference_tags if tag.strip()]
    preference_text = "、".join(preferences[:3]) if preferences else "轻松、不绕路、好拍"
    title_anchor = location
    title = f"{title_anchor}轻松玩法"
    if len(title) > 15:
        title = f"{title_anchor[:8]}玩法"

    content = (
        f"{time_context}想在{location}附近安排一条不费脑子的路线，可以按这个思路走。\n\n"
        f"这条更适合{companion}一起出门，重点是{preference_text}。先找一个好逛的街区慢慢进入状态，"
        f"中间穿插吃饭或咖啡休息，最后留一点时间拍照散步，不用把行程排太满。\n\n"
        f"如果你喜欢{request.query}这种感觉，可以把这条当作基础版：想更出片就多留时间拍照，"
        f"想更舒服就少换地方。觉得有用的话，点左上角头像关注更多{default_city}有趣玩法。"
    )
    tags = [default_city, location, time_context, companion, *preferences, "城市玩法", "不踩雷"]
    deduped_tags = []
    for tag in tags:
        if tag and tag not in deduped_tags:
            deduped_tags.append(tag)

    return {
        "title": title,
        "content": content,
        "tags": deduped_tags[:12],
        "images": _fallback_method(request).steps[0].poi.photos,
    }


def _to_discovery_request(request: GenerateRequest) -> DiscoveryRequest:
    nearby_intent = _nearby_intent(request.query)
    target_area = _extract_target_area(request.query)
    enriched_parts = [request.query]
    enriched_parts.extend(
        [
            request.time_context or "",
            request.companion_type or "",
            " ".join(request.preference_tags),
        ]
    )
    user_location = None
    if request.location_lat is not None and request.location_lng is not None:
        user_location = {"lat": request.location_lat, "lng": request.location_lng}
    return DiscoveryRequest(
        query=" ".join(part for part in enriched_parts if part).strip(),
        user_location=user_location,
        max_results=6,
        max_depth=3,
        preferences={
            "location_text": request.location_text,
            "time_context": request.time_context,
            "companion_type": request.companion_type,
            "preference_tags": request.preference_tags,
            "nearby_intent": nearby_intent,
            "target_area": target_area,
        },
    )


def _discovery_debug_payload(discovery: Any) -> dict[str, Any]:
    debug_info = discovery.debug_info if isinstance(getattr(discovery, "debug_info", None), dict) else {}
    debug_logs = debug_info.get("debug_logs") if isinstance(debug_info.get("debug_logs"), list) else []
    return {
        "success": getattr(discovery, "success", None),
        "message": getattr(discovery, "message", ""),
        "total_count": getattr(discovery, "total_count", 0),
        "processing_time": getattr(discovery, "processing_time", 0),
        "debug_log_count": len(debug_logs),
        "debug_logs_tail": debug_logs[-5:],
    }


def _extract_target_area(query: str) -> str | None:
    compact = (query or "").replace(" ", "")
    district_match = re.search(r"([\u4e00-\u9fff]{1,8}区)", compact)
    if district_match:
        return district_match.group(1)
    return None


def _nearby_intent(query: str) -> bool:
    compact = (query or "").replace(" ", "")
    return any(token in compact for token in ("附近", "周边", "就近", "离我最近", "离我这"))


def _reverse_geocode_name(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    regeocode = data.get("regeocode")
    if not isinstance(regeocode, dict):
        return None
    formatted = str(regeocode.get("formatted_address") or "").strip()
    if formatted:
        return formatted
    address_component = regeocode.get("addressComponent")
    if isinstance(address_component, dict):
        township = str(address_component.get("township") or "").strip()
        district = str(address_component.get("district") or "").strip()
        if township:
            return township
        if district:
            return district
    return None


def _parse_location(raw: Any) -> tuple[float, float]:
    parts = str(raw or "").split(",")
    if len(parts) != 2:
        return 0.0, 0.0
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return 0.0, 0.0


def _method_log(method: PlayMethod) -> dict[str, Any]:
    return {
        "title": method.title,
        "steps": [step.poi.name for step in method.steps],
        "rating": method.rating,
    }


def filter_candidate_methods_for_xhs(
    methods: list[PlayMethod],
    limit: int = MAX_XHS_CANDIDATES,
    min_candidates: int = MIN_XHS_CANDIDATES,
) -> list[PlayMethod]:
    """过滤、去重并排序候选玩法，避免把低质/重复候选塞给 XHS LLM。"""
    if not methods:
        return []

    strict = _dedupe_methods([method for method in methods if _method_is_usable(method)])
    relaxed = _dedupe_methods([method for method in methods if _method_is_relaxed_usable(method)])
    fallback = _dedupe_methods([method for method in methods if method.steps])

    selected = _select_diverse_methods(strict, limit)
    selected = _append_until_minimum(selected, relaxed, min_candidates, limit)
    selected = _append_until_minimum(selected, fallback, min_candidates, limit)
    if len(selected) < min_candidates:
        selected = _append_until_minimum(selected, fallback, limit, limit)
    return selected[:limit]


def _dedupe_methods(methods: list[PlayMethod]) -> list[PlayMethod]:
    deduped: list[PlayMethod] = []
    seen_routes: set[tuple[str, ...]] = set()
    seen_title_first_poi: set[tuple[str, str]] = set()
    for method in sorted(methods, key=_method_quality_score, reverse=True):
        route_key = tuple(_poi_key(step.poi.name) for step in method.steps)
        title_first_key = (_title_key(method.title), _first_poi_key(method))
        if route_key in seen_routes or title_first_key in seen_title_first_poi:
            continue
        seen_routes.add(route_key)
        seen_title_first_poi.add(title_first_key)
        deduped.append(method)
    return deduped


def _select_diverse_methods(methods: list[PlayMethod], limit: int) -> list[PlayMethod]:
    selected: list[PlayMethod] = []
    used_categories: set[str] = set()
    for method in methods:
        categories = {step.poi.category.value for step in method.steps}
        if not categories <= used_categories or len(selected) < 3:
            selected.append(method)
            used_categories.update(categories)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for method in methods:
            if method not in selected:
                selected.append(method)
            if len(selected) >= limit:
                break
    return selected


def _append_until_minimum(
    selected: list[PlayMethod],
    candidates: list[PlayMethod],
    minimum: int,
    limit: int,
) -> list[PlayMethod]:
    if len(selected) >= minimum:
        return selected
    next_selected = selected.copy()
    for method in candidates:
        if method in next_selected:
            continue
        next_selected.append(method)
        if len(next_selected) >= minimum or len(next_selected) >= limit:
            break
    return next_selected


def _method_is_usable(method: PlayMethod) -> bool:
    if not method.steps:
        return False
    if any(_poi_unavailable(step.poi.name) for step in method.steps):
        return False
    if any(not step.poi.latitude or not step.poi.longitude for step in method.steps):
        return False
    if method.rating and method.rating < 3.8:
        return False
    return True


def _method_is_relaxed_usable(method: PlayMethod) -> bool:
    if not method.steps:
        return False
    if any(_poi_unavailable(step.poi.name) for step in method.steps):
        return False
    if any(not step.poi.latitude or not step.poi.longitude for step in method.steps):
        return False
    if method.rating and method.rating < 3.5:
        return False
    return True


def _poi_unavailable(name: str) -> bool:
    return any(token in name for token in ("暂停开放", "暂未开放", "已关闭", "停业"))


def _method_quality_score(method: PlayMethod) -> float:
    ratings = [step.poi.rating for step in method.steps if step.poi.rating]
    avg_rating = sum(ratings) / len(ratings) if ratings else method.rating or 0.0
    step_count = len(method.steps)
    step_score = 0.4 if 2 <= step_count <= 3 else 0.15 if step_count == 1 else 0.25
    photo_score = min(sum(len(step.poi.photos) for step in method.steps), 3) * 0.05
    category_score = len({step.poi.category.value for step in method.steps}) * 0.08
    return avg_rating + step_score + photo_score + category_score


def _poi_key(name: str) -> str:
    return name.split("(")[0].split("（")[0].strip().lower()


def _title_key(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")[:12]


def _first_poi_key(method: PlayMethod) -> str:
    return _poi_key(method.steps[0].poi.name) if method.steps else ""


def _methods_by_selected_indexes(methods: list[PlayMethod], raw_indexes: Any) -> list[PlayMethod]:
    selected: list[PlayMethod] = []
    if isinstance(raw_indexes, list):
        for raw in raw_indexes:
            try:
                index = int(raw)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= len(methods):
                method = methods[index - 1]
                if method not in selected:
                    selected.append(method)
    return selected[:4] if selected else methods[:4]


def _selected_methods_from_card(methods: list[PlayMethod], card: dict[str, Any]) -> list[PlayMethod]:
    selected_methods = card.get("selected_methods")
    if isinstance(selected_methods, list) and all(isinstance(method, PlayMethod) for method in selected_methods):
        return selected_methods[:4]
    return _methods_by_selected_indexes(methods, card.get("selected_method_indexes"))


def _fallback_method(request: GenerateRequest) -> PlayMethod:
    default_city = _default_city()
    default_lat, default_lng = _default_coordinates()
    location = (request.location_text or default_city).strip()
    poi = POIInfo(
        name=f"{location}城市玩法点",
        address=f"{location}附近",
        latitude=request.location_lat or default_lat,
        longitude=request.location_lng or default_lng,
        category=POICategory.OTHER,
        rating=4.5,
        photos=["https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=1200&q=80"],
        source="fallback",
    )
    step = PlayStep(
        step_number=1,
        poi=poi,
        estimated_start_time=request.time_context,
        duration_minutes=90,
        description=f"围绕{request.query}安排轻松路线",
        recommendation_reason="外部服务不可用时生成的兜底玩法点。",
    )
    return PlayMethod(
        title=f"{location}轻松玩法",
        description="包含1个地点的兜底体验路线",
        steps=[step],
        total_duration_minutes=90,
        tags=[default_city, location, "城市玩法"],
        rating=4.5,
    )

