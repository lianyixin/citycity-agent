from datetime import datetime, timedelta

import pytest

from app.amap_cache import SQLiteAmapCache
from app.amap_client import AmapAPIClient
from app.amap_models import AmapAPIRequest, AmapAPIResponse, AmapAPIType
from app.database import create_sqlite_engine, init_db


def test_amap_request_cache_key_ignores_api_key():
    first = AmapAPIRequest(
        api_type=AmapAPIType.POI_SEARCH,
        params={"keywords": "咖啡", "city": "上海", "key": "secret-1"},
    )
    second = AmapAPIRequest(
        api_type=AmapAPIType.POI_SEARCH,
        params={"city": "上海", "keywords": "咖啡", "key": "secret-2"},
    )

    assert first.get_cache_key() == second.get_cache_key()


def test_sqlite_amap_cache_roundtrip_and_hit_count(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    cache = SQLiteAmapCache(engine)
    request = AmapAPIRequest(api_type=AmapAPIType.POI_SEARCH, params={"keywords": "咖啡"})
    response = AmapAPIResponse(status="1", info="OK", data={"pois": []}, count=0)

    cache.set_cached_response(request, response)
    cached = cache.get_cached_response(request)
    cached_again = cache.get_cached_response(request)

    assert cached == response
    assert cached_again == response
    assert cache.get_stats()["total_hits"] == 2


def test_sqlite_amap_cache_ignores_expired_entries(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    cache = SQLiteAmapCache(engine)
    request = AmapAPIRequest(api_type=AmapAPIType.POI_SEARCH, params={"keywords": "咖啡"})
    response = AmapAPIResponse(status="1", info="OK", data={"pois": []}, count=0)

    cache.set_cached_response(request, response, expires_at=datetime.utcnow() - timedelta(minutes=1))

    assert cache.get_cached_response(request) is None


@pytest.mark.asyncio
async def test_amap_client_uses_cache_before_http(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    cache = SQLiteAmapCache(engine)
    client = AmapAPIClient(api_key="test-key", cache=cache)
    request = AmapAPIRequest(
        api_type=AmapAPIType.POI_SEARCH,
        params={"keywords": "咖啡", "city": "上海", "key": "test-key", "offset": 20, "page": 1, "extensions": "all"},
    )
    response = AmapAPIResponse(status="1", info="OK", data={"pois": [{"name": "缓存咖啡"}]}, count=1)
    cache.set_cached_response(request, response)

    result = await client.poi_search(keywords="咖啡", city="上海")

    assert result.data["pois"][0]["name"] == "缓存咖啡"

