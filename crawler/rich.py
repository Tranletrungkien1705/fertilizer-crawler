"""Pull the substance off a product page: photos, video, spec tables and the
agronomic write-up (composition, dosage, technology, cautions).

Shops differ in markup but agree on vocabulary — every Vietnamese fertilizer
listing labels its sections "Thanh phan", "Cong dung", "Huong dan su dung".
So headings are matched on words rather than on CSS, which keeps one
extractor working across Haravan, WooCommerce and the hand-rolled shops.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser, Node

MAX_IMAGES = 12
MAX_CONTENT = 20_000

# Chrome, not merchandise: logos, payment badges, social buttons, tracking
# pixels and theme furniture all arrive as <img> alongside the real photos.
IMAGE_NOISE = re.compile(
    r"(facebook\.com/tr|//theme[s.]|/themes?/|logo|icon|banner|placeholder|"
    r"avatar|zalo|shopee|lazada|tiktok|youtube|spinner|loading|blank|pixel|"
    r"payment|bocongthuong|dmca|certificate|badge|flag|policy|"
    r"bao[-_]gia|gia[-_]si|khuyen[-_]mai|freeship)",
    re.IGNORECASE,
)
# The same photo is served at many sizes: WooCommerce appends -300x300, the
# Haravan/Shopify CDNs append _grande, _large and friends. Both must collapse
# to one key or a gallery of four photos is stored as twelve.
SIZE_SUFFIX = re.compile(
    r"(?:[-_]\d{2,4}x\d{2,4}"
    r"|_(?:grande|large|medium|small|compact|thumb|icon|master|original|pico|"
    r"mini|1024x1024|2048x2048))"
    r"(?=\.[a-z]{3,4}$)",
    re.IGNORECASE,
)
YOUTUBE_ID = re.compile(
    r"(?:youtube\.com/(?:embed/|watch\?v=|v/)|youtu\.be/)([\w-]{11})"
)

HEADING_TAGS = ("h2", "h3", "h4", "h5", "strong", "b")

# Section label -> the words that introduce it. Order matters: the first
# pattern that matches a heading wins, so put the specific ones first.
SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("thanh_phan", re.compile(r"thành phần|thanh phan|hàm lượng|ham luong|nguyên liệu", re.I)),
    ("cong_dung", re.compile(r"công dụng|cong dung|tác dụng|tac dung|lợi ích|đặc điểm|dac diem", re.I)),
    ("huong_dan", re.compile(r"hướng dẫn|huong dan|cách dùng|cach dung|cách sử dụng|sử dụng", re.I)),
    ("lieu_luong", re.compile(r"liều lượng|lieu luong|định mức|dinh muc|tỷ lệ pha|pha loãng", re.I)),
    ("cong_nghe", re.compile(r"công nghệ|cong nghe|quy trình sản xuất|cơ chế", re.I)),
    ("doi_tuong", re.compile(r"đối tượng|doi tuong|cây trồng|dùng cho|chuyên dùng", re.I)),
    ("bao_quan", re.compile(r"bảo quản|bao quan|hạn sử dụng|han su dung", re.I)),
    ("luu_y", re.compile(r"lưu ý|luu y|chú ý|cảnh báo|khuyến cáo", re.I)),
    ("quy_cach", re.compile(r"quy cách|quy cach|đóng gói|khối lượng tịnh|trọng lượng", re.I)),
    ("xuat_xu", re.compile(r"xuất xứ|xuat xu|nhà sản xuất|nhập khẩu|thương hiệu|hãng", re.I)),
]

# Spec tables use these row labels; map them to the same keys as the sections
# so a value found either way lands in one place.
SPEC_KEYS: list[tuple[str, re.Pattern]] = [
    ("thanh_phan", re.compile(r"thành phần|hàm lượng|nguyên liệu", re.I)),
    ("xuat_xu", re.compile(r"xuất xứ|nhà sản xuất|thương hiệu|hãng|nơi sản xuất", re.I)),
    ("quy_cach", re.compile(r"quy cách|đóng gói|khối lượng|trọng lượng|dung tích", re.I)),
    ("doi_tuong", re.compile(r"đối tượng|cây trồng|dùng cho", re.I)),
    ("cong_dung", re.compile(r"công dụng|tác dụng", re.I)),
]


ACCENTS = str.maketrans(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữựỳýỷỹỵđ",
    "a" * 17 + "e" * 11 + "i" * 5 + "o" * 17 + "u" * 11 + "y" * 5 + "d",
)


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(separator=" ", strip=True).split())


def _slug(label: str) -> str:
    """ASCII key for an unrecognised label.

    Stripping accents first matters: without it every Vietnamese vowel is
    dropped and "Thong so" collapses to "th_ng_s".
    """
    plain = label.lower().translate(ACCENTS)
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:40]


def _normalise_key(url: str) -> str:
    """Collapse WooCommerce size variants so one photo counts once."""
    return SIZE_SUFFIX.sub("", url.split("?")[0])


def extract_images(tree: HTMLParser, base_url: str, gallery_sel: str | None = None) -> list[str]:
    """Product photos, biggest-first where the shop offers several sizes."""
    candidates: list[str] = []

    og = tree.css_first("meta[property='og:image']")
    if og:
        content = og.attributes.get("content") or ""
        if content:
            candidates.append(content)

    if gallery_sel:
        scopes = tree.css(gallery_sel)
        # A product with a single photo has no slider to select, and widening
        # the search to the whole page then sweeps up "related products" -
        # that is how a seed packet ends up filed under a fertilizer. When the
        # declared gallery is absent, og:image alone is the honest answer.
        nodes = [img for scope in scopes for img in scope.css("img")]
    else:
        nodes = tree.css("img")

    for img in nodes:
        a = img.attributes
        # Lazy-loading shops leave src as a placeholder and hide the real URL.
        src = (a.get("data-large_image") or a.get("data-zoom-image")
               or a.get("data-src") or a.get("data-lazy-src")
               or a.get("data-original") or a.get("src") or "")
        if src:
            candidates.append(src)

    out: dict[str, str] = {}
    for src in candidates:
        if not src or src.startswith("data:"):
            continue
        url = urljoin(base_url, src.strip())
        if not url.startswith("http"):
            continue
        if IMAGE_NOISE.search(url):
            continue
        if not re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I):
            continue
        out.setdefault(_normalise_key(url), url)

    urls = list(out.values())
    # Shops that serve merchandise from a dedicated product path also drop
    # promo artwork into the page. When both are present, the product path is
    # the trustworthy one.
    on_product_path = [u for u in urls if "/product" in urlparse(u).path
                       or urlparse(u).netloc.startswith("product")]
    if on_product_path:
        urls = on_product_path
    return urls[:MAX_IMAGES]


def extract_videos(tree: HTMLParser, html: str) -> list[str]:
    found: dict[str, str] = {}

    for vid in YOUTUBE_ID.findall(html):
        found.setdefault(vid, f"https://www.youtube.com/watch?v={vid}")

    for frame in tree.css("iframe"):
        src = frame.attributes.get("src") or frame.attributes.get("data-src") or ""
        if src and any(k in src for k in ("vimeo", "facebook.com/plugins/video")):
            found.setdefault(src, src)

    for node in tree.css("video source, video"):
        src = node.attributes.get("src") or ""
        if src and not src.startswith("data:"):
            found.setdefault(src, src)

    return list(found.values())


def extract_specs(tree: HTMLParser) -> dict[str, str]:
    """Two-column spec tables and definition lists, keyed like the sections."""
    specs: dict[str, str] = {}

    def record(label: str, value: str) -> None:
        if not label or not value or len(value) > 600:
            return
        for key, pattern in SPEC_KEYS:
            if pattern.search(label):
                specs.setdefault(key, value)
                return
        # Keep unrecognised rows too - shops invent their own labels.
        slug = _slug(label)
        if slug:
            specs.setdefault(slug, value)

    for table in tree.css("table"):
        for row in table.css("tr"):
            cells = row.css("td, th")
            if len(cells) == 2:
                record(_text(cells[0]), _text(cells[1]))

    for dl in tree.css("dl"):
        terms = dl.css("dt")
        defs = dl.css("dd")
        for term, definition in zip(terms, defs):
            record(_text(term), _text(definition))

    return specs


def _heading_key(block: Node) -> tuple[str | None, str]:
    """Does this block open a labelled section? Returns (key, heading text).

    The label may be the block itself (<h3>Cong dung</h3>) or bolded inside
    it (<p><strong>Cong dung:</strong> ...</p>).
    """
    heads: list[Node] = []
    if block.tag in HEADING_TAGS:
        heads.append(block)
    heads.extend(block.css(",".join(HEADING_TAGS)))

    for node in heads:
        text = _text(node)
        if not text or len(text) > 120:
            continue
        for key, pattern in SECTION_PATTERNS:
            if pattern.search(text):
                return key, text
    return None, ""


HEADING_HTML = re.compile(
    r"<(h[2-5]|strong|b)\b[^>]*>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)


def _strip_tags(fragment: str) -> str:
    return _text(HTMLParser(f"<div>{fragment}</div>").css_first("div"))


def extract_sections(container: Node | None) -> dict[str, str]:
    """Split the write-up into labelled parts using its own headings.

    Cuts the container's HTML at heading tags rather than walking child
    nodes. Shops routinely put the entire write-up inside one <div>, with
    every heading nested somewhere below it, so a scan over block children
    sees a single block and files the whole page under whichever label it
    happens to match first.
    """
    if container is None:
        return {}

    html = container.html or ""
    marks: list[tuple[int, int, str]] = []  # start, end, key

    for match in HEADING_HTML.finditer(html):
        label = _strip_tags(match.group(2))
        if not label or len(label) > 120:
            continue
        for key, pattern in SECTION_PATTERNS:
            if pattern.search(label):
                marks.append((match.start(), match.end(), key))
                break

    if not marks:
        return {}

    sections: dict[str, list[str]] = {}
    for i, (_, body_start, key) in enumerate(marks):
        body_end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        body = _strip_tags(html[body_start:body_end]).strip(" :.-–—")
        if len(body) > 8:
            sections.setdefault(key, []).append(body)

    return {
        key: " ".join(parts)[:4000]
        for key, parts in sections.items()
        if " ".join(parts).strip()
    }


def extract_content(container: Node | None) -> str:
    return _text(container)[:MAX_CONTENT]


def host_of(url: str) -> str:
    return urlparse(url).netloc
