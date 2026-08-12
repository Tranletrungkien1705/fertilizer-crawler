# Fertilizer market crawler

Collects publicly listed fertilizer products (name, price, NPK ratio, package
size) from Vietnamese agriculture retailers into a database.

Built to stay light: `httpx` + `selectolax`, no headless browser, no Docker.
A full run holds well under 100 MB of RAM.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python main.py                      # every enabled site
.\.venv\Scripts\python main.py --site nongnghieppho # one site
.\.venv\Scripts\python main.py --limit 50           # cap pages per listing
.\.venv\Scripts\python report.py                    # inspect what was stored
.\.venv\Scripts\python compare.py                   # cross-supplier prices
.\.venv\Scripts\python reparse.py                   # re-derive npk/pack_kg
```

Results land in `data/fertilizer.db` (SQLite) unless `DATABASE_URL` is set.

`reparse.py` recomputes derived fields from text already in the database.
Parsing rules change more often than the pages do, so reach for it instead of
re-crawling — it is instant and costs the sites nothing.

## Comparing prices

Retailers sell the same fertilizer in a 1 kg consumer pouch and a 50 kg sack,
so raw prices are not comparable. `compare.py` normalises everything to
**price per kg** using the pack weight parsed out of the product name, then
reports two views: same NPK formula across suppliers, and likely-identical
products matched on name keywords.

Every cluster carries a confidence label, and `HIGH` ones are printed first:

- **HIGH** — the members share one NPK ratio, or agree on five-plus keywords.
  Fertilizer matching is reliable because the NPK ratio anchors it.
- **CHECK** — everything else. Pesticides and biologicals have no equivalent
  anchor and their names lean on shared descriptive words ("thuoc tru sau",
  "che pham"), which keyword overlap cannot separate. Read these before
  trusting them; a fair share pair up unrelated goods.

Guards that keep matching honest:

- a pair is rejected when both sides declare a *different* NPK ratio;
- only *mutual* best matches count, so one popular listing cannot absorb every
  vaguely-worded product elsewhere;
- an identical NPK ratio outranks keyword overlap, because a few shared
  marketing words otherwise beat the product carrying the same formula;
- when the NPK ratio already matches, the keyword threshold drops to 1 — shops
  that name things tersely ("NPK 10-60-10 Hu 500g") never clear the normal bar;
- pairs more than 4x apart per kg are dropped: wholesale-versus-retail on one
  product tops out near 2x, so a wider gap means two different goods;
- clusters use *complete linkage* — a product joins only if it matches every
  existing member. Transitive chaining ("A~B, B~C, so A~B~C") looked fine with
  three shops and collapsed unrelated goods into one blob at nine.

## Adding sites in bulk

`discover.py` onboards a shop without hand-probing: it reads the sitemap,
picks agricultural categories, works out the product-link, name, price and
description selectors from real pages, and writes a `sites.json` entry.

```powershell
.\.venv\Scripts\python discover.py example.vn                    # inspect one
.\.venv\Scripts\python discover.py --file candidates.txt         # inspect a list
.\.venv\Scripts\python discover.py --file candidates.txt --write # add the good ones
.\.venv\Scripts\python discover.py example.vn --force            # re-check a known shop
```

A shop is only accepted when it publishes prices on at least 60% of sampled
products, so B2B suppliers quoting "vui long lien he" drop out on their own.
Roughly half of Vietnamese agricultural sites fail this check.

Validate it against a shop you already trust with `--force`: it should
reproduce the selectors that were found by hand.

Always smoke-test a freshly added shop before a full run:

```powershell
.\.venv\Scripts\python main.py --site <name> --limit 2
```

## Adding a site by hand

Selectors live in `sites.json` — no code changes needed. Helpers derive them
from the real pages instead of guessing:

```powershell
.\.venv\Scripts\python probe_platform.py example.vn          # robots.txt + URL shape
.\.venv\Scripts\python list_collections.py example.vn        # listing URLs from sitemap
.\.venv\Scripts\python inspect_site.py https://example.vn/p  # probe selectors
.\.venv\Scripts\python find_price.py https://example.vn/p    # locate the price element
.\.venv\Scripts\python probe_cards.py <listing_url>          # product-card link selector
.\.venv\Scripts\python probe_prices.py <list> <price> <link> # do prices exist at all?
.\.venv\Scripts\python probe_pagination.py <list> <link> [pattern]
```

`probe_cards.py` matters for shops with flat product URLs, where there is no
`/products/` path to filter on and links must be found by card class instead.
`probe_pagination.py` takes the page pattern as a third argument:
`"{base}/page/{n}"` for WooCommerce (default), `"{base}?page={n}"` for
Haravan/Shopify.

Add the entry, set `"enabled": true`, and run with a small `--limit` first.

**Run `probe_prices.py` before anything else.** Many Vietnamese fertilizer
suppliers are B2B and print "vui long lien he" instead of a price — worthless
for comparison. Two such sites are already in `sites.json`, disabled, with the
reason recorded so nobody re-investigates them. Retail garden shops are the
ones that publish real numbers.

## Switching to hosted Postgres

The storage layer speaks both SQLite and Postgres, so moving to a free hosted
database is a connection string and a driver:

```powershell
.\.venv\Scripts\pip install "psycopg[binary]"
copy .env.example .env     # then paste the Neon connection string
```

Neon suits this better than Supabase: Supabase pauses an idle free project
after a week, which would silently break a scheduled crawl.

## Running it off the laptop

`.github/workflows/crawl.yml` runs the crawl daily on GitHub Actions (free tier:
2000 minutes/month). Add the connection string as a repository secret named
`DATABASE_URL`. This keeps long crawls off a machine that needs its RAM for
development.

## Crawling politely

The fetcher reads each host's `robots.txt` and skips disallowed paths, honours
`Crawl-delay` when declared, and otherwise waits 1.5 s between requests to the
same host with at most 3 in flight. Keep these defaults — they are what makes
repeated crawling sustainable rather than something that gets the IP blocked.
