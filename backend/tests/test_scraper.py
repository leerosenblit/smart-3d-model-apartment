"""Scraper parser, LLM fallback (mocked) and upsert tests. No network access."""
import asyncio
import json

import httpx
import pytest
from sqlmodel import Session

from app.models import Product
from app.services import scraper
from app.services.scraper import (
    extract_dimensions,
    extract_price,
    infer_category,
    parse_html,
)

JSONLD_HTML = """
<html><head><title>x</title>
<meta property="og:site_name" content="HomeStore IL">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"BreadcrumbList"},
 {"@type":"Product","name":"ספה תלת מושבית אפורה","image":["/img/sofa.jpg"],
  "offers":{"@type":"Offer","price":"3,490.00","priceCurrency":"ILS"},
  "width":{"@type":"QuantitativeValue","value":2.2,"unitCode":"MTR"},
  "depth":{"@type":"QuantitativeValue","value":95,"unitCode":"CMT"},
  "height":"85 ס\\"מ"}
]}
</script></head><body><h1>ספה</h1></body></html>
"""

HEBREW_REGEX_HTML = """
<html><head>
<meta property="og:title" content="שולחן אוכל נפתח עץ אלון">
<meta property="og:image" content="https://cdn.example.com/table.jpg">
</head><body>
<div class="specs">מידות: רוחב 240 ס"מ | עומק 90 | גובה 76 ס"מ</div>
<span class="price">₪ 4,290</span>
</body></html>
"""

TRIPLE_HTML = """
<html><head><title>מזנון טלוויזיה</title></head>
<body><p>מידות המוצר: 180x42x38 ס"מ</p><p>מחיר: 1,190 ש"ח</p></body></html>
"""


def test_jsonld_product_with_units_and_graph():
    d = parse_html(JSONLD_HTML, "https://store.example/p/sofa")
    assert d["title"] == "ספה תלת מושבית אפורה"
    assert d["price_ils"] == 3490.0
    assert d["width_cm"] == 220.0  # 2.2 m -> cm
    assert d["depth_cm"] == 95.0
    assert d["height_cm"] == 85.0
    assert d["image_url"] == "https://store.example/img/sofa.jpg"
    assert d["category"] == "sofa"
    assert d["store_name"] == "HomeStore IL"
    assert "jsonld" in d["_sources"]


def test_hebrew_labeled_dimensions_and_opengraph():
    d = parse_html(HEBREW_REGEX_HTML, "https://s.example/t")
    assert (d["width_cm"], d["depth_cm"], d["height_cm"]) == (240.0, 90.0, 76.0)
    assert d["price_ils"] == 4290.0
    assert d["category"] == "dining_table"
    assert d["image_url"] == "https://cdn.example.com/table.jpg"
    assert d["store_name"] == "s.example"


def test_triple_dimension_pattern():
    d = parse_html(TRIPLE_HTML, "https://s.example/tv")
    assert (d["width_cm"], d["depth_cm"], d["height_cm"]) == (180.0, 42.0, 38.0)
    assert d["price_ils"] == 1190.0
    assert d["category"] == "tv_unit"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("220x95x85", {"width": 220, "depth": 95, "height": 85}),
        ("220 × 95 × 85 cm", {"width": 220, "depth": 95, "height": 85}),
        ("2.2 x 0.95 x 0.85 m", {"width": 220, "depth": 95, "height": 85}),
        ("2200x950x850 mm", {"width": 220, "depth": 95, "height": 85}),
        ("H x W x D: 85 x 220 x 95 cm", {"width": 220, "depth": 95, "height": 85}),
        ("גובה x רוחב x עומק 85x220x95", {"width": 220, "depth": 95, "height": 85}),
        ("רוחב 240 עומק 90 גובה 80", {"width": 240, "depth": 90, "height": 80}),
        ("Width: 1.8m Depth: 90 cm Height: 0.8 m", {"width": 180, "depth": 90, "height": 80}),
        ("רוחב: 60 ס״מ", {"width": 60}),
    ],
)
def test_extract_dimensions(text, expected):
    assert extract_dimensions(text) == {k: float(v) for k, v in expected.items()}


def test_extract_price_variants():
    assert extract_price("רק ב-₪1,990") == 1990.0
    assert extract_price("1990 ש\"ח") == 1990.0
    assert extract_price("Price: NIS 249.90") == 249.9
    assert extract_price("no price here") is None


def test_infer_category():
    assert infer_category("מקרר דלתות צד") == "appliance"
    assert infer_category("שולחן סלון עגול") == "coffee_table"
    assert infer_category("כורסה מעוצבת") == "armchair"
    assert infer_category("Modern 3 seater sofa") == "sofa"
    assert infer_category("משהו אחר לגמרי") == "other"


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_ingest_creates_then_upsert_preserves_model(empty_session: Session):
    state = {"price": "3490"}

    def handler(request: httpx.Request) -> httpx.Response:
        if "missing" in request.url.path:
            return httpx.Response(404)
        html = JSONLD_HTML.replace("3,490.00", state["price"])
        return httpx.Response(200, text=html)

    url = "https://store.example/p/sofa"

    async def run(urls):
        async with _mock_client(handler) as c:
            return await scraper.ingest_urls(empty_session, urls, client=c)

    res = asyncio.run(run([url]))
    assert res[0].status == "created" and res[0].product.price_ils == 3490.0

    # simulate a cached 3D model, then re-ingest with a new price
    p = empty_session.get(Product, res[0].product.id)
    p.model_3d_url = f"/static/models/{p.id}.glb"
    p.model_status = "ready"
    empty_session.add(p)
    empty_session.commit()

    state["price"] = "2990"
    res2 = asyncio.run(run([url]))
    assert res2[0].status == "updated" and res2[0].product.price_ils == 2990.0
    assert res2[0].product.id == p.id
    assert res2[0].product.model_status == "ready"
    assert res2[0].product.model_3d_url == f"/static/models/{p.id}.glb"


def test_batch_reports_per_url_failures(empty_session: Session):
    def handler(request: httpx.Request) -> httpx.Response:
        if "missing" in request.url.path:
            return httpx.Response(404)
        if "nodims" in request.url.path:
            return httpx.Response(200, text="<html><head><title>ספה</title></head><body>hello</body></html>")
        return httpx.Response(200, text=TRIPLE_HTML)

    async def run():
        async with _mock_client(handler) as c:
            return await scraper.ingest_urls(
                empty_session,
                [
                    "https://s.example/ok",
                    "https://s.example/missing",
                    "https://s.example/nodims",
                    "not a url",
                    "https://s.example/ok",  # duplicate is ignored
                ],
                client=c,
            )

    res = {r.url: r for r in asyncio.run(run())}
    assert res["https://s.example/ok"].status == "created"
    assert res["https://s.example/missing"].status == "failed" and "404" in res["https://s.example/missing"].error
    assert res["https://s.example/nodims"].status == "failed"
    assert res["not a url"].status == "failed"
    assert len(res) == 4


def test_ssrf_guard():
    for bad in ("http://localhost:8000/x", "http://127.0.0.1/x", "http://192.168.1.5/x", "ftp://x.com/a"):
        with pytest.raises(ValueError):
            scraper.validate_url(bad)
    assert scraper.validate_url("https://shop.co.il/a#frag") == "https://shop.co.il/a"


def test_llm_fallback_fills_missing_fields(monkeypatch, empty_session: Session):
    """With an API key set and dims missing, the LLM result fills the gaps (mocked transport)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.anthropic.com":
            calls.append(json.loads(request.content))
            payload = {
                "title": "ספה LLM",
                "store_name": "Store",
                "category": "sofa",
                "price_ils": 2500,
                "width_cm": 210,
                "depth_cm": 92,
                "height_cm": 84,
                "image_url": None,
            }
            return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(payload)}]})
        return httpx.Response(200, text="<html><head><title>ספה יפה</title></head><body>ללא מידות</body></html>")

    async def run():
        async with _mock_client(handler) as c:
            return await scraper.ingest_urls(empty_session, ["https://s.example/llm"], client=c)

    res = asyncio.run(run())[0]
    assert res.status == "created" and res.source == "llm"
    assert (res.product.width_cm, res.product.depth_cm, res.product.height_cm) == (210, 92, 84)
    assert res.product.price_ils == 2500
    assert calls and calls[0]["system"].startswith("You extract")


def test_llm_not_called_without_key(empty_session: Session):
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("api.anthropic.com", "api.openai.com"):
            called.append(1)
        return httpx.Response(200, text="<html><head><title>ספה</title></head></html>")

    async def run():
        async with _mock_client(handler) as c:
            return await scraper.ingest_urls(empty_session, ["https://s.example/x"], client=c)

    assert asyncio.run(run())[0].status == "failed"
    assert not called


def test_clean_llm_result_validates():
    out = scraper.clean_llm_result(
        {"title": " T ", "category": "spaceship", "width_cm": "120", "depth_cm": -5, "height_cm": None,
         "price_ils": "abc", "image_url": "javascript:alert(1)"}
    )
    assert out == {"title": "T", "width_cm": 120.0}
