import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from app.database import session_scope
from app.models import Post
from app.post_images import images_are_displayable
from app.post_visibility import publish_content_is_visible
from app.xhs_content_format import format_xhs_content


@dataclass(frozen=True)
class ImportResult:
    imported_count: int
    skipped_count: int


def import_seed_file(engine: Engine, seed_path: str | Path) -> ImportResult:
    path = Path(seed_path)
    records = json.loads(path.read_text(encoding="utf-8"))
    imported = 0
    skipped = 0

    with session_scope(engine) as session:
        for record in records:
            xhs_content = record.get("xhs_content") or {}
            source_doc_id = _clean_optional_string(record.get("doc_id"))
            if source_doc_id:
                existing = session.execute(
                    select(Post).where(Post.source_doc_id == source_doc_id)
                ).scalar_one_or_none()
                if existing:
                    skipped += 1
                    continue

            images = _ensure_list(xhs_content.get("images"))
            tags = _ensure_list(xhs_content.get("tags"))
            title = str(xhs_content.get("title") or "").strip()
            content = format_xhs_content(str(xhs_content.get("content") or "").strip())
            if not title or not content:
                skipped += 1
                continue
            if not images_are_displayable([str(item) for item in images if str(item).strip()]):
                skipped += 1
                continue
            if not publish_content_is_visible(title, content, tags, _clean_optional_string(record.get("query"))):
                skipped += 1
                continue

            session.add(
                Post(
                    title=title,
                    content=content,
                    tags_json=json.dumps(tags, ensure_ascii=False),
                    images_json=json.dumps(images, ensure_ascii=False),
                    cover_image=images[0] if images else None,
                    source_query=_clean_optional_string(record.get("query")),
                    source_doc_id=source_doc_id,
                    source_type="seed_import",
                    status="published",
                )
            )
            imported += 1

    return ImportResult(imported_count=imported, skipped_count=skipped)


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

