"""Pure-function tests for the catalog crawler (no network)."""
import asyncio
import json

import pytest
from sqlmodel import select

from app.models import Product
from app.services.crawler import common as c
from app.services.crawler.http import RobotsRules
from app.services.crawler.runner import CrawlState, crawl_store
from app.services.crawler.stores import (
    ShopifyStore,
    Store,
    ikea_dimension_block,
    interleave_by_category,
    jsonld_product,
    ld_price,
)


# ------------------------------------------------------------------ cleaning
def test_clean_title_strips_invisible_marks_and_dimension_suffix():
    raw = 'VUKU ארון - לבן ‎74x51x149 ס"מ‏'
    assert c.clean_title(raw) == "VUKU ארון - לבן"
    assert c.clean_title("שולחן אוכל  90*180 סמ") == "שולחן אוכל"
    assert c.clean_title("KIVIK ספה 3 מושבים") == "KIVIK ספה 3 מושבים"  # numbers inside stay


def test_strip_html_keeps_line_breaks_between_blocks():
    assert "רוחב: 80" in c.strip_html("<p>ארון</p><p>רוחב: 80 ס&quot;מ</p>")
    assert c.strip_html("a<br>b").split("\n") == ["a", "b"]


# ------------------------------------------------------------------ Hebrew classification
@pytest.mark.parametrize(
    "title,expected",
    [
        ('ספה תלת מושבית בד קורדרוי 240 ס"מ', "sofa"),
        ("ספה נפתחת למיטה דגם הדס", "sofa"),
        ("כורסת טלוויזיה מעור", "armchair"),
        ("מזנון טלוויזיה צף 180", "tv_unit"),
        ("שולחן סלון דגם ארבל", "coffee_table"),
        ("שולחן אוכל עגול נפתח", "dining_table"),
        ("שולחן כתיבה עם מגירות", "desk"),
        ("כיסא בר ריין אפור", "chair"),
        ("מיטה זוגית 160x200", "bed"),
        ("ארון בגדים 4 דלתות", "wardrobe"),
        ("Samsung RT42 מקרר מקפיא עליון", "appliance"),
        ("מנורת שולחן 8237", "lighting"),
        ("שטיח ורונה 200/290", "decor"),
        ("שולחן מתקפל 60*60", "table"),  # resolved later by height
    ],
)
def test_classify_he_positive(title, expected):
    assert c.classify_he(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "כיסוי לספה זוגית",
        "מפת שולחן מודפסת",
        "רגלי ספה מעץ",
        "מושב אסלה טריקה שקטה",
        "מזרון יוגה",
        "נורת לד E27",
        "ידית לארון ולמגירה",
        "שטיח אמבטיה 70/40",
        "ראש מיטה ברצלונה",
        "תבנית לתנור",
    ],
)
def test_classify_he_rejects_accessories(title):
    assert c.classify_he(title) is None


def test_classify_he_uses_hint_only_when_title_inconclusive():
    assert c.classify_he("דגם סוליס", hint="כורסאות וכסאות המתנה") == "armchair"
    assert c.classify_he("מזרון יוגה", hint="ספות") is None
    assert c.classify_he("דגם סוליס") is None


def test_resolve_table_by_height():
    assert c.resolve_table("table", 45) == "coffee_table"
    assert c.resolve_table("table", 75) == "dining_table"
    assert c.resolve_table("sofa", 10) == "sofa"


# ------------------------------------------------------------------ IKEA slugs
@pytest.mark.parametrize(
    "slug,expected",
    [
        ("vimle-3-seat-sofa-with-headrest-gunnared-medium-grey-s39401327", "sofa"),
        ("friheten-klagshamn-corner-sofa-bed-with-storage-skiftebo-dark-grey-s69444330", "sofa"),
        ("vuku-wardrobe-white-80331973", "wardrobe"),
        ("yxstaby-gaming-tv-stand-on-castors-white-40628952", "tv_unit"),
        ("markus-office-chair-vissle-dark-grey-70261150", "chair"),
        ("lagkapten-alex-desk-white-s59607681", "desk"),
        ("naevlinge-led-desk-lamp-green-20637132", "lighting"),
        ("voxloev-dining-table-light-bamboo-50611263", "dining_table"),
        ("vitval-loft-bed-frame-white-light-grey-60372276", "bed"),
        ("stoense-rug-low-pile-medium-grey-30426836", "decor"),
        ("lagan-fridge-freezer-freestanding-white-90571298", "appliance"),
        ("poaeng-armchair-birch-veneer-gunnared-dark-grey-s89502055", "armchair"),
        ("norrmjoele-table-oak-effect-black-00620566", "table"),
        ("tonstad-groensta-table-and-6-chairs-oak-veneer-grey-s49633874", "dining_table"),
        ("metod-high-cab-f-oven-w-2-doors-shelves-white-s29464424", "wardrobe"),
    ],
)
def test_classify_ikea_slug(slug, expected):
    assert c.classify_ikea_slug(slug) == expected


@pytest.mark.parametrize(
    "slug",
    [
        "valnaes-cover-for-3-seat-sofa-alhamn-dark-grey-blue-10624111",
        "sandviva-oven-glove-silicone-dark-grey-20587882",
        "ytberg-cabinet-lighting-white-dimmable-00516819",
        "alvaro-cushion-cover-pink-90532343",
        "vinterfint-duvet-set-red-10622222",
        "metod-door-for-cabinet-white-12345678",
        "ikea-bulb-led-e27-806-lumen-90000000",
    ],
)
def test_classify_ikea_slug_rejects_accessories(slug):
    assert c.classify_ikea_slug(slug) is None


def test_ikea_family_key_ignores_colours_and_id():
    a = c.ikea_family_key("vuku-wardrobe-white-80331973")
    b = c.ikea_family_key("vuku-wardrobe-black-80331974")
    assert a == b == "vuku-wardrobe"


# ------------------------------------------------------------------ dimension parsing
def test_parse_dims_labeled_hebrew():
    d = c.parse_dims('ארון מידות: רוחב: 80 ס"מ גובה: 240 ס"מ עומק: 57 ס"מ חלוקה')
    assert d == {"width": 80.0, "height": 240.0, "depth": 57.0}


def test_parse_dims_abbreviations_and_length():
    assert c.parse_dims("מידות חיצוניות בס\"מ: ר' 123, ע' 50.1 , ג'76.5") == {
        "width": 123.0,
        "depth": 50.1,
        "height": 76.5,
    }
    bed = c.parse_dims("רוחב 150, אורך 201 , גובה ראש מיטה 106")
    assert bed == {"width": 150.0, "depth": 201.0, "height": 106.0}


def test_parse_dims_triple_pair_diameter_and_rug_slash():
    assert c.parse_dims('מזנון 160*45*50 ס"מ') == {"width": 160.0, "depth": 45.0, "height": 50.0}
    assert c.parse_dims("שטיח 1.50*1.00") == {"width": 150.0, "depth": 100.0}
    assert c.parse_dims("שטיח אליזה 50/80") == {}  # slash only with opt-in
    assert c.parse_dims("שטיח אליזה 50/80", slash_pair=True) == {"width": 50.0, "depth": 80.0}
    r = c.parse_dims('שולחן עגול קוטר 120 ס"מ גובה 75 ס"מ')
    assert (r["width"], r["depth"], r["height"]) == (120.0, 120.0, 75.0)


def test_parse_dims_ignores_unlabeled_prose():
    assert c.parse_dims("ארון נוח ומרווח עם חלוקה פנימית") == {}
    assert "height" not in c.parse_dims('גובה הכיסא הכולל: 104-122ס"מ')


def test_ikea_dimension_block_from_embedded_json():
    html = (
        '..."measurementsProps":{"x":1,"measurements":[{"measure":"45 ס\\"מ","name":"גובה","type":"1"},'
        '{"measure":"75 ס\\"מ","name":"קוטר","type":"2"},{"measure":"10 ק\\"ג","name":"עומס מרבי","type":"3"}],'
        '"packaging":{}}'
    )
    block = ikea_dimension_block(html)
    assert "גובה: 45" in block and "קוטר: 75" in block and "עומס" not in block
    assert c.parse_dims(block)["width"] == 75.0


# ------------------------------------------------------------------ validation / normalisation
def _raw(**kw):
    base = dict(
        title="ספה 3 מושבים",
        category="sofa",
        price_ils=2990,
        width_cm=220,
        depth_cm=95,
        height_cm=85,
        image_url="https://cdn.example.com/a.jpg",
        store_name="X",
    )
    base.update(kw)
    return base


def test_validate_product_ok_and_normalises_width_ge_depth():
    ok, why = c.validate_product(_raw(category="dining_table", width_cm=90, depth_cm=180, height_cm=75))
    assert why == "" and ok["width_cm"] == 180 and ok["depth_cm"] == 90


def test_validate_product_keeps_bed_orientation():
    ok, _ = c.validate_product(_raw(category="bed", title="מיטה זוגית", width_cm=160, depth_cm=200, height_cm=40))
    assert (ok["width_cm"], ok["depth_cm"]) == (160, 200)
    ok, _ = c.validate_product(_raw(category="bed", title="מיטה יחיד", width_cm=97, depth_cm=207, height_cm=60))
    assert (ok["width_cm"], ok["depth_cm"]) == (97, 207)


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"price_ils": 0}, "no_price"),
        ({"price_ils": None}, "no_price"),
        ({"image_url": "http://insecure/x.jpg"}, "no_image"),
        ({"image_url": ""}, "no_image"),
        ({"title": ""}, "no_title"),
        ({"width_cm": None}, "no_dims"),
        ({"height_cm": 0}, "no_dims"),
        ({"width_cm": 2200}, "insane_dims:sofa"),
        ({"height_cm": 5}, "insane_dims:sofa"),
        ({"category": None}, "no_category"),
        ({"category": "spaceship"}, "bad_category"),
    ],
)
def test_validate_product_rejections(kw, reason):
    ok, why = c.validate_product(_raw(**kw))
    assert ok is None and why == reason


def test_validate_product_rug_gets_default_height_and_table_is_resolved():
    ok, _ = c.validate_product(
        _raw(category="decor", title="שטיח סלון", width_cm=200, depth_cm=290, height_cm=None)
    )
    assert ok["height_cm"] == c.RUG_DEFAULT_HEIGHT_CM
    ok, _ = c.validate_product(_raw(category="table", title="שולחן", width_cm=60, depth_cm=60, height_cm=45))
    assert ok["category"] == "coffee_table"
    ok, _ = c.validate_product(_raw(category="table", title="שולחן", width_cm=160, depth_cm=90, height_cm=75))
    assert ok["category"] == "dining_table"


def test_validate_product_protocol_relative_image_is_upgraded():
    ok, _ = c.validate_product(_raw(image_url="//cdn.shopify.com/x.jpg"))
    assert ok["image_url"] == "https://cdn.shopify.com/x.jpg"


# ------------------------------------------------------------------ JSON-LD / Shopify
def test_jsonld_product_and_price_tolerate_raw_newlines():
    html = (
        '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
        '"name":"x","description":"a\nb","offers":[{"price":"1,299.00"},{"price":"999"}]}</script>'
    )
    node = jsonld_product(html)
    assert node["name"] == "x" and ld_price(node) == 999.0


def test_shopify_product_from_json():
    store = ShopifyStore("t", "חנות", "shop.example.co.il")
    p = {
        "title": "ארון בגדים עמי 2 דלתות",
        "handle": "armoire-1",
        "product_type": "ארונות",
        "body_html": "<p>רוחב: 80 ס&quot;מ</p><p>גובה: 240 ס&quot;מ</p><p>עומק: 57 ס&quot;מ</p>",
        "variants": [{"title": "Default Title", "price": "999.00", "available": True}],
        "images": [{"src": "https://cdn.shopify.com/a.jpg"}],
    }
    cand = store.product_from_json(p)
    assert cand["url"] == "https://shop.example.co.il/products/armoire-1"
    ok, why = c.validate_product(cand["data"])
    assert why == "" and ok["category"] == "wardrobe"
    assert (ok["width_cm"], ok["depth_cm"], ok["height_cm"]) == (80, 57, 240)
    # accessory title -> irrelevant
    assert store.product_from_json({**p, "title": "ידית לארון"}) is None
    # no usable variant price -> irrelevant
    assert store.product_from_json({**p, "variants": [{"title": "x", "price": "0"}]}) is None


def test_interleave_by_category_round_robin():
    cands = [{"url": f"a{i}", "category": "a"} for i in range(3)] + [
        {"url": f"b{i}", "category": "b"} for i in range(2)
    ]
    order = [x["url"] for x in interleave_by_category(cands)]
    assert order[:4] == ["a0", "b0", "a1", "b1"] and set(order) == {x["url"] for x in cands}


# ------------------------------------------------------------------ robots
def test_robots_rules_wildcards_and_longest_match():
    rules = RobotsRules(
        "User-agent: Googlebot\nDisallow: /\n\n"
        "User-agent: *\nDisallow: /*?\nDisallow: /catalog/\nDisallow: /furniture/101090000\n"
        "Allow: /catalog/public/\n"
    )
    assert rules.allowed("https://www.ace.co.il/4497062")
    assert rules.allowed("https://www.ace.co.il/furniture/living-room-furniture/tv-stand")
    assert not rules.allowed("https://www.ace.co.il/furniture/tv-stand?p=2")
    assert not rules.allowed("https://www.ace.co.il/catalog/x")
    assert rules.allowed("https://www.ace.co.il/catalog/public/x")
    assert not rules.allowed("https://www.ace.co.il/furniture/101090000/101090100")
    # no '*' group (only a bot-specific one) -> everything allowed
    assert RobotsRules("User-agent: Googlebot\nDisallow: /\n").allowed("https://x.il/a")


# ------------------------------------------------------------------ runner (resume + persistence)
class _FakeStore(Store):
    key = "fake"
    store_name = "פייק"
    host = "fake.example"

    def __init__(self):
        self.fetched: list[str] = []

    async def discover(self, http):
        return [
            {"url": "https://fake.example/p/1", "category": "sofa", "title": "ספה"},
            {"url": "https://fake.example/p/2", "category": "sofa", "title": "ספה"},
            {"url": "https://fake.example/p/3", "category": "sofa", "title": "ספה"},
        ]

    async def fetch(self, http, cand):
        self.fetched.append(cand["url"])
        if cand["url"].endswith("/2"):
            return None  # page without data
        n = int(cand["url"][-1])
        return _raw(title=f"ספה {n}", store_name=self.store_name)


@pytest.fixture()
def crawl_storage(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


def test_crawl_store_upserts_skips_and_resumes(crawl_storage, empty_session):
    store = _FakeStore()
    state = CrawlState(crawl_storage / "state.json")
    rep = asyncio.run(crawl_store(store, None, empty_session, state, workers=2))
    assert (rep.created, rep.updated, sum(rep.skipped.values())) == (2, 0, 1)
    assert len(empty_session.exec(select(Product)).all()) == 2
    saved = json.loads((crawl_storage / "state.json").read_text(encoding="utf-8"))
    assert saved["stores"]["fake"]["done"]["https://fake.example/p/1"] == "ok"
    assert saved["stores"]["fake"]["done"]["https://fake.example/p/2"].startswith("skip:")

    # resume: nothing left to do, nothing fetched again
    store2 = _FakeStore()
    rep2 = asyncio.run(
        crawl_store(store2, None, empty_session, CrawlState(crawl_storage / "state.json"), resume=True)
    )
    assert store2.fetched == [] and rep2.created == 0

    # without --resume everything is re-processed and upserted (no duplicates)
    store3 = _FakeStore()
    rep3 = asyncio.run(crawl_store(store3, None, empty_session, CrawlState(crawl_storage / "state.json")))
    assert (rep3.created, rep3.updated) == (0, 2)
    assert len(empty_session.exec(select(Product)).all()) == 2


def test_crawl_never_wipes_cached_3d_model(crawl_storage, empty_session):
    asyncio.run(crawl_store(_FakeStore(), None, empty_session, CrawlState(crawl_storage / "s.json")))
    p = empty_session.exec(select(Product).where(Product.product_url == "https://fake.example/p/1")).one()
    p.model_status, p.model_3d_url = "ready", "/static/models/1.glb"
    empty_session.add(p)
    empty_session.commit()
    asyncio.run(crawl_store(_FakeStore(), None, empty_session, CrawlState(crawl_storage / "s.json")))
    empty_session.refresh(p)
    assert p.model_status == "ready" and p.model_3d_url == "/static/models/1.glb"


def test_flat_wall_items_get_thin_depth():
    ok, _ = c.validate_product(
        _raw(category="decor", title="מראה גוף", width_cm=75, depth_cm=0, height_cm=178.5)
    )
    assert (ok["width_cm"], ok["depth_cm"], ok["height_cm"]) == (75, 3.0, 178.5)
    ok, _ = c.validate_product(  # "60/160" pair arrives as width/depth -> width x height
        _raw(category="decor", title="מראה אובלית", width_cm=60, depth_cm=160, height_cm=0)
    )
    assert (ok["width_cm"], ok["depth_cm"], ok["height_cm"]) == (60, 3.0, 160)


@pytest.mark.parametrize(
    "title",
    ["פינת אוכל הרמוני שולחן + 4 כסאות", "שולחן אוכל + 4 כסאות", "סלון 2+3 דגם נורית", "מערכת ישיבה 3+2"],
)
def test_multi_piece_sets_are_excluded(title):
    assert c.classify_he(title) is None


def test_crawl_state_save_merges_stores_written_by_other_processes(tmp_path):
    path = tmp_path / "state.json"
    a, b = CrawlState(path), CrawlState(path)
    a.store("ikea")["done"]["u1"] = "ok"
    b.store("ace")["done"]["u2"] = "ok"
    a.save()
    b.save()  # must not drop ikea
    saved = json.loads(path.read_text(encoding="utf-8"))["stores"]
    assert saved["ikea"]["done"] == {"u1": "ok"} and saved["ace"]["done"] == {"u2": "ok"}


def test_parse_product_dims_trusts_pairs_only_in_title():
    # sleeping size of a sofa bed in the prose must not become the footprint
    assert c.parse_product_dims("ספה נפתחת", "נפתחת למיטה בגודל 190*155 ס\"מ") == {}
    assert c.parse_product_dims("מיטה זוגית 160x200", "") == {"width": 160.0, "depth": 200.0}
    # labeled description values override the (mattress-size) title pair
    d = c.parse_product_dims("מיטה זוגית 160x200", "מידות חיצוניות: אורך 202 ס\"מ רוחב 150 ס\"מ גובה ראש מיטה 117 ס\"מ")
    assert d == {"width": 150.0, "depth": 202.0, "height": 117.0}


def test_low_bed_frame_is_rejected_but_mattress_is_fine():
    ok, why = c.validate_product(_raw(category="bed", title="מיטה זוגית", width_cm=146, depth_cm=194, height_cm=13))
    assert ok is None and why == "insane_dims:bed"
    ok, _ = c.validate_product(_raw(category="bed", title="מזרן קפיצי", width_cm=160, depth_cm=200, height_cm=13))
    assert ok is not None
