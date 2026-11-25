"""One-off cleanup: split the crawl's 'wardrobe' bucket into 'wardrobe' (tall clothes wardrobes) and 'storage'
(dressers, shoe/bathroom cabinets, shelving, storage systems). Update-only; never deletes rows.

    python -m scripts.recategorize [--dry-run]
"""
from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models import Product, utcnow
from app.services.crawler.common import refine_wardrobe


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry-run" in sys.argv
    init_db()
    moved = kept = 0
    with Session(get_engine()) as session:
        for p in session.exec(select(Product).where(Product.category == "wardrobe")).all():
            new = refine_wardrobe(p.title, p.height_cm)
            if new == "wardrobe":
                kept += 1
                continue
            moved += 1
            if not dry:
                p.category = new
                p.updated_at = utcnow()
                session.add(p)
        if not dry:
            session.commit()
    print(f"{'would move' if dry else 'moved'} {moved} to storage, kept {kept} as wardrobe")


if __name__ == "__main__":
    main()
