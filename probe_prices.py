"""Dev helper: how many products on a site actually publish a price?

Worth running before adding a site for price comparison — some Vietnamese
suppliers hide prices behind "vui long lien he".
"""
import asyncio
import sys

import httpx
from selectolax.parser import HTMLParser

from crawler.extract import extract_links, parse_price

UA = "FertilizerDataBot/1.0 (+research crawler)"


async def main(
    list_url: str,
    price_sel: str,
    link_sel: str = "a[href*='/products/']",
    sample: int = 8,
) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=25, follow_redirects=True
    ) as c:
        r = await c.get(list_url)
        links = extract_links(r.text, list_url, link_sel)[:sample]
        print(f"probing {len(links)} products from {list_url}\n")

        priced = 0
        for url in links:
            p = await c.get(url)
            tree = HTMLParser(p.text)
            name_node = tree.css_first("h1")
            name = name_node.text(strip=True)[:44] if name_node else "?"
            node = tree.css_first(price_sel)
            raw = " ".join(node.text(separator=" ", strip=True).split()) if node else ""
            value = parse_price(raw)
            if value:
                priced += 1
            print(f"  {name:46} {raw[:30]:32} -> {value or 'NO PRICE'}")
            await asyncio.sleep(1.5)

        print(f"\n{priced}/{len(links)} products have a usable price")


if __name__ == "__main__":
    # usage: probe_prices.py <list_url> <price_selector> [link_selector]
    asyncio.run(main(*sys.argv[1:4]))
