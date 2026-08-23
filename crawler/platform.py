"""Read a product from the shop's own JSON instead of its rendered page.

Most Vietnamese shops run on Haravan, Shopify or WooCommerce, and all three
publish the product as JSON next to the page it renders. That payload holds
what HTML cannot give reliably — SKU, vendor, per-variant price, stock counts,
ratings — and it holds it in the same shape for every shop on that platform.

So the ladder is: platform JSON, then JSON-LD embedded in the page, then CSS
selectors. Each rung down loses fields and gains guesswork. A browser is the
rung below all of them and is not needed for any shop crawled so far.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

HARAVAN = "haravan"      # also Shopify: same product .js contract
SAPO = "sapo"            # same .js contract, but prices are not minor units
WOOCOMMERCE = "woocommerce"
JSONLD = "jsonld"
HTML = "html"

# Haravan and Shopify quote money in minor units regardless of currency, so a
# VND price arrives multiplied by 100. Sapo serves the same endpoint shape but
# quotes plain VND, and treating the two alike divides its prices by a hundred
# — 126.000 becomes 1.260 and every comparison built on it is wrong.
PRICE_MINOR = {HARAVAN: 100, SAPO: 1}


def detect(html: str) -> str:
    """Guess the platform from fingerprints in the page."""
    # Sapo first: it also answers on /<handle>.js, so a looser Haravan test
    # would swallow it.
    if re.search(r"bizweb\.dktcdn|sapo\.vn|sapoapp", html, re.I):
        return SAPO
    if re.search(r"haravan|hstatic\.net", html, re.I):
        return HARAVAN
    if re.search(r"cdn\.shopify\.com|shopify\.theme", html, re.I):
        return HARAVAN
    if re.search(r"woocommerce|wp-content/plugins/woocommerce", html, re.I):
        return WOOCOMMERCE
    if re.search(r'"@type"\s*:\s*"Product"', html):
        return JSONLD
    return HTML


def _money(value: Any, minor: int = 1) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    amount = amount / minor
    return amount if amount > 0 else None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;|&#\d+;", " ", text)
    return " ".join(text.split()) or None


# --------------------------------------------------------------------------
# Haravan / Shopify
# --------------------------------------------------------------------------

def haravan_url(product_url: str) -> str:
    return product_url.split("?")[0].rstrip("/") + ".js"


def parse_haravan(payload: dict, base_url: str, minor: int = 100) -> dict:
    variants = []
    stock = 0
    counted = False
    for v in payload.get("variants") or []:
        qty = v.get("inventory_quantity")
        if isinstance(qty, int):
            # Shops let this go negative on oversold lines; clamp so a single
            # oversold variant cannot report the product as negative stock.
            stock += max(qty, 0)
            counted = True
        variants.append({
            "title": v.get("title"),
            "sku": v.get("sku") or None,
            "price": _money(v.get("price"), minor),
            "compare_at": _money(v.get("compare_at_price"), minor),
            "available": v.get("available"),
            "stock": qty,
        })

    images = [urljoin(base_url, i) for i in (payload.get("images") or [])
              if isinstance(i, str)]

    first_sku = next((v["sku"] for v in variants if v.get("sku")), None)

    return {
        "name": _clean(payload.get("title")),
        "price": _money(payload.get("price"), minor),
        "price_min": _money(payload.get("price_min"), minor),
        "price_max": _money(payload.get("price_max"), minor),
        "sku": first_sku,
        "vendor": _clean(payload.get("vendor")),
        "product_type": _clean(payload.get("type")),
        "tags": payload.get("tags") or [],
        "in_stock": payload.get("available"),
        "stock_qty": stock if counted else None,
        "rating": None,
        "review_count": None,
        "variants": variants,
        "images": images,
        "content_html": payload.get("content") or payload.get("description"),
    }


# --------------------------------------------------------------------------
# WooCommerce Store API
# --------------------------------------------------------------------------

def woo_url(product_url: str) -> str:
    parts = urlparse(product_url)
    slug = parts.path.rstrip("/").split("/")[-1]
    return f"{parts.scheme}://{parts.netloc}/wp-json/wc/store/v1/products?slug={slug}"


def woo_reviews_url(product_url: str, product_id: int) -> str:
    parts = urlparse(product_url)
    return (f"{parts.scheme}://{parts.netloc}/wp-json/wc/store/v1/products/reviews"
            f"?product_id={product_id}&per_page=10")


def parse_woo(payload: dict) -> dict:
    prices = payload.get("prices") or {}
    # WooCommerce states its own decimal places; VND uses 0, USD would use 2.
    minor = 10 ** int(prices.get("currency_minor_unit") or 0)

    price_range = prices.get("price_range") or {}
    variants = []
    for var in payload.get("variations") or []:
        attrs = var.get("attributes") or []
        variants.append({
            "title": " / ".join(str(a.get("value")) for a in attrs) or None,
            "sku": None,
            "price": None,   # the Store API lists ids, not prices, per variation
            "id": var.get("id"),
            "available": None,
            "stock": None,
        })

    categories = [c.get("name") for c in (payload.get("categories") or [])]
    brands = [b.get("name") for b in (payload.get("brands") or [])]

    return {
        "name": _clean(payload.get("name")),
        "price": _money(prices.get("price"), minor),
        "price_min": _money(price_range.get("min_amount"), minor),
        "price_max": _money(price_range.get("max_amount"), minor),
        "sku": payload.get("sku") or None,
        "vendor": _clean(brands[0]) if brands else None,
        "product_type": _clean(categories[0]) if categories else None,
        "tags": [t.get("name") for t in (payload.get("tags") or [])],
        "in_stock": payload.get("is_in_stock"),
        "stock_qty": payload.get("low_stock_remaining"),
        "rating": float(payload["average_rating"]) if payload.get("average_rating") else None,
        "review_count": payload.get("review_count") or 0,
        "variants": variants,
        "images": [i.get("src") for i in (payload.get("images") or []) if i.get("src")],
        "content_html": payload.get("description") or payload.get("short_description"),
        "_id": payload.get("id"),
    }


def parse_woo_reviews(payload: list) -> list[dict]:
    out = []
    for r in payload or []:
        out.append({
            "author": _clean(r.get("reviewer")),
            "rating": r.get("rating"),
            "date": r.get("date_created"),
            "text": _clean(r.get("review")),
        })
    return out


# --------------------------------------------------------------------------
# JSON-LD embedded in the page
# --------------------------------------------------------------------------

LD_BLOCK = re.compile(
    r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I
)


def parse_jsonld(html: str) -> dict | None:
    for block in LD_BLOCK.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else data
        if not isinstance(candidates, list):
            candidates = [candidates]
        for item in candidates:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            rating = item.get("aggregateRating") or {}
            images = item.get("image")
            if isinstance(images, str):
                images = [images]
            availability = str(offers.get("availability") or "")
            return {
                "name": _clean(item.get("name")),
                "price": _money(offers.get("price")),
                "price_min": None,
                "price_max": None,
                "sku": item.get("sku") or None,
                "vendor": _clean((item.get("brand") or {}).get("name")
                                 if isinstance(item.get("brand"), dict)
                                 else item.get("brand")),
                "product_type": _clean(item.get("category")),
                "tags": [],
                "in_stock": ("InStock" in availability) if availability else None,
                "stock_qty": None,
                "rating": _money(rating.get("ratingValue")),
                "review_count": int(rating["reviewCount"]) if rating.get("reviewCount") else None,
                "variants": [],
                "images": [i for i in (images or []) if isinstance(i, str)],
                "content_html": item.get("description"),
            }
    return None
