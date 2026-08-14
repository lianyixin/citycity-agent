import json
from datetime import datetime, timedelta

from sqlalchemy import Engine, select

from app.amap_models import AmapAPIRequest, AmapAPIResponse
from app.database import session_scope
from app.models import AmapCacheEntry


class SQLiteAmapCache:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_cached_response(self, request: AmapAPIRequest) -> AmapAPIResponse | None:
        cache_key = request.get_cache_key()
        with session_scope(self.engine) as session:
            entry = session.execute(
                select(AmapCacheEntry).where(AmapCacheEntry.cache_key == cache_key)
            ).scalar_one_or_none()
            if entry is None or entry.cache_status != "valid":
                return None
            if entry.expires_at and entry.expires_at <= datetime.utcnow():
                return None
            entry.hit_count += 1
            entry.last_hit_at = datetime.utcnow()
            return AmapAPIResponse(**json.loads(entry.response_data_json))

    def set_cached_response(
        self,
        request: AmapAPIRequest,
        response: AmapAPIResponse,
        expires_at: datetime | None = None,
    ) -> None:
        cache_key = request.get_cache_key()
        expiry = expires_at or _default_expiry(response)
        request_params = {key: value for key, value in request.params.items() if key != "key"}
        with session_scope(self.engine) as session:
            entry = session.execute(
                select(AmapCacheEntry).where(AmapCacheEntry.cache_key == cache_key)
            ).scalar_one_or_none()
            if entry is None:
                entry = AmapCacheEntry(
                    cache_key=cache_key,
                    api_type=request.api_type.value,
                    request_params_json=json.dumps(request_params, ensure_ascii=False),
                    response_data_json=response.model_dump_json(),
                    expires_at=expiry,
                    cache_status="valid" if response.is_success() else "error",
                )
                session.add(entry)
            else:
                entry.api_type = request.api_type.value
                entry.request_params_json = json.dumps(request_params, ensure_ascii=False)
                entry.response_data_json = response.model_dump_json()
                entry.expires_at = expiry
                entry.cache_status = "valid" if response.is_success() else "error"

    def get_stats(self) -> dict[str, int]:
        with session_scope(self.engine) as session:
            entries = session.query(AmapCacheEntry).all()
            return {
                "total_records": len(entries),
                "total_hits": sum(entry.hit_count for entry in entries),
            }


def _default_expiry(response: AmapAPIResponse) -> datetime:
    if response.is_quota_exceeded():
        return datetime.utcnow() + timedelta(minutes=30)
    if not response.is_success():
        return datetime.utcnow() + timedelta(hours=1)
    return datetime.utcnow() + timedelta(days=3650)

