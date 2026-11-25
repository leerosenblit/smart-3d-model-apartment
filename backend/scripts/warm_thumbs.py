"""Pre-cache product thumbnails so catalog cards load instantly.

Usage (from ``backend/``):
    python -m scripts.warm_thumbs [--concurrency 4] [--limit N]

Resumable: products whose ``storage/thumbs/{id}.jpg`` already exists are skipped, so it can be
stopped and re-run (e.g. after more products were crawled). Keeps concurrency low to stay polite.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models import Product
from app.services import thumbs


async def run(concurrency: int, limit: int | None) -> int:
    init_db()
    with Session(get_engine()) as session:
        products = [
            p
            for p in session.exec(select(Product).order_by(Product.id)).all()
            if thumbs.is_remote_image(p.image_url) and not thumbs.thumb_path(p.id).exists()
        ]
    if limit:
        products = products[:limit]
    total = len(products)
    print(f"{total} thumbnails to fetch (concurrency {concurrency})", flush=True)

    sem = asyncio.Semaphore(concurrency)
    done = ok = 0
    started = time.time()

    async def one(p: Product) -> None:
        nonlocal done, ok
        async with sem:
            try:
                path = await thumbs.get_or_create_thumb(p)
            except Exception as exc:  # noqa: BLE001
                path = None
                print(f"  ! {p.id}: {exc.__class__.__name__}", flush=True)
            done += 1
            ok += 1 if path else 0
            if done % 100 == 0 or done == total:
                rate = done / max(1e-6, time.time() - started)
                print(f"  {done}/{total} ({ok} ok) {rate:.1f}/s", flush=True)

    await asyncio.gather(*(one(p) for p in products))
    return total - ok


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    failed = asyncio.run(run(args.concurrency, args.limit))
    print(f"finished, {failed} without a thumbnail", flush=True)


if __name__ == "__main__":
    main()
