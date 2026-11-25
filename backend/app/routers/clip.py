"""Endpoint for the RoomCraft Clipper browser extension.

The extension sends the HTML of a product page the user is looking at (so bot protection, logins and
JavaScript-rendered pages are no problem: it is the user's own browser). The server parses it with the
same pipeline as the URL importer, optionally applies the user's manual corrections, and upserts the
product. Nothing is fetched server-side here.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import get_session
from ..models import CATEGORIES
from ..schemas import ProductRead
from ..services import scraper
from ..services.crawler.common import clean_title, normalize_dims, refine_wardrobe

router = APIRouter(prefix="/api/products", tags=["clip"])

OVERRIDABLE = ("title", "store_name", "category", "price_ils", "width_cm", "depth_cm", "height_cm", "image_url")


class ClipRequest(BaseModel):
    url: str
    html: str = Field(max_length=8_000_000)
    dry_run: bool = False
    overrides: dict[str, Any] = Field(default_factory=dict)


class ClipResult(BaseModel):
    status: Literal["preview", "created", "updated", "failed"]
    parsed: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    product: Optional[ProductRead] = None
    error: Optional[str] = None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def clip_page(session: Session, req: ClipRequest) -> ClipResult:
    p = urlparse(req.url.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(422, "url must be http(s)")
    url = req.url.strip().split("#")[0]

    data = scraper.parse_html(req.html, url)
    for key in OVERRIDABLE:
        if key not in req.overrides or req.overrides[key] in (None, ""):
            continue
        val = req.overrides[key]
        if key in ("price_ils", "width_cm", "depth_cm", "height_cm"):
            num = _num(val)
            if num is not None:
                data[key] = num
        elif key == "category":
            data[key] = val if val in CATEGORIES else "other"
        else:
            data[key] = str(val).strip()
    if data.get("title"):
        data["title"] = clean_title(data["title"])
    if data.get("category") == "wardrobe" and "category" not in req.overrides and _num(data.get("height_cm")):
        data["category"] = refine_wardrobe(data.get("title", ""), float(data["height_cm"]))  # dressers/cabinets -> storage
    if all(_num(data.get(k)) for k in ("width_cm", "depth_cm", "height_cm")):
        w, d, h = normalize_dims(
            data.get("category", "other"), float(data["width_cm"]), float(data["depth_cm"]), float(data["height_cm"])
        )
        data["width_cm"], data["depth_cm"], data["height_cm"] = round(w, 1), round(d, 1), round(h, 1)

    missing = [f for f in scraper.REQUIRED_FIELDS if not data.get(f)]
    parsed = {k: v for k, v in data.items() if not k.startswith("_")}
    parsed["sources"] = data.get("_sources", [])

    if req.dry_run:
        return ClipResult(status="preview", parsed=parsed, missing=missing)
    if missing:
        return ClipResult(status="failed", parsed=parsed, missing=missing, error="חסרים נתונים: " + ", ".join(missing))
    if any(not (1 <= float(data[k]) <= 1500) for k in ("width_cm", "depth_cm", "height_cm")):
        return ClipResult(status="failed", parsed=parsed, error="מידות לא הגיוניות (צריך להיות בס\"מ)")
    product, created = scraper.upsert_product(session, url, data)
    return ClipResult(
        status="created" if created else "updated",
        parsed=parsed,
        product=ProductRead.model_validate(product, from_attributes=True),
    )


@router.post("/clip", response_model=ClipResult)
def clip(req: ClipRequest, session: Session = Depends(get_session)):
    return clip_page(session, req)
