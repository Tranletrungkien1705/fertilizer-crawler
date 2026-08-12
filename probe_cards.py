"""Dev helper: find the product-card link selector on a listing page.

Needed for shops with flat product URLs, where 'a[href*=/products/]' has
nothing to match on. Walks up from each price to the enclosing link and
reports which container classes repeat.
"""
import asyncio
import re
import sys
from collections import Counter

import httpx
from selectolax.parser import HTMLParser

UA = "FertilizerDataBot/1.0 (+research crawler)"
MONEY = re.compile(r"\d[\d.,]{3,}\s*(?:₫|đ|VND)", re.IGNORECASE)


async def main(url: str) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(url)
    tree = HTMLParser(r.text)
    print(f"{url} -> HTTP {r.status_code}\n")

    containers: Counter = Counter()
    link_classes: Counter = Counter()
    samples: dict[str, str] = {}

    for node in tree.css("*"):
        text = " ".join(node.text(deep=False, separator=" ", strip=True).split())
        if not text or not MONEY.search(text):
            continue
        # Climb to the nearest ancestor that wraps a real product link.
        cur = node
        for _ in range(6):
            cur = cur.parent
            if cur is None:
                break
            cls = cur.attributes.get("class") or ""
            if not cls:
                continue
            link = cur.css_first("a[href]")
            if link is None:
                continue
            href = link.attributes.get("href", "")
            if not href or href.startswith(("#", "javascript:")):
                continue
            key = "." + ".".join(cls.split()[:2])
            containers[key] += 1
            lc = link.attributes.get("class") or ""
            link_classes["a." + ".".join(lc.split()[:2]) if lc else "a"] += 1
            samples.setdefault(key, href)
            break

    print("--- containers wrapping a price + link ---")
    for sel, n in containers.most_common(8):
        print(f"  {sel:44} {n:3}  e.g. {samples[sel][:46]}")

    print("\n--- link classes inside them ---")
    for sel, n in link_classes.most_common(6):
        print(f"  {sel:44} {n}")

    if containers:
        best = containers.most_common(1)[0][0]
        print(f"\nsuggested product_link selector:  {best} a")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
