"""批量为 SQLite 中的小红书正文补全段落标题加粗。"""
from __future__ import annotations

from sqlalchemy import select

from app.database import engine, init_db, session_scope
from app.models import Post
from app.xhs_content_format import format_xhs_content


def main() -> None:
    init_db(engine)
    updated = 0
    with session_scope(engine) as session:
        posts = session.execute(select(Post)).scalars().all()
        for post in posts:
            formatted = format_xhs_content(post.content)
            if formatted != post.content:
                post.content = formatted
                updated += 1
    print(f"updated_posts={updated}")


if __name__ == "__main__":
    main()
