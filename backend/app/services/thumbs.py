"""Lazy product thumbnails: download the store photo once, shrink it, cache it on disk.

Real product photos are hot-linked from the stores' CDNs by the crawler. The UI never loads those
directly (some CDNs refuse foreign referers and the originals are ~2000px): it asks
``GET /api/products/{id}/image`` which downloads the photo lazily (with the crawler headers and the
store's Referer), resizes it to at most ``THUMB_MAX`` px (JPEG, white background for transparency)
and serves it from ``storage/thumbs/{id}.jpg``.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps

from ..config import get_settings
from ..models import Product
from .scraper import HEADERS

log = logging.getLogger("roomcraft.thumbs")

THUMB_MAX = 320
JPEG_QUALITY = 82
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
FAIL_TTL_SECONDS = 600

_sem: Optional[asyncio.Semaphore] = None
_failed: dict[int, float] = {}


def thumbs_dir() -> Path:
    d = get_settings().storage_path / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_path(product_id: int) -> Path:
    return thumbs_dir() / f"{product_id}.jpg"


def is_remote_image(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def referer_for(product: Product) -> Optional[str]:
    """Origin of the product page (e.g. https://www.ikea.com/) - what a browser on that site would send."""
    for u in (product.product_url, product.image_url):
        p = urlparse(u or "")
        if p.scheme in ("http", "https") and p.netloc:
            return f"{p.scheme}://{p.netloc}/"
    return None


def make_client() -> httpx.AsyncClient:
    """Factory kept separate so tests can swap in an ``httpx.MockTransport`` client."""
    return httpx.AsyncClient(follow_redirects=True, timeout=20)


async def fetch_image_bytes(url: str, referer: Optional[str]) -> Optional[bytes]:
    headers = {**HEADERS, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    try:
        async with make_client() as client:
            r = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        log.info("thumbnail download failed for %s: %s", url, exc.__class__.__name__)
        return None
    if r.status_code != 200 or len(r.content) > MAX_DOWNLOAD_BYTES:
        log.info("thumbnail download for %s -> HTTP %s (%d bytes)", url, r.status_code, len(r.content))
        return None
    ctype = r.headers.get("content-type", "").lower()
    if ctype and not ctype.startswith(("image/", "application/octet-stream", "binary/")):
        return None
    return r.content


def render_thumbnail(data: bytes, max_px: int = THUMB_MAX) -> Optional[bytes]:
    """Resize to fit ``max_px`` (aspect kept), flatten transparency onto white, encode JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.format == "JPEG":
            img.draft("RGB", (max_px * 2, max_px * 2))  # fast DCT-domain downscale for huge photos
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - corrupt/unsupported image (e.g. SVG)
        log.info("thumbnail render failed: %s", exc)
        return None


async def get_or_create_thumb(product: Product) -> Optional[Path]:
    """Path of the cached thumbnail, creating it on first use. None -> caller should 404."""
    global _sem
    pid = product.id
    if pid is None or not is_remote_image(product.image_url or ""):
        return None
    path = thumb_path(pid)
    if path.exists() and path.stat().st_size > 0:
        return path
    if time.monotonic() - _failed.get(pid, -1e9) < FAIL_TTL_SECONDS:
        return None
    if _sem is None:
        _sem = asyncio.Semaphore(6)
    async with _sem:
        if path.exists() and path.stat().st_size > 0:  # another request finished meanwhile
            return path
        data = await fetch_image_bytes(product.image_url, referer_for(product))
        jpeg = await asyncio.to_thread(render_thumbnail, data) if data else None
        if not jpeg:
            _failed[pid] = time.monotonic()
            return None
        # unique temp name: the API server and a warm-up script may create the same thumbnail at once
        tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_bytes(jpeg)
            tmp.replace(path)
        except OSError:
            tmp.unlink(missing_ok=True)
            if not (path.exists() and path.stat().st_size > 0):  # someone else did not finish it either
                return None
        _failed.pop(pid, None)
        return path
