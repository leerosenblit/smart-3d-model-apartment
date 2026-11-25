"""Batch product ingestion CLI.

Usage:
    python -m scripts.ingest urls.txt        # one URL per line, '#' comments allowed
    python -m scripts.ingest products.json   # JSON list of URL strings and/or product objects

Product objects use the Product fields (product_url, title, category, price_ils,
width_cm, depth_cm, height_cm, image_url, store_name) and are upserted directly.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlmodel import Session

from app.db import get_engine, init_db
from app.services.scraper import ingest_urls, upsert_product


def load_inputs(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
        if not isinstance(raw, list):
            raise SystemExit("JSON file must contain a list")
        urls = [x for x in raw if isinstance(x, str)]
        objs = [x for x in raw if isinstance(x, dict)]
        return urls, objs
    urls = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return urls, []


async def run(path: Path) -> int:
    init_db()
    urls, objs = load_inputs(path)
    failed = 0
    with Session(get_engine()) as session:
        for obj in objs:
            try:
                url = obj["product_url"]
                _, created = upsert_product(session, url, obj)
                print(f"{'created' if created else 'updated':8} {url}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"failed   {obj.get('product_url', '?')}: {exc}")
        if urls:
            for r in await ingest_urls(session, urls):
                if r.status == "failed":
                    failed += 1
                    print(f"failed   {r.url}: {r.error}")
                else:
                    p = r.product
                    print(
                        f"{r.status:8} {r.url} -> {p.title} "
                        f"[{p.category}] {p.width_cm}x{p.depth_cm}x{p.height_cm} cm, "
                        f"{p.price_ils} ILS (via {r.source})"
                    )
    return failed


def main() -> None:
    # Hebrew messages must not crash legacy Windows (cp1252) consoles.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    failed = asyncio.run(run(path))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
