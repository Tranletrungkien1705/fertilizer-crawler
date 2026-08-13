# Using this crawler for another industry

Nothing in the fetching, storage or platform layer is about fertilizer. Only
three things are: the section vocabulary, the NPK parser, and the pack-weight
parser. Swap those and the rest carries over unchanged.

## The ladder

Always climb down, never start at the bottom:

| Rung | Source | What you get | Cost |
|---|---|---|---|
| 1 | Platform JSON (`platform.py`) | price, SKU, vendor, variants, stock, rating, reviews | one request, zero selectors |
| 2 | JSON-LD in the page | price, SKU, brand, availability, rating | free, already fetched |
| 3 | CSS selectors (`sites.json`) | whatever you can name | fragile, per-shop work |
| 4 | Headless browser | the rendered DOM | ~300–500 MB per instance |

Run `probe_api.py <a product url>` first. It reports which rungs that shop
offers. Every shop crawled so far answered on rung 1 or 2, so no browser has
been needed — see "When you really need a browser" below.

## Adding a shop

```powershell
.\.venv\Scripts\python probe_api.py https://shop.vn/products/anything
```

**If it answers on rung 1** (`haravan/shopify product .js` or `woo store api`),
you need almost nothing: add the shop to `sites.json` with a `product_link`
selector so listings can be walked, and leave the rest null. The API supplies
name, price, images, SKU, stock and variants.

**If it answers on rung 2 or 3**, use the selector helpers:

```powershell
.\.venv\Scripts\python probe_platform.py shop.vn        # robots.txt, URL shape
.\.venv\Scripts\python probe_cards.py <listing url>     # product-link selector
.\.venv\Scripts\python find_price.py <product url>      # where the price lives
.\.venv\Scripts\python probe_prices.py <list> <price> <link>   # are prices public?
.\.venv\Scripts\python probe_pagination.py <list> <link>       # how many pages
.\.venv\Scripts\python audit_rich.py                    # what the config yields
```

Run `probe_prices.py` before the rest. Plenty of Vietnamese B2B suppliers
print "vui lòng liên hệ" instead of a price, and a shop with no public prices
is not worth configuring — two such shops sit disabled in `sites.json` with
the reason recorded.

## Retargeting to a new industry

Three files hold the domain knowledge.

**`crawler/rich.py` — `SECTION_PATTERNS`.** The headings a listing uses to
introduce each part of its write-up. Fertilizer uses composition, benefits,
dosage. Swap for what your industry writes:

```python
# cosmetics
("thanh_phan",  re.compile(r"thành phần|ingredients", re.I)),
("cong_dung",   re.compile(r"công dụng|tác dụng", re.I)),
("cach_dung",   re.compile(r"cách dùng|hướng dẫn", re.I)),
("loai_da",     re.compile(r"loại da|phù hợp với da", re.I)),

# electronics
("thong_so",    re.compile(r"thông số|cấu hình|specifications", re.I)),
("tinh_nang",   re.compile(r"tính năng|chức năng", re.I)),
("bao_hanh",    re.compile(r"bảo hành|chính sách đổi trả", re.I)),
```

Keys become JSON keys in the `sections` column, so pick them once and keep
them stable.

**`crawler/extract.py` — the domain parsers.** `parse_npk` and `parse_pack_kg`
are fertilizer-specific. Replace with whatever makes your products comparable:
screen size and storage for phones, volume and concentration for cosmetics,
horsepower for machinery. The pattern to copy is `parse_pack_kg`: read from
the *name* first and consult the description only right after a packaging
word, because descriptions quote dosages that look exactly like pack sizes.

**`compare.py` — the matching anchor.** Cross-shop comparison needs one
attribute that identifies the same product across sellers. Fertilizer uses the
NPK ratio; electronics would use the model number, books the ISBN. Whatever it
is, guard on it the way `compatible()` guards on NPK — brand words alone will
happily pair a 16-16-8 with a 20-20-15.

Also normalise before comparing. Shops sell the same thing in a 1 kg pouch and
a 50 kg sack, so raw prices are meaningless; `compare.py` divides by pack
weight. Your industry needs its own unit: per litre, per 100 g, per unit.

## What carries over untouched

`fetcher.py` (robots.txt, per-host rate limiting, retry, redirect handling),
`storage.py` (SQLite and Postgres behind one interface, migrations, reconnect),
`platform.py` (the JSON adapters), the GitHub Actions schedule, and every probe
helper.

## When you really need a browser

Only when the data exists solely in the rendered DOM: infinite-scroll listings
with no paginated URL, prices assembled by script from an authenticated call,
or a client-rendered app with no JSON endpoint. Check first — `probe_api.py`
looks for `__NEXT_DATA__` and `__NUXT__`, and a Next.js or Nuxt app almost
always ships its data as JSON inside the page, which needs no browser at all.

If it is genuinely required:

```powershell
.\.venv\Scripts\pip install playwright
.\.venv\Scripts\python -m playwright install chromium
```

Then fetch through Playwright and hand the resulting HTML to the same
extractors — they take HTML text, not a live page, so nothing else changes.

Budget for it honestly: each Chromium instance costs roughly 300–500 MB. On a
machine with 8 GB that is the difference between crawling in the background
and not using the machine meanwhile, so run browser-backed shops on GitHub
Actions rather than locally.
