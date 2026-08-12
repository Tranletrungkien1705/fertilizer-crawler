"""Dev helper: check robots.txt and probe CSS selectors on a real page."""
import asyncio
import sys

import httpx
from selectolax.parser import HTMLParser

UA = "FertilizerDataBot/1.0 (+research crawler)"


async def main(url: str) -> None:
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=25, follow_redirects=True
    ) as c:
        r = await c.get(f"https://{host}/robots.txt")
        print(f"--- robots.txt ({r.status_code}) ---")
        print(r.text[:1200] if r.status_code == 200 else "(none)")

        r = await c.get(url)
        print(f"\n--- page {url} -> HTTP {r.status_code}, {len(r.text)} bytes ---")
        tree = HTMLParser(r.text)

        title = tree.css_first("title")
        print("title:", title.text(strip=True) if title else "?")

        print("\n--- candidate product links ---")
        for sel in ["a.product-item__link", ".product-item a", "a[href*='/products/']",
                    ".product-block a", "h3 a", ".card a",
                    # WooCommerce
                    "li.product a.woocommerce-LoopProduct-link",
                    "ul.products li.product a", ".product-small a", "a.woocommerce-loop-product__link"]:
            found = tree.css(sel)
            if found:
                print(f"  {sel:32} -> {len(found)} hits | e.g. {found[0].attributes.get('href')}")

        print("\n--- candidate name/price selectors ---")
        for sel in ["h1", ".product-title", ".product__title", ".price",
                    ".product-price", ".price-box", "[itemprop='price']",
                    ".product-single__price",
                    # WooCommerce
                    "p.price", ".summary .price", ".woocommerce-Price-amount",
                    "h1.product_title", ".woocommerce-product-details__short-description"]:
            n = tree.css_first(sel)
            if n:
                txt = " ".join(n.text(separator=" ", strip=True).split())[:80]
                print(f"  {sel:28} -> {txt!r}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
