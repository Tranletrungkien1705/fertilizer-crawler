"""Dev helper: run the rich extractors against a live page and show results."""
import asyncio
import json
import sys

import httpx
from selectolax.parser import HTMLParser

from crawler.rich import (
    extract_content,
    extract_images,
    extract_sections,
    extract_specs,
    extract_videos,
)

UA = "FertilizerDataBot/1.0 (+research crawler)"

DESCRIPTION_SELECTORS = [
    "#tab-description", ".product-content", ".rte", ".entry-content",
    ".woocommerce-Tabs-panel--description", ".product-description",
]


async def main(url: str, gallery: str | None = None) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(url)
    tree = HTMLParser(r.text)

    print(f"{url}\n")
    h1 = tree.css_first("h1")
    print("name  :", _short(h1.text(strip=True) if h1 else "?", 66))

    images = extract_images(tree, url, gallery)
    print(f"\nimages: {len(images)}")
    for i in images[:6]:
        print("   ", i[:100])

    videos = extract_videos(tree, r.text)
    print(f"\nvideos: {len(videos)}")
    for v in videos:
        print("   ", v[:100])

    specs = extract_specs(tree)
    print(f"\nspecs : {len(specs)}")
    for k, v in list(specs.items())[:8]:
        print(f"    {k:16} {_short(v, 62)}")

    container = None
    for sel in DESCRIPTION_SELECTORS:
        container = tree.css_first(sel)
        if container is not None:
            print(f"\ndescription container: {sel}")
            break

    sections = extract_sections(container)
    print(f"sections: {len(sections)}")
    for k, v in sections.items():
        print(f"    {k:16} {len(v):>5} chars  {_short(v, 50)}")

    content = extract_content(container)
    print(f"\ncontent: {len(content)} chars")
    print("   ", _short(content, 140))

    print("\n--- as stored (json) ---")
    print(json.dumps({"images": len(images), "videos": len(videos),
                      "specs": list(specs), "sections": list(sections)},
                     ensure_ascii=False))


def _short(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("..." if len(text) > n else "")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
