"""Lazy 3D generation flow with the mock provider (and provider failure path)."""
import asyncio
from pathlib import Path

import httpx
import pytest
import trimesh

from app.config import get_settings
from app.services import model_3d
from app.services.model_3d import (
    GenerationError,
    ImageTo3DProvider,
    MeshyProvider,
    MockGlbProvider,
    ProductInfo,
    Tripo3DProvider,
    build_category_mesh,
    get_provider,
)


def first_product(client, category="sofa"):
    return client.get("/api/products", params={"category": category}).json()[0]


def test_lazy_generation_flow(client):
    p = first_product(client)
    pid = p["id"]
    assert p["model_status"] == "none" and p["model_3d_url"] is None

    # trigger: returns 'generating' immediately; background task then finishes
    r = client.post(f"/api/products/{pid}/generate-3d")
    assert r.status_code == 200
    assert r.json()["model_status"] == "generating"

    status = client.get(f"/api/products/{pid}/3d-status").json()
    assert status["model_status"] == "ready"
    # the URL carries a ?v= cache-buster so a regenerated model is never served stale
    assert status["model_3d_url"].startswith(f"/static/models/{pid}.glb?v=")
    assert status["model_error"] is None

    # file exists on disk, is served, and is a valid GLB
    path = get_settings().models_dir / f"{pid}.glb"
    assert path.exists()
    served = client.get(status["model_3d_url"])
    assert served.status_code == 200 and served.content[:4] == b"glTF"
    scene = trimesh.load(path, file_type="glb")
    assert len(scene.geometry) > 1 and scene.bounds[1][1] > 0

    # product row is updated in the catalog too
    assert client.get(f"/api/products/{pid}").json()["model_status"] == "ready"


def test_generate_is_idempotent_and_cached(client, monkeypatch):
    pid = first_product(client, "bed")["id"]
    client.post(f"/api/products/{pid}/generate-3d")
    mtime = (get_settings().models_dir / f"{pid}.glb").stat().st_mtime_ns

    calls = []
    original = model_3d.get_provider
    monkeypatch.setattr(model_3d, "get_provider", lambda: calls.append(1) or original())
    r = client.post(f"/api/products/{pid}/generate-3d")
    assert r.json()["model_status"] == "ready"  # no re-generation
    assert not calls
    assert (get_settings().models_dir / f"{pid}.glb").stat().st_mtime_ns == mtime


def test_failed_generation_then_retry(client, monkeypatch):
    pid = first_product(client, "chair")["id"]

    class Boom(ImageTo3DProvider):
        async def generate(self, product, out_path):
            raise GenerationError("provider exploded")

    monkeypatch.setattr(model_3d, "get_provider", lambda: Boom())
    client.post(f"/api/products/{pid}/generate-3d")
    st = client.get(f"/api/products/{pid}/3d-status").json()
    assert st["model_status"] == "failed" and "exploded" in st["model_error"]
    assert st["model_3d_url"] is None

    monkeypatch.setattr(model_3d, "get_provider", lambda: MockGlbProvider())
    r = client.post(f"/api/products/{pid}/generate-3d")
    assert r.json()["model_status"] == "generating"  # failed -> retry allowed
    st = client.get(f"/api/products/{pid}/3d-status").json()
    assert st["model_status"] == "ready" and st["model_error"] is None


def test_generate_unknown_product_404(client):
    assert client.post("/api/products/99999/generate-3d").status_code == 404
    assert client.get("/api/products/99999/3d-status").status_code == 404


def test_generating_status_is_idempotent_while_running(client, engine):
    from sqlmodel import Session

    from app.models import Product

    pid = first_product(client, "desk")["id"]
    with Session(engine) as s:
        p = s.get(Product, pid)
        p.model_status = "generating"
        s.add(p)
        s.commit()
    r = client.post(f"/api/products/{pid}/generate-3d")
    assert r.json()["model_status"] == "generating"
    # no background job was queued, so it stays 'generating'
    assert client.get(f"/api/products/{pid}/3d-status").json()["model_status"] == "generating"


@pytest.mark.parametrize(
    "category",
    ["sofa", "armchair", "coffee_table", "dining_table", "desk", "chair", "bed", "tv_unit",
     "wardrobe", "appliance", "lighting", "decor", "other"],
)
def test_mock_meshes_are_valid_and_distinct(category, tmp_path):
    scene = build_category_mesh(category, 200, 90, 80)
    data = scene.export(file_type="glb")
    assert data[:4] == b"glTF"
    (tmp_path / "m.glb").write_bytes(data)
    loaded = trimesh.load(tmp_path / "m.glb", file_type="glb")
    ext = loaded.extents
    assert all(e > 0 for e in ext)
    assert abs(loaded.bounds[0][1]) < 1e-3  # sits on the floor


def test_get_provider_selection(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "image_to_3d_provider", "tripo3d")
    monkeypatch.setattr(s, "tripo_api_key", "")
    assert isinstance(get_provider(), MockGlbProvider)  # no key -> mock fallback
    monkeypatch.setattr(s, "tripo_api_key", "k")
    assert isinstance(get_provider(), Tripo3DProvider)
    monkeypatch.setattr(s, "image_to_3d_provider", "meshy")
    monkeypatch.setattr(s, "meshy_api_key", "k")
    assert isinstance(get_provider(), MeshyProvider)
    monkeypatch.setattr(s, "image_to_3d_provider", "mock")
    assert isinstance(get_provider(), MockGlbProvider)


GLB_BYTES = build_category_mesh("sofa", 200, 90, 80).export(file_type="glb")
INFO = ProductInfo(1, "t", "sofa", "https://img.example/p.jpg", 200, 90, 80)


def _patch_async_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(model_3d.httpx, "AsyncClient", factory)


def test_tripo_flow_with_mock_transport(monkeypatch, tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        assert request.headers["authorization"] == "Bearer k"
        if request.url.host == "img.example":
            return httpx.Response(200, content=b"\xff\xd8\xffJPEG")
        if path.endswith("/upload"):
            return httpx.Response(200, json={"code": 0, "data": {"image_token": "tok"}})
        if path.endswith("/task") and request.method == "POST":
            body = request.read()
            assert b"image_to_model" in body and b"tok" in body
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "T1"}})
        if path.endswith("/task/T1"):
            return httpx.Response(
                200, json={"data": {"status": "success", "output": {"model": "https://cdn.tripo/model.glb"}}}
            )
        if request.url.host == "cdn.tripo":
            return httpx.Response(200, content=GLB_BYTES)
        return httpx.Response(404)

    _patch_async_client(monkeypatch, handler)
    out = tmp_path / "1.glb"
    asyncio.run(Tripo3DProvider("k", poll_interval=0).generate(INFO, out))
    assert out.read_bytes()[:4] == b"glTF"
    assert ("POST", "/v2/openapi/task") in seen


def test_meshy_flow_with_mock_transport(monkeypatch, tmp_path):
    polls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert b"image_url" in request.read()
            return httpx.Response(202, json={"result": "M1"})
        if request.url.path.endswith("/M1"):
            polls["n"] += 1
            if polls["n"] < 2:
                return httpx.Response(200, json={"status": "IN_PROGRESS"})
            return httpx.Response(
                200, json={"status": "SUCCEEDED", "model_urls": {"glb": "https://assets.meshy/m.glb"}}
            )
        if request.url.host == "assets.meshy":
            return httpx.Response(200, content=GLB_BYTES)
        return httpx.Response(404)

    _patch_async_client(monkeypatch, handler)
    out = tmp_path / "m.glb"
    asyncio.run(MeshyProvider("k", poll_interval=0).generate(INFO, out))
    assert out.read_bytes()[:4] == b"glTF" and polls["n"] == 2


def test_real_providers_reject_non_http_image(tmp_path):
    info = ProductInfo(1, "t", "sofa", "data:image/svg+xml;utf8,x", 1, 1, 1)
    with pytest.raises(GenerationError):
        asyncio.run(Tripo3DProvider("k").generate(info, tmp_path / "x.glb"))
    with pytest.raises(GenerationError):
        asyncio.run(MeshyProvider("k").generate(info, tmp_path / "x.glb"))


# ---- product-photo colours and richer shapes

def _photo(color, size=(120, 120)):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, "white")  # white studio background
    ImageDraw.Draw(img).rectangle([20, 40, 100, 100], fill=color)
    return img


def test_palette_reads_product_colour_and_ignores_white_background():
    from app.services.model_3d import dominant_palette

    pal = dominant_palette(_photo((60, 130, 70)))  # green sofa on white
    assert not pal.pale
    assert pal.main[1] > pal.main[0] + 30 and pal.main[1] > pal.main[2] + 30  # clearly green
    white = dominant_palette(_photo((250, 250, 250)))
    assert white.pale  # a white product on a white background -> "pale" palette


def _vertex_colors(scene):
    import numpy as np

    cols = set()
    for g in scene.geometry.values():
        cols |= {tuple(c[:3]) for c in np.unique(g.visual.vertex_colors, axis=0)}
    return cols


def test_mock_model_uses_photo_colour_and_differs_per_product():
    from app.services.model_3d import Palette, build_category_mesh

    green = Palette((60, 130, 70), (90, 60, 40))
    red = Palette((170, 50, 50), (30, 30, 30))
    a = build_category_mesh("sofa", 220, 90, 80, green, "ספה")
    b = build_category_mesh("sofa", 220, 90, 80, red, "ספה")
    assert _vertex_colors(a) != _vertex_colors(b)
    assert any(c[1] > c[0] and c[1] > c[2] for c in _vertex_colors(a))  # green present
    # sectional sofas (title or deep footprint) get a different, L-shaped silhouette than plain ones
    plain = build_category_mesh("sofa", 220, 90, 80, green, "ספה תלת מושבית")
    corner = build_category_mesh("sofa", 300, 160, 80, green, "ספה פינתית")

    def front_width(scene, z_min):  # x-extent of everything in front of z_min (metres)
        import trimesh

        v = trimesh.util.concatenate(scene.dump()).vertices
        front = v[v[:, 2] > z_min]
        return float(front[:, 0].max() - front[:, 0].min())

    assert front_width(plain, 0.3) > 0.8 * 2.2  # a plain sofa is full width at the front
    assert front_width(corner, 0.3) < 0.5 * 3.0  # only the chaise reaches the front -> L shape
    # wardrobes show door seams proportional to their width
    narrow = build_category_mesh("wardrobe", 60, 55, 200, green, "ארון")
    wide = build_category_mesh("wardrobe", 250, 60, 220, green, "ארון הזזה")
    assert len(wide.geometry) > len(narrow.geometry)


def test_force_regenerates_a_ready_model_with_a_new_url(client):
    pid = first_product(client, "armchair")["id"]
    client.post(f"/api/products/{pid}/generate-3d")
    first = client.get(f"/api/products/{pid}/3d-status").json()
    assert first["model_status"] == "ready"
    assert client.post(f"/api/products/{pid}/generate-3d").json()["model_status"] == "ready"  # idempotent
    import time

    time.sleep(1.1)  # the ?v= cache-buster is a unix timestamp
    r = client.post(f"/api/products/{pid}/generate-3d", params={"force": "true"})
    assert r.json()["model_status"] == "generating"
    second = client.get(f"/api/products/{pid}/3d-status").json()
    assert second["model_status"] == "ready" and second["model_3d_url"] != first["model_3d_url"]


def test_orphaned_generating_status_expires_and_is_retried(client, engine):
    from datetime import timedelta

    from sqlmodel import Session

    from app.models import Product, utcnow

    pid = first_product(client, "lighting")["id"]
    with Session(engine) as s:
        p = s.get(Product, pid)
        p.model_status = "generating"  # a task the server lost (restart / crash)
        p.updated_at = utcnow() - timedelta(minutes=10)
        s.add(p)
        s.commit()
    # the status endpoint reports 'none' so clients re-trigger generation ...
    assert client.get(f"/api/products/{pid}/3d-status").json()["model_status"] == "none"
    # ... and a fresh generate call works
    assert client.post(f"/api/products/{pid}/generate-3d").json()["model_status"] == "generating"
    assert client.get(f"/api/products/{pid}/3d-status").json()["model_status"] == "ready"


def test_slow_photo_host_does_not_block_model_generation(client, monkeypatch):
    import asyncio

    from app.services import model_3d

    async def never(_info):
        await asyncio.sleep(3600)  # an image host that never answers

    monkeypatch.setattr(model_3d, "palette_for", never)
    monkeypatch.setattr(model_3d, "PALETTE_TIMEOUT_S", 0.05)
    pid = first_product(client, "decor")["id"]
    client.post(f"/api/products/{pid}/generate-3d")
    # falls back to default colours and still finishes
    assert client.get(f"/api/products/{pid}/3d-status").json()["model_status"] == "ready"


# ---- colours named in the product title beat the (often room-scene) photo

def test_title_colours_hebrew_modifiers_and_pairs():
    from app.services.procedural import colors_from_title

    blue = colors_from_title('ספה דגם JOHNSON רוחב 200 ס"מ בגוון כחול')[0]
    assert blue[2] > blue[0] + 40 and blue[2] > blue[1] + 20  # clearly blue
    grey = colors_from_title("ספה בגוון אפור")[0]
    dark = colors_from_title("ספה בגוון אפור כהה")[0]
    light = colors_from_title("ספה בגוון אפור בהיר")[0]
    assert sum(dark) < sum(grey) < sum(light)
    assert len(colors_from_title("מזנון לבן/אלון")) == 2  # white body + oak accent
    assert colors_from_title("שולחן דגם נורית") == []  # no colour word
    assert colors_from_title("ספה בכחול")  # Hebrew prefix ב + color
    assert colors_from_title("Sofa in navy blue")


def test_title_colour_overrides_photo_palette_but_photo_is_the_fallback():
    from app.services.model_3d import build_category_mesh
    from app.services.procedural import Palette, resolve_palette

    beige_room_photo = Palette((205, 186, 156), (150, 120, 90))  # walls + floor of a lifestyle photo
    pal = resolve_palette("ספה דגם JOHNSON בגוון כחול", beige_room_photo)
    assert pal.main[2] > pal.main[0]  # blue, not beige
    assert resolve_palette("ספה דגם נורית", beige_room_photo) is beige_room_photo
    scene = build_category_mesh("sofa", 200, 98, 78, pal, "ספה בגוון כחול", 3)
    blueish = [c for c in _vertex_colors(scene) if c[2] > c[0] + 20]
    beigeish = [c for c in _vertex_colors(scene) if c[0] > c[2] + 40 and c[0] > 150]
    assert blueish and not beigeish  # the sofa really is blue and has no beige parts
