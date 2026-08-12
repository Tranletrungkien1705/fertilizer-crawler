"""Dev helper: list a site's collection URLs from its sitemap."""
import asyncio
import re
import sys

import httpx

UA = "FertilizerDataBot/1.0 (+research crawler)"
KEYWORDS = ("phan", "npk", "huu-co", "vi-sinh", "bon", "dam", "lan", "kali")


async def main(host: str) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        root = await c.get(f"https://{host}/sitemap.xml")
        subs = re.findall(r"<loc>(.*?)</loc>", root.text)
        col_maps = [u for u in subs if "collection" in u] or subs[:4]

        urls: set[str] = set()
        for m in col_maps:
            r = await c.get(m)
            urls.update(
                u for u in re.findall(r"<loc>(.*?)</loc>", r.text)
                if "/collections/" in u
            )

        hits = sorted(u for u in urls if any(k in u.lower() for k in KEYWORDS))
        print(f"{len(urls)} collections total, {len(hits)} fertilizer-related:\n")
        for u in hits:
            print(" ", u)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
