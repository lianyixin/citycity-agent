from dataclasses import dataclass
from typing import Sequence
import time

from sqlalchemy import Engine, select
from sqlalchemy.orm import load_only

from app.database import session_scope
from app.feed_ranking import SORT_POPULAR, SORT_RECOMMEND, SORT_TIME, VALID_SORTS, rank_posts
from app.models import Place, Post, PostInteraction
from app.post_visibility import post_is_visible, visible_posts_clause
from app.tags import post_matches_tag


@dataclass(frozen=True)
class PageResult:
    items: Sequence[Post]
    total: int
    page: int
    page_size: int


_LIST_POSTS_CACHE: dict[tuple, tuple[float, list, int]] = {}
_CACHE_TTL = 120.0


class PostRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list_posts(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        sort: str = SORT_RECOMMEND,
        user_lat: float | None = None,
        user_lng: float | None = None,
        tag: str | None = None,
    ) -> PageResult:
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 50)
        offset = (safe_page - 1) * safe_page_size
        safe_sort = sort if sort in VALID_SORTS else SORT_RECOMMEND

        cache_key = (safe_sort, (tag or "").strip(), user_lat, user_lng)
        now = time.monotonic()
        cached = _LIST_POSTS_CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            ranked_ids = cached[1]
            total = cached[2]
        else:
            ranked_ids, total = self._rank_all_posts(safe_sort, user_lat, user_lng, tag)
            _LIST_POSTS_CACHE[cache_key] = (now, ranked_ids, total)

        page_ids = ranked_ids[offset : offset + safe_page_size]
        page_items = self._load_page_items(page_ids) if page_ids else []
        return PageResult(items=page_items, total=total, page=safe_page, page_size=safe_page_size)

    def _rank_all_posts(
        self,
        sort: str,
        user_lat: float | None,
        user_lng: float | None,
        tag: str | None,
    ) -> tuple[list[int], int]:
        with session_scope(self.engine) as session:
            clause = visible_posts_clause()
            query = (
                select(Post)
                .where(Post.status == "published", clause)
                .options(
                    load_only(
                        Post.id,
                        Post.title,
                        # content is required by post_is_visible (blocked-keyword
                        # scan + route_match). Load it here in the single batch
                        # query; omitting it caused a lazy-load per post (N+1) that
                        # dominated cold-cache latency.
                        Post.content,
                        Post.created_at,
                        Post.like_count,
                        Post.favorite_count,
                        Post.source_type,
                        Post.tags_json,
                        Post.images_json,
                        Post.cover_image,
                        Post.source_query,
                        Post.view_count,
                        Post.author_user_id,
                        Post.status,
                    )
                )
            )
            if sort == SORT_TIME:
                query = query.order_by(Post.created_at.desc(), Post.id.desc()).limit(200)
            elif sort == SORT_POPULAR:
                query = query.order_by(
                    (Post.like_count + Post.favorite_count * 1.5).desc(),
                    Post.created_at.desc(),
                    Post.id.desc(),
                ).limit(200)
            else:
                query = query.order_by(Post.created_at.desc()).limit(200)
            items = session.execute(query).scalars().all()

            if items:
                post_ids = [item.id for item in items]
                places_by_post: dict[int, list[Place]] = {pid: [] for pid in post_ids}
                for place in session.execute(
                    select(Place).where(Place.post_id.in_(post_ids))
                ).scalars().all():
                    places_by_post.setdefault(place.post_id, []).append(place)
                for item in items:
                    item.places = places_by_post.get(item.id, [])

            visible_items = [item for item in items if post_is_visible(item)]
            if tag and tag.strip():
                visible_items = [item for item in visible_items if post_matches_tag(item, tag)]
            ranked = rank_posts(visible_items, sort, user_lat=user_lat, user_lng=user_lng)
            return [item.id for item in ranked], len(ranked)

    def _load_page_items(self, post_ids: list[int]) -> list[Post]:
        if not post_ids:
            return []
        with session_scope(self.engine) as session:
            items_by_id = {
                post.id: post
                for post in session.execute(
                    select(Post).where(Post.id.in_(post_ids))
                ).scalars().all()
            }
            places_by_post: dict[int, list[Place]] = {pid: [] for pid in post_ids}
            for place in session.execute(
                select(Place).where(Place.post_id.in_(post_ids))
            ).scalars().all():
                places_by_post.setdefault(place.post_id, []).append(place)
            result: list[Post] = []
            for pid in post_ids:
                post = items_by_id.get(pid)
                if post is None:
                    continue
                post.places = places_by_post.get(pid, [])
                result.append(post)
            return result

    def get_post(self, post_id: int) -> Post | None:
        return self._get_post(post_id, visible_only=True)

    def get_post_any(self, post_id: int) -> Post | None:
        return self._get_post(post_id, visible_only=False)

    def _get_post(self, post_id: int, visible_only: bool) -> Post | None:
        with session_scope(self.engine) as session:
            post = session.get(Post, post_id)
            if post is None:
                return None

            places = session.execute(select(Place).where(Place.post_id == post.id)).scalars().all()
            post.places = list(places)
            if visible_only and not post_is_visible(post):
                return None
            return post

    def get_interaction(self, post_id: int, user_id: str) -> PostInteraction | None:
        with session_scope(self.engine) as session:
            return session.execute(
                select(PostInteraction).where(
                    PostInteraction.post_id == post_id,
                    PostInteraction.user_id == user_id,
                )
            ).scalar_one_or_none()

    def get_interactions_batch(
        self, post_ids: list[int], user_id: str | None
    ) -> dict[int, PostInteraction]:
        if not user_id or not post_ids:
            return {}
        with session_scope(self.engine) as session:
            rows = session.execute(
                select(PostInteraction).where(
                    PostInteraction.post_id.in_(post_ids),
                    PostInteraction.user_id == user_id,
                )
            ).scalars().all()
            return {row.post_id: row for row in rows}

    def toggle_like(self, post_id: int, user_id: str) -> tuple[bool, int]:
        with session_scope(self.engine) as session:
            post = session.get(Post, post_id)
            if post is None:
                raise ValueError("post_not_found")
            interaction = _get_or_create_interaction(session, post_id, user_id)
            interaction.liked = not interaction.liked
            post.like_count = max(0, post.like_count + (1 if interaction.liked else -1))
            session.flush()
            return interaction.liked, post.like_count

    def toggle_favorite(self, post_id: int, user_id: str) -> tuple[bool, int]:
        with session_scope(self.engine) as session:
            post = session.get(Post, post_id)
            if post is None:
                raise ValueError("post_not_found")
            interaction = _get_or_create_interaction(session, post_id, user_id)
            interaction.favorited = not interaction.favorited
            post.favorite_count = max(0, post.favorite_count + (1 if interaction.favorited else -1))
            session.flush()
            return interaction.favorited, post.favorite_count


def _get_or_create_interaction(session, post_id: int, user_id: str) -> PostInteraction:
    interaction = session.execute(
        select(PostInteraction).where(
            PostInteraction.post_id == post_id,
            PostInteraction.user_id == user_id,
        )
    ).scalar_one_or_none()
    if interaction is None:
        interaction = PostInteraction(post_id=post_id, user_id=user_id)
        session.add(interaction)
        session.flush()
    return interaction

