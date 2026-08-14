import json

from app.database import create_sqlite_engine, init_db, session_scope
from app.models import Post
from app.repositories import PostRepository
from app.search import search_posts


def _add_post(session, title, content, tags, source_query=None, like_count=0, images_json="[]"):
    post = Post(
        title=title,
        content=content,
        tags_json=json.dumps(tags, ensure_ascii=False),
        images_json=images_json,
        source_query=source_query,
        source_type="seed_import",
        status="published",
        like_count=like_count,
    )
    session.add(post)
    session.flush()
    return post


def test_post_repository_lists_published_posts_with_pagination(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        _add_post(session, "第一篇", "内容", ["上海"])
        _add_post(session, "第二篇", "内容", ["上海"])
        _add_post(session, "草稿", "内容", ["上海"]).status = "failed"

    repo = PostRepository(engine)
    result = repo.list_posts(page=1, page_size=1)

    assert result.total == 2
    assert len(result.items) == 1
    assert result.items[0].status == "published"


def test_post_repository_gets_detail(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        post = _add_post(session, "上海夜游", "江边散步", ["夜景"])
        post_id = post.id

    repo = PostRepository(engine)

    assert repo.get_post(post_id).title == "上海夜游"
    assert repo.get_post(99999) is None


def test_search_posts_ranks_title_and_tag_matches_above_content_only(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        _add_post(session, "上海静安寺拍照", "适合周末", ["上海"], like_count=0)
        _add_post(session, "周末放松", "静安寺附近可以拍照", ["上海"], like_count=50)
        _add_post(session, "美食路线", "适合朋友", ["静安寺"], like_count=0)
        _add_post(session, "无关内容", "浦东散步", ["夜景"], like_count=100)

    results = search_posts(engine, query="静安寺", page=1, page_size=10)

    assert results.total == 3
    assert [post.title for post in results.items] == ["上海静安寺拍照", "美食路线", "周末放松"]


def test_search_posts_can_filter_by_tag(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        _add_post(session, "夜游", "内容", ["夜景"])
        _add_post(session, "亲子", "内容", ["亲子"])

    results = search_posts(engine, tag="亲子", page=1, page_size=10)

    assert results.total == 1
    assert results.items[0].title == "亲子"


def test_posts_with_expired_polish_images_are_hidden(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    expired = json.dumps(
        [
            "https://p26-aiop-sign.byteimg.com/tos-cn-i-vuqhorh59i/demo~tplv-vuqhorh59i-image-v1.image"
            "?x-expires=1762167580&x-signature=abc"
        ],
        ensure_ascii=False,
    )
    stable = json.dumps(
        ["https://store.is.autonavi.com/showpic/demo123"],
        ensure_ascii=False,
    )
    with session_scope(engine) as session:
        _add_post(session, "过期润色图", "内容", ["上海"], images_json=expired)
        _add_post(session, "正常高德图", "内容", ["上海"], images_json=stable)

    repo = PostRepository(engine)
    listed = repo.list_posts(page=1, page_size=10)
    assert listed.total == 1
    assert listed.items[0].title == "正常高德图"
    assert repo.get_post(1) is None

    results = search_posts(engine, query="上海", page=1, page_size=10)
    assert results.total == 1
    assert results.items[0].title == "正常高德图"


def test_posts_with_blocked_store_keywords_are_hidden(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    stable = json.dumps(
        ["https://store.is.autonavi.com/showpic/demo123"],
        ensure_ascii=False,
    )
    with session_scope(engine) as session:
        _add_post(session, "全家便利店探店", "周末逛街", ["上海"], images_json=stable)
        _add_post(session, "罗森新品测评", "便当推荐", ["美食"], images_json=stable)
        _add_post(session, "普通咖啡馆", "罗森隔壁有家咖啡店", ["咖啡"], images_json=stable)
        _add_post(session, "静安寺散步", "适合周末", ["上海"], images_json=stable)

    repo = PostRepository(engine)
    listed = repo.list_posts(page=1, page_size=10)
    assert listed.total == 1
    assert listed.items[0].title == "静安寺散步"

    results = search_posts(engine, query="上海", page=1, page_size=10)
    assert results.total == 1
    assert results.items[0].title == "静安寺散步"

    results = search_posts(engine, query="咖啡", page=1, page_size=10)
    assert results.total == 0


def test_posts_with_single_play_method_are_hidden(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    stable = json.dumps(
        ["https://store.is.autonavi.com/showpic/demo123"],
        ensure_ascii=False,
    )
    with session_scope(engine) as session:
        from app.models import Place

        single = _add_post(session, "单玩法路线", "玩法一：只有一条", ["上海"], images_json=stable)
        session.add(
            Place(
                post_id=single.id,
                name="地点A",
                lat=31.2,
                lng=121.4,
                method_order=1,
                method_title="单玩法",
            )
        )
        multi = _add_post(session, "多玩法路线", "玩法一和玩法二", ["上海"], images_json=stable)
        session.add(
            Place(
                post_id=multi.id,
                name="地点A",
                lat=31.2,
                lng=121.4,
                method_order=1,
                method_title="玩法一",
            )
        )
        session.add(
            Place(
                post_id=multi.id,
                name="地点B",
                lat=31.21,
                lng=121.41,
                method_order=2,
                method_title="玩法二",
            )
        )

    repo = PostRepository(engine)
    listed = repo.list_posts(page=1, page_size=10)
    assert listed.total == 1
    assert listed.items[0].title == "多玩法路线"
    assert repo.get_post(single.id) is None

    results = search_posts(engine, query="玩法", page=1, page_size=10)
    assert results.total == 1
    assert results.items[0].title == "多玩法路线"

