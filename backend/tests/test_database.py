from sqlalchemy import inspect

from app.database import create_sqlite_engine, init_db, session_scope
from app.models import Post


def test_init_db_creates_core_tables(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")

    init_db(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {"posts", "post_interactions", "generation_requests", "places"}.issubset(table_names)


def test_session_scope_commits_post(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)

    with session_scope(engine) as session:
        session.add(
            Post(
                title="上海周末夜游",
                content="适合朋友一起去江边散步拍照。",
                tags_json='["上海", "夜游"]',
                images_json="[]",
                source_type="seed_import",
                status="published",
            )
        )

    with session_scope(engine) as session:
        assert session.query(Post).count() == 1

