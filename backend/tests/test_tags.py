import json

from app.database import create_sqlite_engine, init_db, session_scope
from app.models import Post
from app.tags import get_hot_tags, post_matches_tag


def test_get_hot_tags_excludes_generic_tags_and_ranks_by_frequency(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(
            Post(
                title="A",
                content="内容",
                tags_json=json.dumps(["上海", "情侣约会", "氛围感"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
        session.add(
            Post(
                title="B",
                content="内容",
                tags_json=json.dumps(["上海", "情侣约会", "周末去哪"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
        session.add(
            Post(
                title="C",
                content="内容",
                tags_json=json.dumps(["上海", "氛围感"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )

    items = get_hot_tags(engine, limit=5)
    tags = [item["tag"] for item in items]

    assert "上海" not in tags
    assert tags[0] == "情侣约会"
    assert "氛围感" in tags
    assert "周末去哪" in tags


def test_get_hot_tags_merges_similar_tags(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    with session_scope(engine) as session:
        session.add(
            Post(
                title="A",
                content="内容",
                tags_json=json.dumps(["城市漫步", "氛围感"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
        session.add(
            Post(
                title="B",
                content="内容",
                tags_json=json.dumps(["城市散步", "周末去哪"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )
        session.add(
            Post(
                title="C",
                content="内容",
                tags_json=json.dumps(["城市漫游", "周末去哪儿"], ensure_ascii=False),
                source_type="seed_import",
                status="published",
            )
        )

    items = get_hot_tags(engine, limit=10)
    tags = [item["tag"] for item in items]
    counts = {item["tag"]: item["count"] for item in items}

    assert "城市散步" not in tags
    assert "城市漫游" not in tags
    assert "周末去哪儿" not in tags
    assert counts["城市漫步"] == 3
    assert counts["周末去哪"] == 2


def test_post_matches_tag_uses_canonical_aliases():
    post = Post(
        title="A",
        content="内容",
        tags_json=json.dumps(["城市散步", "情侣约会"], ensure_ascii=False),
        source_type="seed_import",
        status="published",
    )

    assert post_matches_tag(post, "城市漫步")
    assert post_matches_tag(post, "情侣约会")
    assert not post_matches_tag(post, "亲子")
