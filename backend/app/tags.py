import json
import os
from collections import Counter

from sqlalchemy import Engine, select

from app.database import session_scope
from app.models import Place, Post
from app.post_visibility import post_is_visible
from app.tag_catalog import canonicalize_tag

DEFAULT_EXCLUDED_TAGS = frozenset({os.getenv("DEFAULT_CITY", "上海").strip() or "上海"})


def get_hot_tags(
    engine: Engine,
    *,
    limit: int = 12,
    exclude: frozenset[str] | None = None,
) -> list[dict[str, int | str]]:
    excluded = exclude if exclude is not None else DEFAULT_EXCLUDED_TAGS
    safe_limit = min(max(limit, 1), 30)

    with session_scope(engine) as session:
        posts = session.execute(
            select(Post).where(Post.status == "published")
        ).scalars().all()
        for post in posts:
            places = session.execute(select(Place).where(Place.post_id == post.id)).scalars().all()
            post.places = list(places)

    counter: Counter[str] = Counter()
    for post in posts:
        if not post_is_visible(post):
            continue
        for tag in _loads_tags(post.tags_json):
            normalized = canonicalize_tag(str(tag).strip())
            if not normalized or normalized in excluded:
                continue
            counter[normalized] += 1

    return [
        {"tag": tag, "count": count}
        for tag, count in counter.most_common(safe_limit)
    ]


def post_matches_tag(post: Post, tag: str | None) -> bool:
    normalized_tag = canonicalize_tag(str(tag or "").strip()).lower()
    if not normalized_tag:
        return True
    tags = [canonicalize_tag(str(item).strip()).lower() for item in _loads_tags(post.tags_json)]
    return any(normalized_tag in item for item in tags)


def _loads_tags(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
