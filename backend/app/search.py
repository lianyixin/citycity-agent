import json
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Engine, select

from app.database import session_scope
from app.models import Place, Post
from app.post_visibility import post_is_visible


@dataclass(frozen=True)
class SearchResult:
    items: Sequence[Post]
    total: int
    page: int
    page_size: int


def search_posts(
    engine: Engine,
    query: str | None = None,
    tag: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchResult:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 50)
    normalized_query = (query or "").strip().lower()
    normalized_tag = (tag or "").strip().lower()

    with session_scope(engine) as session:
        posts = session.execute(
            select(Post).where(Post.status == "published")
        ).scalars().all()
        
        # Load places for all visible posts
        for post in posts:
            places = session.execute(select(Place).where(Place.post_id == post.id)).scalars().all()
            post.places = list(places)

    scored = []
    for post in posts:
        if not post_is_visible(post):
            continue
        score = _score_post(post, normalized_query, normalized_tag)
        if score is not None:
            scored.append((score, post))

    scored.sort(key=lambda item: (item[0], item[1].like_count, item[1].id), reverse=True)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return SearchResult(
        items=[post for _, post in scored[start:end]],
        total=len(scored),
        page=safe_page,
        page_size=safe_page_size,
    )


def _score_post(post: Post, query: str, tag: str) -> int | None:
    tags = [str(item).lower() for item in _loads_list(post.tags_json)]
    if tag and not any(tag in item for item in tags):
        return None

    if not query:
        return 1

    title = post.title.lower()
    content = post.content.lower()
    source_query = (post.source_query or "").lower()

    score = 0
    if query in title:
        score += 100
    if any(query in item for item in tags):
        score += 80
    if query in source_query:
        score += 60
    if query in content:
        score += 30

    return score if score > 0 else None


def _loads_list(raw: str) -> list:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []

