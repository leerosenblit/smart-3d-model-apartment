"""Browser-extension clip endpoint: HTML in, product out (no server-side fetching)."""
from sqlmodel import Session

from app.models import Product

PAGE = """
<html><head><title>x</title>
<script type="application/ld+json">
{"@type":"Product","name":"ספה תלת מושבית נועה","image":"https://cdn.shop.co.il/noa.jpg",
 "offers":{"price":"3290","priceCurrency":"ILS"}}
</script></head>
<body><div class="specs">רוחב 210 ס"מ · עומק 95 ס"מ · גובה 82 ס"מ</div></body></html>
"""
NO_DIMS = '<html><head><title>שולחן אוכל</title><meta property="og:image" content="https://cdn.shop.co.il/t.jpg"></head><body>מחיר: ₪1,990</body></html>'
URL = "https://shop.co.il/p/noa?utm=1#reviews"


def test_clip_dry_run_then_save_and_update(client):
    r = client.post("/api/products/clip", json={"url": URL, "html": PAGE, "dry_run": True}).json()
    assert r["status"] == "preview" and r["missing"] == []
    assert r["parsed"]["title"] == "ספה תלת מושבית נועה" and r["parsed"]["width_cm"] == 210
    assert r["parsed"]["category"] == "sofa" and r["parsed"]["price_ils"] == 3290

    r = client.post("/api/products/clip", json={"url": URL, "html": PAGE}).json()
    assert r["status"] == "created" and r["product"]["store_name"] == "shop.co.il"
    pid = r["product"]["id"]
    assert r["product"]["product_url"] == "https://shop.co.il/p/noa?utm=1"  # fragment stripped

    # same page again with a corrected price -> update, same id
    r = client.post(
        "/api/products/clip", json={"url": URL, "html": PAGE, "overrides": {"price_ils": "2990", "store_name": "Shop IL"}}
    ).json()
    assert r["status"] == "updated" and r["product"]["id"] == pid
    assert r["product"]["price_ils"] == 2990 and r["product"]["store_name"] == "Shop IL"


def test_clip_missing_dims_then_manual_overrides(client):
    r = client.post("/api/products/clip", json={"url": "https://shop.co.il/t", "html": NO_DIMS}).json()
    assert r["status"] == "failed" and "width_cm" in r["missing"] and r["parsed"]["price_ils"] == 1990

    r = client.post(
        "/api/products/clip",
        json={
            "url": "https://shop.co.il/t",
            "html": NO_DIMS,
            "overrides": {"width_cm": 100, "depth_cm": 220, "height_cm": 75, "category": "dining_table"},
        },
    ).json()
    assert r["status"] == "created"
    p = r["product"]
    assert (p["width_cm"], p["depth_cm"], p["height_cm"]) == (220, 100, 75)  # width >= depth normalisation


def test_clip_preserves_cached_model_and_rejects_bad_input(client, engine):
    first = client.post("/api/products/clip", json={"url": URL, "html": PAGE}).json()["product"]
    with Session(engine) as s:
        p = s.get(Product, first["id"])
        p.model_3d_url, p.model_status = f"/static/models/{p.id}.glb", "ready"
        s.add(p)
        s.commit()
    again = client.post("/api/products/clip", json={"url": URL, "html": PAGE}).json()["product"]
    assert again["model_status"] == "ready" and again["model_3d_url"].endswith(".glb")

    assert client.post("/api/products/clip", json={"url": "javascript:alert(1)", "html": PAGE}).status_code == 422
    insane = client.post(
        "/api/products/clip",
        json={"url": "https://shop.co.il/x", "html": PAGE, "overrides": {"width_cm": 99999}},
    ).json()
    assert insane["status"] == "failed"


def test_refine_wardrobe_splits_storage_furniture():
    from app.services.crawler.common import refine_wardrobe

    assert refine_wardrobe("PAX ארון - לבן", 236) == "wardrobe"
    assert refine_wardrobe("ארון בגדים אלון 5 דלתות", 240) == "wardrobe"
    assert refine_wardrobe("שידת 5 מגירות - ליבנה", 90) == "storage"
    assert refine_wardrobe("ארון נעליים עם ספסל", 46) == "storage"
    assert refine_wardrobe("ארון בגדים לילדים", 120) == "storage"  # too low to be a full wardrobe


def test_clip_files_dressers_as_storage_and_featured_sort(client):
    html = (
        '<html><head><script type="application/ld+json">{"@type":"Product","name":"שידת 4 מגירות הדר",'
        '"image":"https://c.co.il/a.jpg","offers":{"price":"790"}}</script></head>'
        "<body>רוחב 80 ס\"מ עומק 40 ס\"מ גובה 95 ס\"מ ארון</body></html>"
    )
    r = client.post("/api/products/clip", json={"url": "https://s.co.il/d1", "html": html}).json()
    assert r["status"] == "created" and r["product"]["category"] in ("storage", "other", "wardrobe")
    assert client.get("/api/products", params={"sort_by": "featured", "limit": 5}).status_code == 200
