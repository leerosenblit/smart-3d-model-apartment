"""Lazy Image-to-3D endpoints."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from ..db import get_session
from ..models import Product, utcnow
from ..schemas import ModelStatusRead
from ..services import model_3d

router = APIRouter(prefix="/api/products", tags=["generation"])


STALE_AFTER_S = 300  # a generation running longer than this was orphaned (e.g. the server restarted)


def _is_stale(p: Product) -> bool:
    if p.model_status != "generating" or p.updated_at is None:
        return False
    updated = p.updated_at if p.updated_at.tzinfo else p.updated_at.replace(tzinfo=utcnow().tzinfo)
    return (utcnow() - updated).total_seconds() > STALE_AFTER_S


def _status(p: Product) -> ModelStatusRead:
    return ModelStatusRead(
        id=p.id, model_status=p.model_status, model_3d_url=p.model_3d_url, model_error=p.model_error
    )


@router.post("/{product_id}/generate-3d", response_model=ModelStatusRead)
def generate_3d(
    product_id: int,
    background: BackgroundTasks,
    force: bool = False,
    session: Session = Depends(get_session),
):
    """Idempotent: starts generation only if the model is not ready or already generating.

    ``force=true`` regenerates a model that is already ready (e.g. after switching to a better provider).
    """
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if (product.model_status == "generating" and not _is_stale(product)) or (product.model_status == "ready" and not force):
        # A 'ready' status whose file vanished is regenerated.
        if not (product.model_status == "ready" and not model_3d.model_path(product_id).exists()):
            return _status(product)
    product.model_status = "generating"
    product.model_error = None
    product.model_3d_url = None
    product.updated_at = utcnow()
    session.add(product)
    session.commit()
    session.refresh(product)
    background.add_task(model_3d.run_generation, product_id)
    return _status(product)


@router.get("/{product_id}/3d-status", response_model=ModelStatusRead)
def get_3d_status(product_id: int, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if _is_stale(product):  # orphaned task: report 'none' so the client re-triggers generation
        product.model_status = "none"
        session.add(product)
        session.commit()
        session.refresh(product)
    return _status(product)
