import json

from fastapi.testclient import TestClient

from app.auth_middleware import get_current_user_id, require_current_user_id
from app.database import create_sqlite_engine, init_db, session_scope
from app.main import create_app
from app.models import PolishedImage, Post


TEST_USER_ID = "test-user-1"


class FakeJimengService:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def polish_image(self, image_url: str, prompt: str) -> str:
        self.calls.append((image_url, prompt))
        return f"https://example.com/polished-{len(self.calls)}.jpg"


def _client_with_post(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        post = Post(
            title="上海静安寺夜拍",
            content="适合朋友晚上拍照吃饭。",
            tags_json=json.dumps(["上海", "静安寺", "拍照"], ensure_ascii=False),
            images_json=json.dumps(["https://example.com/a.jpg"]),
            cover_image="https://example.com/a.jpg",
            source_query="静安寺晚上怎么玩",
            source_type="seed_import",
            status="published",
        )
        session.add(post)
        session.flush()
        post_id = post.id
    app = create_app(engine)
    # Override auth dependencies so tests don't need real Logto JWTs
    app.dependency_overrides[require_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    return TestClient(app), post_id


def test_get_posts_returns_cards(tmp_path):
    client, post_id = _client_with_post(tmp_path)

    response = client.get("/api/posts", params={"user_id": "u1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == post_id
    assert payload["items"][0]["tags"] == ["上海", "静安寺", "拍照"]
    assert payload["items"][0]["is_liked"] is False


def test_get_posts_supports_time_sort_for_new_generated_cards(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        old_post = Post(
            title="旧平台内容",
            content="旧内容",
            tags_json=json.dumps(["上海"], ensure_ascii=False),
            images_json=json.dumps(["https://example.com/old.jpg"]),
            cover_image="https://example.com/old.jpg",
            source_query="旧 query",
            source_type="mongo_import",
            like_count=999,
            favorite_count=999,
            status="published",
        )
        session.add(old_post)
        session.flush()
        new_post = Post(
            title="新生成内容",
            content="新内容",
            tags_json=json.dumps(["上海"], ensure_ascii=False),
            images_json=json.dumps(["https://example.com/new.jpg"]),
            cover_image="https://example.com/new.jpg",
            source_query="新 query",
            source_type="platform_auto",
            status="published",
        )
        session.add(new_post)
        session.flush()
        new_post_id = new_post.id
    client = TestClient(create_app(engine))

    response = client.get("/api/posts", params={"sort": "time", "page_size": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "time"
    assert payload["items"][0]["id"] == new_post_id


def test_get_search_returns_relevant_cards(tmp_path):
    client, post_id = _client_with_post(tmp_path)

    response = client.get("/api/search", params={"query": "静安寺", "user_id": "u1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == post_id


def test_get_post_detail_returns_card(tmp_path):
    client, post_id = _client_with_post(tmp_path)

    response = client.get(f"/api/posts/{post_id}", params={"user_id": "u1"})

    assert response.status_code == 200
    assert response.json()["title"] == "上海静安寺夜拍"


def test_like_toggle_updates_state_and_count(tmp_path):
    client, post_id = _client_with_post(tmp_path)

    liked = client.post(f"/api/posts/{post_id}/like", json={"user_id": "u1"})
    unliked = client.post(f"/api/posts/{post_id}/like", json={"user_id": "u1"})

    assert liked.status_code == 200
    assert liked.json()["is_liked"] is True
    assert liked.json()["like_count"] == 1
    assert unliked.json()["is_liked"] is False
    assert unliked.json()["like_count"] == 0


def test_favorite_toggle_updates_state_and_count(tmp_path):
    client, post_id = _client_with_post(tmp_path)

    favorited = client.post(f"/api/posts/{post_id}/favorite", json={"user_id": "u1"})

    assert favorited.status_code == 200
    assert favorited.json()["is_favorited"] is True
    assert favorited.json()["favorite_count"] == 1


def test_hot_tags_endpoint_returns_ranked_tags(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(
            Post(
                title="A",
                content="内容",
                tags_json=json.dumps(["上海", "情侣约会"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
        session.add(
            Post(
                title="B",
                content="内容",
                tags_json=json.dumps(["上海", "情侣约会", "夜游"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
    client = TestClient(create_app(engine))

    response = client.get("/api/tags/hot", params={"limit": 5})

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0] == {"tag": "情侣约会", "count": 2}
    assert {"tag": "夜游", "count": 1} in items
    assert all(item["tag"] != "上海" for item in items)


def test_start_polish_returns_cached_result_without_calling_jimeng(tmp_path):
    client, post_id = _client_with_post(tmp_path)
    fake_jimeng = FakeJimengService()
    client.app.state.jimeng_service = fake_jimeng
    with session_scope(client.app.state.db_engine) as session:
        session.add(
            PolishedImage(
                post_id=post_id,
                original_url="https://example.com/a.jpg",
                prompt="make it clear",
                polished_url="https://example.com/cached.jpg",
            )
        )

    response = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/a.jpg", "prompt": "make it clear"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "polished_image_url": "https://example.com/cached.jpg",
        "cached": True,
    }
    assert fake_jimeng.calls == []


def test_start_polish_creates_queryable_task(tmp_path):
    client, post_id = _client_with_post(tmp_path)
    client.app.state.jimeng_service = FakeJimengService()

    started = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/a.jpg", "prompt": "make it brighter"},
    )

    assert started.status_code == 200
    payload = started.json()
    assert payload["status"] in {"pending", "running", "success"}
    assert isinstance(payload["polish_request_id"], int)

    status = client.get(f"/api/images/polish/{payload['polish_request_id']}")

    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["polish_request_id"] == payload["polish_request_id"]
    assert status_payload["status"] == "success"
    assert status_payload["polished_image_url"] == "https://example.com/polished-1.jpg"

    cached = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/a.jpg", "prompt": "make it brighter"},
    )

    assert cached.status_code == 200
    assert cached.json()["cached"] is True


def test_polish_gating_returns_402_after_free_limit(tmp_path):
    """Free users get 2 polish uses, then 402 subscription_required."""
    client, post_id = _client_with_post(tmp_path)
    client.app.state.jimeng_service = FakeJimengService()

    # First polish: allowed (free_used 0 -> 1)
    r1 = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/1.jpg", "prompt": "p1"},
    )
    assert r1.status_code == 200

    # Second polish: allowed (free_used 1 -> 2)
    r2 = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/2.jpg", "prompt": "p2"},
    )
    assert r2.status_code == 200

    # Third polish: blocked (free_used=2, limit=2)
    r3 = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/3.jpg", "prompt": "p3"},
    )
    assert r3.status_code == 402
    detail = r3.json()["detail"]
    assert detail["error"] == "subscription_required"
    assert detail["free_used"] == 2
    assert detail["free_limit"] == 2


def test_polish_cache_hit_allowed_after_quota_exhausted(tmp_path):
    """Cache hits don't consume quota - users can still view polished images."""
    client, post_id = _client_with_post(tmp_path)
    client.app.state.jimeng_service = FakeJimengService()

    # Use up free quota
    for i in range(2):
        client.post(
            "/api/images/polish",
            json={"post_id": post_id, "image_url": f"https://example.com/{i}.jpg", "prompt": f"p{i}"},
        )

    # New polish blocked
    r3 = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/3.jpg", "prompt": "p3"},
    )
    assert r3.status_code == 402

    # Cache hit on previously polished image still works
    r_cached = client.post(
        "/api/images/polish",
        json={"post_id": post_id, "image_url": "https://example.com/0.jpg", "prompt": "p0"},
    )
    assert r_cached.status_code == 200
    assert r_cached.json()["cached"] is True
    assert r_cached.json()["polished_image_url"] == "https://example.com/polished-1.jpg"


def test_polish_unauthenticated_returns_401(tmp_path):
    """Polish endpoint requires auth - no Bearer token means 401, not 200."""
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    app = create_app(engine)
    # No dependency_overrides - real auth middleware is active
    client = TestClient(app)

    r = client.post(
        "/api/images/polish",
        json={"image_url": "https://example.com/a.jpg", "prompt": "p"},
    )
    assert r.status_code == 401


def test_polish_with_invalid_bearer_token_returns_401(tmp_path):
    """Polish with a malformed Bearer token returns 401."""
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    app = create_app(engine)
    client = TestClient(app)

    r = client.post(
        "/api/images/polish",
        json={"image_url": "https://example.com/a.jpg", "prompt": "p"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401


def test_auth_me_invalid_bearer_returns_authenticated_false(tmp_path, monkeypatch):
    """Optional auth endpoint must not 401 on bad Bearer — treat as anonymous."""
    monkeypatch.setenv("LOGTO_ENDPOINT", "https://logto.example.com")
    monkeypatch.setenv("LOGTO_APP_ID", "test-app-id")
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    app = create_app(engine)
    client = TestClient(app)

    r = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 200
    assert r.json() == {"authenticated": False}

