import os
from typing import Any

import httpx

from app.amap_cache import SQLiteAmapCache
from app.amap_models import AmapAPIRequest, AmapAPIResponse, AmapAPIType


class AmapAPIException(Exception):
    pass


class AmapQuotaExceededException(AmapAPIException):
    pass


_DEFAULT_AMAP_BASE_URL = "https://restapi.amap.com/v3"


class AmapAPIClient:
    def __init__(
        self,
        api_key: str | None = None,
        cache: SQLiteAmapCache | None = None,
        base_url: str | None = None,
        proxy_token: str | None = None,
    ):
        self.api_key = api_key or os.getenv("AMAP_API_KEY", "")
        self.cache = cache
        resolved_base_url = base_url or os.getenv("AMAP_BASE_URL", "") or _DEFAULT_AMAP_BASE_URL
        self.base_url = resolved_base_url.rstrip("/")
        self.proxy_token = proxy_token if proxy_token is not None else os.getenv("AMAP_PROXY_TOKEN", "")

    @property
    def uses_proxy(self) -> bool:
        return bool(self.proxy_token) or self.base_url.rstrip("/") != _DEFAULT_AMAP_BASE_URL

    async def poi_search(
        self,
        keywords: str,
        location: str | None = None,
        city: str | None = None,
        radius: int = 3000,
        limit: int = 20,
        use_cache: bool = True,
    ) -> AmapAPIResponse:
        params: dict[str, Any] = {
            "key": self.api_key,
            "keywords": keywords,
            "offset": limit,
            "page": 1,
            "extensions": "all",
        }
        if location:
            params["location"] = location
            params["radius"] = radius
        elif city:
            params["city"] = city
        return await self._call_with_cache("/place/text", AmapAPIType.POI_SEARCH, params, use_cache)

    async def poi_detail(self, poi_id: str, use_cache: bool = True) -> AmapAPIResponse:
        params = {"key": self.api_key, "id": poi_id, "extensions": "all"}
        return await self._call_with_cache("/place/detail", AmapAPIType.POI_DETAIL, params, use_cache)

    async def geocode(self, address: str, city: str | None = None, use_cache: bool = True) -> AmapAPIResponse:
        params = {"key": self.api_key, "address": address}
        if city:
            params["city"] = city
        return await self._call_with_cache("/geocode/geo", AmapAPIType.GEOCODE, params, use_cache)

    async def reverse_geocode(self, location: str, use_cache: bool = True) -> AmapAPIResponse:
        params = {"key": self.api_key, "location": location}
        return await self._call_with_cache("/geocode/regeo", AmapAPIType.REVERSE_GEOCODE, params, use_cache)

    async def _call_with_cache(
        self,
        endpoint: str,
        api_type: AmapAPIType,
        params: dict[str, Any],
        use_cache: bool,
    ) -> AmapAPIResponse:
        request = AmapAPIRequest(api_type=api_type, params=params)
        if use_cache and self.cache:
            cached = self.cache.get_cached_response(request)
            if cached:
                return cached
        response = await self._call_api(endpoint, params)
        if use_cache and self.cache:
            self.cache.set_cached_response(request, response)
        return response

    async def _call_api(self, endpoint: str, params: dict[str, Any]) -> AmapAPIResponse:
        # When routing through the Amap proxy gateway, the real key is injected
        # server-side, so a local AMAP_API_KEY is not required.
        if not self.api_key and not self.uses_proxy:
            raise AmapAPIException("AMAP_API_KEY is required")
        headers: dict[str, str] = {}
        if self.proxy_token:
            headers["X-Amap-Proxy-Token"] = self.proxy_token
        async with httpx.AsyncClient(timeout=60.0) as client:
            result = await client.get(f"{self.base_url}{endpoint}", params=params, headers=headers)
            result.raise_for_status()
        payload = result.json()
        response = AmapAPIResponse(
            status=str(payload.get("status", "")),
            info=str(payload.get("info", "")),
            data=payload,
            count=_parse_count(payload.get("count")),
        )
        if response.is_quota_exceeded():
            raise AmapQuotaExceededException(response.info)
        # Amap returns status="1" for success, including "0 results" (count=0).
        # status="0" is always a hard failure (e.g. INVALID_USER_IP,
        # INVALID_USER_KEY). Surface it instead of silently returning an empty
        # result that would masquerade as "no POIs found" downstream.
        if not response.is_success():
            raise AmapAPIException(f"Amap API error: {response.info or 'unknown'} (status={response.status})")
        return response


def _parse_count(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

