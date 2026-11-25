"""CRUD, filtering, seed and floorplan upload tests."""
import io

import pymupdf
from PIL import Image
from sqlmodel import Session, select

from app.models import Product
from app.services.seed_data import seed_products


def new_product(**over):
    base = {
        "store_name": "Test Store",
        "product_url": "https://example.com/p/1",
        "title": "ספה בדיקה",
        "category": "sofa",
        "price_ils": 1000,
        "width_cm": 200,
        "depth_cm": 90,
        "height_cm": 80,
        "image_url": "",
    }
    base.update(over)
    return base


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


# ---- seed

def test_autoseed_on_startup(client):
    products = client.get("/api/products").json()
    assert 18 <= len(products) <= 30
    cats = {p["category"] for p in products}
    for c in ("sofa", "tv_unit", "dining_table", "chair", "bed", "wardrobe", "desk", "appliance", "armchair"):
        assert c in cats
    assert all(p["model_status"] == "none" and p["model_3d_url"] is None for p in products)
    assert all(p["width_cm"] > 0 and p["price_ils"] > 0 for p in products)


def test_seed_is_idempotent(empty_session: Session):
    first = seed_products(empty_session)
    assert first > 0
    assert seed_products(empty_session) == 0
    assert seed_products(empty_session, force=True) == 0  # never duplicates
    assert len(empty_session.exec(select(Product)).all()) == first


# ---- product CRUD

def test_product_crud(client):
    r = client.post("/api/products", json=new_product())
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["model_status"] == "none"

    assert client.post("/api/products", json=new_product()).status_code == 409  # duplicate URL

    assert client.get(f"/api/products/{pid}").json()["title"] == "ספה בדיקה"
    r = client.patch(f"/api/products/{pid}", json={"price_ils": 1234, "category": "bogus"})
    assert r.status_code == 200
    assert r.json()["price_ils"] == 1234 and r.json()["category"] == "other"

    assert client.delete(f"/api/products/{pid}").status_code == 204
    assert client.get(f"/api/products/{pid}").status_code == 404


def test_product_validation(client):
    r = client.post("/api/products", json=new_product(width_cm=0))
    assert r.status_code == 422


def test_product_filters_and_sort(client):
    all_ = client.get("/api/products").json()
    sofas = client.get("/api/products", params={"category": "sofa"}).json()
    assert sofas and all(p["category"] == "sofa" for p in sofas)

    narrow = client.get("/api/products", params={"max_width_cm": 100}).json()
    assert narrow and all(p["width_cm"] <= 100 for p in narrow)
    assert len(narrow) < len(all_)

    shallow = client.get("/api/products", params={"max_depth_cm": 50}).json()
    assert all(p["depth_cm"] <= 50 for p in shallow)

    cheap = client.get("/api/products", params={"max_price_ils": 500}).json()
    assert cheap and all(p["price_ils"] <= 500 for p in cheap)

    found = client.get("/api/products", params={"search": "KIVIK"}).json()
    assert len(found) == 1 and "KIVIK" in found[0]["title"]
    assert client.get("/api/products", params={"search": "ספה"}).json()

    asc = [p["price_ils"] for p in client.get("/api/products", params={"sort_by": "price_asc"}).json()]
    assert asc == sorted(asc)
    desc = [p["price_ils"] for p in client.get("/api/products", params={"sort_by": "price_desc"}).json()]
    assert desc == sorted(desc, reverse=True)
    assert client.get("/api/products", params={"sort_by": "nope"}).status_code == 422

    store = client.get("/api/products/stores").json()[0]
    by_store = client.get("/api/products", params={"store_name": store}).json()
    assert by_store and all(p["store_name"] == store for p in by_store)
    assert "sofa" in client.get("/api/products/categories").json()


# ---- projects

def test_project_crud(client):
    scene = {
        "ceilingHeightCm": 280,
        "walls": [{"id": "w1", "x1": 0, "y1": 0, "x2": 400, "y2": 0, "thicknessCm": 15}],
        "openings": [],
        "placedItems": [],
    }
    r = client.post("/api/projects", json={"name": "דירה", "pixels_per_cm": 2.5, "scene": scene})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["scene"]["ceilingHeightCm"] == 280

    got = client.get(f"/api/projects/{pid}").json()
    assert got["scene"]["walls"][0]["x2"] == 400 and got["pixels_per_cm"] == 2.5

    r = client.put(f"/api/projects/{pid}", json={"name": "דירה 2", "scene": {**scene, "ceilingHeightCm": 300}})
    assert r.json()["name"] == "דירה 2" and r.json()["scene"]["ceilingHeightCm"] == 300
    assert r.json()["pixels_per_cm"] == 2.5  # untouched

    assert [p["id"] for p in client.get("/api/projects").json()] == [pid]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


# ---- floorplan upload

def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), "white").save(buf, "PNG")
    return buf.getvalue()


def test_upload_png_and_static_serving(client):
    r = client.post("/api/floorplans/upload", files={"file": ("plan.png", _png_bytes(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("/static/floorplans/") and body["url"].endswith(".png")
    assert (body["width_px"], body["height_px"]) == (64, 32)
    assert client.get(body["url"]).status_code == 200


def test_upload_rejects_bad_type(client):
    r = client.post("/api/floorplans/upload", files={"file": ("x.txt", b"hello world", "text/plain")})
    assert r.status_code == 415


def test_upload_pdf_is_rendered_to_png(client):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(20, 20, 280, 180))
    pdf_bytes = doc.tobytes()
    doc.close()

    r = client.post("/api/floorplans/upload", files={"file": ("plan.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["url"].endswith(".png")
    assert body["width_px"] > 300  # rendered at high DPI (200 dpi => ~833px for 300pt)
    img = client.get(body["url"])
    assert img.content.startswith(b"\x89PNG")
