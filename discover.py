"""Auto-onboard a shop: work out its selectors and emit a sites.json entry.

Hand-probing a site takes half a dozen steps, which does not scale past a
handful of shops. This runs the same checks automatically and refuses any
site whose prices are not public, so the catalogue only grows with sources
that are actually usable.

    python discover.py nongnghiepshop.vn            # inspect one shop
    python discover.py --file candidates.txt        # inspect a list
    python discover.py --file candidates.txt --write  # append passing ones
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from crawler.extract import extract_links, parse_price

ROOT = Path(__file__).resolve().parent
SITES_FILE = ROOT / "sites.json"
UA = "FertilizerDataBot/1.0 (+research crawler; contact: kientlt59@gmail.com)"

MONEY = re.compile(r"\d[\d.,]{3,}\s*(?:₫|đ|VND)", re.IGNORECASE)

# Category slugs worth crawling, across agricultural retail generally.
CATEGORY_HINTS = (
    "phan", "npk", "huu-co", "vi-sinh", "vo-co", "dinh-duong", "hat-giong",
    "giong", "thuoc", "bvtv", "vat-tu", "gia-the", "dat-trong", "che-pham",
    "nong", "trun-que", "kali", "dam", "lan",
)
# Slugs that are never product categories.
CATEGORY_BLOCK = ("blog", "tin-tuc", "news", "gioi-thieu", "lien-he", "chinh-sach")

LINK_SELECTORS = (
    "a[href*='/products/']",
    "a[href*='/san-pham/']",
    "a[href*='/product/']",
    "a.product-name",
    "a.woocommerce-loop-product__link",
    "a.product-item__link",
)
PRICE_SELECTORS = (
    ".product-price", ".price-box", "p.price", ".woocommerce-Price-amount",
    ".product__price", ".product-single__price", ".summary .price", ".price",
)
NAME_SELECTORS = ("h1.product_title", "h1.product-title", "h1", ".product-title")
DESC_SELECTORS = (
    ".product-summary", ".woocommerce-product-details__short-description",
    ".product-description", ".short-description", ".rte", ".product-detail",
)


def text_of(node) -> str:
    return " ".join(node.text(separator=" ", strip=True).split()) if node else ""


class Client:
    def __init__(self) -> None:
        self.c = httpx.AsyncClient(
            headers={"User-Agent": UA}, timeout=25, follow_redirects=True
        )

    async def get(self, url: str) -> httpx.Response | None:
        try:
            r = await self.c.get(url)
            return r if r.status_code == 200 else None
        except httpx.HTTPError:
            return None

    async def close(self) -> None:
        await self.c.aclose()


async def sitemap_urls(cl: Client, host: str) -> list[str]:
    """Every URL reachable from the sitemap index, one level deep."""
    robots = await cl.get(f"https://{host}/robots.txt")
    maps = re.findall(r"(?i)sitemap:\s*(\S+)", robots.text) if robots else []
    if not maps:
        maps = [f"https://{host}/sitemap.xml", f"https://{host}/sitemap_index.xml"]

    urls: list[str] = []
    for m in maps[:2]:
        r = await cl.get(m)
        if not r:
            continue
        locs = re.findall(r"<loc>(.*?)</loc>", r.text)
        subs = [u for u in locs if u.endswith(".xml")]
        if subs:
            for s in subs[:8]:
                rs = await cl.get(s)
                if rs:
                    urls += re.findall(r"<loc>(.*?)</loc>", rs.text)
        else:
            urls += locs
        if len(urls) > 6000:
            break
    return urls


def pick_categories(urls: list[str], host: str) -> list[str]:
    cats: list[str] = []
    seen: set[str] = set()
    for u in dict.fromkeys(urls):  # sitemaps overlap; keep first occurrence
        if u in seen:
            continue
        seen.add(u)
        path = urlparse(u).path.lower().strip("/")
        if not path or any(b in path for b in CATEGORY_BLOCK):
            continue
        depth = path.count("/")
        looks_like_cat = "/collections/" in u or "/danh-muc/" in u or depth == 0
        if looks_like_cat and any(k in path for k in CATEGORY_HINTS):
            cats.append(u)
    # Shorter slugs are broader categories; prefer them.
    cats.sort(key=lambda u: (len(urlparse(u).path), u))
    return cats[:12]


async def detect_links(cl: Client, cat_url: str) -> tuple[str | None, list[str]]:
    r = await cl.get(cat_url)
    if not r:
        return None, []

    best_sel, best_links = None, []
    for sel in LINK_SELECTORS:
        links = [u for u in extract_links(r.text, cat_url, sel)
                 if urlparse(u).path.strip("/")]
        if len(links) > len(best_links):
            best_sel, best_links = sel, links

    if len(best_links) >= 4:
        return best_sel, best_links

    # Flat product URLs: find the card class that wraps a price and a link.
    tree = HTMLParser(r.text)
    containers: Counter = Counter()
    for node in tree.css("*"):
        own = " ".join(node.text(deep=False, separator=" ", strip=True).split())
        if not own or not MONEY.search(own):
            continue
        cur = node
        for _ in range(6):
            cur = cur.parent
            if cur is None:
                break
            cls = cur.attributes.get("class") or ""
            link = cur.css_first("a[href]") if cls else None
            if link is None:
                continue
            href = link.attributes.get("href", "")
            if not href or href.startswith(("#", "javascript:")):
                continue
            lc = link.attributes.get("class") or ""
            containers["a." + lc.split()[0] if lc else "." + cls.split()[0] + " a"] += 1
            break

    for sel, _ in containers.most_common(3):
        links = [u for u in extract_links(r.text, cat_url, sel)
                 if urlparse(u).path.strip("/")]
        if len(links) > len(best_links):
            best_sel, best_links = sel, links

    return best_sel, best_links


async def detect_product_selectors(cl: Client, product_urls: list[str]) -> dict | None:
    """Try candidate selectors on real product pages and keep what works."""
    pages = []
    for url in product_urls[:4]:
        r = await cl.get(url)
        if r:
            pages.append((url, HTMLParser(r.text)))
        await asyncio.sleep(1.2)
    if len(pages) < 2:
        return None

    # A name selector must produce different text on different products,
    # otherwise it is picking up the site title.
    name_sel = None
    for sel in NAME_SELECTORS:
        values = {text_of(t.css_first(sel)) for _, t in pages}
        if len(values) == len(pages) and all(2 < len(v) < 200 for v in values):
            name_sel = sel
            break
    if not name_sel:
        return None

    price_sel, priced = None, 0
    for sel in PRICE_SELECTORS:
        hits = sum(1 for _, t in pages if parse_price(text_of(t.css_first(sel))))
        if hits > priced:
            price_sel, priced = sel, hits
    if not price_sel or priced < len(pages) * 0.6:
        return None

    desc_sel = None
    for sel in DESC_SELECTORS:
        if sum(1 for _, t in pages if len(text_of(t.css_first(sel))) > 25) >= 2:
            desc_sel = sel
            break

    return {
        "name": name_sel,
        "price": price_sel,
        "description": desc_sel,
        "priced_ratio": priced / len(pages),
    }


async def discover(host: str) -> dict | None:
    cl = Client()
    try:
        host = host.strip().lower().replace("https://", "").replace("http://", "").strip("/")
        print(f"\n=== {host} ===")

        urls = await sitemap_urls(cl, host)
        if not urls:
            print("  no sitemap - skipped")
            return None

        cats = pick_categories(urls, host)
        if not cats:
            print(f"  {len(urls)} urls, but no agricultural category found - skipped")
            return None
        print(f"  {len(urls)} urls, {len(cats)} candidate categories")

        for cat in cats[:4]:
            link_sel, links = await detect_links(cl, cat)
            if not link_sel or len(links) < 4:
                continue
            print(f"  category {cat}")
            print(f"    links: {link_sel} -> {len(links)}")

            sels = await detect_product_selectors(cl, links)
            if not sels:
                print("    could not read name/price - trying next category")
                continue

            print(f"    name={sels['name']}  price={sels['price']}  "
                  f"desc={sels['description']}  priced={sels['priced_ratio']:.0%}")

            # Confirm the other candidates really are listings. On shops with
            # flat URLs a product page looks just like a category by its path,
            # and crawling those wastes requests for nothing.
            confirmed = [cat]
            for other in cats:
                if other == cat or len(confirmed) >= 6:
                    continue
                _, other_links = await detect_links(cl, other)
                if len(other_links) >= 4:
                    confirmed.append(other)
                await asyncio.sleep(1.2)
            print(f"    categories confirmed: {len(confirmed)}/{len(cats)}")

            return {
                "name": host.split(".")[0].replace("-", ""),
                "enabled": True,
                "note": f"auto-discovered from {cat}",
                "list_urls": confirmed,
                "selectors": {
                    "product_link": link_sel,
                    "name": sels["name"],
                    "price": sels["price"],
                    "description": sels["description"],
                    "brand": None,
                    "category": None,
                },
            }

        print("  no usable category - skipped (prices probably not public)")
        return None
    finally:
        await cl.close()


async def run(hosts: list[str], write: bool, force: bool = False) -> None:
    existing = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    known = {s["name"] for s in existing}
    known_hosts = {urlparse(u).netloc.replace("www.", "")
                   for s in existing for u in s["list_urls"]}

    found = []
    considered = 0
    for host in hosts:
        clean = host.strip().lower().replace("https://", "").replace("www.", "").strip("/")
        if not clean or clean.startswith("#"):
            continue
        considered += 1
        if clean in known_hosts and not force:
            print(f"\n=== {clean} ===\n  already in sites.json - skipped")
            continue
        entry = await discover(clean)
        if entry and entry["name"] not in known:
            found.append(entry)
            known.add(entry["name"])

    print(f"\n{len(found)} of {considered} shops usable")
    for e in found:
        print(f"  + {e['name']:20} {len(e['list_urls'])} categories")

    if write and found:
        SITES_FILE.write_text(
            json.dumps(existing + found, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nappended {len(found)} entries to sites.json")
    elif found:
        print("\n(re-run with --write to add them to sites.json)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("hosts", nargs="*", help="shop domains")
    ap.add_argument("--file", help="file with one domain per line")
    ap.add_argument("--write", action="store_true", help="append to sites.json")
    ap.add_argument("--force", action="store_true",
                    help="re-inspect shops already in sites.json (validation)")
    args = ap.parse_args()

    hosts = list(args.hosts)
    if args.file:
        hosts += Path(args.file).read_text(encoding="utf-8").splitlines()
    if not hosts:
        ap.error("give at least one domain, or --file")

    asyncio.run(run(hosts, args.write, args.force))


if __name__ == "__main__":
    main()
