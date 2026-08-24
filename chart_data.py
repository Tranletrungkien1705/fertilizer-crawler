"""Pull the numbers the dashboard needs and write them as JSON.

Kept separate from rendering: the page embeds this output, so it stays a
self-contained file with no database credentials and no network calls.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# Below this pack weight a per-kilo price stops describing a purchase anyone
# makes: seed packets and single-dose sachets live here.
BULK_KG = 0.25

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def rows(db, sql, args=()):
    with db._conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def build(db) -> dict:
    totals = rows(db, """
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE price > 0),
               COUNT(*) FILTER (WHERE price > 0 AND pack_kg > 0),
               COUNT(DISTINCT source)
        FROM products
    """)[0]

    hist = rows(db, """
        SELECT COUNT(*), COUNT(DISTINCT url),
               MIN(observed_at), MAX(observed_at),
               COUNT(DISTINCT DATE(observed_at))
        FROM price_history
    """)[0]

    # Per-shop spread of unit price, over bulk goods only.
    #
    # Seed packets weigh 5 g and sachets of pesticide the same, so dividing
    # their price by weight yields millions per kilo - arithmetically right,
    # and meaningless next to a 50 kg sack. Nobody buys seed by the kilo. The
    # cut keeps the comparison between things that are actually alternatives.
    per_shop = rows(db, """
        SELECT source,
               COUNT(*)                                                  AS n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price/pack_kg) AS median,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY price/pack_kg) AS q1,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY price/pack_kg) AS q3,
               MIN(price/pack_kg)                                        AS lo,
               MAX(price/pack_kg)                                        AS hi
        FROM products
        WHERE price > 0 AND pack_kg >= %s
        GROUP BY source
        HAVING COUNT(*) >= 3
        ORDER BY 3
    """, (BULK_KG,))

    excluded = rows(db, """
        SELECT COUNT(*) FROM products
        WHERE price > 0 AND pack_kg > 0 AND pack_kg < %s
    """, (BULK_KG,))[0][0]

    # The same nutrient ratio offered by more than one shop: the only
    # like-for-like price comparison the data supports.
    npk = rows(db, """
        WITH priced AS (
            SELECT npk, source, name, price, pack_kg, price/pack_kg AS per_kg
            FROM products
            WHERE npk IS NOT NULL AND price > 0 AND pack_kg > 0
        )
        SELECT npk, source, MIN(per_kg) AS per_kg, MIN(name) AS name
        FROM priced
        GROUP BY npk, source
        HAVING npk IN (
            SELECT npk FROM priced GROUP BY npk HAVING COUNT(DISTINCT source) > 1
        )
        ORDER BY npk, 3
    """)

    stock = rows(db, """
        SELECT source,
               COUNT(*) FILTER (WHERE in_stock = 1) AS in_stock,
               COUNT(*) FILTER (WHERE in_stock = 0) AS out,
               COALESCE(SUM(stock_qty), 0)          AS units
        FROM products
        WHERE in_stock IS NOT NULL
        GROUP BY source ORDER BY 2 DESC
    """)

    # One point per product per day. Empty of movement until a second day
    # lands - the page says so rather than drawing a flat line.
    series = rows(db, """
        SELECT h.url, p.name, h.source, DATE(h.observed_at) AS day,
               AVG(h.price) AS price
        FROM price_history h JOIN products p ON p.url = h.url
        WHERE h.price IS NOT NULL
        GROUP BY h.url, p.name, h.source, DATE(h.observed_at)
        ORDER BY h.url, day
    """)

    moved = rows(db, """
        SELECT COUNT(*) FROM (
            SELECT url FROM price_history WHERE price IS NOT NULL
            GROUP BY url HAVING COUNT(DISTINCT price) > 1) t
    """)[0][0]

    by_day = rows(db, """
        SELECT DATE(observed_at) AS day, COUNT(*) AS n, COUNT(DISTINCT source)
        FROM price_history GROUP BY 1 ORDER BY 1
    """)

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "products": totals[0], "priced": totals[1],
            "comparable": totals[2], "shops": totals[3],
        },
        "history": {
            "rows": hist[0], "tracked": hist[1],
            "first": str(hist[2])[:19], "last": str(hist[3])[:19],
            "days": hist[4], "moved": moved,
        },
        "bulk_kg": BULK_KG,
        "excluded_small": excluded,
        "per_shop": [
            {"shop": s, "n": n, "median": float(m), "q1": float(q1),
             "q3": float(q3), "lo": float(lo), "hi": float(hi)}
            for s, n, m, q1, q3, lo, hi in per_shop
        ],
        "npk": [
            {"npk": f, "shop": s, "per_kg": float(p), "name": nm}
            for f, s, p, nm in npk
        ],
        "stock": [
            {"shop": s, "in_stock": i, "out": o, "units": int(u)}
            for s, i, o, u in stock
        ],
        "series": [
            {"url": u, "name": nm, "shop": s, "day": str(d), "price": float(p)}
            for u, nm, s, d, p in series
        ],
        "by_day": [{"day": str(d), "n": n, "shops": sh} for d, n, sh in by_day],
    }


def main() -> None:
    with Storage() as db:
        data = build(db)
    out = ROOT / "dashboard_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    t, h = data["totals"], data["history"]
    print(f"products {t['products']}  priced {t['priced']}  comparable {t['comparable']}")
    print(f"history  {h['rows']} rows over {h['days']} day(s); {h['moved']} products moved")
    print(f"per_shop {len(data['per_shop'])} shops (bulk >= {data['bulk_kg']}kg, "
          f"{data['excluded_small']} small packs excluded)")
    print(f"npk pairs {len(data['npk'])}  series points {len(data['series'])}")
    print(f"wrote {out.name} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
