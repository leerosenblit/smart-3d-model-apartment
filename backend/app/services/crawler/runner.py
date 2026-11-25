"""Crawl orchestration: resumable state, worker pool, validation, batched upserts."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from ...config import get_settings
from ..scraper import upsert_product
from .common import validate_product
from .http import BlockedError, PoliteClient
from .stores import STORES, Store

log = logging.getLogger("roomcraft.crawler")


# --------------------------------------------------------------------------- state

class CrawlState:
    """JSON state file: per store ``{"discovered_at", "done": {url: status}}``.

    status is ``"ok"`` (stored), ``"skip:<reason>"`` (page fetched but unusable: re-fetching would not
    help) or ``"fail:<reason>"`` (network problem: retried on the next run).
    """

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"stores": {}}
        self._touched: set[str] = set()
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("could not read %s, starting with empty state", path)
        self.data.setdefault("stores", {})

    def store(self, key: str) -> dict:
        self._touched.add(key)
        return self.data["stores"].setdefault(key, {"done": {}})

    def reset_store(self, key: str) -> None:
        self._touched.add(key)
        self.data["stores"][key] = {"done": {}}

    def save(self) -> None:
        """Write only the stores this process works on, merged into whatever is on disk (several crawler
        processes - e.g. one per store - may share the file)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged: dict = {"stores": {}}
        if self.path.exists():
            try:
                merged = json.loads(self.path.read_text(encoding="utf-8"))
                merged.setdefault("stores", {})
            except (OSError, ValueError):
                merged = {"stores": {}}
        for key in self._touched:
            if key in self.data["stores"]:
                merged["stores"][key] = self.data["stores"][key]
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def cache_path(key: str) -> Path:
    return get_settings().storage_path / "crawl_cache" / f"{key}.json"


async def get_candidates(store: Store, http: PoliteClient, *, use_cache: bool) -> list[dict]:
    path = cache_path(store.key)
    if use_cache and path.exists():
        try:
            cands = json.loads(path.read_text(encoding="utf-8"))
            log.info("%s: using %d cached candidates (%s)", store.key, len(cands), path.name)
            return cands
        except (OSError, ValueError):
            pass
    cands = await store.discover(http)
    if cands and store.discovery_complete:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    elif not store.discovery_complete:
        log.warning("%s: discovery incomplete (%d candidates) - not caching it", store.key, len(cands))
    return cands


# --------------------------------------------------------------------------- crawl

class Report:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0
        self.skipped: Counter = Counter()
        self.failed: Counter = Counter()
        self.by_category: Counter = Counter()

    def line(self) -> str:
        return (
            f"created={self.created} updated={self.updated} "
            f"skipped={sum(self.skipped.values())} failed={sum(self.failed.values())}"
        )


async def crawl_store(
    store: Store,
    http: PoliteClient,
    session: Session,
    state: CrawlState,
    *,
    limit: Optional[int] = None,
    resume: bool = False,
    retry_skipped: bool = False,
    rediscover: bool = False,
    workers: int = 3,
    batch_size: int = 25,
) -> Report:
    report = Report()
    if not resume:
        state.reset_store(store.key)
    st = state.store(store.key)
    done: dict[str, str] = st["done"]

    try:
        cands = await get_candidates(store, http, use_cache=resume and not rediscover)
    except BlockedError as exc:
        log.error("%s: blocked during discovery: %s", store.key, exc)
        return report
    retry = ("fail:", "skip:") if retry_skipped else ("fail:",)
    todo = [c for c in cands if not (c["url"] in done and not done[c["url"]].startswith(retry))]
    if limit is not None:
        todo = todo[:limit]
    log.info("%s: %d candidates, %d to process (%d already done)", store.key, len(cands), len(todo), len(cands) - len(todo))
    if not todo:
        return report

    queue: asyncio.Queue = asyncio.Queue()
    for c in todo:
        queue.put_nowait(c)
    total = len(todo)
    processed = 0
    t0 = time.monotonic()
    blocked = asyncio.Event()
    pending: list[tuple[str, dict]] = []

    def finish(url: str, status: str) -> None:
        nonlocal processed
        done[url] = status
        processed += 1
        if processed % 25 == 0 or processed == total:
            rate = processed / max(1e-6, time.monotonic() - t0)
            eta = (total - processed) / rate if rate else 0
            log.info(
                "%s: %d/%d (%.1f/s, eta %dm) %s",
                store.key, processed, total, rate, eta // 60, report.line(),
            )
        if processed % 100 == 0:
            state.save()

    def write_batch() -> None:
        """Upsert the buffered rows in ONE short transaction (the dev server shares this SQLite file, so a
        write transaction must never stay open while we wait for the network)."""
        if not pending:
            return
        batch = list(pending)
        pending.clear()
        try:
            created_flags = [upsert_product(session, url, clean, commit=False)[1] for url, clean in batch]
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            log.warning("%s: DB error for a batch of %d rows: %s", store.key, len(batch), exc)
            for url, _ in batch:
                report.failed["db_error"] += 1
                finish(url, "fail:db_error")
            return
        for (url, clean), created in zip(batch, created_flags):
            if created:
                report.created += 1
            else:
                report.updated += 1
            report.by_category[clean["category"]] += 1
            finish(url, "ok")

    async def worker() -> None:
        while not blocked.is_set():
            try:
                cand = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            url = cand["url"]
            try:
                raw = await store.fetch(http, cand)
            except BlockedError as exc:
                log.error("%s: %s", store.key, exc)
                blocked.set()
                return
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop the crawl
                log.warning("%s: failed %s: %s: %s", store.key, url, exc.__class__.__name__, exc)
                report.failed[exc.__class__.__name__] += 1
                finish(url, f"fail:{exc.__class__.__name__}")
                continue
            if raw is None:
                report.skipped["no_data"] += 1
                finish(url, "skip:no_data")
                continue
            clean, reason = validate_product(raw)
            if clean is None:
                report.skipped[reason.split(":")[0]] += 1
                log.debug("%s: skip %s (%s)", store.key, url, reason)
                finish(url, f"skip:{reason}")
                continue
            pending.append((url, clean))
            if len(pending) >= batch_size:
                write_batch()
            await asyncio.sleep(0)  # let other workers / the event loop breathe even without network I/O

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise
    finally:
        write_batch()
        state.save()
    return report


async def run(
    store_keys: list[str],
    session: Session,
    *,
    limit: Optional[int] = None,
    resume: bool = False,
    retry_skipped: bool = False,
    rediscover: bool = False,
    workers: int = 3,
    delay: float = 0.45,
) -> dict[str, Report]:
    state = CrawlState(get_settings().storage_path / "crawl_state.json")
    http = PoliteClient(concurrency=workers, delay=delay)
    reports: dict[str, Report] = {}
    try:
        for key in store_keys:
            store = STORES[key]
            log.info("=== %s (%s) ===", key, store.store_name)
            reports[key] = await crawl_store(
                store, http, session, state, limit=limit, resume=resume,
                retry_skipped=retry_skipped, rediscover=rediscover, workers=workers
            )
            log.info("=== %s done: %s", key, reports[key].line())
    finally:
        state.save()
        await http.aclose()
    return reports
