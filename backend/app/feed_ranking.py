from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Sequence

from app.geo_utils import haversine_meters

SORT_RECOMMEND = "recommend"
SORT_TIME = "time"
SORT_POPULAR = "popular"
SORT_DISTANCE = "distance"

VALID_SORTS = {SORT_RECOMMEND, SORT_TIME, SORT_POPULAR, SORT_DISTANCE}

WEIGHT_TIME = 0.30
WEIGHT_POPULAR = 0.30
WEIGHT_DISTANCE = 0.25
WEIGHT_USER_GENERATED = 0.15


def post_min_distance_meters(places: Sequence[Any], user_lat: float, user_lng: float) -> float | None:
    distances: list[float] = []
    for place in places:
        lat = getattr(place, "lat", None)
        lng = getattr(place, "lng", None)
        if lat is None or lng is None:
            continue
        distances.append(haversine_meters(user_lat, user_lng, float(lat), float(lng)))
    return min(distances) if distances else None


def popularity_raw(like_count: int, favorite_count: int) -> float:
    return float(like_count) + float(favorite_count) * 1.5


def recency_raw(created_at: datetime, now: datetime) -> float:
    age_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
    return 1.0 / (1.0 + age_hours / 24.0)


def distance_score(meters: float | None) -> float | None:
    if meters is None:
        return None
    return 1.0 / (1.0 + meters / 3000.0)


def _normalize(values: list[float | None], *, missing: float = 0.0) -> list[float]:
    nums = [value for value in values if value is not None]
    if not nums:
        return [missing] * len(values)
    low, high = min(nums), max(nums)
    if math.isclose(low, high):
        return [1.0 if value is not None else missing for value in values]
    return [
        missing if value is None else (value - low) / (high - low)
        for value in values
    ]


def _distance_sort_key(post: Any, user_lat: float, user_lng: float) -> tuple[bool, float, int]:
    distance = post_min_distance_meters(getattr(post, "places", None) or [], user_lat, user_lng)
    if distance is None:
        return (True, float("inf"), -post.id)
    return (False, distance, -post.id)


def user_generated_raw(source_type: str) -> float:
    return 1.0 if source_type == "user_generated" else 0.0


def rank_posts(
    posts: Sequence[Any],
    sort: str = SORT_RECOMMEND,
    *,
    user_lat: float | None = None,
    user_lng: float | None = None,
    now: datetime | None = None,
) -> list[Any]:
    if not posts:
        return []
    safe_sort = sort if sort in VALID_SORTS else SORT_RECOMMEND
    current = now or datetime.utcnow()
    has_location = user_lat is not None and user_lng is not None
    post_list = list(posts)

    if safe_sort == SORT_TIME:
        return sorted(post_list, key=lambda post: (post.created_at, post.id), reverse=True)

    if safe_sort == SORT_POPULAR:
        return sorted(
            post_list,
            key=lambda post: (popularity_raw(post.like_count, post.favorite_count), post.created_at, post.id),
            reverse=True,
        )

    distances: list[float | None] = []
    if has_location:
        for post in post_list:
            places = getattr(post, "places", None) or []
            distances.append(post_min_distance_meters(places, float(user_lat), float(user_lng)))
    else:
        distances = [None] * len(post_list)

    if safe_sort == SORT_DISTANCE:
        if not has_location:
            return sorted(post_list, key=lambda post: (post.created_at, post.id), reverse=True)
        return sorted(
            post_list,
            key=lambda post: _distance_sort_key(post, float(user_lat), float(user_lng)),
        )

    recency = [recency_raw(post.created_at, current) for post in post_list]
    popular = [popularity_raw(post.like_count, post.favorite_count) for post in post_list]
    dist_values = [distance_score(distance) for distance in distances]
    user_generated = [user_generated_raw(getattr(post, "source_type", "")) for post in post_list]

    recency_n = _normalize(recency)
    popular_n = _normalize(popular)
    user_generated_n = _normalize(user_generated)
    if has_location:
        dist_n = _normalize(dist_values, missing=0.0)
        weight_time = WEIGHT_TIME
        weight_popular = WEIGHT_POPULAR
        weight_distance = WEIGHT_DISTANCE
        weight_user_generated = WEIGHT_USER_GENERATED
    else:
        dist_n = [0.0] * len(post_list)
        total = WEIGHT_TIME + WEIGHT_POPULAR + WEIGHT_USER_GENERATED
        weight_time = WEIGHT_TIME / total
        weight_popular = WEIGHT_POPULAR / total
        weight_distance = 0.0
        weight_user_generated = WEIGHT_USER_GENERATED / total

    scored: list[tuple[float, datetime, int, Any]] = []
    for index, post in enumerate(post_list):
        score = (
            weight_time * recency_n[index]
            + weight_popular * popular_n[index]
            + weight_distance * dist_n[index]
            + weight_user_generated * user_generated_n[index]
        )
        scored.append((score, post.created_at, post.id, post))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in scored]
