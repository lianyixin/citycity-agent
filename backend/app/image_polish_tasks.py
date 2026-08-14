"""图片润色任务服务：负责缓存复用、任务状态查询与后台执行。"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import Engine, select

from app.database import session_scope
from app.models import ImagePolishRequestRecord, PolishedImage
from app.schemas import ImagePolishRequest

logger = logging.getLogger(__name__)


TERMINAL_STATUSES = {"success", "failed"}
ACTIVE_STATUSES = {"pending", "running"}
STALE_RUNNING_SECONDS = 240


class ImagePolishTaskService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def start(self, request: ImagePolishRequest, user_id: str | None = None) -> dict[str, object]:
        self.sweep_stale()
        cached = self.find_cached(request)
        if cached:
            return {
                "status": "success",
                "polished_image_url": cached.polished_url,
                "cached": True,
            }

        active = self.find_active(request)
        if active:
            return self.payload(active)

        with session_scope(self.engine) as session:
            row = ImagePolishRequestRecord(
                post_id=request.post_id,
                user_id=user_id,
                original_url=request.image_url,
                prompt=request.prompt,
                status="pending",
            )
            session.add(row)
            session.flush()
            return self.payload(row)

    def find_cached(self, request: ImagePolishRequest) -> PolishedImage | None:
        with session_scope(self.engine) as session:
            return session.execute(
                select(PolishedImage)
                .where(PolishedImage.post_id == request.post_id)
                .where(PolishedImage.original_url == request.image_url)
                .where(PolishedImage.prompt == request.prompt)
                .order_by(PolishedImage.created_at.desc(), PolishedImage.id.desc())
            ).scalars().first()

    def find_active(self, request: ImagePolishRequest) -> ImagePolishRequestRecord | None:
        with session_scope(self.engine) as session:
            return session.execute(
                select(ImagePolishRequestRecord)
                .where(ImagePolishRequestRecord.post_id == request.post_id)
                .where(ImagePolishRequestRecord.original_url == request.image_url)
                .where(ImagePolishRequestRecord.prompt == request.prompt)
                .where(ImagePolishRequestRecord.status.in_(ACTIVE_STATUSES))
                .order_by(ImagePolishRequestRecord.created_at.desc(), ImagePolishRequestRecord.id.desc())
            ).scalars().first()

    def get(self, request_id: int) -> ImagePolishRequestRecord | None:
        self.sweep_stale()
        with session_scope(self.engine) as session:
            return session.get(ImagePolishRequestRecord, request_id)

    def mark_running(self, request_id: int) -> ImagePolishRequestRecord | None:
        with session_scope(self.engine) as session:
            row = session.get(ImagePolishRequestRecord, request_id)
            if row and row.status == "pending":
                row.status = "running"
                return row
            return None

    def mark_success(self, request_id: int, polished_url: str) -> None:
        with session_scope(self.engine) as session:
            row = session.get(ImagePolishRequestRecord, request_id)
            if not row:
                return
            row.status = "success"
            row.polished_url = polished_url
            row.error_message = None
            session.add(
                PolishedImage(
                    post_id=row.post_id,
                    user_id=row.user_id,
                    original_url=row.original_url,
                    prompt=row.prompt,
                    polished_url=polished_url,
                )
            )

    def mark_failed(self, request_id: int, message: str) -> None:
        with session_scope(self.engine) as session:
            row = session.get(ImagePolishRequestRecord, request_id)
            if not row:
                return
            row.status = "failed"
            row.error_message = message

    def _safe_mark_failed(self, request_id: int, message: str) -> None:
        """mark_failed that never raises - for use in except blocks."""
        try:
            self.mark_failed(request_id, message)
        except Exception:
            logger.exception("❌ mark_failed itself crashed for request %s", request_id)

    def sweep_stale(self, max_running_seconds: int = STALE_RUNNING_SECONDS) -> int:
        """Mark running tasks older than max_running_seconds as failed.

        Guards against tasks stuck in "running" forever (e.g. background task
        died before reaching mark_failed/mark_success). Returns count swept.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=max_running_seconds)
        with session_scope(self.engine) as session:
            rows = session.execute(
                select(ImagePolishRequestRecord)
                .where(ImagePolishRequestRecord.status == "running")
                .where(ImagePolishRequestRecord.updated_at < cutoff)
            ).scalars().all()
            for row in rows:
                row.status = "failed"
                row.error_message = "润色任务超时，请重试"
                logger.warning("⏰ swept stale polish request %s (running since %s)", row.id, row.updated_at)
            return len(rows)

    def payload(self, row: ImagePolishRequestRecord) -> dict[str, object]:
        payload: dict[str, object] = {
            "polish_request_id": row.id,
            "status": row.status,
            "original_url": row.original_url,
            "prompt": row.prompt,
            "cached": False,
        }
        if row.polished_url:
            payload["polished_image_url"] = row.polished_url
        if row.error_message:
            payload["error_message"] = row.error_message
        return payload

    async def run(self, request_id: int, jimeng_service: object) -> None:
        row = self.mark_running(request_id)
        if not row:
            return
        original_url = row.original_url
        prompt = row.prompt
        user_id = row.user_id
        logger.info("▶️ polish request %s started (user=%s)", request_id, user_id)
        try:
            polished_url = await jimeng_service.polish_image(image_url=original_url, prompt=prompt)
        except Exception as exc:
            logger.exception("❌ polish request %s raised", request_id)
            self._safe_mark_failed(request_id, str(exc) or "图片润色失败，请重试")
            return
        if not polished_url:
            logger.error("❌ polish request %s returned no url", request_id)
            self._safe_mark_failed(request_id, "图片润色失败，请重试")
            return
        try:
            self.mark_success(request_id, polished_url)
        except Exception:
            logger.exception("❌ mark_success crashed for request %s", request_id)
            self._safe_mark_failed(request_id, "图片润色结果保存失败，请重试")
            return
        logger.info("✅ polish request %s succeeded", request_id)
        # Increment free usage counter only on success (non-subscriber)
        if user_id:
            try:
                from app.subscription_service import increment_polish_usage_if_not_subscribed
                increment_polish_usage_if_not_subscribed(self.engine, user_id)
            except Exception:
                logger.warning("⚠️ increment_polish_usage failed for request %s", request_id, exc_info=True)
