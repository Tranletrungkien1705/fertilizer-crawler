"""Crawl public fertilizer listings into a free-tier database.

Usage:
    python main.py                 # crawl every site in sites.json
    python main.py --site <name>   # crawl one site
    python main.py --limit 20      # cap detail pages per site
    python main.py --stats         # show what is already stored
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from crawler.extract import extract_links, extract_product
from crawler.fetcher import PoliteFetcher
from crawler.storage import Storage

ROOT = Path(__file__).resolve().parent
SITES_FILE = ROOT / "sites.json"

load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawl")


def load_sites() -> list[dict]:
    if not SITES_FILE.exists():
        raise SystemExit(f"Missing config: {SITES_FILE}")
    sites = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    return [s for s in sites if s.get("enabled", True)]


async def crawl_site(fetcher: PoliteFetcher, site: dict, limit: int) -> list:
    name = site["name"]
    products: list = []
    # Collections overlap heavily, so the same product shows up in several
    # listings. Track final URLs to fetch each detail page only once.
    seen: set[str] = set()

    for list_url in site["list_urls"]:
        log.info("[%s] listing %s", name, list_url)
        listing = await fetcher.fetch(list_url)
        if not listing:
            continue

        links = extract_links(listing.html, listing.url,
                              site["selectors"]["product_link"])
        log.info("[%s] found %d product links", name, len(links))

        fetched = 0
        for url in links:
            if fetched >= limit:
                break
            if url in seen:
                continue
            page = await fetcher.fetch(url)
            if not page:
                continue
            fetched += 1
            if page.url in seen:
                log.debug("[%s] redirect landed on known page %s", name, page.url)
                continue
            seen.add(url)
            seen.add(page.url)

            product = extract_product(page.html, page.url, name, site["selectors"])
            if product:
                products.append(product)
                log.info("[%s] %s | %s", name, product.name[:60],
                         f"{product.price:,.0f}d" if product.price else "no price")
            else:
                log.debug("[%s] no product data at %s", name, page.url)

    return products


async def run(site_filter: str | None, limit: int) -> None:
    sites = load_sites()
    if site_filter:
        sites = [s for s in sites if s["name"] == site_filter]
        if not sites:
            raise SystemExit(f"No enabled site named {site_filter!r}")

    failed_sites: list[str] = []
    total_saved = 0

    # Write after every shop rather than once at the end: a run across many
    # sites takes a while, and results should be queryable as they land
    # instead of being lost if a later shop breaks.
    with Storage() as db:
        async with PoliteFetcher(delay_seconds=1.5, max_concurrency=3) as fetcher:
            for site in sites:
                name = site["name"]
                try:
                    products = await crawl_site(fetcher, site, limit)
                except Exception as exc:
                    log.error("[%s] crawl failed: %s", name, exc)
                    failed_sites.append(name)
                    continue

                saved = db.save_many(products)
                total_saved += saved
                log.info("[%s] saved %d rows; table now holds %d",
                         name, saved, db.count())

            s = fetcher.stats
            log.info("fetched ok=%d failed=%d robots-blocked=%d",
                     s.ok, s.failed, s.blocked_by_robots)

        if failed_sites:
            log.warning("sites that errored: %s", ", ".join(failed_sites))
        log.info("saved %d rows total; table holds %d", total_saved, db.count())


def show_stats() -> None:
    with Storage() as db:
        print(f"products stored: {db.count()}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", help="crawl only this site name")
    ap.add_argument("--limit", type=int, default=25,
                    help="max detail pages per listing (default 25)")
    ap.add_argument("--stats", action="store_true", help="show stored row count")
    args = ap.parse_args()

    if args.stats:
        show_stats()
        return

    asyncio.run(run(args.site, args.limit))


if __name__ == "__main__":
    main()
