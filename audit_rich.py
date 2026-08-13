"""Run the full extractor over one live product per shop and report coverage.

Worth running after any selector change: it shows at a glance which shops
yield photos, video and agronomic sections, and which quietly yield nothing.
"""
import asyncio
import json
from pathlib import Path

import httpx

from crawler.extract import extract_links, extract_product
from crawler.fetcher import USER_AGENT

ROOT = Path(__file__).resolve().parent


async def one(client: httpx.AsyncClient, site: dict) -> dict:
    name = site["name"]
    sel = site["selectors"]
    row = {"shop": name, "product": "-", "img": 0, "vid": 0,
           "specs": 0, "sections": "", "content": 0}

    try:
        listing = await client.get(site["list_urls"][0])
        links = extract_links(listing.text, str(listing.url), sel["product_link"])
        if not links:
            row["product"] = "(no product links)"
            return row

        page = await client.get(links[0])
        product = extract_product(page.text, str(page.url), name, sel)
        if product is None:
            row["product"] = "(no product parsed)"
            return row

        row["product"] = product.name[:34]
        row["img"] = len(json.loads(product.images)) if product.images else 0
        row["vid"] = len(json.loads(product.videos)) if product.videos else 0
        row["specs"] = len(json.loads(product.specs)) if product.specs else 0
        keys = list(json.loads(product.sections)) if product.sections else []
        row["sections"] = ",".join(keys)[:38]
        row["content"] = len(product.content or "")
    except Exception as exc:
        row["product"] = f"ERROR {type(exc).__name__}"
    return row


async def main() -> None:
    sites = [s for s in json.loads((ROOT / "sites.json").read_text("utf-8"))
             if s.get("enabled", True)]

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        rows = []
        for site in sites:
            rows.append(await one(client, site))
            await asyncio.sleep(1.5)

    head = f"{'SHOP':20} {'IMG':>4} {'VID':>4} {'SPEC':>5} {'CONTENT':>8}  SECTIONS"
    print(head)
    print("-" * len(head) + "-" * 20)
    for r in rows:
        print(f"{r['shop']:20} {r['img']:>4} {r['vid']:>4} {r['specs']:>5} "
              f"{r['content']:>8}  {r['sections'] or r['product']}")

    weak = [r["shop"] for r in rows if r["img"] == 0 and r["content"] == 0]
    if weak:
        print(f"\nyielding nothing rich: {', '.join(weak)}")


if __name__ == "__main__":
    asyncio.run(main())
