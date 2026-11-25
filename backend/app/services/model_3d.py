"""Image-to-3D providers (Tripo3D, Meshy, procedural mock) and the lazy generation runner."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import trimesh
from sqlmodel import Session

from ..config import get_settings
from ..models import Product, utcnow

log = logging.getLogger("roomcraft.model3d")


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

Color = tuple[int, int, int]


def _box(extents, center, color: Color) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=extents)
    m.apply_translation(center)
    m.visual = trimesh.visual.ColorVisuals(
        mesh=m, vertex_colors=np.tile(np.array([*color, 255], dtype=np.uint8), (len(m.vertices), 1))
    )
    return m


def build_category_mesh(category: str, w_cm: float, d_cm: float, h_cm: float) -> trimesh.Scene:
    """Procedural, recognizable category-shaped model. X=width, Y=height (up), Z=depth.

    Origin is bottom-center. Real dimensions are re-applied by the client's normalizeGlbModel.
    """
    w, d, h = w_cm / 100.0, d_cm / 100.0, h_cm / 100.0
    parts: list[trimesh.Trimesh] = []
    add = lambda ext, c, col: parts.append(_box(ext, c, col))  # noqa: E731

    if category == "sofa":
        fabric, dark = (96, 125, 139), (69, 90, 100)
        base_h, arm_w = h * 0.45, w * 0.1
        add((w, base_h, d), (0, base_h / 2, 0), fabric)
        add((w - 2 * arm_w, h * 0.55, d * 0.22), (0, base_h + h * 0.275 - 0.0, -d * 0.39), dark)
        for s in (-1, 1):
            add((arm_w, h * 0.7, d), (s * (w / 2 - arm_w / 2), h * 0.35, 0), dark)
    elif category == "armchair":
        fabric, dark = (161, 136, 127), (121, 85, 72)
        base_h, arm_w = h * 0.45, w * 0.16
        add((w, base_h, d), (0, base_h / 2, 0), fabric)
        add((w - 2 * arm_w, h * 0.55, d * 0.25), (0, base_h + h * 0.275, -d * 0.375), dark)
        for s in (-1, 1):
            add((arm_w, h * 0.65, d), (s * (w / 2 - arm_w / 2), h * 0.325, 0), dark)
    elif category in ("coffee_table", "dining_table", "desk"):
        wood, leg_c = (141, 110, 99), (93, 64, 55)
        top_t, leg = max(h * 0.08, 0.03), min(w, d) * 0.07
        add((w, top_t, d), (0, h - top_t / 2, 0), wood)
        for sx in (-1, 1):
            for sz in (-1, 1):
                add((leg, h - top_t, leg), (sx * (w / 2 - leg), (h - top_t) / 2, sz * (d / 2 - leg)), leg_c)
    elif category == "chair":
        wood, seat_c = (121, 85, 72), (188, 170, 164)
        seat_h, leg = h * 0.48, min(w, d) * 0.1
        add((w, h * 0.06, d), (0, seat_h, 0), seat_c)
        add((w, h - seat_h, h * 0.05), (0, seat_h + (h - seat_h) / 2, -d / 2 + 0.02), wood)
        for sx in (-1, 1):
            for sz in (-1, 1):
                add((leg, seat_h, leg), (sx * (w / 2 - leg), seat_h / 2, sz * (d / 2 - leg)), wood)
    elif category == "bed":
        frame, mattress, pillow = (109, 76, 65), (236, 239, 241), (255, 255, 255)
        add((w, h * 0.4, d), (0, h * 0.2, 0), frame)
        add((w * 0.96, h * 0.3, d * 0.96), (0, h * 0.4 + h * 0.15, 0.0), mattress)
        add((w, h * 0.9, d * 0.04), (0, h * 0.45, -d / 2 + d * 0.02), frame)
        for s in (-1, 1):
            add((w * 0.35, h * 0.1, d * 0.15), (s * w * 0.22, h * 0.75, -d * 0.35), pillow)
    elif category == "tv_unit":
        wood, screen = (161, 136, 127), (33, 33, 33)
        cab_h = h * 0.4
        add((w, cab_h, d), (0, cab_h / 2, 0), wood)
        add((w * 0.7, h * 0.5, d * 0.08), (0, cab_h + h * 0.3, 0), screen)
        add((w * 0.12, h * 0.1, d * 0.4), (0, cab_h + h * 0.05, 0), (66, 66, 66))
    elif category == "wardrobe":
        body, handle = (215, 204, 200), (120, 120, 120)
        add((w, h, d), (0, h / 2, 0), body)
        add((0.01, h * 0.8, 0.02), (0, h / 2, d / 2 + 0.005), (90, 90, 90))
        for s in (-1, 1):
            add((0.02, h * 0.12, 0.03), (s * w * 0.06, h * 0.5, d / 2 + 0.015), handle)
    elif category == "storage":
        body, line = (176, 150, 130), (90, 70, 55)
        add((w, h, d), (0, h / 2, 0), body)
        rows = 3 if h > 0.6 else 2
        for i in range(1, rows):
            add((w * 0.98, 0.01, 0.02), (0, h * i / rows, d / 2 + 0.005), line)
        add((0.03, 0.02, 0.03), (0, h * 0.8, d / 2 + 0.015), (60, 60, 60))
    elif category == "appliance":
        body, trim = (236, 239, 241), (176, 190, 197)
        add((w, h, d), (0, h / 2, 0), body)
        add((w * 0.96, 0.01, 0.02), (0, h * 0.62, d / 2 + 0.005), trim)
        add((0.03, h * 0.2, 0.03), (w * 0.38, h * 0.8, d / 2 + 0.015), trim)
    elif category == "lighting":
        stand, shade = (66, 66, 66), (255, 241, 118)
        add((w * 0.45, 0.02, d * 0.45), (0, 0.01, 0), stand)
        add((0.03, h * 0.75, 0.03), (0, h * 0.375, 0), stand)
        add((w, h * 0.25, d), (0, h * 0.875, 0), shade)
    elif category == "decor":
        add((w, h, d), (0, h / 2, 0), (128, 203, 196))
    else:
        add((w, h, d), (0, h / 2, 0), (176, 190, 197))

    scene = trimesh.Scene()
    for i, m in enumerate(parts):
        scene.add_geometry(m, node_name=f"part_{i}", geom_name=f"part_{i}")
    return scene


class MockGlbProvider(ImageTo3DProvider):
    name = "mock"

    async def generate(self, product: ProductInfo, out_path: Path) -> None:
        await asyncio.sleep(get_settings().mock_generation_seconds)
        scene = build_category_mesh(product.category, product.width_cm, product.depth_cm, product.height_cm)
        data = scene.export(file_type="glb")
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


async def run_generation(product_id: int) -> None:
    """Background task: generate + cache the GLB, then update the product row."""
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
        await get_provider().generate(info, out_path)
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
            product.model_3d_url = f"/static/models/{product_id}.glb"
            product.model_status = "ready"
            product.model_error = None
        else:
            product.model_status = "failed"
            product.model_error = error
        product.updated_at = utcnow()
        session.add(product)
        session.commit()
