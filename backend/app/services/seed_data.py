"""Seed catalog: realistic Israeli-market furniture & appliances (placeholder data).

Product URLs are illustrative placeholders, not live store links. Dimensions are in cm.
"""
from __future__ import annotations

from urllib.parse import quote
from xml.sax.saxutils import escape

from sqlmodel import Session, select

from ..models import Product

_CAT_STYLE = {
    "sofa": ("#607d8b", "🛋"),
    "armchair": ("#a1887f", "🪑"),
    "tv_unit": ("#8d6e63", "📺"),
    "coffee_table": ("#bcaaa4", "☕"),
    "dining_table": ("#a1887f", "🍽"),
    "chair": ("#8d6e63", "🪑"),
    "bed": ("#7986cb", "🛏"),
    "wardrobe": ("#90a4ae", "🚪"),
    "desk": ("#4db6ac", "💻"),
    "appliance": ("#78909c", "🔌"),
    "lighting": ("#fbc02d", "💡"),
    "decor": ("#4db6ac", "🪴"),
    "other": ("#90a4ae", "📦"),
}


def thumbnail(title: str, category: str) -> str:
    color, icon = _CAT_STYLE.get(category, _CAT_STYLE["other"])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">'
        f'<rect width="320" height="240" fill="{color}" opacity="0.18"/>'
        f'<rect x="12" y="12" width="296" height="216" rx="14" fill="none" stroke="{color}" stroke-width="3"/>'
        f'<text x="160" y="125" font-size="76" text-anchor="middle">{icon}</text>'
        f'<text x="160" y="195" font-size="20" text-anchor="middle" fill="#37474f" '
        f'font-family="Arial, sans-serif">{escape(title[:28])}</text></svg>'
    )
    return "data:image/svg+xml;utf8," + quote(svg)


# (store, slug, title, category, price_ils, width, depth, height)
_RAW = [
    ("IKEA ישראל", "kivik-3", "ספה תלת-מושבית KIVIK", "sofa", 3990, 228, 95, 83),
    ("הום סנטר", "lounge-sofa-l", "ספה פינתית לאונג'", "sofa", 5490, 280, 160, 85),
    ("רשת קסטרו Home", "nordic-sofa-2", "ספה דו-מושבית נורדית", "sofa", 2790, 180, 90, 80),
    ("IKEA ישראל", "poang", "כורסה POÄNG", "armchair", 899, 68, 82, 100),
    ("הום סנטר", "velvet-armchair", "כורסת קטיפה אפורה", "armchair", 1290, 78, 80, 85),
    ("IKEA ישראל", "besta-tv", "מזנון טלוויזיה BESTÅ", "tv_unit", 1190, 180, 42, 38),
    ("ביתילי", "oak-tv-220", "מזנון טלוויזיה אלון 220", "tv_unit", 2390, 220, 45, 50),
    ("IKEA ישראל", "lack-coffee", "שולחן סלון LACK", "coffee_table", 149, 90, 55, 45),
    ("ביתילי", "extend-dining-240", "שולחן אוכל נפתח 240", "dining_table", 3290, 240, 100, 76),
    ("IKEA ישראל", "ingolf-chair", "כיסא אוכל INGOLF", "chair", 249, 43, 52, 91),
    ("הום סנטר", "scandi-chair", "כיסא אוכל סקנדינבי", "chair", 390, 46, 54, 84),
    ("IKEA ישראל", "malm-160", "מיטה זוגית MALM 160", "bed", 1990, 175, 209, 100),
    ("ביתילי", "king-bed-180", "מיטה קינג 180 מרופדת", "bed", 4290, 195, 215, 110),
    ("IKEA ישראל", "pax-200", "ארון הזזה PAX 200", "wardrobe", 2490, 200, 66, 236),
    ("ביתילי", "wardrobe-3door", "ארון 3 דלתות לבן", "wardrobe", 2190, 150, 58, 220),
    ("IKEA ישראל", "bekant-desk", "שולחן עבודה BEKANT", "desk", 799, 160, 80, 74),
    ("אלקטרה", "fridge-lg-600", "מקרר דלתות צד 600 ליטר", "appliance", 5990, 91, 74, 178),
    ("חשמל ישיר", "washer-8kg", "מכונת כביסה 8 ק\"ג", "appliance", 1990, 60, 55, 85),
    ("אלקטרה", "oven-built-in", "תנור בנוי 72 ליטר", "appliance", 1790, 60, 55, 60),
    ("חשמל ישיר", "dishwasher-60", "מדיחי כלים 60 ס\"מ", "appliance", 2290, 60, 60, 85),
    ("IKEA ישראל", "arstid-floor-lamp", "מנורת עמידה ÅRSTID", "lighting", 249, 35, 35, 150),
    ("הום סנטר", "round-rug", "שטיח עגול 160", "decor", 590, 160, 160, 2),
    ("IKEA ישראל", "billy-bookcase", "ספרייה BILLY", "other", 449, 80, 28, 202),
]


def seed_rows() -> list[Product]:
    rows = []
    for store, slug, title, cat, price, w, d, h in _RAW:
        rows.append(
            Product(
                store_name=store,
                product_url=f"https://example.co.il/{slug}",
                title=title,
                category=cat,
                price_ils=float(price),
                width_cm=float(w),
                depth_cm=float(d),
                height_cm=float(h),
                image_url=thumbnail(title, cat),
            )
        )
    return rows


def seed_products(session: Session, force: bool = False) -> int:
    """Insert seed products. Without ``force`` does nothing if the table already has rows.

    With ``force`` inserts only seed URLs that do not exist yet (never duplicates).
    Returns number of inserted rows.
    """
    existing = session.exec(select(Product.product_url)).all()
    if existing and not force:
        return 0
    known = set(existing)
    n = 0
    for p in seed_rows():
        if p.product_url in known:
            continue
        session.add(p)
        n += 1
    session.commit()
    return n
