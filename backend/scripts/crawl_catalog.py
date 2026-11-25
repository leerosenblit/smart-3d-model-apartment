"""Resumable, polite catalog crawler: real Israeli-market products -> SQLite `products` table.

Usage (from backend/):
    python -m scripts.crawl_catalog                         # all stores, fresh discovery
    python -m scripts.crawl_catalog --store ikea,ace        # selected stores
    python -m scripts.crawl_catalog --store ikea --limit 50 # smoke test
    python -m scripts.crawl_catalog --resume                # continue: reuse discovery cache + skip done URLs
    python -m scripts.crawl_catalog --resume --retry-skipped
    python -m scripts.crawl_catalog --store ikea --resume --rediscover --ikea-per-family 10

State lives in storage/crawl_state.json, discovery results in storage/crawl_cache/<store>.json.
Existing rows are only upserted by product_url (cached 3D models are never touched, nothing is deleted).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlmodel import Session, create_engine, func, select

from app import db
from app.config import get_settings
from app.models import Product
from app.services.crawler import runner
from app.services.crawler.stores import STORES


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", "--stores", dest="stores", default="all",
                    help=f"comma separated: {','.join(STORES)} (default: all)")
    ap.add_argument("--limit", type=int, default=None, help="max candidate pages to process per store")
    ap.add_argument("--resume", action="store_true", help="reuse cached discovery and skip already-done URLs")
    ap.add_argument("--retry-skipped", action="store_true", help="with --resume: also re-fetch skipped URLs")
    ap.add_argument("--rediscover", action="store_true",
                    help="with --resume: rebuild the URL list (sitemaps) instead of using the cache; URLs "
                         "already done stay done, so only newly discovered pages are fetched")
    ap.add_argument("--ikea-per-family", type=int, default=None,
                    help="max colour variants kept per IKEA design (default 8)")
    ap.add_argument("--ikea-per-line", type=int, default=None,
                    help="max items per IKEA product line + category, e.g. METOD cabinets (default 60)")
    ap.add_argument("--workers", type=int, default=3, help="concurrent requests per host (default 3, max 4)")
    ap.add_argument("--delay", type=float, default=0.45, help="seconds between request starts per host (>=0.3)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    keys = list(STORES) if args.stores == "all" else [k.strip() for k in args.stores.split(",") if k.strip()]
    unknown = [k for k in keys if k not in STORES]
    if unknown:
        ap.error(f"unknown store(s): {', '.join(unknown)}")
    if args.ikea_per_family:
        STORES["ikea"].max_per_family = args.ikea_per_family
    if args.ikea_per_line:
        STORES["ikea"].max_per_line = args.ikea_per_line
    workers = max(1, min(4, args.workers))
    delay = max(0.3, args.delay)

    # long busy timeout: the dev server may be writing to the same SQLite file
    engine = create_engine(
        get_settings().database_url, connect_args={"check_same_thread": False, "timeout": 120}
    )
    db.set_engine(engine)
    db.init_db()
    with Session(engine) as session:
        before = session.exec(select(func.count()).select_from(Product)).one()
        try:
            reports = asyncio.run(
                runner.run(keys, session, limit=args.limit, resume=args.resume,
                           retry_skipped=args.retry_skipped, rediscover=args.rediscover,
                           workers=workers, delay=delay)
            )
        except KeyboardInterrupt:
            print("interrupted - state saved, re-run with --resume to continue", file=sys.stderr)
            return 130
        after = session.exec(select(func.count()).select_from(Product)).one()

    print(f"\nproducts: {before} -> {after}")
    for key, rep in reports.items():
        print(f"[{key}] {rep.line()}")
        if rep.skipped:
            print("   skipped:", dict(rep.skipped.most_common()))
        if rep.failed:
            print("   failed:", dict(rep.failed.most_common()))
        if rep.by_category:
            print("   categories:", dict(rep.by_category.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
