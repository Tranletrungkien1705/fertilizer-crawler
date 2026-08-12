"""HTML -> Product extraction, driven by CSS selectors from sites.yaml."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .storage import Product

# "16-16-8", "20 - 20 - 15", "NPK 15:15:15", and en/em-dash variants that
# retailers produce when their editor auto-formats hyphens ("20 – 20 – 15").
NPK_RE = re.compile(
    r"\b(\d{1,2})\s*[-‐-―:.]\s*(\d{1,2})\s*[-‐-―:.]\s*(\d{1,2})\b"
)
# Vietnamese prices: "250.000 đ", "1,250,000₫", "250000 VND"
PRICE_RE = re.compile(r"(\d[\d.,]{2,})\s*(?:₫|đ|vnd|vnđ)", re.IGNORECASE)
UNIT_RE = re.compile(
    r"\b(?:bao|túi|chai|gói|kg|tấn|lít|ml|g)\s*\d*\s*(?:kg|g|lít|l|ml)?\b",
    re.IGNORECASE,
)
# Package weight: "50kg", "500 gr", "1 tấn". Solids only — liquids (ml/lit)
# are deliberately left out so price-per-kg never mixes the two.
WEIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|kilogram|gr|gam|gram|g|tấn|tan)\b",
    re.IGNORECASE,
)
TO_KG = {
    "kg": 1.0, "kilogram": 1.0,
    "g": 0.001, "gr": 0.001, "gam": 0.001, "gram": 0.001,
    "tấn": 1000.0, "tan": 1000.0,
}
# A weight inside a description counts only when a packaging word introduces
# it, which separates "Goi 100g" from dosage advice like "pha 5g / 1 lit".
PACK_CONTEXT_RE = re.compile(
    r"(?:gói|goi|bao|túi|tui|chai|hũ|hu|lọ|lo|hộp|hop|can|quy\s*cách|quy\s*cach"
    r"|khối\s*lượng|khoi\s*luong|trọng\s*lượng|trong\s*luong)"
    r"\s*:?\s*(?P<weight>\d+(?:[.,]\d+)?\s*(?:kg|kilogram|gr|gam|gram|g|tấn|tan)\b)",
    re.IGNORECASE,
)


def _text(node) -> str:
    return " ".join(node.text(separator=" ", strip=True).split()) if node else ""


def parse_price(raw: str) -> float | None:
    """Vietnamese sites use '.' as thousands separator: 250.000 -> 250000."""
    if not raw:
        return None
    m = PRICE_RE.search(raw)
    candidate = m.group(1) if m else raw.strip()

    digits = re.sub(r"[^\d.,]", "", candidate)
    if not digits:
        return None

    # Strip separators; the last group decides whether it was a decimal point.
    normalized = digits.replace(".", "").replace(",", "")
    try:
        value = float(normalized)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_npk(text: str) -> str | None:
    m = NPK_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_unit(text: str) -> str | None:
    m = UNIT_RE.search(text or "")
    return m.group(0).strip() if m else None


def _to_kg(match: re.Match) -> float | None:
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    kg = amount * TO_KG[match.group(2).lower()]
    # Guard against nonsense pulled out of marketing copy.
    return kg if 0.005 <= kg <= 2000 else None


def parse_pack_kg(name: str, description: str | None = None) -> float | None:
    """Package weight in kg, so prices across pack sizes stay comparable.

    The name is the trustworthy source: retailers put the pack size there
    ("Bao 50kg", "(1kg)"). Descriptions are marketing copy where the first
    weight-shaped number is usually a *dosage* ("pha 5g cho 1 lit nuoc"), and
    reading that as a package size silently wrecks every price-per-kg figure.
    So the description is consulted only right after a packaging word.

    Variable products list the smallest pack first ("2kg-5kg-10kg") and their
    price element leads with the matching lowest price, so taking the first
    match on both sides keeps weight and price consistent.
    """
    m = WEIGHT_RE.search(name or "")
    if m:
        return _to_kg(m)

    if description:
        m = PACK_CONTEXT_RE.search(description)
        if m:
            inner = WEIGHT_RE.search(m.group("weight"))
            if inner:
                return _to_kg(inner)
    return None


def extract_links(html: str, base_url: str, selector: str) -> list[str]:
    """Collect absolute product-detail URLs from a listing page.

    Anything that does not resolve to a plain http(s) URL with a host is
    dropped here rather than downstream: across many unfamiliar shops the
    markup throws up "tel:", bare fragments and malformed hrefs.
    """
    tree = HTMLParser(html)
    seen: dict[str, None] = {}
    for node in tree.css(selector):
        href = node.attributes.get("href")
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href.strip())
        parts = urlparse(absolute)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            continue
        seen.setdefault(absolute, None)
    return list(seen)


def extract_product(html: str, url: str, source: str, sel: dict) -> Product | None:
    """Build a Product from a detail page. Returns None when no name is found."""
    tree = HTMLParser(html)

    def pick(key: str) -> str:
        css = sel.get(key)
        return _text(tree.css_first(css)) if css else ""

    name = pick("name")
    if not name:
        return None

    price_text = pick("price")
    description = pick("description")
    haystack = f"{name} {description}"

    return Product(
        source=source,
        url=url,
        name=name,
        price=parse_price(price_text),
        unit=parse_unit(haystack),
        pack_kg=parse_pack_kg(name, description),
        brand=pick("brand") or None,
        category=pick("category") or None,
        npk=parse_npk(haystack),
        description=description[:2000] or None,
    )
