"""Polite async HTTP fetcher: robots.txt, per-domain rate limit, retry."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import NamedTuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = (
    "FertilizerDataBot/1.0 (+research crawler; contact: kientlt59@gmail.com)"
)


@dataclass
class FetchStats:
    ok: int = 0
    failed: int = 0
    blocked_by_robots: int = 0


class Page(NamedTuple):
    html: str
    # URL after redirects. Storing the requested URL instead would file the
    # same product under several addresses and defeat de-duplication.
    url: str


@dataclass
class PoliteFetcher:
    """Fetches pages while respecting robots.txt and a per-domain delay.

    delay_seconds is the minimum gap between two requests to the same host;
    robots.txt Crawl-delay overrides it when larger.
    """

    delay_seconds: float = 1.5
    timeout: float = 20.0
    max_concurrency: int = 4
    stats: FetchStats = field(default_factory=FetchStats)

    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict)
    _last_hit: dict[str, float] = field(default_factory=dict)
    _host_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _client: httpx.AsyncClient | None = None
    _sem: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "PoliteFetcher":
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=self.max_concurrency),
        )
        self._sem = asyncio.Semaphore(self.max_concurrency)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        host = urlparse(url).netloc
        if not host:
            return None
        if host in self._robots:
            return self._robots[host]

        scheme = urlparse(url).scheme or "https"
        robots_url = f"{scheme}://{host}/robots.txt"
        parser: RobotFileParser | None = None
        try:
            resp = await self._client.get(robots_url)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
                log.info("robots.txt loaded for %s", host)
            else:
                log.info("no robots.txt for %s (HTTP %s)", host, resp.status_code)
        except httpx.HTTPError as exc:
            log.warning("robots.txt fetch failed for %s: %s", host, exc)

        self._robots[host] = parser
        return parser

    def _effective_delay(self, url: str, parser: RobotFileParser | None) -> float:
        if parser is None:
            return self.delay_seconds
        try:
            declared = parser.crawl_delay(USER_AGENT)
        except Exception:
            declared = None
        return max(self.delay_seconds, float(declared)) if declared else self.delay_seconds

    async def _throttle(self, host: str, delay: float) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_hit.get(host, 0.0)
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last_hit[host] = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _get(self, url: str) -> httpx.Response:
        resp = await self._client.get(url)
        # Retry only on transient server-side problems.
        if resp.status_code >= 500 or resp.status_code == 429:
            resp.raise_for_status()
        return resp

    async def fetch(self, url: str) -> Page | None:
        """Return the page, or None if disallowed / failed."""
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            log.warning("skipping malformed url %r", url)
            self.stats.failed += 1
            return None

        parser = await self._robots_for(url)
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            log.info("robots.txt disallows %s", url)
            self.stats.blocked_by_robots += 1
            return None

        host = urlparse(url).netloc
        delay = self._effective_delay(url, parser)

        async with self._sem:
            await self._throttle(host, delay)
            try:
                resp = await self._get(url)
            except httpx.HTTPError as exc:
                log.warning("fetch failed %s: %s", url, exc)
                self.stats.failed += 1
                return None

        if resp.status_code != 200:
            log.warning("fetch %s -> HTTP %s", url, resp.status_code)
            self.stats.failed += 1
            return None

        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            log.info("skip non-HTML %s (%s)", url, ctype)
            self.stats.failed += 1
            return None

        self.stats.ok += 1
        return Page(resp.text, str(resp.url))

    async def fetch_json(self, url: str):
        """Fetch a JSON endpoint under the same courtesy rules as a page.

        Returns None on anything unexpected: these endpoints are an
        optimisation, and a shop that does not serve one is not an error.
        """
        parser = await self._robots_for(url)
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            self.stats.blocked_by_robots += 1
            return None

        host = urlparse(url).netloc
        delay = self._effective_delay(url, parser)

        async with self._sem:
            await self._throttle(host, delay)
            try:
                resp = await self._client.get(url, headers={"Accept": "application/json"})
            except httpx.HTTPError as exc:
                log.debug("json fetch failed %s: %s", url, exc)
                return None

        if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
            return None
        try:
            return resp.json()
        except ValueError:
            return None
