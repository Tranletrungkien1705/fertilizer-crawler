"""Dev helper: how many pages does a listing have, and products per page?"""
import asyncio
import sys

import httpx

from crawler.extract import extract_links

UA = "FertilizerDataBot/1.0 (+research crawler)"


async def main(base: str, link_sel: str, pattern: str = "{base}/page/{n}") -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        total: set[str] = set()
        for n in range(1, 12):
            url = base if n == 1 else pattern.format(base=base.rstrip("/"), n=n)
            try:
                r = await c.get(url)
            except httpx.HTTPError as exc:
                print(f"  page {n}: {exc}")
                break
            if r.status_code != 200:
                print(f"  page {n}: HTTP {r.status_code} (stop)")
                break
            links = set(extract_links(r.text, url, link_sel))
            fresh = links - total
            print(f"  page {n}: {len(links)} links, {len(fresh)} new")
            if not fresh:
                print("  (no new products - stop)")
                break
            total |= links
            await asyncio.sleep(1.5)

        print(f"\ntotal unique products: {len(total)}")


if __name__ == "__main__":
    # usage: probe_pagination.py <base_url> <link_selector> [page_pattern]
    #   WooCommerce: "{base}/page/{n}" (default)   Haravan/Shopify: "{base}?page={n}"
    asyncio.run(main(*sys.argv[1:4]))
