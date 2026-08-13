"""Dev helper: survey what a product page carries beyond name and price.

Images, video embeds, spec tables and the headings that introduce the
agronomic content (composition, dosage, technology) all live in different
places per shop, so look before writing selectors.
"""
import asyncio
import re
import sys
from collections import Counter

import httpx
from selectolax.parser import HTMLParser

UA = "FertilizerDataBot/1.0 (+research crawler)"

TOPIC_WORDS = [
    "thành phần", "thanh phan", "hàm lượng", "công dụng", "cong dung",
    "cách dùng", "cach dung", "hướng dẫn", "huong dan", "liều lượng",
    "lieu luong", "công nghệ", "cong nghe", "quy cách", "quy cach",
    "xuất xứ", "xuat xu", "nhà sản xuất", "bảo quản", "lưu ý",
]


async def main(url: str) -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": UA}, timeout=30, follow_redirects=True
    ) as c:
        r = await c.get(url)
    tree = HTMLParser(r.text)
    print(f"{url}\nHTTP {r.status_code}, {len(r.text)} bytes\n")

    h1 = tree.css_first("h1")
    print("name:", h1.text(strip=True)[:70] if h1 else "?")

    # --- images ---------------------------------------------------------
    print("\n--- images ---")
    srcs: list[str] = []
    for img in tree.css("img"):
        a = img.attributes
        src = a.get("data-src") or a.get("data-lazy-src") or a.get("src") or ""
        if src and not src.startswith("data:"):
            srcs.append(src)
    print(f"  {len(srcs)} <img> tags, {len(set(srcs))} unique")
    for s in list(dict.fromkeys(srcs))[:5]:
        print("   ", s[:96])

    og = tree.css_first("meta[property='og:image']")
    if og:
        print("  og:image:", (og.attributes.get("content") or "")[:96])

    print("\n  container classes holding images:")
    holders: Counter = Counter()
    for img in tree.css("img"):
        p = img.parent
        for _ in range(3):
            if p is None:
                break
            cls = p.attributes.get("class") or ""
            if cls:
                holders["." + ".".join(cls.split()[:2])] += 1
                break
            p = p.parent
    for sel, n in holders.most_common(6):
        print(f"    {sel:44} {n}")

    # --- video ----------------------------------------------------------
    print("\n--- video ---")
    vids = []
    for f in tree.css("iframe"):
        s = f.attributes.get("src") or f.attributes.get("data-src") or ""
        if any(k in s for k in ("youtube", "youtu.be", "vimeo", "facebook")):
            vids.append(s)
    for v in tree.css("video source, video"):
        s = v.attributes.get("src") or ""
        if s:
            vids.append(s)
    yt = re.findall(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})", r.text)
    print(f"  {len(vids)} embeds, {len(set(yt))} youtube ids in raw html")
    for v in vids[:4]:
        print("   ", v[:96])
    if yt:
        print("  youtube ids:", ", ".join(sorted(set(yt))[:6]))

    # --- structured content --------------------------------------------
    print("\n--- tables ---")
    for i, t in enumerate(tree.css("table")[:3]):
        rows = t.css("tr")
        print(f"  table {i}: {len(rows)} rows")
        for tr in rows[:4]:
            cells = [" ".join(td.text(strip=True).split())[:30] for td in tr.css("td, th")]
            if cells:
                print("     ", " | ".join(cells))

    print("\n--- headings that look agronomic ---")
    for tag in ("h2", "h3", "h4", "strong", "b"):
        for n in tree.css(tag):
            txt = " ".join(n.text(strip=True).split())
            low = txt.lower()
            if txt and any(w in low for w in TOPIC_WORDS) and len(txt) < 90:
                print(f"  <{tag}> {txt[:80]}")

    print("\n--- long text blocks ---")
    for sel in (".rte", ".product-description", ".tab-content", ".product-summary",
                ".woocommerce-product-details__short-description", "#tab-description",
                ".product-content", ".entry-content"):
        n = tree.css_first(sel)
        if n:
            txt = " ".join(n.text(separator=" ", strip=True).split())
            print(f"  {sel:50} {len(txt):>6} chars")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
