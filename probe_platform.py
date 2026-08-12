"""Dev helper: identify a shop's platform and URL patterns from its sitemap."""
import asyncio
import re
import sys
from collections import Counter

import httpx

UA = "FertilizerDataBot/1.0 (+research crawler)"


async def main(host: str) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(f"https://{host}/robots.txt")
        print(f"--- robots.txt HTTP {r.status_code} ---")
        for line in r.text.splitlines():
            if line.lower().startswith(("disallow", "sitemap", "crawl-delay", "user-agent")):
                print("  " + line.strip())
        print()

        maps = re.findall(r"(?i)sitemap:\s*(\S+)", r.text) or [f"https://{host}/sitemap.xml"]
        urls: set[str] = set()
        for m in maps[:3]:
            try:
                s = await c.get(m)
            except httpx.HTTPError as exc:
                print(f"  sitemap {m} failed: {exc}")
                continue
            locs = re.findall(r"<loc>(.*?)</loc>", s.text)
            for loc in locs[:60]:
                if loc.endswith(".xml"):
                    try:
                        sub = await c.get(loc)
                        urls.update(re.findall(r"<loc>(.*?)</loc>", sub.text))
                    except httpx.HTTPError:
                        pass
                else:
                    urls.add(loc)

        print(f"--- {len(urls)} URLs sampled; common path prefixes ---")
        segs = Counter()
        for u in urls:
            parts = [p for p in u.split(host, 1)[-1].split("/") if p]
            if parts:
                segs["/" + parts[0]] += 1
        for seg, n in segs.most_common(12):
            print(f"  {seg:34} {n}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
