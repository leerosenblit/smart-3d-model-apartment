"""Product catalog CRUD, filtering and ingestion endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlmodel import Session, select

from ..db import get_session
from ..models import CATEGORIES, Product, utcnow
from ..schemas import (
    IngestBatchRequest,
    IngestResult,
    IngestUrlRequest,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from ..services import scraper, thumbs

router = APIRouter(prefix="/api/products", tags=["products"])

SORTS = {
    # stable pseudo-random mix: page one shows several stores and styles instead of the last crawled batch
    "featured": lambda: (Product.id * 7919) % 1009,
    "price_asc": lambda: Product.price_ils.asc(),
    "price_desc": lambda: Product.price_ils.desc(),
    "width": lambda: Product.width_cm.asc(),
    "title": lambda: Product.title.asc(),
    "updated": lambda: Product.updated_at.desc(),
}


@router.get("", response_model=list[ProductRead])
def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    store_name: Optional[str] = None,
    max_width_cm: Optional[float] = Query(None, gt=0),
    max_depth_cm: Optional[float] = Query(None, gt=0),
    max_price_ils: Optional[float] = Query(None, ge=0),
    sort_by: str = "updated",
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Product)
    if search and search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Product.title.ilike(like), Product.store_name.ilike(like)))
    if category:
        stmt = stmt.where(Product.category == category)
    if store_name:
        stmt = stmt.where(Product.store_name == store_name)
    if max_width_cm is not None:
        stmt = stmt.where(Product.width_cm <= max_width_cm)
    if max_depth_cm is not None:
        stmt = stmt.where(Product.depth_cm <= max_depth_cm)
    if max_price_ils is not None:
        stmt = stmt.where(Product.price_ils <= max_price_ils)
    if sort_by not in SORTS:
        raise HTTPException(422, f"sort_by must be one of {sorted(SORTS)}")
    stmt = stmt.order_by(SORTS[sort_by](), Product.id).offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/categories", response_model=list[str])
def list_categories():
    return CATEGORIES


@router.get("/stores", response_model=list[str])
def list_stores(session: Session = Depends(get_session)):
    rows = session.exec(select(Product.store_name).distinct().order_by(Product.store_name)).all()
    return [r for r in rows if r]


@router.post("/ingest-url", response_model=IngestResult)
async def ingest_url(body: IngestUrlRequest, session: Session = Depends(get_session)):
    results = await scraper.ingest_urls(session, [body.url])
    if not results:
        raise HTTPException(422, "empty url")
    return results[0]


@router.post("/ingest-batch", response_model=list[IngestResult])
async def ingest_batch(body: IngestBatchRequest, session: Session = Depends(get_session)):
    return await scraper.ingest_urls(session, body.urls)


@router.post("", response_model=ProductRead, status_code=201)
def create_product(body: ProductCreate, session: Session = Depends(get_session)):
    exists = session.exec(select(Product).where(Product.product_url == body.product_url)).first()
    if exists:
        raise HTTPException(409, "Product with this URL already exists")
    product = Product(**body.model_dump())
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.get("/{product_id}/image")
async def get_product_image(product_id: int, session: Session = Depends(get_session)):
    """Small cached JPEG thumbnail of the product photo (lazily downloaded + resized).

    404 when the product has no remote photo (e.g. ``data:`` placeholder) or the download failed -
    the UI then falls back to ``image_url`` / a neutral placeholder.
    """
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    path = await thumbs.get_or_create_thumb(product)
    if path is None:
        raise HTTPException(404, "No thumbnail available")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(product_id: int, body: ProductUpdate, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in CATEGORIES:
        data["category"] = "other"
    if "product_url" in data and data["product_url"] != product.product_url:
        dup = session.exec(select(Product).where(Product.product_url == data["product_url"])).first()
        if dup:
            raise HTTPException(409, "Product with this URL already exists")
    for k, v in data.items():
        setattr(product, k, v)
    product.updated_at = utcnow()
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    session.delete(product)
    session.commit()
    return Response(status_code=204)
