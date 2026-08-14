from datetime import datetime, timedelta

from app.feed_ranking import SORT_DISTANCE, SORT_POPULAR, SORT_RECOMMEND, SORT_TIME, rank_posts


class FakePlace:
    def __init__(self, lat: float, lng: float):
        self.lat = lat
        self.lng = lng


class FakePost:
    def __init__(
        self,
        post_id: int,
        *,
        created_at: datetime,
        like_count: int = 0,
        favorite_count: int = 0,
        places: list[FakePlace] | None = None,
        source_type: str = "seed_import",
    ):
        self.id = post_id
        self.created_at = created_at
        self.like_count = like_count
        self.favorite_count = favorite_count
        self.places = places or []
        self.source_type = source_type


def test_rank_posts_by_time():
    now = datetime.utcnow()
    posts = [
        FakePost(1, created_at=now - timedelta(days=2)),
        FakePost(2, created_at=now - timedelta(hours=1)),
    ]

    ranked = rank_posts(posts, SORT_TIME)

    assert [post.id for post in ranked] == [2, 1]


def test_rank_posts_by_popularity():
    now = datetime.utcnow()
    posts = [
        FakePost(1, created_at=now, like_count=2, favorite_count=0),
        FakePost(2, created_at=now, like_count=10, favorite_count=2),
    ]

    ranked = rank_posts(posts, SORT_POPULAR)

    assert ranked[0].id == 2


def test_rank_posts_by_distance():
    now = datetime.utcnow()
    posts = [
        FakePost(1, created_at=now, places=[FakePlace(31.23, 121.47)]),
        FakePost(2, created_at=now, places=[FakePlace(31.20, 121.44)]),
    ]

    ranked = rank_posts(posts, SORT_DISTANCE, user_lat=31.20, user_lng=121.44)

    assert ranked[0].id == 2


def test_recommend_boosts_user_generated_posts():
    now = datetime.utcnow()
    posts = [
        FakePost(1, created_at=now, like_count=5, favorite_count=0, source_type="seed_import"),
        FakePost(2, created_at=now, like_count=5, favorite_count=0, source_type="user_generated"),
    ]

    ranked = rank_posts(posts, SORT_RECOMMEND)

    assert ranked[0].id == 2


def test_recommend_uses_weighted_score_with_location():
    now = datetime.utcnow()
    posts = [
        FakePost(1, created_at=now - timedelta(days=7), like_count=1, places=[FakePlace(31.30, 121.50)]),
        FakePost(2, created_at=now, like_count=20, places=[FakePlace(31.20, 121.44)]),
        FakePost(3, created_at=now - timedelta(hours=2), like_count=5, places=[FakePlace(31.201, 121.441)]),
    ]

    ranked = rank_posts(posts, SORT_RECOMMEND, user_lat=31.20, user_lng=121.44)

    assert ranked[0].id in {2, 3}
    assert ranked[-1].id == 1
