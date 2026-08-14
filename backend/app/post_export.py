"""把小红书笔记内容（标题+正文+标签+图片）打包成 zip，供用户下载。"""

import asyncio
import io
import ipaddress
import os
import socket
import zipfile
from typing import Sequence
from urllib.parse import urlparse

import httpx

from app.models import Post
from app.schemas import PostExportRequest


# Allowed image host suffixes. Add more as the project integrates new CDNs.
# Amap/Autonavi often serve original post images over plain HTTP; Jimeng polish
# results commonly land on byteimg.com. Keep the SSRF host whitelist strict, but
# allow both http and https for these known public CDNs.
_DEFAULT_ALLOWED_IMAGE_HOSTS = (
    "volccdn.com",
    "volces.com",
    "byteimg.com",
    "unsplash.com",
    "aliyuncs.com",
    "amap.com",
    "autonavi.com",
    "alicdn.com",
)
_ALLOWED_IMAGE_HOSTS = _DEFAULT_ALLOWED_IMAGE_HOSTS + tuple(
    host.strip().lower()
    for host in os.getenv("EXTRA_IMAGE_HOSTS", "").split(",")
    if host.strip()
)


def is_safe_image_url(url: str) -> bool:
    """Validate that a URL is safe for server-side fetching.

    Allows only http/https URLs on the public CDN whitelist. Rejects literal
    private/internal IPs and non-whitelisted hosts to prevent SSRF.
    """
    if not url or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    # Production posts mix http:// and https:// Amap/Autonavi CDN URLs.
    # Require a known CDN host rather than forcing HTTPS-only.
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname or ""
    if not hostname:
        return False
    # Reject literal IP addresses (prevent direct IP access to internal services)
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        pass
    # Check against allowed host suffixes
    lowered = hostname.lower()
    return any(
        lowered == allowed or lowered.endswith("." + allowed)
        for allowed in _ALLOWED_IMAGE_HOSTS
    )


def _preferred_download_urls(url: str) -> list[str]:
    """Prefer HTTPS for HTTP CDN URLs, then fall back to the original URL."""
    parsed = urlparse(url)
    if parsed.scheme == "http":
        https_url = parsed._replace(scheme="https").geturl()
        if https_url != url:
            return [https_url, url]
    return [url]


def _resolve_host_ips(hostname: str) -> list[str]:
    """Resolve a hostname to its IP addresses for SSRF validation."""
    try:
        _, _, ips = socket.getaddrinfo(hostname, None)
        return list({ip[4][0] for ip in ips})
    except (socket.gaierror, socket.herror):
        return []


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # treat unparseable as private (deny by default)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _guess_extension(content_type: str | None, url: str) -> str:
    if content_type:
        content_type = content_type.split(";")[0].strip().lower()
        mapping = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        if content_type in mapping:
            return mapping[content_type]
    lowered = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if lowered.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


async def _download_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    if not is_safe_image_url(url):
        return None
    for candidate in _preferred_download_urls(url):
        try:
            response = await client.get(candidate, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException):
            continue
        # Defense in depth: verify the final resolved host is not a private IP
        final_host = response.url.host or ""
        if final_host:
            try:
                ipaddress.ip_address(final_host)
                if _is_private_ip(final_host):
                    return None
            except ValueError:
                pass
        ext = _guess_extension(response.headers.get("content-type"), candidate)
        return response.content, ext
    return None


async def _download_images(image_urls: Sequence[str]) -> list[tuple[str, bytes, str]]:
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(_download_image(client, url) for url in image_urls))
    downloaded: list[tuple[str, bytes, str]] = []
    for url, result in zip(image_urls, results):
        if result is None:
            continue
        content, ext = result
        downloaded.append((url, content, ext))
    return downloaded


def _sanitize_filename(title: str) -> str:
    keep = "".join(ch for ch in title if ch.isalnum() or ch in " _-")
    keep = keep.strip().replace(" ", "_")
    return keep[:40] or "xhs_note"


async def build_post_export_zip(post: Post, request: PostExportRequest) -> tuple[bytes, str]:
    """构建导出 zip 的字节内容，返回 (zip_bytes, download_filename)。"""
    import json

    images_from_post: list[str] = []
    try:
        raw = json.loads(post.images_json or "[]")
        if isinstance(raw, list):
            images_from_post = [str(item).strip() for item in raw if str(item).strip()]
    except json.JSONDecodeError:
        images_from_post = []

    image_urls = request.image_urls if request.image_urls else images_from_post
    downloaded = await _download_images(image_urls)

    tags = []
    try:
        raw_tags = json.loads(post.tags_json or "[]")
        if isinstance(raw_tags, list):
            tags = [str(tag) for tag in raw_tags]
    except json.JSONDecodeError:
        tags = []

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("title.txt", post.title or "")
        archive.writestr("content.txt", post.content or "")
        archive.writestr("tags.txt", "\n".join(f"#{tag}" for tag in tags))
        for index, (_url, content, ext) in enumerate(downloaded, start=1):
            archive.writestr(f"images/{index:02d}{ext}", content)

    filename = f"{_sanitize_filename(post.title)}.zip"
    return buffer.getvalue(), filename
