import json

from app.models import Post


def is_ephemeral_image_url(url: str) -> bool:
    lowered = url.lower()
    if "byteimg.com" in lowered:
        return True
    return "x-expires=" in lowered and "x-signature=" in lowered


def images_from_post(post: Post) -> list[str]:
    try:
        raw = json.loads(post.images_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def post_has_displayable_images(post: Post) -> bool:
    images = images_from_post(post)
    if not images:
        return True
    return not any(is_ephemeral_image_url(url) for url in images)


def images_are_displayable(images: list[str]) -> bool:
    if not images:
        return True
    return not any(is_ephemeral_image_url(url) for url in images)
