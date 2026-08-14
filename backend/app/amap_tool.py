import os
from typing import Any

from app.agent_models import POICategory, POIInfo
from app.amap_client import AmapAPIClient


class AmapTool:
    def __init__(self, client: AmapAPIClient):
        self.client = client

    async def search_pois(
        self,
        query: str,
        location: str | None = None,
        city: str | None = None,
        radius: int = 3000,
        limit: int = 10,
    ) -> list[POIInfo]:
        response = await self.client.poi_search(
            keywords=query,
            location=location,
            city=city or _default_city(),
            radius=radius,
            limit=limit,
        )
        pois = response.data.get("pois", [])
        return [_poi_from_amap(item) for item in pois[:limit]]

    async def suggest_locations(
        self,
        query: str | None = None,
        location: str | None = None,
        city: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        city = city or _default_city()
        if query and query.strip():
            geocode_response = await self.client.geocode(query.strip(), city=city)
            suggestions = _suggestions_from_geocode(geocode_response.data, "geocode")
            poi_response = await self.client.poi_search(
                keywords=query.strip(),
                city=city,
                limit=limit,
                radius=3000,
            )
            suggestions.extend(_suggestions_from_pois(poi_response.data, "poi"))
            return _dedupe_suggestions(suggestions)[:limit]

        if location:
            response = await self.client.reverse_geocode(location)
            suggestion = _suggestion_from_reverse_geocode(response.data)
            return [suggestion] if suggestion else []

        return []


def _default_city() -> str:
    return os.getenv("DEFAULT_CITY", "上海").strip() or "上海"


def _poi_from_amap(item: dict[str, Any]) -> POIInfo:
    lng, lat = _parse_location(item.get("location"))
    biz_ext = item.get("biz_ext") if isinstance(item.get("biz_ext"), dict) else {}
    photos = item.get("photos") if isinstance(item.get("photos"), list) else []
    photo_urls = [photo.get("url") for photo in photos if isinstance(photo, dict) and photo.get("url")]
    return POIInfo(
        name=str(item.get("name") or ""),
        address=str(item.get("address") or ""),
        latitude=lat,
        longitude=lng,
        category=_category_from_type(str(item.get("type") or "")),
        rating=_parse_float(biz_ext.get("rating")),
        cost_per_person=str(biz_ext.get("cost")) if biz_ext.get("cost") else None,
        photos=photo_urls,
        business_area=str(item.get("business_area") or ""),
        type_code=str(item.get("typecode") or ""),
        amap_poi_id=str(item.get("id") or ""),
        source="amap",
        biz_ext=biz_ext,
    )


def _suggestions_from_geocode(data: dict[str, Any], source: str) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    geocodes = data.get("geocodes") if isinstance(data, dict) else []
    if not isinstance(geocodes, list):
        return suggestions
    for item in geocodes:
        if not isinstance(item, dict):
            continue
        lng, lat = _parse_location(item.get("location"))
        if not lat or not lng:
            continue
        suggestions.append(
            {
                "name": str(item.get("formatted_address") or item.get("district") or item.get("address") or ""),
                "address": str(item.get("formatted_address") or ""),
                "lat": lat,
                "lng": lng,
                "source": source,
                "amap_id": None,
            }
        )
    return suggestions


def _suggestions_from_pois(data: dict[str, Any], source: str) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    pois = data.get("pois") if isinstance(data, dict) else []
    if not isinstance(pois, list):
        return suggestions
    for item in pois:
        if not isinstance(item, dict):
            continue
        lng, lat = _parse_location(item.get("location"))
        if not lat or not lng:
            continue
        suggestions.append(
            {
                "name": str(item.get("name") or ""),
                "address": str(item.get("address") or ""),
                "lat": lat,
                "lng": lng,
                "source": source,
                "amap_id": str(item.get("id") or "") or None,
            }
        )
    return suggestions


def _suggestion_from_reverse_geocode(data: dict[str, Any]) -> dict[str, object] | None:
    regeocode = data.get("regeocode") if isinstance(data, dict) else None
    if not isinstance(regeocode, dict):
        return None
    address = str(regeocode.get("formatted_address") or "")
    component = regeocode.get("addressComponent") if isinstance(regeocode.get("addressComponent"), dict) else {}
    name = str(component.get("township") or component.get("district") or address or "当前位置")
    location = data.get("location") or ""
    lng, lat = _parse_location(location)
    if not lat or not lng:
        return None
    return {"name": name, "address": address, "lat": lat, "lng": lng, "source": "reverse_geocode", "amap_id": None}


def _dedupe_suggestions(suggestions: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in suggestions:
        key = (str(item.get("name") or ""), f"{float(item.get('lat') or 0):.5f},{float(item.get('lng') or 0):.5f}")
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _parse_location(raw: Any) -> tuple[float, float]:
    if not raw:
        return 0.0, 0.0
    parts = str(raw).split(",")
    if len(parts) != 2:
        return 0.0, 0.0
    return _parse_float(parts[0]), _parse_float(parts[1])


def _parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _category_from_type(type_text: str) -> POICategory:
    text = type_text.lower()
    if "餐饮" in text or "restaurant" in text:
        return POICategory.RESTAURANT
    if "购物" in text:
        return POICategory.SHOPPING
    if "体育" in text or "运动" in text:
        return POICategory.SPORTS
    if "科教" in text or "文化" in text or "博物" in text or "艺术" in text:
        return POICategory.CULTURE
    if "风景" in text or "公园" in text or "旅游" in text:
        return POICategory.TOURISM
    if "娱乐" in text or "酒吧" in text:
        return POICategory.ENTERTAINMENT
    return POICategory.OTHER

