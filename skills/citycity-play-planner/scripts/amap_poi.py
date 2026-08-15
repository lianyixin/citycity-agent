#!/usr/bin/env python3
"""Amap POI search and geocoding for the citycity-play-planner skill.

Requires AMAP_API_KEY. Optional: AMAP_BASE_URL, AMAP_PROXY_TOKEN, DEFAULT_CITY.

    python3 amap_poi.py geocode --address 静安寺 --city 上海
    python3 amap_poi.py search --keywords "咖啡 街区" --location 121.4453,31.2237 --radius 5000
"""

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://restapi.amap.com/v3"
QUOTA_CODES = {"DAILY_QUERY_OVER_LIMIT", "CUQPS_HAS_EXCEEDED_THE_LIMIT", "OVER_QUOTA"}

EXIT_CONFIG = 2
EXIT_API = 3
EXIT_NETWORK = 4


class AmapError(Exception):
    def __init__(self, message, exit_code=EXIT_API):
        super().__init__(message)
        self.exit_code = exit_code


def call_amap(endpoint, params):
    api_key = os.getenv("AMAP_API_KEY", "").strip()
    proxy_token = os.getenv("AMAP_PROXY_TOKEN", "").strip()
    base_url = (os.getenv("AMAP_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")

    if not api_key and not proxy_token and base_url == DEFAULT_BASE_URL:
        raise AmapError(
            "AMAP_API_KEY is not set. Ask the user for an Amap Web Service key "
            "instead of answering from memory.",
            EXIT_CONFIG,
        )

    query = {key: value for key, value in params.items() if value not in (None, "")}
    query["key"] = api_key
    url = "%s%s?%s" % (base_url, endpoint, urllib.parse.urlencode(query))
    request = urllib.request.Request(url)
    if proxy_token:
        request.add_header("X-Amap-Proxy-Token", proxy_token)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AmapError("Amap HTTP error %s" % exc.code, EXIT_NETWORK)
    except urllib.error.URLError as exc:
        raise AmapError("Cannot reach the Amap API: %s" % exc.reason, EXIT_NETWORK)
    except ValueError:
        raise AmapError("Amap returned a malformed response", EXIT_API)

    info = str(payload.get("info") or "")
    # Amap uses status="1" for success, including zero results. status="0" is a hard failure.
    if str(payload.get("status")) != "1":
        if info in QUOTA_CODES:
            raise AmapError("Amap quota exceeded (%s). Retry later or use another key." % info)
        raise AmapError("Amap API error: %s" % (info or "unknown"))
    return payload


def haversine_meters(lat1, lng1, lat2, lng2):
    radius = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)))


def parse_location(raw):
    parts = str(raw or "").split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def category_from_type(type_text):
    text = str(type_text or "")
    if "餐饮" in text:
        return "restaurant"
    if "购物" in text:
        return "shopping"
    if "体育" in text or "运动" in text:
        return "sports"
    if "科教" in text or "文化" in text or "博物" in text or "艺术" in text:
        return "culture"
    if "风景" in text or "公园" in text or "旅游" in text:
        return "tourism"
    if "娱乐" in text or "酒吧" in text:
        return "entertainment"
    return "other"


def normalize_poi(item, center):
    lng, lat = parse_location(item.get("location"))
    biz_ext = item.get("biz_ext") if isinstance(item.get("biz_ext"), dict) else {}
    photos = item.get("photos") if isinstance(item.get("photos"), list) else []
    photo_urls = [photo.get("url") for photo in photos if isinstance(photo, dict) and photo.get("url")]

    poi = {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "address": str(item.get("address") or ""),
        "category": category_from_type(item.get("type")),
        "type": str(item.get("type") or ""),
        "rating": to_float(biz_ext.get("rating")),
        "cost_per_person": str(biz_ext.get("cost")) if biz_ext.get("cost") else None,
        "business_area": str(item.get("business_area") or ""),
        "tel": str(item.get("tel") or ""),
        "lat": lat,
        "lng": lng,
        "photos": photo_urls[:6],
        "opentime": str(biz_ext.get("opentime") or item.get("business") or "") or None,
        "tag": str(item.get("tag") or ""),
        "distance_meters": None,
    }
    if center and lat and lng:
        poi["distance_meters"] = haversine_meters(center[0], center[1], lat, lng)
    return poi


def resolve_center(location_arg):
    """An agent cannot read the user's GPS, so fall back to the configured home base."""
    if location_arg:
        lng, lat = parse_location(location_arg)
        if lat is None or lng is None:
            raise AmapError("--location must be 'lng,lat'", EXIT_CONFIG)
        return (lat, lng), location_arg, "argument"

    env_lat = to_float(os.getenv("DEFAULT_CITY_LAT"))
    env_lng = to_float(os.getenv("DEFAULT_CITY_LNG"))
    if env_lat is not None and env_lng is not None:
        return (env_lat, env_lng), "%s,%s" % (env_lng, env_lat), "DEFAULT_CITY_LAT/LNG"

    return None, None, None


def command_search(args):
    center, location, center_source = resolve_center(args.location)
    city = args.city or os.getenv("DEFAULT_CITY", "").strip()

    if not center and not city:
        raise AmapError(
            "No search center and no city. Pass --location or --city, or set DEFAULT_CITY "
            "(optionally DEFAULT_CITY_LAT/DEFAULT_CITY_LNG). Ask the user where they are "
            "instead of guessing a city.",
            EXIT_CONFIG,
        )

    params = {
        "keywords": args.keywords,
        "offset": args.limit,
        "page": 1,
        "extensions": "all",
    }
    if center:
        params["location"] = location
        params["radius"] = args.radius
    else:
        params["city"] = city

    payload = call_amap("/place/text", params)
    raw_pois = payload.get("pois") if isinstance(payload.get("pois"), list) else []
    pois = [normalize_poi(item, center) for item in raw_pois[: args.limit] if isinstance(item, dict)]
    if center:
        pois.sort(key=lambda poi: poi["distance_meters"] if poi["distance_meters"] is not None else 10**9)

    return {
        "query": args.keywords,
        "center": location,
        "center_source": center_source,
        "city": city or None,
        "radius": args.radius if center else None,
        "count": len(pois),
        "pois": pois,
    }


def command_geocode(args):
    city = args.city or os.getenv("DEFAULT_CITY", "").strip()
    payload = call_amap("/geocode/geo", {"address": args.address, "city": city})
    geocodes = payload.get("geocodes") if isinstance(payload.get("geocodes"), list) else []

    results = []
    for item in geocodes:
        if not isinstance(item, dict):
            continue
        lng, lat = parse_location(item.get("location"))
        if lat is None or lng is None:
            continue
        results.append(
            {
                "name": str(item.get("formatted_address") or args.address),
                "city": str(item.get("city") or ""),
                "district": str(item.get("district") or ""),
                "lat": lat,
                "lng": lng,
                "location": "%s,%s" % (lng, lat),
            }
        )

    return {"address": args.address, "count": len(results), "results": results}


def build_parser():
    parser = argparse.ArgumentParser(description="Amap POI search and geocoding")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    search = subparsers.add_parser("search", help="Search POIs by keywords")
    search.add_argument("--keywords", required=True, help="Space-separated map search terms")
    search.add_argument("--location", help="Search center as 'lng,lat'")
    search.add_argument("--city", help="City name, used when no center is given")
    search.add_argument("--radius", type=int, default=5000, help="Search radius in meters")
    search.add_argument("--limit", type=int, default=12, help="Maximum candidates to return")
    search.set_defaults(handler=command_search)

    geocode = subparsers.add_parser("geocode", help="Resolve an address to coordinates")
    geocode.add_argument("--address", required=True)
    geocode.add_argument("--city")
    geocode.set_defaults(handler=command_geocode)

    return parser


def write(stream, text):
    # Results contain Chinese place names, which break on ASCII-configured terminals.
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text + "\n")
    else:
        buffer.write((text + "\n").encode("utf-8"))
        buffer.flush()


def main():
    args = build_parser().parse_args()
    try:
        result = args.handler(args)
    except AmapError as exc:
        write(sys.stderr, json.dumps({"error": str(exc)}, ensure_ascii=False))
        return exc.exit_code
    write(sys.stdout, json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
