"""Pure helpers shared by all store adapters: text cleaning, classification, dimension parsing and
sanity validation. No network / DB access here so everything is unit-testable.

All dimensions are centimeters (project rule); prices are ILS.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Optional

from ..scraper import extract_dimensions

CATEGORY_SET = {
    "sofa", "armchair", "tv_unit", "coffee_table", "dining_table", "chair", "bed", "wardrobe", "storage", "desk",
    "appliance", "lighting", "decor", "other",
}

# --------------------------------------------------------------------------- text cleaning

_INVISIBLE = {
    ord(c): None
    for c in "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿​‌‍"
}

_DIM_SUFFIX_RE = re.compile(
    r"[\s,\-–|]*\d+(?:[.,]\d+)?(?:\s*[x×*]\s*\d+(?:[.,]\d+)?)+\s*(?:ס\"מ|ס״מ|סמ|ס'מ|cm|מ\"מ)?\s*$",
    re.IGNORECASE,
)


def clean_text(s: Any) -> str:
    """Unescape HTML entities, drop bidi/zero-width marks, collapse whitespace."""
    if s is None:
        return ""
    s = _html.unescape(str(s)).translate(_INVISIBLE).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def clean_title(raw: Any) -> str:
    """Real product title: invisible marks removed and a trailing dimension suffix (` 74x51x149 ס"מ`) cut."""
    t = clean_text(raw)
    for _ in range(2):
        t = _DIM_SUFFIX_RE.sub("", t).strip()
    return t.strip(" -–|,").strip()


def strip_html(s: Any) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", str(s))
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).translate(_INVISIBLE).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


# --------------------------------------------------------------------------- classification (Hebrew)

# Words that, when they START a title, mean "accessory / spare part / service", not furniture.
_ACCESSORY_FIRST = {
    "כיסוי", "כיסויי", "כיסויים", "מצע", "מצעים", "ציפית", "ציפיות", "סדין", "סדינים", "רגלי", "רגלית",
    "רגליים", "גלגלי", "גלגלים", "ידית", "ידיות", "מסנן", "פילטר", "צינור", "שלט", "נועל", "סיפון",
    "מעמד", "מתקן", "תושבת", "מארז", "אביזרי", "אביזר", "חלקי", "חלק", "מכסה", "מגן", "בסיס", "ריפוד",
    "כרית", "כריות", "מגני", "מגש", "תבנית", "קולב", "מתלה", "ווים", "וו", "בורג", "ברגים", "מסילה",
    "שקית", "שקיות", "מגירה", "מדף", "מדפים", "דלת", "דלתות", "פנל", "קיט", "ערכה", "ערכת", "סט",
    "נורה", "נורת", "נורות", "אהיל", "מתאם", "מפסק", "שקע", "וילון", "וילונות", "מפה", "מפת", "זווית", "מגבת",
    "שמיכה", "שמיכת", "כרטיס", "שובר", "מתנה", "אחריות", "שירות", "הובלה", "התקנה", "הרכבה",
    "ניקוי", "מנקה", "ספריי", "משחה", "שמן", "צבע", "דבק", "חומר", "רפידה", "רפידות", "מגנט",
    "סרט", "פס", "כבל", "מטען", "סוללה", "סוללות", "בטרייה", "מנעול", "ציר", "צירים", "ברז", "כיור",
    "צעצוע", "בובה", "משחק", "משחקי", "פאזל", "תיק", "ילקוט", "בגד", "חולצה", "מכנסיים", "נעלי", "נעל",
    "cover", "covers", "leg", "legs", "handle", "knob", "filter", "bulb", "remote",
}

_EXCLUDE_ANY = re.compile(
    r"יוגה|פילאטיס|פילטיס|התעמלות|קמפינג|מתנפח|מתנפחת|מזרן ים|מזרון ים|דשא סינטטי|שטיח אמבטיה|שטיחון|"
    r"שטיח רכב|שטיחי רכב|שטיח עכבר|מייבש (?:כלים|שיער|ידיים|שערות|פירות|מזון)|"
    r"צעצוע|דגם מיניאטורי|בובות|שטיח משחק|שטיח פעילות|בית בובות|כיסוי ל|מתאים ל(?:מקרר|תנור|מדיח)|"
    r"מצע ל|קצף סיליקון|חיתוך|משחק|סנוקר|קלפים|גיהוץ|פינג|ערכת|שיזוף|מושב אסלה|לבריכה|כושר|ראש מיטה|"
    r"ראש למיטה|מפת |זווית כסא|פינת (?:אוכל|קפה|ישיבה)|\+\s*\d*\s*(?:כסאות|כיסאות|ספסלים|ספסל|שרפרפים)|"
    r"(?:ספה|סלון|ספת)\s*\d\s*\+\s*\d|\d\s*\+\s*\d\s*(?:ספה|מערכת|סלון)|מסגרת מיטה ל|תאורת (?:חירום|הצפה)|תאורת חוץ|פנס חירום|בקבוק|תיק "
)

# (category, pattern) matched against the FIRST FEW WORDS only (the head noun comes first in Hebrew titles).
# Order matters on ties: more specific patterns first.
_HE_PATTERNS: list[tuple[str, str]] = [
    ("tv_unit", r"מזנון|מזנונים|מערכת\s+(?:טלוויזיה|טלויזיה|מדיה)|(?:ארון|שידת|שידה|יחידת|קונסולת|קונסולה)\s+(?:ל)?(?:טלוויזיה|טלויזיה|מדיה)"),
    ("coffee_table", r"שולחן\s+(?:סלון|קפה|צד|טרקלין|ליד|עזר|קונסולה)|שולחנות\s+(?:סלון|קפה|צד)|סט\s+שולחנות|coffee\s*table"),
    ("dining_table", r"שולחן\s+(?:אוכל|נפתח|בר|פינת|ישיבה|גינה|למטבח|מטבח)|פינת\s+אוכל|פינת\s+קפה|פינת\s+ישיבה|שולחנות\s+אוכל"),
    ("desk", r"שולחן\s+(?:כתיבה|עבודה|מחשב|גיימינג|לימוד|ילדים|איפור|תלמיד|משרדי|מנהלים)|שולחנות\s+עבודה|עמדת\s+(?:עבודה|מחשב|גיימינג)"),
    ("table", r"שולחן|שולחנות"),
    ("armchair", r"כורסא|כורסה|כורסת|כורסאות|כורסות|ריקליינר|פוטל"),
    ("sofa", r"ספה|ספת|ספות|ספונית|סלון\s+פינתי|מערכת\s+ישיבה"),
    ("bed", r"מיטה|מיטת|מיטות|מזרן|מזרון|מזרנים|מזרונים|עריסה|עריסת"),
    ("appliance", r"מקרר|מקפיא|מדיח|מכונת\s+כביסה|מכונות\s+כביסה|מייבש\s+(?:כביסה|בגדים)|תנור|כיריים|כירים|קולט\s+אדים|מיקרוגל|מזגן|טלוויזיה|טלויזיה"),
    ("lighting", r"מנורה|מנורת|מנורות|גוף\s+תאורה|גופי\s+תאורה|נברשת|ספוט|תאורת|תאורה|פנס\s+(?:קיר|תלוי|רצפה|שולחני|גינה|תקרה)"),
    ("wardrobe", r"ארון|ארונית|ארונות|שידה|שידת|ויטרינה|קומודה|שידות|מערכת\s+(?:אחסון|ארונות)"),
    ("chair", r"כיסא|כסא|כיסאות|כסאות|שרפרף|שרפרפים|ספסל|בר\s*סטול|סטול|פוף|פופים|מושב"),
    ("other", r"כוננית|כוורת|כוורות|כוננות|ספריה|ספרייה|מערכת\s+מדפים|מחיצה|פרגוד"),
    ("decor", r"שטיח|שטיחים|מראה|מראות|אגרטל|פסל|עציץ|עציצים|שעון\s+קיר|קנבס"),
]
_HE_RULES: list[tuple[str, re.Pattern]] = [
    (cat, re.compile(r"(?<![א-תA-Za-z0-9])(?:" + pat + r")", re.IGNORECASE)) for cat, pat in _HE_PATTERNS
]
_HEAD_TOKENS = 4


def classify_he(title: str, hint: str = "") -> Optional[str]:
    """Furniture category from a Hebrew product title (head noun among the first words).

    None = not a relevant piece of furniture/appliance/lighting/decor. ``hint`` is an optional store
    taxonomy string (e.g. Shopify product_type) used only when the title itself is inconclusive. The
    pseudo-category ``"table"`` (plain שולחן) must be resolved with :func:`resolve_table` once the
    height is known.
    """
    title = clean_text(title)
    words = title.split()
    if not words:
        return None
    first = words[0].strip("\"'׳״-").lower()
    if first in _ACCESSORY_FIRST or _EXCLUDE_ANY.search(title):
        return None
    prefix = " ".join(words[:_HEAD_TOKENS])
    best: Optional[tuple[int, int, str]] = None
    for rank, (cat, rx) in enumerate(_HE_RULES):
        m = rx.search(prefix)
        if m:
            key = (m.start(), rank, cat)
            if best is None or key < best:
                best = key
    if best:
        return best[2]
    if hint:
        h = clean_text(hint)
        if h and not _EXCLUDE_ANY.search(h) and h.split()[0] not in _ACCESSORY_FIRST:
            for cat, rx in _HE_RULES:
                if rx.search(h):
                    return cat
    return None


def resolve_table(category: str, height_cm: float) -> str:
    """A plain 'table' becomes a coffee table when low, otherwise a dining table."""
    if category != "table":
        return category
    return "coffee_table" if height_cm <= 58 else "dining_table"


# --------------------------------------------------------------------------- classification (IKEA slugs)

_IKEA_EXCLUDE = re.compile(
    r"(?:^|-)(?:cover|covers|cushion|cushions|pillow|pillows|pillowcase|pillowcases|leg|legs|bulb|bulbs|shade|"
    r"shades|handle|handles|knob|knobs|hinge|hinges|bracket|brackets|fitting|fittings|accessory|accessories|"
    r"spare|filter|filters|duvet|duvets|sheet|sheets|throw|blanket|curtain|curtains|blind|blinds|cord|cable|"
    r"plug|socket|switch|remote|organiser|organizer|insert|inserts|divider|dividers|hanger|hangers|hook|hooks|"
    r"rail|rails|pad|protector|topper|slats|plinth|toy|toys|pot|candle|candles|candleholder|towel|towels|mat|"
    r"doormat|poster|picture|clock|lid|lids|holder|holders|sink|tap|faucet|worktop|countertop|wheels|runner|"
    r"dish|plate|bowl|mug|cup|pan|jug|tray|basket|baskets|box|boxes|bin|sofa-cover|chair-pad|seat-pad|"
    r"changing-table|play-table|children-s-play|play-mat|decoration|decorations|garland|lantern|artificial|"
    r"flower|flowers|bouquet|ornament|figurine|wreath|christmas|xmas|advent|gift|gifts|sticker|stickers|"
    r"umbrella|parasol|awning|trolley-cover|dog|cat|pet|glove|gloves|mitt|mitts|thumbstick|lighting|strip|"
    r"light-strip|ledlist)(?:-|$)|"
    r"(?:cab|cabinet|mirror|shelf|wardrobe|drawer)-light(?:-|$)|led-(?:cab|cabinet|mirror|shelf)-|"
    r"(?:^|-)(?:door|doors|drawer|drawers|shelf|shelves|panel|panels|front|fronts|frame|frames|base|top)-(?:for|to|fits)-|"
    r"(?:^|-)(?:door|drawer|panel|front|shelf)-(?:white|black|grey|gray|beige|brown|green|blue|red|oak|glass)-"
)

_IKEA_PATTERNS: list[tuple[str, str]] = [
    ("lighting", r"floor-lamp|table-lamp|pendant-lamp|desk-lamp|wall-lamp|ceiling-lamp|work-lamp|reading-lamp|"
                 r"standing-lamp|lamp|chandelier|uplighter|spotlight"),
    ("appliance", r"refrigerator|fridge|freezer|oven|dishwasher|washing-machine|tumble-dryer|dryer|hob|"
                  r"cooker-hood|extractor-hood|hood|microwave|wine-cooler|wine-fridge|fridge-freezer"),
    ("tv_unit", r"tv-unit|tv-bench|tv-stand|tv-storage-combination|tv-storage|media-storage|tv-cabinet|tv-table"),
    ("coffee_table", r"coffee-table|side-table|nest-of-tables|nesting-tables|end-table|sofa-table"),
    ("desk", r"desk|computer-desk|gaming-desk|desk-combination"),
    ("dining_table", r"dining-table|bar-table|drop-leaf-table|extendable-table|gateleg-table|bistro-table|"
                     r"garden-table|folding-table|table-and-\d-chairs?|table-and-chairs?|bar-table-and"),
    ("sofa", r"sofa-bed|corner-sofa|chaise-longue|modular-sofa|sectional|loveseat|sofa"),
    ("armchair", r"armchair|recliner|rocking-chair|lounge-chair|easy-chair|rocking-armchair"),
    ("bed", r"bed-frame|bunk-bed|loft-bed|day-bed|mattress|cot|cradle|ottoman-bed|bed-with-storage|bed"),
    ("wardrobe", r"wardrobe|cab|chest-of-drawers|chest-of-\d-drawers|cabinet|sideboard|shoe-cabinet|shoe-storage|"
                 r"storage-cabinet|storage-unit|dresser|display-cabinet|storage-combination|drawer-unit|"
                 r"bedside-table|highboy|tallboy|bathroom-vanity|wash-stand"),
    ("chair", r"chair|stool|bench|footstool|bar-stool|pouffe|swivel-chair|office-chair|desk-chair|high-chair"),
    ("other", r"bookcase|shelving-unit|shelf-unit|open-shelving|bookshelf|room-divider|coat-stand|shelving|"
              r"clothes-rack|wall-shelf|storage-system"),
    ("decor", r"rug|mirror|vase|floor-mirror|full-length-mirror|plant-stand"),
]
_IKEA_RULES = [
    (cat, re.compile(r"(?<![a-z])(?:" + pat + r")(?![a-z])")) for cat, pat in _IKEA_PATTERNS
]
_IKEA_TABLE = re.compile(r"(?<![a-z])table(?![a-z])")
_IKEA_CUT = re.compile(r"-(?:with|on|for|and|incl|including|w|f|without|in)-")
_IKEA_ID = re.compile(r"-s?\d{8}$")

_IKEA_COLOR_WORDS = set(
    "white black grey gray dark light beige green brown blue red pink yellow orange turquoise anthracite "
    "multicolour natural oak birch pine ash walnut bamboo stained veneer effect matt gloss clear glass steel "
    "stainless aluminium chrome plated brass colour nickel off mid medium pale deep bright silver gold "
    "bronze copper lilac purple cream golden dyed patterned".split()
)


def classify_ikea_slug(slug: str) -> Optional[str]:
    """Category from an IKEA URL slug like ``vimle-3-seat-sofa-with-headrest-gunnared-grey-s39401327``.

    Accessories (covers, legs, cushions, bulbs, doors/drawer fronts for systems ...) return None. The
    head noun is the right-most rule match before the first ``-with-/-on-/-for-/-and-`` connector, e.g.
    ``office-desk-chair-...`` -> chair. A plain table yields the pseudo-category ``"table"``.
    """
    s = _IKEA_ID.sub("", slug.lower()).replace("mirror-glass", "glass")
    if _IKEA_EXCLUDE.search(s):
        return None
    if re.search(r"table-and-\d-chairs?|table-and-chairs?", s):
        return "dining_table"
    cut = _IKEA_CUT.split(s, maxsplit=1)[0]
    if "sofa-bed" in cut:
        return "sofa"
    best: Optional[tuple[int, int, str]] = None  # (end, -rank) -> maximise end, then lowest rank
    for rank, (cat, rx) in enumerate(_IKEA_RULES):
        for m in rx.finditer(cut):
            key = (m.end(), -rank, cat)
            if best is None or key > best:
                best = key
    if best:
        return best[2]
    if _IKEA_TABLE.search(cut):
        return "table"
    return None


def ikea_family_key(slug: str) -> str:
    """Group colour variants of one design: slug without colour/material words and without the id."""
    s = _IKEA_ID.sub("", slug.lower())
    return "-".join(t for t in s.split("-") if t and t not in _IKEA_COLOR_WORDS)


# --------------------------------------------------------------------------- dimensions

_NUM = r"\d+(?:[.,]\d+)?"
_CMU = r"(?:ס\"מ|ס״מ|סמ|ס'מ|ס”מ|cm)"
_UNIT_ANY = r"(מ\"מ|mm|מטר|מ'|m(?![A-Za-z]))"
_DIAM_RE = re.compile(
    rf"(?:קוטר|diameter|Ø|⌀)(?:\s+(?:אהיל|בסיס|השולחן|הכיסא|פנימי|חיצוני|עליון))*\s*[:\-–]?\s*({_NUM})\s*{_UNIT_ANY}?",
    re.IGNORECASE,
)
_PAIR_RE = re.compile(
    rf"(?<![\d.,/*xX×])({_NUM})\s*[x×*X]\s*({_NUM})(?!\s*[x×*X]\s*\d)\s*(מ\"מ|mm)?"
)
# rugs are often sold as "200/290" (cm); only used when the caller opts in with slash_pair=True
_SLASH_PAIR_RE = re.compile(r"(?<![\d./])(\d{2,3})\s*/\s*(\d{2,3})(?![\d/])()")
_LABEL_RE = {
    key: re.compile(rf"(?:{pat})\s*(?:של)?\s*[:\-–=]?\s*({_NUM})\s*{_UNIT_ANY}?", re.IGNORECASE)
    for key, pat in {
        "width": r"רוחב|width",
        "length": r"אורך|length",
        "depth": r"עומק|depth",
        "height": r"גובה(?:\s+(?:ראש\s+מיטה|המוצר|כללי|הארון|השולחן|המזנון|הספה|הכורסא|המיטה|המנורה|המקרר|התנור|המדיח))?|height",
    }.items()
}
# abbreviations used in some Hebrew spec lines: ר' 123, ע' 50.1, ג'76.5  (width / depth / height)
_ABBR_RE = {
    "width": re.compile(rf"(?<![א-ת])ר['׳’]\s*[:\-]?\s*({_NUM})"),
    "depth": re.compile(rf"(?<![א-ת])ע['׳’]\s*[:\-]?\s*({_NUM})"),
    "height": re.compile(rf"(?<![א-ת])ג['׳’]\s*[:\-]?\s*({_NUM})"),
}


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _to_cm(v: float, unit: Optional[str], mx: float) -> float:
    u = (unit or "").lower()
    if u in ("מ\"מ", "mm"):
        return round(v / 10, 1)
    if u in ("מטר", "מ'", "m"):
        return round(v * 100, 1)
    if mx < 10:  # unit-less and tiny -> meters
        return round(v * 100, 1)
    if mx > 1000:  # unit-less and huge -> millimeters
        return round(v / 10, 1)
    return round(v, 1)


def parse_dims(text: str, *, allow_pair: bool = True, slash_pair: bool = False) -> dict[str, float]:
    """Best-effort width/depth/height (cm) from free text. Keys are present only when found.

    Trust order: explicit labels (רוחב/עומק/גובה/אורך/קוטר) -> NxNxN triple -> a N x N pair (width/depth).
    ``אורך`` (length) is the width unless a separate רוחב exists, in which case it is the depth.
    """
    text = clean_text(text)
    out: dict[str, float] = {}

    raw: dict[str, tuple[float, Optional[str]]] = {}
    for key, rx in _LABEL_RE.items():
        m = rx.search(text)
        if m:
            raw[key] = (_f(m.group(1)), m.group(2))
    dm = _DIAM_RE.search(text)
    if not raw:
        abbr = {k: _ABBR_RE[k].search(text) for k in _ABBR_RE}
        if sum(1 for m in abbr.values() if m) >= 2:
            raw = {("width" if k == "width" else k): (_f(m.group(1)), None) for k, m in abbr.items() if m}
    if raw or dm:
        mx = max([v for v, _ in raw.values()] + ([_f(dm.group(1))] if dm else []))
        cm = {k: _to_cm(v, u, mx) for k, (v, u) in raw.items()}
        if "length" in cm and cm.get("length") == cm.get("width"):
            del cm["length"]  # same number said twice ("ברוחב 180 ... אורך 180")
        if "width" in cm and "length" in cm:
            out["width"], out["depth"] = cm["width"], cm["length"]
        elif "length" in cm:
            out["width"] = cm["length"]
        elif "width" in cm:
            out["width"] = cm["width"]
        if "depth" in cm:
            out["depth"] = cm["depth"]
        if "height" in cm:
            out["height"] = cm["height"]
        if dm:
            d = _to_cm(_f(dm.group(1)), dm.group(2), mx)
            out.setdefault("width", d)
            out.setdefault("depth", d)
    if all(k in out for k in ("width", "depth", "height")):
        return out

    if re.search(rf"{_NUM}\s*[x×*X]\s*{_NUM}\s*[x×*X]\s*{_NUM}", text):
        triple = extract_dimensions(text)
        if all(k in triple for k in ("width", "depth", "height")):
            for k, v in triple.items():
                out.setdefault(k, v)
            return out

    if allow_pair and ("width" not in out or "depth" not in out):
        m = _PAIR_RE.search(text) or (_SLASH_PAIR_RE.search(text) if slash_pair else None)
        if m:
            a, b = _f(m.group(1)), _f(m.group(2))
            mx = max(a, b)
            a, b = _to_cm(a, m.group(3), mx), _to_cm(b, m.group(3), mx)
            out.setdefault("width", a)
            out.setdefault("depth", b)
    return out


def parse_product_dims(title: str, description: str, *, slash_pair: bool = False) -> dict[str, float]:
    """Dimensions of a product from its title and free-text description.

    Labeled values / NxNxN triples in the description win; a bare ``N x N`` pair is only trusted in the
    *title* ("מיטה 160x200"), never in running prose (it is often the sleeping size of a sofa bed, a
    mattress size, a packaging size ...).
    """
    dims = parse_dims(title, slash_pair=slash_pair)
    dims.update(parse_dims(description, allow_pair=False))
    return dims


# --------------------------------------------------------------------------- sanity & normalisation

# category -> ((w_min, w_max), (d_min, d_max), (h_min, h_max)) in cm; anything outside is parse garbage.
SANE: dict[str, tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = {
    "sofa": ((60, 450), (50, 300), (45, 140)),
    "armchair": ((40, 140), (40, 140), (45, 140)),
    "tv_unit": ((30, 400), (15, 90), (10, 260)),
    "coffee_table": ((20, 160), (20, 130), (10, 80)),
    "dining_table": ((40, 400), (40, 140), (35, 120)),
    "chair": ((20, 200), (20, 90), (20, 160)),
    "bed": ((60, 260), (60, 260), (8, 250)),
    "wardrobe": ((15, 450), (12, 100), (15, 300)),
    "storage": ((15, 450), (12, 100), (8, 300)),
    "desk": ((40, 260), (30, 130), (35, 200)),
    "appliance": ((20, 130), (15, 110), (15, 230)),
    "lighting": ((8, 200), (8, 200), (10, 260)),
    "decor": ((10, 450), (1, 450), (0.5, 300)),
    "other": ((10, 450), (10, 130), (10, 300)),
}

RUG_DEFAULT_HEIGHT_CM = 1.5


_WARDROBE_RE = re.compile(
    r"ארון\s+(?:בגדים|הזזה|שינה|פתוח|קיר)|ארונות\s+(?:בגדים|הזזה)|ארון\s+\d+\s*דל|ארון\s+דלתות|"
    r"(?<![A-Za-z])wardrobe(?![A-Za-z])|(?<![A-Za-z])PAX(?![A-Za-z])|(?<![A-Za-z])PLATSA(?![A-Za-z]).*ארון\s+בגדים",
    re.IGNORECASE,
)


def refine_wardrobe(title: str, h: float) -> str:
    """The crawl's 'wardrobe' bucket also holds dressers, shoe/bathroom cabinets and shelving units.

    Only tall clothes wardrobes stay 'wardrobe'; everything else becomes 'storage'.
    """
    return "wardrobe" if (_WARDROBE_RE.search(title) and h >= 150) else "storage"


def is_rug(title: str) -> bool:
    return bool(re.search(r"(?<![א-ת])שטיח|\brug\b|\bcarpet\b", title, re.IGNORECASE))


def normalize_dims(
    category: str, w: float, d: float, h: float, *, round_item: bool = False
) -> tuple[float, float, float]:
    """width >= depth for every category except beds (a bed's footprint orientation is fixed) and round items."""
    if category != "bed" and not round_item and w < d:
        w, d = d, w
    return w, d, h


def validate_product(p: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    """Return (clean product dict, "") or (None, reason). Never raises."""
    title = clean_title(p.get("title"))
    if len(title) < 3:
        return None, "no_title"
    cat = p.get("category")
    if not cat:
        return None, "no_category"
    try:
        price = float(p.get("price_ils") or 0)
        w = float(p.get("width_cm") or 0)
        d = float(p.get("depth_cm") or 0)
        h = float(p.get("height_cm") or 0)
    except (TypeError, ValueError):
        return None, "bad_number"
    if price <= 0:
        return None, "no_price"
    if price > 500_000:
        return None, "price_insane"
    img = str(p.get("image_url") or "").strip()
    if img.startswith("//"):
        img = "https:" + img
    if not img.startswith("https://"):
        return None, "no_image"
    if cat == "decor" and re.search(r"מראה|קנבס|תמונה|מסגרת", title):
        # flat wall items: a "W x H" pair arrives as width/depth, thickness is a few cm
        if h <= 0 and w > 0 and d > 0:
            h, d = d, 3.0
        elif d <= 0 and w > 0 and h > 0:
            d = 3.0
    if not (w > 0 and d > 0):
        return None, "no_dims"
    if h <= 0:
        if cat == "decor" and is_rug(title):
            h = RUG_DEFAULT_HEIGHT_CM
        else:
            return None, "no_dims"
    cat = resolve_table(cat, h)
    if cat == "wardrobe":
        cat = refine_wardrobe(title, h)
    if cat not in CATEGORY_SET:
        return None, "bad_category"
    w, d, h = normalize_dims(cat, w, d, h, round_item=bool(p.get("round")))
    (w0, w1), (d0, d1), (h0, h1) = SANE[cat]
    if not (w0 <= w <= w1 and d0 <= d <= d1 and h0 <= h <= h1):
        return None, f"insane_dims:{cat}"
    if cat == "bed" and h < 15 and not re.search(r"מזרן|מזרון|mattress", title, re.IGNORECASE):
        return None, "insane_dims:bed"  # a bed frame is never this low: the number is a leg height or similar
    return {
        "title": title,
        "category": cat,
        "price_ils": round(price, 2),
        "width_cm": round(w, 1),
        "depth_cm": round(d, 1),
        "height_cm": round(h, 1),
        "image_url": img,
        "store_name": p.get("store_name") or "",
    }, ""
