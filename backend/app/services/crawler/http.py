"""Polite async HTTP: robots.txt honouring, per-host concurrency + spacing, retry/back-off.

Never tries to get around protection: a host answering 403/429 repeatedly is "blocked" and the crawler
for that store stops (see :class:`BlockedError`).
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..scraper import HEADERS

log = logging.getLogger("roomcraft.crawler")

ROBOTS_UA = "*"


class BlockedError(RuntimeError):
    """The site keeps refusing us (403/429/captcha): stop crawling it."""


class RobotsRules:
    """Minimal robots.txt (Google-style wildcards, longest-match wins, Allow beats Disallow on ties)."""

    def __init__(self, text: str = "", agent: str = ROBOTS_UA):
        self.rules: list[tuple[bool, re.Pattern, int]] = []  # (allow, regex, specificity)
        self._parse(text, agent)

    @staticmethod
    def _compile(path: str) -> re.Pattern:
        anchored = path.endswith("$")
        if anchored:
            path = path[:-1]
        rx = re.escape(path).replace(r"\*", ".*")
        return re.compile("^" + rx + ("$" if anchored else ""))

    def _parse(self, text: str, agent: str) -> None:
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if last_was_rule:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(v.lower())
                last_was_rule = False
            elif k in ("allow", "disallow"):
                rules.append((k == "allow", v))
                last_was_rule = True
        if agents:
            groups.append((agents, rules))
        chosen = [g for g in groups if agent in g[0]]
        for _agents, rs in chosen:
            for allow, path in rs:
                if not path:  # "Disallow:" (empty) allows everything
                    continue
                self.rules.append((allow, self._compile(path), len(path)))

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        target = p.path or "/"
        if p.query:
            target += "?" + p.query
        best: Optional[tuple[int, bool]] = None
        for allow, rx, spec in self.rules:
            if rx.match(target):
                key = (spec, allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


class PoliteClient:
    """One shared client; each host gets its own concurrency limit and request spacing."""

    def __init__(
        self,
        *,
        concurrency: int = 3,
        delay: float = 0.45,
        timeout: float = 30.0,
        max_retries: int = 4,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.concurrency = concurrency
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._own = client is None
        self.client = client or httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=timeout, http2=False,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )
        if self._own:
            # stateless like curl: Shopify answers 429 to sessions carrying its analytics cookies
            self.client.cookies.jar.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._next_slot: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, RobotsRules] = {}
        self._denied: dict[str, int] = {}
        self.host_delay: dict[str, float] = {}  # per-host override of ``delay`` (seconds between starts)
        self.stats = {"requests": 0, "retries": 0, "robots_blocked": 0}

    async def aclose(self) -> None:
        if self._own:
            await self.client.aclose()

    # -- robots ------------------------------------------------------------------------------
    async def _rules(self, url: str) -> RobotsRules:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            text = ""
            try:
                r = await self.client.get(origin + "/robots.txt", headers=HEADERS, timeout=20)
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "").lower():
                    text = r.text
            except httpx.HTTPError as exc:
                log.warning("robots.txt fetch failed for %s: %s", origin, exc)
            self._robots[origin] = RobotsRules(text)
            log.info("robots.txt for %s: %d rules for '*'", origin, len(self._robots[origin].rules))
        return self._robots[origin]

    async def allowed(self, url: str) -> bool:
        return (await self._rules(url)).allowed(url)

    # -- throttling --------------------------------------------------------------------------
    async def _slot(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            at = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = at + max(self.delay, self.host_delay.get(host, 0.0))
        if at > now:
            await asyncio.sleep(at - now)

    def penalise(self, host: str, seconds: float) -> None:
        """Push the next-request slot out (back-off shared by all workers of that host)."""
        self._next_slot[host] = max(self._next_slot.get(host, 0.0), time.monotonic() + seconds)

    # -- GET ---------------------------------------------------------------------------------
    async def get(
        self, url: str, *, check_robots: bool = True, headers: Optional[dict] = None
    ) -> Optional[httpx.Response]:
        """GET with politeness. Returns None for robots-disallowed URLs and 404/410; raises
        :class:`BlockedError` when the host keeps denying us; other failures return None after retries."""
        host = urlparse(url).netloc
        if check_robots and not await self.allowed(url):
            self.stats["robots_blocked"] += 1
            log.debug("robots.txt disallows %s", url)
            return None
        sem = self._sems.setdefault(host, asyncio.Semaphore(self.concurrency))
        async with sem:
            for attempt in range(self.max_retries + 1):
                await self._slot(host)
                self.stats["requests"] += 1
                try:
                    r = await self.client.get(url, headers={**HEADERS, **(headers or {})})
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    wait = min(60, 3 * 2**attempt)
                    log.warning("%s on %s (try %d), backing off %ss", exc.__class__.__name__, url, attempt + 1, wait)
                    self.penalise(host, wait)
                    self.stats["retries"] += 1
                    continue
                code = r.status_code
                if code == 200:
                    self._denied[host] = 0
                    return r
                if code in (404, 410):
                    return None
                if code in (403, 429, 503):
                    self._denied[host] = self._denied.get(host, 0) + 1
                    ra = r.headers.get("retry-after", "")
                    wait = float(ra) if ra.replace(".", "", 1).isdigit() else min(120, 5 * 2**attempt)
                    log.warning("HTTP %s from %s (try %d) - backing off %.0fs", code, host, attempt + 1, wait)
                    self.penalise(host, wait)
                    self.stats["retries"] += 1
                    if self._denied[host] >= 8:
                        raise BlockedError(f"{host} keeps answering {code}; giving up on this store")
                    continue
                if 500 <= code < 600:
                    wait = min(60, 3 * 2**attempt)
                    self.penalise(host, wait)
                    self.stats["retries"] += 1
                    continue
                log.warning("HTTP %s for %s", code, url)
                return None
        return None
