"""Smart product ingestion: structured metadata -> Hebrew/English regex -> optional LLM -> upsert.

All parsing functions are pure (HTML/text in, dict out) so they can be tested without network.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from ..config import get_settings
from ..models import CATEGORIES, Product, utcnow
from ..schemas import IngestResult, ProductRead

log = logging.getLogger("roomcraft.scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

# --------------------------------------------------------------------------- numbers / units

_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = (
    r"(?:mm|מ\"מ|מ״מ|"                              # millimeters
    r"ס\"מ|ס״מ|סמ|ס'מ|סנטימטר(?:ים)?|cm|centimet(?:er|re)s?|"  # centimeters
    r"מטר|מ'|מ׳|(?<![A-Za-z])m(?![A-Za-z]))"          # meters
)
_DIM_KEYS = {
    "width": r"(?:רוחב|אורך|width|length|wide)",
    "depth": r"(?:עומק|depth|deep)",
    "height": r"(?:גובה|height|high)",
}


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def _unit_factor(unit: Optional[str]) -> Optional[float]:
    """Return multiplier to centimeters for a unit token, or None if unknown/absent."""
    if not unit:
        return None
    u = unit.lower()
    if u in ("mm", 'מ"מ', "מ״מ"):
        return 0.1
    if u in ("מטר", "מ'", "מ׳", "m"):
        return 100.0
    return 1.0


def _normalize_cm(value: float, unit: Optional[str], *, siblings_max: Optional[float] = None) -> float:
    f = _unit_factor(unit)
    if f is not None:
        return round(value * f, 1)
    ref = siblings_max if siblings_max is not None else value
    if ref < 10:  # unit-less and tiny -> meters
        return round(value * 100, 1)
    if ref > 1000:  # unit-less and huge -> millimeters
        return round(value / 10, 1)
    return round(value, 1)


def _first_label_order(prefix: str) -> Optional[list[str]]:
    """Infer dimension order (e.g. ['height','width','depth']) from labels preceding a NxNxN match."""
    hits: list[tuple[int, str]] = []
    for key, pat in _DIM_KEYS.items():
        m = re.search(pat, prefix, re.IGNORECASE)
        if m:
            hits.append((m.start(), key))
    letters = {"w": "width", "l": "width", "d": "depth", "h": "height"}
    for m in re.finditer(r"(?<![A-Za-z])([WLDH])(?![A-Za-z])", prefix):
        key = letters[m.group(1).lower()]
        if all(k != key for _, k in hits):
            hits.append((m.start(), key))
    hits.sort()
    order: list[str] = []
    for _, k in hits:
        if k not in order:
            order.append(k)
    return order if len(order) == 3 else None


def extract_dimensions(text: str) -> dict[str, float]:
    """Extract width/depth/height (cm) from free text in Hebrew or English."""
    text = text.replace("‏", " ").replace("‎", " ")
    out: dict[str, float] = {}

    # 1) 220x95x85 [unit]
    triple = re.compile(
        rf"({_NUM})\s*(?:{_UNIT})?\s*[x×X*]\s*({_NUM})\s*(?:{_UNIT})?\s*[x×X*]\s*({_NUM})\s*({_UNIT})?",
        re.IGNORECASE,
    )
    m = triple.search(text)
    if m:
        vals = [_to_float(m.group(i)) for i in (1, 2, 3)]
        unit = m.group(4)
        mx = max(vals)
        cms = [_normalize_cm(v, unit, siblings_max=mx) for v in vals]
        prefix = text[max(0, m.start() - 45): m.start()]
        order = _first_label_order(prefix) or ["width", "depth", "height"]
        out = dict(zip(order, cms))
        if all(k in out for k in ("width", "depth", "height")):
            return out

    # 2) labeled values: "רוחב 240", "depth: 90 cm", "גובה 80 ס"מ"
    found: dict[str, tuple[float, Optional[str]]] = {}
    for key, pat in _DIM_KEYS.items():
        lm = re.search(rf"{pat}\s*(?:[:\-–]|של)?\s*({_NUM})\s*({_UNIT})?", text, re.IGNORECASE)
        if lm:
            found[key] = (_to_float(lm.group(1)), lm.group(2))
    # trailing form: "240 ס"מ רוחב"
    for key, pat in _DIM_KEYS.items():
        if key in found:
            continue
        lm = re.search(rf"({_NUM})\s*({_UNIT})?\s*{pat}", text, re.IGNORECASE)
        if lm:
            found[key] = (_to_float(lm.group(1)), lm.group(2))
    if found:
        mx = max(v for v, _ in found.values())
        for key, (v, unit) in found.items():
            out.setdefault(key, _normalize_cm(v, unit, siblings_max=mx))
    return out


_PRICE_RE = [
    re.compile(r"(?:₪|ש\"ח|ש״ח|שח|NIS|ILS)\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:₪|ש\"ח|ש״ח|שח|NIS|ILS)", re.IGNORECASE),
]


def extract_price(text: str) -> Optional[float]:
    for rx in _PRICE_RE:
        m = rx.search(text)
        if m:
            try:
                v = float(re.sub(r"[,\s]", "", m.group(1)))
                if v > 0:
                    return v
            except ValueError:
                continue
    return None


_CATEGORY_RULES: list[tuple[str, str]] = [
    ("tv_unit", r"מזנון|tv\s*(?:unit|stand|cabinet|console)|ארון\s*טלוויזיה|טלוויזיה\s*מזנון|media\s*console"),
    ("coffee_table", r"שולחן\s*(?:סלון|קפה)|coffee\s*table|side\s*table|שולחן\s*צד"),
    ("dining_table", r"שולחן\s*(?:אוכל|פינת\s*אוכל|נפתח)|dining\s*table"),
    ("desk", r"שולחן\s*(?:עבודה|כתיבה|מחשב)|\bdesk\b|שולחן\s*מחשב"),
    ("armchair", r"כורסא|כורסה|armchair|recliner|lounge\s*chair"),
    ("sofa", r"ספה|ספת|sofa|couch|sectional|loveseat"),
    ("bed", r"מיטה|מיטת|bed\b|מזרן|mattress"),
    ("wardrobe", r"ארון|wardrobe|closet|armoire|cabinet"),
    (
        "appliance",
        r"מקרר|מקפיא|מכונת|תנור|מדיח|מיקרוגל|כיריים|מייבש|מזגן|fridge|refrigerator|freezer|washing|washer|dryer|oven|dishwasher|microwave|cooker|\bhob\b",
    ),
    ("lighting", r"מנורה|תאורה|נברשת|lamp|lighting|chandelier|\blight\b"),
    ("decor", r"שטיח|מראה|תמונה|אגרטל|כרית|rug|carpet|mirror|vase|decor|cushion|plant|עציץ"),
    ("chair", r"כיסא|כסא|שרפרף|כיסאות|chair|stool|bench|ספסל"),
]


def infer_category(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        for cat, pat in _CATEGORY_RULES:
            if re.search(pat, text, re.IGNORECASE):
                return cat
    return "other"


# --------------------------------------------------------------------------- structured metadata

def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(re.sub(r"[\x00-\x1f]+", " ", raw))
            except json.JSONDecodeError:
                continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                if "@graph" in node:
                    stack.append(node["@graph"])


def _is_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == name.lower() for x in t)
    return isinstance(t, str) and t.lower() == name.lower()


_UNIT_CODES = {"CMT": "cm", "MTR": "m", "MMT": "mm", "INH": "in"}


def _qv_to_cm(val: Any) -> Optional[float]:
    """Convert a schema.org QuantitativeValue / string / number into cm."""
    if val is None:
        return None
    unit = None
    if isinstance(val, dict):
        unit = val.get("unitCode") or val.get("unitText")
        val = val.get("value", val.get("name"))
        if val is None:
            return None
    if isinstance(val, (int, float)):
        num, unit_s = float(val), None
    else:
        m = re.search(rf"({_NUM})\s*({_UNIT}|in(?:ch(?:es)?)?)?", str(val), re.IGNORECASE)
        if not m:
            return None
        num, unit_s = _to_float(m.group(1)), m.group(2)
    u = unit_s or (_UNIT_CODES.get(str(unit).upper(), str(unit)) if unit else None)
    if u and str(u).lower().startswith("in"):
        return round(num * 2.54, 1)
    return _normalize_cm(num, u)


def _first_str(v: Any) -> Optional[str]:
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return _first_str(v[0])
    if isinstance(v, dict):
        return _first_str(v.get("url") or v.get("contentUrl") or v.get("@id"))
    return None


def _parse_jsonld_product(node: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if node.get("name"):
        out["title"] = str(node["name"]).strip()
    img = _first_str(node.get("image"))
    if img:
        out["image_url"] = img
    brand = node.get("brand")
    if isinstance(brand, dict) and brand.get("name"):
        out["brand"] = str(brand["name"])
    elif isinstance(brand, str):
        out["brand"] = brand
    if node.get("category"):
        out["category_hint"] = str(_first_str(node["category"]) or "")

    offers = node.get("offers")
    offer_list = offers if isinstance(offers, list) else [offers] if offers else []
    for off in offer_list:
        if not isinstance(off, dict):
            continue
        price = off.get("price")
        if price is None and isinstance(off.get("priceSpecification"), dict):
            price = off["priceSpecification"].get("price")
        if price is None:
            price = off.get("lowPrice")
        if price is not None:
            try:
                out["price_ils"] = float(str(price).replace(",", ""))
                break
            except ValueError:
                pass

    for key in ("width", "depth", "height"):
        cm = _qv_to_cm(node.get(key))
        if cm:
            out[key + "_cm"] = cm
    # additionalProperty: [{name: 'רוחב', value: '240 ס"מ'}]
    props = node.get("additionalProperty")
    if isinstance(props, dict):
        props = [props]
    if isinstance(props, list):
        text = " ; ".join(
            f"{p.get('name', '')}: {p.get('value', '')}" for p in props if isinstance(p, dict)
        )
        for k, v in extract_dimensions(text).items():
            out.setdefault(k + "_cm", v)
    return out


def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def _microdata(soup: BeautifulSoup) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def prop(name: str) -> Optional[str]:
        el = soup.find(attrs={"itemprop": name})
        if not el:
            return None
        if el.get("content"):
            return str(el["content"])
        if el.name == "img" and el.get("src"):
            return str(el["src"])
        if el.name == "link" and el.get("href"):
            return str(el["href"])
        return el.get_text(" ", strip=True) or None

    if (v := prop("name")):
        out["title"] = v
    if (v := prop("image")):
        out["image_url"] = v
    if (v := prop("price")):
        try:
            out["price_ils"] = float(re.sub(r"[^\d.]", "", v.replace(",", "")))
        except ValueError:
            pass
    for key in ("width", "depth", "height"):
        if (v := prop(key)):
            cm = _qv_to_cm(v)
            if cm:
                out[key + "_cm"] = cm
    return out


def _store_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return re.sub(r"^www\.", "", host)


REQUIRED_FIELDS = ("title", "width_cm", "depth_cm", "height_cm")


def parse_html(html: str, url: str) -> dict[str, Any]:
    """Parse a product page into a dict. Missing fields are simply absent (or category 'other')."""
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, Any] = {}
    sources: list[str] = []

    # 1. JSON-LD Product
    for node in _iter_jsonld(soup):
        if _is_type(node, "Product"):
            parsed = _parse_jsonld_product(node)
            if parsed:
                for k, v in parsed.items():
                    data.setdefault(k, v)
                sources.append("jsonld")
            break

    # 2. microdata
    micro = _microdata(soup)
    if micro:
        before = dict(data)
        for k, v in micro.items():
            data.setdefault(k, v)
        if data != before:
            sources.append("microdata")

    # 3. OpenGraph / meta
    og_title = _meta(soup, "og:title", "twitter:title")
    og_image = _meta(soup, "og:image", "twitter:image")
    og_site = _meta(soup, "og:site_name")
    og_price = _meta(soup, "product:price:amount", "og:price:amount")
    og_desc = _meta(soup, "og:description", "description")
    if og_title:
        data.setdefault("title", og_title)
    if og_image:
        data.setdefault("image_url", og_image)
    if og_price:
        try:
            data.setdefault("price_ils", float(og_price.replace(",", "")))
        except ValueError:
            pass
    if og_title or og_image or og_price:
        sources.append("opengraph")
    if "title" not in data:
        if soup.title and soup.title.string:
            data["title"] = soup.title.string.strip()
        elif (h1 := soup.find("h1")):
            data["title"] = h1.get_text(" ", strip=True)

    # 4. regex over visible text (dimensions / price)
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    scan_text = " ".join(filter(None, [data.get("title"), og_desc, text]))
    need_dims = any(k not in data for k in ("width_cm", "depth_cm", "height_cm"))
    if need_dims:
        dims = extract_dimensions(scan_text)
        added = False
        for k, v in dims.items():
            if (k + "_cm") not in data:
                data[k + "_cm"] = v
                added = True
        if added:
            sources.append("html")
    if "price_ils" not in data:
        p = extract_price(scan_text)
        if p:
            data["price_ils"] = p
            if "html" not in sources:
                sources.append("html")

    # 5. category / store / image
    data["category"] = infer_category(data.get("title", ""), data.get("category_hint", ""), og_desc or "")
    if data["category"] == "other":
        data["category"] = infer_category(text[:1500])
    data["store_name"] = og_site or data.get("brand") or _store_from_url(url)
    if data.get("image_url"):
        data["image_url"] = urljoin(url, data["image_url"])
    data.pop("brand", None)
    data.pop("category_hint", None)
    data["_sources"] = sources
    data["_text"] = text[:6000]
    return data


def missing_fields(data: dict[str, Any]) -> list[str]:
    miss = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if not data.get("price_ils"):
        miss.append("price_ils")
    if data.get("category", "other") == "other":
        miss.append("category")
    if not data.get("image_url"):
        miss.append("image_url")
    return miss


# --------------------------------------------------------------------------- LLM fallback

LLM_SYSTEM = (
    "You extract structured product data from furniture/appliance store pages (Hebrew or English). "
    "Respond with ONLY a JSON object, no prose, with exactly these keys: "
    '{"title": string, "store_name": string, "category": one of '
    + json.dumps(CATEGORIES)
    + ', "price_ils": number|null, "width_cm": number|null, "depth_cm": number|null, '
    '"height_cm": number|null, "image_url": string|null}. '
    "All dimensions MUST be in centimeters (convert meters/mm). width is the longest horizontal side "
    "as seen from the front, depth is front-to-back. Use null when a value is not on the page; never guess."
)


def _extract_json_obj(s: str) -> dict[str, Any]:
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in LLM response")
    return json.loads(s[a: b + 1])


def clean_llm_result(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(raw.get("title"), str) and raw["title"].strip():
        out["title"] = raw["title"].strip()
    if isinstance(raw.get("store_name"), str) and raw["store_name"].strip():
        out["store_name"] = raw["store_name"].strip()
    if raw.get("category") in CATEGORIES:
        out["category"] = raw["category"]
    if isinstance(raw.get("image_url"), str) and raw["image_url"].startswith(("http://", "https://")):
        out["image_url"] = raw["image_url"]
    for k in ("price_ils", "width_cm", "depth_cm", "height_cm"):
        v = raw.get(k)
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            f = None
        if f is not None and f > 0:
            out[k] = round(f, 1)
    return out


async def llm_extract(
    text: str, url: str, client: httpx.AsyncClient, hint_title: str = ""
) -> Optional[dict[str, Any]]:
    s = get_settings()
    user = f"URL: {url}\nTitle: {hint_title}\n\nPage text:\n{text[:6000]}"
    try:
        if s.anthropic_api_key:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": s.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": s.anthropic_model,
                    "max_tokens": 500,
                    "system": LLM_SYSTEM,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=60,
            )
            r.raise_for_status()
            content = "".join(b.get("text", "") for b in r.json().get("content", []))
            return clean_llm_result(_extract_json_obj(content))
        if s.openai_api_key:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={
                    "model": s.openai_model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": LLM_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=60,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return clean_llm_result(_extract_json_obj(content))
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM extraction failed for %s: %s", url, exc)
    return None


def llm_available() -> bool:
    s = get_settings()
    return bool(s.anthropic_api_key or s.openai_api_key)


# --------------------------------------------------------------------------- fetch + pipeline

def validate_url(url: str) -> str:
    url = url.strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("כתובת לא תקינה (נדרש http/https)")
    host = p.hostname or ""
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("כתובות מקומיות אינן נתמכות")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("כתובות פרטיות אינן נתמכות")
    except ValueError as exc:
        if "אינן נתמכות" in str(exc):
            raise
    return url.split("#")[0]


async def fetch_html(url: str, client: httpx.AsyncClient) -> str:
    r = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.text


async def fetch_and_parse(url: str, client: httpx.AsyncClient) -> tuple[dict[str, Any], str]:
    """Fetch URL and run the full extraction pipeline. Returns (data, source)."""
    html = await fetch_html(url, client)
    data = parse_html(html, url)
    source = (data.get("_sources") or ["html"])[0]
    miss = missing_fields(data)
    # LLM only when there is something to fix that matters (dims / price / category).
    needs_llm = any(m in miss for m in ("width_cm", "depth_cm", "height_cm", "price_ils", "category"))
    if needs_llm and llm_available():
        llm = await llm_extract(data.get("_text", ""), url, client, data.get("title", ""))
        if llm:
            for k, v in llm.items():
                if k == "category":
                    if data.get("category", "other") == "other":
                        data["category"] = v
                elif not data.get(k):
                    data[k] = v
            source = "llm" if len(miss) > 0 else source
    return data, source


def upsert_product(
    session: Session, url: str, data: dict[str, Any], *, commit: bool = True
) -> tuple[Product, bool]:
    """Insert or update by product_url. Never wipes cached 3D model fields.

    ``commit=False`` only flushes (bulk crawlers commit in batches).
    """
    existing = session.exec(select(Product).where(Product.product_url == url)).first()
    fields = {
        "store_name": data.get("store_name") or _store_from_url(url),
        "title": data["title"],
        "category": data.get("category") if data.get("category") in CATEGORIES else "other",
        "price_ils": float(data.get("price_ils") or 0),
        "width_cm": float(data["width_cm"]),
        "depth_cm": float(data["depth_cm"]),
        "height_cm": float(data["height_cm"]),
        "image_url": data.get("image_url") or "",
    }
    if existing:
        for k, v in fields.items():
            if k == "image_url" and not v:
                continue
            setattr(existing, k, v)
        existing.updated_at = utcnow()
        session.add(existing)
        _persist(session, existing, commit)
        return existing, False
    product = Product(product_url=url, **fields)
    session.add(product)
    _persist(session, product, commit)
    return product, True


def _persist(session: Session, obj: Product, commit: bool) -> None:
    if commit:
        session.commit()
        session.refresh(obj)
    else:
        session.flush()


def _failed(url: str, msg: str) -> IngestResult:
    return IngestResult(url=url, status="failed", error=msg)


async def ingest_urls(
    session: Session,
    urls: list[str],
    client: Optional[httpx.AsyncClient] = None,
    concurrency: int = 4,
) -> list[IngestResult]:
    """Fetch/parse concurrently, upsert sequentially. Never raises for per-URL problems."""
    own = client is None
    client = client or httpx.AsyncClient()
    sem = asyncio.Semaphore(concurrency)
    clean: list[str] = []
    seen: set[str] = set()
    results: dict[str, IngestResult] = {}

    for raw in urls:
        raw = raw.strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        try:
            clean.append(validate_url(raw))
        except ValueError as exc:
            results[raw] = _failed(raw, str(exc))

    async def work(u: str):
        async with sem:
            try:
                return u, await fetch_and_parse(u, client), None
            except httpx.HTTPStatusError as exc:
                return u, None, f"HTTP {exc.response.status_code}"
            except httpx.HTTPError as exc:
                return u, None, f"שגיאת רשת: {exc.__class__.__name__}"
            except Exception as exc:  # noqa: BLE001
                log.exception("ingest failed for %s", u)
                return u, None, f"שגיאה בעיבוד הדף: {exc}"

    try:
        fetched = await asyncio.gather(*(work(u) for u in clean))
    finally:
        if own:
            await client.aclose()

    for u, res, err in fetched:
        if err or res is None:
            results[u] = _failed(u, err or "unknown error")
            continue
        data, source = res
        missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
        if missing:
            results[u] = _failed(u, "חסרים נתונים: " + ", ".join(missing) + " — ניתן להוסיף ידנית")
            continue
        product, created = upsert_product(session, u, data)
        results[u] = IngestResult(
            url=u,
            status="created" if created else "updated",
            source=source,
            product=ProductRead.model_validate(product, from_attributes=True),
        )

    ordered = [results[k] for k in results]
    return ordered
