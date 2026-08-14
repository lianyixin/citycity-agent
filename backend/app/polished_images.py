"""图片 AI 润色历史存取：记录每张原图对应的润色结果，便于回溯与复用。"""

from sqlalchemy import Engine, select

from app.database import session_scope
from app.models import PolishedImage


def save_polished_image(
    engine: Engine,
    *,
    post_id: int | None,
    original_url: str,
    prompt: str,
    polished_url: str,
    user_id: str | None = None,
) -> None:
    with session_scope(engine) as session:
        session.add(
            PolishedImage(
                post_id=post_id,
                user_id=user_id,
                original_url=original_url,
                prompt=prompt,
                polished_url=polished_url,
            )
        )


def list_polished_images_for_post(engine: Engine, post_id: int) -> list[PolishedImage]:
    """返回某帖子下的全部润色记录（含历史多次润色），按时间正序，便于回溯每张原图的润色轨迹。"""
    with session_scope(engine) as session:
        rows = session.execute(
            select(PolishedImage)
            .where(PolishedImage.post_id == post_id)
            .order_by(PolishedImage.created_at.asc(), PolishedImage.id.asc())
        ).scalars().all()
        return list(rows)


def latest_polished_by_original_url(engine: Engine, post_id: int) -> dict[str, PolishedImage]:
    """返回每个原图 URL 对应的最新一次润色记录，用于前端预填「已润色」状态。"""
    latest: dict[str, PolishedImage] = {}
    for row in list_polished_images_for_post(engine, post_id):
        latest[row.original_url] = row
    return latest
