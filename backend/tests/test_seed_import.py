import json

from app.database import create_sqlite_engine, init_db, session_scope
from app.import_seed import import_seed_file
from app.models import Post


def test_import_seed_file_creates_post(tmp_path):
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "doc_id": "doc-1",
                    "query": "上海周末拍照",
                    "xhs_content": {
                        "title": "上海周末好拍",
                        "content": "这条路线适合朋友周末慢慢逛。",
                        "tags": ["上海", "拍照"],
                        "images": ["https://example.com/a.jpg"],
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)

    result = import_seed_file(engine, seed_path)

    assert result.imported_count == 1
    with session_scope(engine) as session:
        post = session.query(Post).one()
        assert post.title == "上海周末好拍"
        assert post.source_query == "上海周末拍照"
        assert post.source_doc_id == "doc-1"
        assert post.source_type == "seed_import"
        assert post.cover_image == "https://example.com/a.jpg"


def test_import_seed_file_is_idempotent_by_source_doc_id(tmp_path):
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {
                    "doc_id": "doc-1",
                    "query": "上海周末拍照",
                    "xhs_content": {
                        "title": "上海周末好拍",
                        "content": "这条路线适合朋友周末慢慢逛。",
                        "tags": ["上海", "拍照"],
                        "images": [],
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)

    first = import_seed_file(engine, seed_path)
    second = import_seed_file(engine, seed_path)

    assert first.imported_count == 1
    assert second.imported_count == 0
    assert second.skipped_count == 1
    with session_scope(engine) as session:
        assert session.query(Post).count() == 1

