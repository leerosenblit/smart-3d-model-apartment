"""Per-store adapters: URL discovery + product extraction.

Each adapter has:
  * ``discover(http)``      -> list of candidate dicts ``{"url", "category", "title", ["data"]}``
  * ``fetch(http, cand)``   -> raw product dict (title, price_ils, width_cm, depth_cm, height_cm,
                                image_url, category, store_name) or None when the page has no usable data.
Raw dicts are validated/normalised by :func:`common.validate_product` afterwards.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Optional
from urllib.parse import quote

from .common import (
    classify_he,
    classify_ikea_slug,
    clean_text,
    ikea_family_key,
    parse_dims,
    parse_product_dims,
    strip_html,
)
from .http import PoliteClient

log = logging.getLogger("roomcraft.crawler")


# --------------------------------------------------------------------------- generic helpers

_LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def jsonld_product(html: str) -> Optional[dict]:
    """First schema.org Product node in the page's JSON-LD blocks (tolerates raw newlines in strings)."""
    for m in _LD_RE.finditer(html):
        raw = m.group(1).strip()
        if '"Product"' not in raw:
            continue
        try:
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    return node
                if "@graph" in node:
                    stack.append(node["@graph"])
    return None


def ld_price(node: dict) -> Optional[float]:
    offers = node.get("offers")
    offers = offers if isinstance(offers, list) else [offers] if offers else []
    best: Optional[float] = None
    for off in offers:
        if not isinstance(off, dict):
            continue
        for key in ("price", "lowPrice"):
            v = off.get(key)
            if v is None and isinstance(off.get("priceSpecification"), dict):
                v = off["priceSpecification"].get(key)
            if v is not None:
                try:
                    f = float(str(v).replace(",", ""))
                except ValueError:
                    continue
                if f > 0 and (best is None or f < best):
                    best = f
    return best


def ld_image(node: dict) -> Optional[str]:
    img = node.get("image")
    while isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, dict):
        img = img.get("contentUrl") or img.get("url")
    return img if isinstance(img, str) and img else None


def _cm_value(v: Any) -> Optional[float]:
    """'51 ס"מ' / 51 / {'value': 51, 'unitText': 'cm'} -> cm."""
    if isinstance(v, dict):
        v = v.get("value")
    if v is None:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(מ\"מ|mm|מ'|מטר|m\b)?", str(v))
    if not m:
        return None
    x = float(m.group(1).replace(",", "."))
    u = m.group(2) or ""
    if u in ("מ\"מ", "mm"):
        return round(x / 10, 1)
    if u in ("מ'", "מטר", "m"):
        return round(x * 100, 1)
    return round(x, 1)


_IKEA_MEASURE_NAMES = {"גובה", "רוחב", "אורך", "עומק", "קוטר"}


def ikea_dimension_block(html: str) -> str:
    """Product dimensions from the page's embedded ``measurementsProps.measurements`` list, as label text
    ("גובה: 45 ס"מ. קוטר: 75 ס"מ"). Package sizes and loose qualifiers (cable length, max/min) are ignored."""
    i = html.find('"measurementsProps"')
    if i < 0:
        return ""
    j = html.find('"measurements":[', i)
    if j < 0 or j - i > 6000:
        return ""
    k = j + len('"measurements":')
    depth = 0
    for e in range(k, min(len(html), k + 4000)):
        ch = html[e]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
    else:
        return ""
    try:
        items = json.loads(html[k : e + 1])
    except ValueError:
        return ""
    parts = []
    for it in items:
        if isinstance(it, dict) and clean_text(it.get("name")) in _IKEA_MEASURE_NAMES and it.get("measure"):
            parts.append(f"{clean_text(it['name'])}: {clean_text(it['measure'])}")
    return ". ".join(parts)


def interleave_by_category(cands: list[dict]) -> list[dict]:
    """Round-robin over categories so an early stop (--limit / Ctrl-C) still yields a varied catalog."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in cands:
        buckets[c.get("category") or "other"].append(c)
    out: list[dict] = []
    queues = [list(reversed(v)) for _, v in sorted(buckets.items())]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop())
    return out


async def _get_text(http: PoliteClient, url: str) -> Optional[str]:
    r = await http.get(url)
    return r.text if r is not None else None


# --------------------------------------------------------------------------- base class

class Store:
    key = ""
    store_name = ""
    host = ""
    #: False when the last discovery was cut short (rate limiting, network): the runner then won't cache it
    discovery_complete = True

    async def discover(self, http: PoliteClient) -> list[dict]:  # pragma: no cover - network
        raise NotImplementedError

    async def fetch(self, http: PoliteClient, cand: dict) -> Optional[dict]:  # pragma: no cover - network
        raise NotImplementedError


# --------------------------------------------------------------------------- IKEA Israel

IKEA_SITEMAP_INDEX = "https://www.ikea.com/sitemaps/sitemap.xml"
IKEA_MAX_PER_FAMILY = 8   # colour variants of one design
IKEA_MAX_PER_LINE = 60    # per (product line name, category), e.g. METOD kitchen cabinets


class IkeaStore(Store):
    key = "ikea"
    store_name = "IKEA"
    host = "www.ikea.com"
    max_per_family = IKEA_MAX_PER_FAMILY
    max_per_line = IKEA_MAX_PER_LINE

    async def discover(self, http: PoliteClient) -> list[dict]:
        idx = await _get_text(http, IKEA_SITEMAP_INDEX)
        if not idx:
            return []
        sitemaps = [u for u in re.findall(r"<loc>([^<]+)</loc>", idx) if re.search(r"prod-he-IL_\d+\.xml", u)]
        log.info("ikea: %d product sitemaps", len(sitemaps))
        fam: Counter = Counter()
        line: Counter = Counter()
        cands: list[dict] = []
        self.discovery_complete = True
        for sm in sorted(sitemaps):
            xml = await _get_text(http, sm)
            if not xml:
                self.discovery_complete = False
                continue
            for url in re.findall(r"<loc>([^<]+)</loc>", xml):
                m = re.search(r"/il/he/p/(.+?)/?$", url)
                if not m:
                    continue
                slug = m.group(1)
                cat = classify_ikea_slug(slug)
                if not cat:
                    continue
                toks = slug.split("-")
                name = "-".join(toks[:3]) if toks[0] == "ikea" else toks[0]
                fk = ikea_family_key(slug)
                if fam[fk] >= self.max_per_family or line[(name, cat)] >= self.max_per_line:
                    continue
                fam[fk] += 1
                line[(name, cat)] += 1
                cands.append({"url": url, "category": cat, "title": slug})
        log.info("ikea: %d candidate product pages after filters/caps", len(cands))
        return interleave_by_category(cands)

    async def fetch(self, http: PoliteClient, cand: dict) -> Optional[dict]:
        r = await http.get(cand["url"])
        if r is None:
            return None
        node = jsonld_product(r.text)
        if not node:
            return None
        raw_name = clean_text(node.get("name"))
        dims: dict[str, float] = {}
        for k in ("width", "depth", "height"):
            v = _cm_value(node.get(k))
            if v:
                dims[k] = v
        if len(dims) < 3:  # the on-page "מידות" block (product dimensions, not the package)
            for k, v in parse_dims(ikea_dimension_block(r.text), allow_pair=False).items():
                dims.setdefault(k, v)
        if len(dims) < 3:
            # title suffix "74x51x149 ס"מ" (W x D x H); description repeats it
            td = parse_dims(raw_name, slash_pair=False)
            if len(dims) == 0 and len(td) == 3:
                dims = td
            else:
                for k, v in td.items():
                    dims.setdefault(k, v)
        return {
            "title": raw_name,
            "category": cand["category"],
            "price_ils": ld_price(node),
            "width_cm": dims.get("width"),
            "depth_cm": dims.get("depth"),
            "height_cm": dims.get("height"),
            "image_url": ld_image(node),
            "store_name": self.store_name,
        }


# --------------------------------------------------------------------------- ACE (Magento)

ACE_SITEMAP_INDEX = "https://www.ace.co.il/sitemap.xml"


def ace_page_description(html: str) -> str:
    """Visible product description text. JSON-LD ``description`` is cut after ~300 chars, but the page shows
    the full text (incl. "מידות: אורך ... עומק ... גובה ...") right before the "מפרט טכני" heading."""
    chunks: list[str] = []
    pos = 0
    while len(chunks) < 3:
        i = html.find("מפרט טכני", pos)
        if i < 0:
            break
        pos = i + 1
        seg = re.sub(r"(?is)<(script|style).*?</>", " ", html[max(0, i - 9000) : i])
        chunks.append(clean_text(re.sub(r"<[^>]+>", " ", seg))[-3500:])
    return " ".join(chunks)


class AceStore(Store):
    key = "ace"
    store_name = "ACE"
    host = "www.ace.co.il"

    async def discover(self, http: PoliteClient) -> list[dict]:
        idx = await _get_text(http, ACE_SITEMAP_INDEX)
        if not idx:
            return []
        sitemaps = [u for u in re.findall(r"<loc>([^<]+)</loc>", idx) if "sitemap-" in u]
        log.info("ace: %d sitemaps", len(sitemaps))
        cands: list[dict] = []
        seen: set[str] = set()
        self.discovery_complete = True
        for sm in sitemaps:
            xml = await _get_text(http, _html.unescape(sm))
            if not xml:
                self.discovery_complete = False
                continue
            for block in xml.split("<url>")[1:]:
                m = re.match(r"<loc>(https://www\.ace\.co\.il/\d+)</loc>", block)
                if not m:
                    continue
                url = m.group(1)
                t = re.search(r"<image:title>([^<]*)</image:title>", block)
                title = _html.unescape(t.group(1)) if t else ""
                cat = classify_he(title)
                if not cat or url in seen:
                    continue
                seen.add(url)
                cands.append({"url": url, "category": cat, "title": title})
        log.info("ace: %d candidate product pages", len(cands))
        return interleave_by_category(cands)

    async def fetch(self, http: PoliteClient, cand: dict) -> Optional[dict]:
        r = await http.get(cand["url"])
        if r is None:
            return None
        node = jsonld_product(r.text)
        if not node:
            return None
        title = clean_text(node.get("name")) or cand["title"]
        desc = clean_text(node.get("description"))
        cat = cand["category"]
        dims = parse_product_dims(title, desc, slash_pair=(cat == "decor"))
        if not all(k in dims for k in ("width", "depth", "height")):
            full = ace_page_description(r.text)
            if full:
                dims = parse_product_dims(title, f"{desc}. {full}", slash_pair=(cat == "decor"))
        return {
            "title": title,
            "category": cat,
            "price_ils": ld_price(node),
            "width_cm": dims.get("width"),
            "depth_cm": dims.get("depth"),
            "height_cm": dims.get("height"),
            "image_url": ld_image(node),
            "store_name": self.store_name,
        }


# --------------------------------------------------------------------------- Shopify stores (products.json)

class ShopifyStore(Store):
    """Bulk ``/products.json?limit=250&page=N`` (public Shopify storefront feed, not disallowed by robots).

    Everything needed is in the feed (title, body_html with dimensions, price, images, product_type), so
    discovery already yields complete product data and no per-product page is fetched.
    """

    PAGE_LIMIT = 250
    PAGE_DELAY = 2.0
    MAX_PAGES = 120

    def __init__(self, key: str, store_name: str, host: str, *, type_denylist: Optional[re.Pattern] = None):
        self.key, self.store_name, self.host = key, store_name, host
        self.type_denylist = type_denylist

    def product_from_json(self, p: dict) -> Optional[dict]:
        """Pure: one products.json entry -> candidate dict with ``data`` (or None if irrelevant)."""
        title = clean_text(p.get("title"))
        ptype = clean_text(p.get("product_type"))
        if self.type_denylist and self.type_denylist.search(ptype):
            return None
        cat = classify_he(title, hint=ptype)
        if not cat:
            return None
        variants = [v for v in (p.get("variants") or []) if isinstance(v, dict)]
        if not variants:
            return None
        avail = [v for v in variants if v.get("available", True)] or variants
        prices = []
        for v in avail:
            try:
                f = float(str(v.get("price")).replace(",", ""))
            except ValueError:
                continue
            if f > 0:
                prices.append((f, v))
        if not prices:
            return None
        price, variant = min(prices, key=lambda x: x[0])
        vtitle = clean_text(variant.get("title"))
        vtitle = "" if vtitle.lower().startswith("default") else vtitle
        dims = parse_product_dims(
            " ".join(x for x in (title, vtitle) if x), strip_html(p.get("body_html")), slash_pair=(cat == "decor")
        )
        images = p.get("images") or []
        image = ""
        if images and isinstance(images[0], dict):
            image = images[0].get("src") or ""
        elif isinstance(p.get("image"), dict):
            image = p["image"].get("src") or ""
        if "cdn.shopify.com" in image and "width=" not in image:
            image += ("&" if "?" in image else "?") + "width=800"  # originals are up to 4000px
        handle = p.get("handle") or ""
        if not handle:
            return None
        url = f"https://{self.host}/products/{quote(handle, safe='-_.~')}"
        return {
            "url": url,
            "category": cat,
            "title": title,
            "data": {
                "title": title,
                "category": cat,
                "price_ils": price,
                "width_cm": dims.get("width"),
                "depth_cm": dims.get("depth"),
                "height_cm": dims.get("height"),
                "image_url": image,
                "store_name": self.store_name,
            },
        }

    async def discover(self, http: PoliteClient) -> list[dict]:
        cands: list[dict] = []
        total = 0
        self.discovery_complete = False
        # big JSON pages: be extra gentle (Shopify answers 429 quickly otherwise)
        http.host_delay[self.host] = max(self.PAGE_DELAY, http.host_delay.get(self.host, 0.0))
        for page in range(1, self.MAX_PAGES + 1):
            r = await http.get(f"https://{self.host}/products.json?limit={self.PAGE_LIMIT}&page={page}")
            if r is None:
                log.warning("%s: page %d unavailable - discovery is partial", self.key, page)
                break
            try:
                products = r.json().get("products", [])
            except ValueError:
                break
            if not products:
                self.discovery_complete = True
                break
            total += len(products)
            for p in products:
                c = self.product_from_json(p)
                if c:
                    cands.append(c)
            log.info("%s: page %d -> %d products (%d relevant so far)", self.key, page, len(products), len(cands))
        http.host_delay.pop(self.host, None)
        log.info("%s: %d products scanned, %d relevant", self.key, total, len(cands))
        return interleave_by_category(cands)

    async def fetch(self, http: PoliteClient, cand: dict) -> Optional[dict]:
        return cand.get("data")


_BABY_ONLY_DENY = re.compile(r"בגדי|הנקה|צעצוע|משחק|טיולון|עגלות|מושבי בטיחות|הנקה|האכלה|חיתול|רחצה")

STORES: dict[str, Store] = {
    s.key: s
    for s in [
        IkeaStore(),
        AceStore(),
        ShopifyStore("homecenter", "הום סנטר", "www.homecenter.co.il"),
        ShopifyStore("shilav", "שילב", "www.shilav.co.il", type_denylist=_BABY_ONLY_DENY),
        ShopifyStore("aminach", "אמינח", "www.aminach.co.il"),
        ShopifyStore("homestyle", "הום סטייל", "www.homestyle.co.il"),
        ShopifyStore("foxhome", "פוקס הום", "www.foxhome.co.il"),
    ]
}
