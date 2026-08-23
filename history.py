"""Read the price and stock history.

    python history.py                # what changed recently, across all shops
    python history.py --movers       # biggest price moves, cheapest first
    python history.py --url <url>    # the full series for one product
    python history.py --size         # how much the history table is costing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

# Product names are Vietnamese and the Windows console defaults to cp1252,
# which cannot encode them: without this the report dies on its first row.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(db, sql, args=()):
    if db.is_pg:
        with db._conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    return list(db._conn.execute(sql, args))


def mark(db) -> str:
    return "%s" if db.is_pg else "?"


def money(value) -> str:
    return f"{value:,.0f}d" if value else "-"


def recent(db, days: int) -> None:
    """Products whose price actually moved, newest first."""
    cutoff = ("NOW() - INTERVAL '%s days'" % days if db.is_pg
              else f"datetime('now', '-{days} days')")
    rows = run(db, f"""
        SELECT h.source, p.name, h.price, h.observed_at, h.url
        FROM price_history h
        JOIN products p ON p.url = h.url
        WHERE h.observed_at >= {cutoff}
          AND h.price IS NOT NULL
        ORDER BY h.observed_at DESC
        LIMIT 40
    """)
    if not rows:
        print(f"no observations in the last {days} days")
        return

    print(f"{'WHEN':17} {'SHOP':18} {'PRICE':>12}  PRODUCT")
    print("-" * 86)
    for source, name, price, at, _ in rows:
        print(f"{str(at)[:16]:17} {source:18} {money(price):>12}  {name[:36]}")


def movers(db) -> None:
    """Compare each product's earliest and latest recorded price."""
    rows = run(db, """
        WITH bounds AS (
            SELECT url,
                   MIN(observed_at) AS first_at,
                   MAX(observed_at) AS last_at
            FROM price_history
            WHERE price IS NOT NULL
            GROUP BY url
            HAVING COUNT(*) > 1
        )
        SELECT p.source, p.name,
               f.price AS old_price,
               l.price AS new_price,
               b.first_at, b.last_at
        FROM bounds b
        JOIN price_history f ON f.url = b.url AND f.observed_at = b.first_at
        JOIN price_history l ON l.url = b.url AND l.observed_at = b.last_at
        JOIN products p       ON p.url = b.url
        WHERE f.price IS NOT NULL AND l.price IS NOT NULL
          AND f.price <> l.price
    """)
    if not rows:
        print("no product has two different recorded prices yet.")
        print("history needs a second crawl on a later day to show movement.")
        return

    scored = []
    for source, name, old, new, first_at, last_at in rows:
        pct = (new - old) / old * 100 if old else 0
        scored.append((pct, source, name, old, new, first_at, last_at))
    scored.sort()

    print(f"{'CHANGE':>8} {'SHOP':18} {'FROM':>12} {'TO':>12}  PRODUCT")
    print("-" * 90)
    for pct, source, name, old, new, _, _ in scored:
        arrow = "down" if pct < 0 else "up"
        print(f"{pct:+7.1f}% {source:18} {money(old):>12} {money(new):>12}  "
              f"{name[:30]} ({arrow})")


def series(db, url: str) -> None:
    rows = run(db, f"""
        SELECT observed_at, price, in_stock, stock_qty
        FROM price_history WHERE url = {mark(db)}
        ORDER BY observed_at
    """, (url,))
    if not rows:
        print("no history for that URL")
        return

    name = run(db, f"SELECT name FROM products WHERE url = {mark(db)}", (url,))
    if name:
        print(name[0][0][:76])
    print(f"\n{'WHEN':17} {'PRICE':>12} {'STOCK':>7} {'QTY':>6}")
    print("-" * 46)
    previous = None
    for at, price, in_stock, qty in rows:
        delta = ""
        if previous and price and price != previous:
            delta = f"  {(price - previous) / previous * 100:+.1f}%"
        print(f"{str(at)[:16]:17} {money(price):>12} "
              f"{'yes' if in_stock else 'no':>7} {qty if qty is not None else '-':>6}{delta}")
        if price:
            previous = price


def size(db) -> None:
    total = run(db, "SELECT COUNT(*) FROM price_history")[0][0]
    tracked = run(db, "SELECT COUNT(DISTINCT url) FROM price_history")[0][0]
    span = run(db, "SELECT MIN(observed_at), MAX(observed_at) FROM price_history")[0]
    products = run(db, "SELECT COUNT(*) FROM products")[0][0]

    print(f"history rows     : {total}")
    print(f"products tracked : {tracked} of {products}")
    print(f"first observation: {str(span[0])[:19]}")
    print(f"last observation : {str(span[1])[:19]}")
    if total:
        # Each row is a handful of numbers plus a URL.
        print(f"\nroughly {total * 150 / 1024:.0f} KB. Only changes are stored, so a "
              f"quiet day costs nothing.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--movers", action="store_true", help="biggest price moves")
    ap.add_argument("--url", help="full series for one product")
    ap.add_argument("--size", action="store_true", help="history table size")
    ap.add_argument("--days", type=int, default=7, help="window for recent (default 7)")
    args = ap.parse_args()

    with Storage() as db:
        if args.size:
            size(db)
        elif args.movers:
            movers(db)
        elif args.url:
            series(db, args.url)
        else:
            recent(db, args.days)


if __name__ == "__main__":
    main()
