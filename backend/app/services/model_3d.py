"""Image-to-3D providers (Tripo3D, Meshy, procedural mock) and the lazy generation runner."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import trimesh
from PIL import Image
from sqlmodel import Session

from ..config import get_settings
from ..models import Product, utcnow
from .procedural import Color, Palette, build_model

log = logging.getLogger("roomcraft.model3d")

PALETTE_TIMEOUT_S = 6.0  # max wait for the product photo before falling back to default colours


@dataclass
class ProductInfo:
    """Detached snapshot of a product, safe to pass to background tasks."""

    id: int
    title: str
    category: str
    image_url: str
    width_cm: float
    depth_cm: float
    height_cm: float
    palette: Optional[Palette] = None

    @classmethod
    def from_product(cls, p: Product) -> "ProductInfo":
        return cls(p.id, p.title, p.category, p.image_url, p.width_cm, p.depth_cm, p.height_cm)


class GenerationError(RuntimeError):
    pass


class ImageTo3DProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(self, product: ProductInfo, out_path: Path) -> None:
        """Generate a .glb for the product and write it to ``out_path``."""


# --------------------------------------------------------------------------- mock

def _shade(c: Color, f: float) -> Color:
    return (max(0, min(255, int(c[0] * f))), max(0, min(255, int(c[1] * f))), max(0, min(255, int(c[2] * f))))


def _dist(a: Color, b: Color) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def dominant_palette(img: Image.Image) -> Optional[Palette]:
    """Dominant + accent colour of a product photo, ignoring the white/grey studio background."""
    im = img.convert("RGB")
    im.thumbnail((64, 64))
    px = list(im.getdata())
    if not px:
        return None
    fg: list[Color] = []
    for r, g, b in px:
        mx, mn = max(r, g, b), min(r, g, b)
        if mn > 228:  # white background
            continue
        if mx - mn < 14 and mx > 205:  # light-grey background / soft shadow
            continue
        fg.append((r, g, b))
    if len(fg) < 0.06 * len(px):
        return Palette(main=(236, 236, 238), accent=(150, 150, 156), pale=True)
    buckets: dict[tuple[int, int, int], list[Color]] = {}
    for c in fg:
        buckets.setdefault((c[0] // 40, c[1] // 40, c[2] // 40), []).append(c)
    ranked = sorted(buckets.values(), key=len, reverse=True)

    def avg(v: list[Color]) -> Color:
        return (sum(c[0] for c in v) // len(v), sum(c[1] for c in v) // len(v), sum(c[2] for c in v) // len(v))

    main = avg(ranked[0])
    accent = next(
        (avg(v) for v in ranked[1:] if len(v) >= 0.05 * len(fg) and _dist(avg(v), main) > 70),
        _shade(main, 0.55),
    )
    return Palette(main, accent)


def build_category_mesh(
    category: str,
    w_cm: float,
    d_cm: float,
    h_cm: float,
    palette: Optional[Palette] = None,
    title: str = "",
    seed: int = 0,
) -> trimesh.Scene:
    """Procedural model of a product (see procedural.py): coloured from the photo, styled per product."""
    return build_model(category, w_cm, d_cm, h_cm, palette, title, seed)


async def palette_for(info: ProductInfo) -> Optional[Palette]:
    """Colours of the product photo (via the cached thumbnail); None when there is no usable remote image."""
    try:
        from . import thumbs

        probe = Product(id=info.id, title=info.title, product_url="", image_url=info.image_url)
        path = await thumbs.get_or_create_thumb(probe)
        if not path:
            return None
        with Image.open(path) as im:
            return dominant_palette(im)
    except Exception:  # noqa: BLE001 - colours are a nicety, never a failure
        return None


class MockGlbProvider(ImageTo3DProvider):
    name = "mock"

    async def generate(self, product: ProductInfo, out_path: Path) -> None:
        await asyncio.sleep(get_settings().mock_generation_seconds)
        # CPU-bound mesh building + GLB export run in a worker thread so the API stays responsive
        scene = await asyncio.to_thread(
            build_category_mesh,
            product.category, product.width_cm, product.depth_cm, product.height_cm, product.palette, product.title, product.id,
        )
        data = await asyncio.to_thread(scene.export, file_type="glb")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)


# --------------------------------------------------------------------------- helpers

async def _download(client: httpx.AsyncClient, url: str, out_path: Path) -> None:
    r = await client.get(url, follow_redirects=True)
    r.raise_for_status()
    if not r.content:
        raise GenerationError("Downloaded model is empty")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)


def _require_http_image(product: ProductInfo) -> str:
    if not product.image_url.startswith(("http://", "https://")):
        raise GenerationError("Product has no public image URL to send to the 3D provider")
    return product.image_url


def _image_ext(url: str) -> str:
    low = url.lower().split("?")[0]
    if low.endswith(".png"):
        return "png"
    if low.endswith(".webp"):
        return "webp"
    return "jpg"


# --------------------------------------------------------------------------- Tripo3D

class Tripo3DProvider(ImageTo3DProvider):
    name = "tripo3d"
    base_url = "https://api.tripo3d.ai/v2/openapi"

    def __init__(self, api_key: str, poll_interval: float = 3.0, timeout_s: float = 600.0):
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    async def generate(self, product: ProductInfo, out_path: Path) -> None:
        image_url = _require_http_image(product)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            # 1. fetch the product image and upload it to Tripo
            img = await client.get(image_url, follow_redirects=True)
            img.raise_for_status()
            ext = _image_ext(image_url)
            up = await client.post(
                f"{self.base_url}/upload",
                files={"file": (f"product.{ext}", img.content, f"image/{'jpeg' if ext == 'jpg' else ext}")},
            )
            up.raise_for_status()
            up_json = up.json()
            token = (up_json.get("data") or {}).get("image_token")
            if up_json.get("code", 0) != 0 or not token:
                raise GenerationError(f"Tripo upload failed: {up_json}")

            # 2. create the image_to_model task
            task = await client.post(
                f"{self.base_url}/task",
                json={"type": "image_to_model", "file": {"type": ext, "file_token": token}},
            )
            task.raise_for_status()
            task_json = task.json()
            task_id = (task_json.get("data") or {}).get("task_id")
            if task_json.get("code", 0) != 0 or not task_id:
                raise GenerationError(f"Tripo task creation failed: {task_json}")

            # 3. poll
            elapsed = 0.0
            while elapsed < self.timeout_s:
                st = await client.get(f"{self.base_url}/task/{task_id}")
                st.raise_for_status()
                data = (st.json().get("data") or {})
                status = data.get("status")
                if status == "success":
                    output = data.get("output") or {}
                    model_url = output.get("pbr_model") or output.get("model")
                    if not model_url:
                        raise GenerationError("Tripo returned no model URL")
                    await _download(client, model_url, out_path)
                    return
                if status in ("failed", "cancelled", "unknown", "banned", "expired"):
                    raise GenerationError(f"Tripo task {status}")
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
            raise GenerationError("Tripo generation timed out")


# --------------------------------------------------------------------------- Meshy

class MeshyProvider(ImageTo3DProvider):
    name = "meshy"
    base_url = "https://api.meshy.ai/openapi/v1/image-to-3d"

    def __init__(self, api_key: str, poll_interval: float = 3.0, timeout_s: float = 600.0):
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    async def generate(self, product: ProductInfo, out_path: Path) -> None:
        image_url = _require_http_image(product)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            r = await client.post(
                self.base_url,
                json={"image_url": image_url, "enable_pbr": True, "should_remesh": True, "should_texture": True},
            )
            r.raise_for_status()
            task_id = r.json().get("result")
            if not task_id:
                raise GenerationError(f"Meshy task creation failed: {r.text[:200]}")
            elapsed = 0.0
            while elapsed < self.timeout_s:
                st = await client.get(f"{self.base_url}/{task_id}")
                st.raise_for_status()
                data = st.json()
                status = data.get("status")
                if status == "SUCCEEDED":
                    glb = (data.get("model_urls") or {}).get("glb")
                    if not glb:
                        raise GenerationError("Meshy returned no GLB URL")
                    await _download(client, glb, out_path)
                    return
                if status in ("FAILED", "CANCELED"):
                    msg = (data.get("task_error") or {}).get("message") or status
                    raise GenerationError(f"Meshy task failed: {msg}")
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
            raise GenerationError("Meshy generation timed out")


# --------------------------------------------------------------------------- factory + runner

def get_provider() -> ImageTo3DProvider:
    s = get_settings()
    choice = (s.image_to_3d_provider or "mock").lower()
    if choice == "tripo3d" and s.tripo_api_key:
        return Tripo3DProvider(s.tripo_api_key)
    if choice == "meshy" and s.meshy_api_key:
        return MeshyProvider(s.meshy_api_key)
    if choice in ("tripo3d", "meshy"):
        log.warning("Provider %s selected without API key; falling back to mock", choice)
    return MockGlbProvider()


def model_path(product_id: int) -> Path:
    return get_settings().models_dir / f"{product_id}.glb"


_semaphores: dict[int, asyncio.Semaphore] = {}


def _generation_slots() -> asyncio.Semaphore:
    """At most 4 generations at once per event loop (SQLite, CPU and provider rate limits)."""
    loop_id = id(asyncio.get_running_loop())
    return _semaphores.setdefault(loop_id, asyncio.Semaphore(4))


async def run_generation(product_id: int) -> None:
    """Background task: generate + cache the GLB, then update the product row."""
    async with _generation_slots():
        await _run_generation(product_id)


async def _run_generation(product_id: int) -> None:
    from ..db import get_engine

    engine = get_engine()
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product is None:
            return
        info = ProductInfo.from_product(product)

    out_path = model_path(product_id)
    error: str | None = None
    try:
        provider = get_provider()
        if isinstance(provider, MockGlbProvider):
            try:  # colours from the product photo; a slow image host must never block the model
                info.palette = await asyncio.wait_for(palette_for(info), timeout=PALETTE_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.info("palette lookup timed out for product %s; using default colours", product_id)
        await provider.generate(info, out_path)
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise GenerationError("Provider did not produce a model file")
    except Exception as exc:  # noqa: BLE001 - surface any provider failure as status
        log.exception("3D generation failed for product %s", product_id)
        error = str(exc)[:500] or exc.__class__.__name__

    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product is None:
            return
        if error is None:
            # ?v= busts browser/GLTF caches when a model is regenerated (the static route ignores it)
            product.model_3d_url = f"/static/models/{product_id}.glb?v={int(time.time())}"
            product.model_status = "ready"
            product.model_error = None
        else:
            product.model_status = "failed"
            product.model_error = error
        product.updated_at = utcnow()
        session.add(product)
        session.commit()
