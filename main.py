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
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawler.extract import extract_links, extract_product, merge_structured
from crawler.fetcher import PoliteFetcher
from crawler.platform import (
    HARAVAN,
    PRICE_MINOR,
    SAPO,
    WOOCOMMERCE,
    detect,
    haravan_url,
    parse_haravan,
    parse_woo,
    parse_woo_reviews,
    woo_reviews_url,
    woo_url,
)
from crawler.storage import Storage

ROOT = Path(__file__).resolve().parent
SITES_FILE = ROOT / "sites.json"

# Product names are Vietnamese; the Windows console defaults to cp1252 and
# mangles them in the log.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


async def fetch_structured(fetcher: PoliteFetcher, url: str, platform: str):
    """Ask the shop's own API for this product. Returns (data, reviews)."""
    if platform in (HARAVAN, SAPO):
        payload = await fetcher.fetch_json(haravan_url(url))
        if isinstance(payload, dict) and payload.get("variants") is not None:
            # Same endpoint, different money scale - see PRICE_MINOR.
            return parse_haravan(payload, url, PRICE_MINOR[platform]), None

    elif platform == WOOCOMMERCE:
        payload = await fetcher.fetch_json(woo_url(url))
        if isinstance(payload, list) and payload:
            data = parse_woo(payload[0])
            reviews = None
            if data.get("review_count") and data.get("_id"):
                raw = await fetcher.fetch_json(woo_reviews_url(url, data["_id"]))
                reviews = parse_woo_reviews(raw) if isinstance(raw, list) else None
            data.pop("_id", None)
            return data, reviews

    return None, None


async def crawl_site(fetcher: PoliteFetcher, site: dict, limit: int) -> list:
    name = site["name"]
    products: list = []
    platform: str | None = None
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
            if not product:
                log.debug("[%s] no product data at %s", name, page.url)
                continue

            if platform is None:
                platform = site.get("platform") or detect(page.html)
                log.info("[%s] platform: %s", name, platform)

            data, reviews = await fetch_structured(fetcher, page.url, platform)
            product = merge_structured(product, data, platform, reviews)

            products.append(product)
            extras = []
            if product.sku:
                extras.append(product.sku)
            if product.stock_qty is not None:
                extras.append(f"stock {product.stock_qty}")
            if product.review_count:
                extras.append(f"{product.review_count} reviews")
            log.info("[%s] %s | %s%s", name, product.name[:52],
                     f"{product.price:,.0f}d" if product.price else "no price",
                     "  " + " ".join(extras) if extras else "")

    return products


async def run(site_filter: str | None, limit: int) -> None:
    sites = load_sites()
    if site_filter:
        sites = [s for s in sites if s["name"] == site_filter]
        if not sites:
            raise SystemExit(f"No enabled site named {site_filter!r}")

    failed_sites: list[str] = []
    per_site: dict[str, int] = {}
    total_saved = 0
    total_moved = 0

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

                # Saving is inside the guard too. A write that fails on the
                # fourth shop used to abandon the five behind it, discarding
                # work already fetched.
                try:
                    # Before the upsert, while the table still holds the
                    # previous prices to compare against.
                    moved = db.record_history(products)
                    saved = db.save_many(products)
                except Exception as exc:
                    log.error("[%s] save failed: %s", name, exc)
                    failed_sites.append(name)
                    continue

                total_moved += moved
                if moved:
                    log.info("[%s] %d price/stock changes recorded", name, moved)

                total_saved += saved
                per_site[name] = saved
                log.info("[%s] saved %d rows; table now holds %d",
                         name, saved, db.count())

            s = fetcher.stats
            log.info("fetched ok=%d failed=%d robots-blocked=%d",
                     s.ok, s.failed, s.blocked_by_robots)

        if failed_sites:
            log.warning("sites that errored: %s", ", ".join(failed_sites))

        # Some shops serve an empty page to datacentre addresses while working
        # fine from a home connection, so a run from CI can lose a site
        # without anything looking wrong. Name them.
        empty = [name for name, n in per_site.items() if n == 0]
        if empty:
            log.warning(
                "sites that returned nothing: %s "
                "(they may be refusing this network - try them locally)",
                ", ".join(empty),
            )
        log.info("saved %d rows total; table holds %d", total_saved, db.count())
        log.info("%d price/stock changes appended to history", total_moved)

    # A run that collects nothing is a broken run, not an up-to-date one:
    # selectors rot, and shops serve empty pages to datacentre addresses.
    # Say so with an exit code, or a nightly job reports success forever
    # while the data quietly goes stale.
    if total_saved == 0:
        raise SystemExit(
            "no products were saved - every listing came back empty. "
            "Check the selectors in sites.json, or whether the shops are "
            "refusing this network."
        )


def show_stats() -> None:
    with Storage() as db:
        print(f"products stored: {db.count()}")
        for source, n in db.count_by_source():
            print(f"  {source:22} {n}")


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
