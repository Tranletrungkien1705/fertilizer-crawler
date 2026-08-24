"""Re-crawl specific product URLs.

A listing walk only reaches products that still appear in a category page, so
a row can go stale where a parsing fix never lands on it. This refreshes named
URLs directly.

    python refresh_urls.py https://shop.vn/a https://shop.vn/b
    python refresh_urls.py --stale-below 5000   # rows whose price looks wrong
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawler.extract import extract_product, merge_structured
from crawler.fetcher import PoliteFetcher
from crawler.platform import detect
from crawler.storage import Storage
from main import fetch_structured, load_sites

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def site_for(url: str, sites: list[dict]) -> dict | None:
    for site in sites:
        if any(url.startswith(u.split("?")[0].rsplit("/", 1)[0]) for u in site["list_urls"]):
            return site
    host = url.split("/")[2]
    for site in sites:
        if host in site["list_urls"][0]:
            return site
    return None


def find_stale(db, below: float) -> list[tuple[str, str]]:
    with db._conn.cursor() as cur:
        cur.execute(
            "SELECT url, source FROM products WHERE price > 0 AND price < %s"
            if db.is_pg else
            "SELECT url, source FROM products WHERE price > 0 AND price < ?",
            (below,))
        return cur.fetchall()


async def run(urls: list[str]) -> None:
    sites = load_sites()
    updated = 0

    with Storage() as db:
        async with PoliteFetcher(delay_seconds=1.5, max_concurrency=2) as fetcher:
            for url in urls:
                site = site_for(url, sites)
                if site is None:
                    print(f"  no site config matches {url}")
                    continue

                page = await fetcher.fetch(url)
                if not page:
                    print(f"  fetch failed {url}")
                    continue

                product = extract_product(page.html, page.url, site["name"],
                                          site["selectors"])
                if not product:
                    print(f"  no product parsed at {url}")
                    continue

                platform = site.get("platform") or detect(page.html)
                data, reviews = await fetch_structured(fetcher, page.url, platform)
                product = merge_structured(product, data, platform, reviews)

                db.record_history([product])
                db.save_many([product])
                updated += 1
                print(f"  {product.price:>12,.0f}d  {product.name[:52]}")

    print(f"\nrefreshed {updated} of {len(urls)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="product URLs to refresh")
    ap.add_argument("--stale-below", type=float,
                    help="refresh every product priced below this (VND)")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.stale_below:
        with Storage() as db:
            found = find_stale(db, args.stale_below)
        print(f"{len(found)} rows priced below {args.stale_below:,.0f}d")
        urls += [u for u, _ in found]

    if not urls:
        raise SystemExit("nothing to refresh")
    asyncio.run(run(urls))


if __name__ == "__main__":
    main()
