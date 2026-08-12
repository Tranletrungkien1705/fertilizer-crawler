"""Show what has been crawled so far."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "fertilizer.db"


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"No database yet at {DB}")

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT name, price, npk, unit, source FROM products ORDER BY price DESC"
    ).fetchall()

    print(f"{'PRODUCT':56} {'PRICE':>12} {'NPK':>10} {'UNIT':>10}")
    print("-" * 92)
    for name, price, npk, unit, _ in rows:
        price_s = f"{price:,.0f}d" if price else "-"
        print(f"{(name or '')[:54]:56} {price_s:>12} {npk or '-':>10} {unit or '-':>10}")

    with_price = sum(1 for r in rows if r[1])
    with_npk = sum(1 for r in rows if r[2])
    print(f"\nrows={len(rows)}  price parsed={with_price}  npk parsed={with_npk}")

    by_source = con.execute(
        "SELECT source, COUNT(*) FROM products GROUP BY source"
    ).fetchall()
    for src, n in by_source:
        print(f"  {src}: {n}")


if __name__ == "__main__":
    main()
