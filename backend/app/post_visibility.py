import json
from collections import OrderedDict
from typing import Any

from sqlalchemy import and_, or_, inspect

from app.models import Post
from app.post_images import post_has_displayable_images

BLOCKED_KEYWORDS = ("罗森",)
BLOCKED_PATTERNS = ("全家便利", "FamilyMart", "familymart")

# route_groups_payload is an expensive pure function of (content, places) and is
# invoked once per post during feed ranking. On a cold feed cache this runs for
# ~200 posts and dominated latency. Memoize by a stable signature so repeated
# cold-cache rebuilds (feed recomputes every 120s) reuse prior results.
_ROUTE_GROUP_COUNT_CACHE: "OrderedDict[str, int]" = OrderedDict()
_ROUTE_GROUP_COUNT_CACHE_MAX = 1024


def text_contains_blocked_keyword(text: str) -> bool:
    normalized = text or ""
    return any(keyword in normalized for keyword in BLOCKED_KEYWORDS) or any(
        pattern in normalized for pattern in BLOCKED_PATTERNS
    )


def _tags_text(tags_json: str) -> str:
    try:
        raw = json.loads(tags_json or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(raw, list):
        return ""
    return " ".join(str(item) for item in raw)


def play_method_count(post: Post) -> int:
    state = inspect(post)
    if state is not None and "places" in state.unloaded:
        return 0
    places = state.dict.get("places", []) if state is not None else []
    method_orders = {int(place.method_order) for place in places if int(place.method_order or 0) > 0}
    if method_orders:
        return len(method_orders)

    if places:
        place_dicts: list[dict[str, Any]] = [
            {
                "name": place.name,
                "lat": place.lat,
                "lng": place.lng,
                "method_order": place.method_order,
                "method_title": place.method_title,
                "step_order": place.step_order,
            }
            for place in places
            if place.lat and place.lng
        ]
        if place_dicts:
            cache_key = _route_group_cache_key(post.content, place_dicts)
            cached = _ROUTE_GROUP_COUNT_CACHE.get(cache_key)
            if cached is not None:
                _ROUTE_GROUP_COUNT_CACHE.move_to_end(cache_key)
                return cached

            from app.route_match import route_groups_payload

            groups = route_groups_payload(post.content, place_dicts)
            count = len(groups) if groups else 0
            _ROUTE_GROUP_COUNT_CACHE[cache_key] = count
            _ROUTE_GROUP_COUNT_CACHE.move_to_end(cache_key)
            if len(_ROUTE_GROUP_COUNT_CACHE) > _ROUTE_GROUP_COUNT_CACHE_MAX:
                _ROUTE_GROUP_COUNT_CACHE.popitem(last=False)
            return count if count else 0
    return 0


def _route_group_cache_key(content: str, place_dicts: list[dict[str, Any]]) -> str:
    import hashlib

    signature = {
        "content": content or "",
        "places": [
            [pd.get("name"), pd.get("lat"), pd.get("lng"), pd.get("step_order")]
            for pd in place_dicts
        ],
    }
    raw = json.dumps(signature, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def post_is_visible(post: Post) -> bool:
    if not post_has_displayable_images(post):
        return False
    fields = (
        post.title,
        post.content,
        _tags_text(post.tags_json),
        post.source_query or "",
    )
    if any(text_contains_blocked_keyword(field) for field in fields):
        return False
    return play_method_count(post) != 1


def publish_content_is_visible(
    title: str,
    content: str,
    tags: list[str],
    source_query: str | None = None,
) -> bool:
    fields = (title, content, " ".join(tags), source_query or "")
    return not any(text_contains_blocked_keyword(field) for field in fields)


def visible_posts_clause():
    clauses = [~Post.images_json.contains("byteimg.com")]
    for keyword in (*BLOCKED_KEYWORDS, *BLOCKED_PATTERNS):
        clauses.append(~Post.title.contains(keyword))
        clauses.append(~Post.content.contains(keyword))
        clauses.append(~Post.tags_json.contains(keyword))
        clauses.append(
            or_(Post.source_query.is_(None), ~Post.source_query.contains(keyword))
        )
    return and_(*clauses)
