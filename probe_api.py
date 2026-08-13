"""Dev helper: does this shop expose structured data without a browser?

Scraping rendered HTML is the last resort. Most Vietnamese shops run on
Haravan, Shopify or WooCommerce, and all three publish JSON that already
contains variants, stock and images - no rendering, no guessing selectors,
and far less traffic. Check for that before reaching for Playwright.
"""
import asyncio
import json
import re
import sys

import httpx

UA = "FertilizerDataBot/1.0 (+research crawler)"


async def try_json(client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
    try:
        r = await client.get(url)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        return False, f"not json ({ctype[:24]})"
    try:
        data = r.json()
    except ValueError:
        return False, "unparseable"
    if isinstance(data, list):
        return True, f"list of {len(data)}"
    if isinstance(data, dict):
        return True, "keys: " + ", ".join(list(data)[:8])
    return True, type(data).__name__


async def main(product_url: str) -> None:
    base = "/".join(product_url.split("/")[:3])
    handle = product_url.rstrip("/").split("/")[-1].split("?")[0]

    candidates = [
        # Haravan and Shopify both serve a product as JSON beside its page.
        (f"{product_url.rstrip('/')}.js", "haravan/shopify product .js"),
        (f"{product_url.rstrip('/')}.json", "shopify product .json"),
        (f"{base}/products.json?limit=5", "shopify products.json"),
        # WooCommerce Store API is public and needs no key.
        (f"{base}/wp-json/wc/store/v1/products?per_page=3", "woo store api v1"),
        (f"{base}/wp-json/wc/store/products?per_page=3", "woo store api"),
        (f"{base}/?wc-ajax=get_refreshed_fragments", "woo fragments"),
    ]

    async with httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept": "application/json"},
        timeout=25, follow_redirects=True
    ) as client:
        print(f"shop: {base}\nproduct: {handle}\n")
        for url, label in candidates:
            ok, detail = await try_json(client, url)
            mark = "OK " if ok else "-  "
            print(f"  {mark}{label:28} {detail}")
            print(f"     {url[:96]}")
            await asyncio.sleep(0.6)

        # Embedded payloads: data rendered into the page by the app itself.
        print("\n  embedded in the HTML:")
        r = await client.get(product_url, headers={"Accept": "text/html"})
        html = r.text
        checks = [
            ("JSON-LD Product", r'"@type"\s*:\s*"Product"'),
            ("__NEXT_DATA__", r"__NEXT_DATA__"),
            ("__NUXT__", r"__NUXT__"),
            ("window.product", r"window\.product\s*="),
            ("var product =", r"var\s+product\s*="),
            ("meta itemprop price", r'itemprop=["\']price'),
            ("variants array", r'"variants"\s*:\s*\['),
            ("inventory_quantity", r"inventory_quantity"),
            ("available", r'"available"\s*:'),
        ]
        for label, pattern in checks:
            hits = len(re.findall(pattern, html))
            if hits:
                print(f"    OK {label:22} x{hits}")

        for block in re.findall(
            r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S
        ):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            items = data.get("@graph", [data]) if isinstance(data, dict) else data
            for item in items if isinstance(items, list) else [items]:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    keys = ", ".join(list(item)[:12])
                    print(f"    JSON-LD Product keys: {keys}")
                    offers = item.get("offers")
                    if offers:
                        sample = offers[0] if isinstance(offers, list) else offers
                        print(f"    offers: {json.dumps(sample, ensure_ascii=False)[:160]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
