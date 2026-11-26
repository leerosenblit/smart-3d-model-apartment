"""Portable catalog snapshot: the scraped products as one small gzip-JSON file that lives in git.

A fresh clone has no database, so on first start the server loads this file instead of the 23-product
fallback seed. 3D models are not part of it (they are generated lazily); thumbnails are re-fetched
on demand from each product's image URL.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from sqlmodel import Session, select

from ..models import Product

FIELDS = ["id", "store_name", "product_url", "title", "category", "price_ils", "width_cm", "depth_cm", "height_cm", "image_url"]


def export_catalog(session: Session, path: Path) -> int:
    rows = session.exec(select(Product).order_by(Product.id)).all()
    data = [{f: getattr(p, f) for f in FIELDS} for p in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    return len(data)


def import_catalog(session: Session, path: Path) -> int:
    """Insert snapshot rows that are not in the table yet (matched by product_url). Returns rows inserted."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    known = set(session.exec(select(Product.product_url)).all())
    n = 0
    for row in data:
        if row["product_url"] in known:
            continue
        session.add(Product(**{f: row[f] for f in FIELDS if f in row}))
        n += 1
    session.commit()
    return n
