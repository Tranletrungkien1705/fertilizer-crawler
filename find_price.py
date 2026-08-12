"""Dev helper: locate which element actually holds the price on a page.

Scans for currency-looking text and reports the tag/class path, so a new
site's price selector can be read off instead of guessed.
"""
import asyncio
import re
import sys

import httpx
from selectolax.parser import HTMLParser

UA = "FertilizerDataBot/1.0 (+research crawler)"
MONEY = re.compile(r"\d[\d.,]{3,}\s*(?:₫|đ|VND|vnđ)", re.IGNORECASE)


def describe(node) -> str:
    tag = node.tag
    cls = node.attributes.get("class") or ""
    idv = node.attributes.get("id") or ""
    sel = tag
    if idv:
        sel += f"#{idv}"
    if cls:
        sel += "." + ".".join(cls.split()[:3])
    return sel


async def main(url: str) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(url)
    print(f"{url} -> HTTP {r.status_code}, {len(r.text)} bytes\n")

    tree = HTMLParser(r.text)
    h1 = tree.css_first("h1")
    print("h1:", h1.text(strip=True) if h1 else "(none)")

    print("\n--- elements whose own text looks like money ---")
    seen: set[str] = set()
    for node in tree.css("*"):
        text = " ".join(node.text(deep=False, separator=" ", strip=True).split())
        if not text or not MONEY.search(text):
            continue
        path = []
        cur = node
        for _ in range(3):
            if cur is None or cur.tag == "html":
                break
            path.append(describe(cur))
            cur = cur.parent
        key = " < ".join(path)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {text[:34]:36} {key}")
        if len(seen) >= 12:
            break

    if not seen:
        print("  (none found - price is probably rendered by JavaScript)")
        for meta in tree.css("meta[property*='price'], meta[itemprop*='price']"):
            print("  meta:", meta.attributes)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
