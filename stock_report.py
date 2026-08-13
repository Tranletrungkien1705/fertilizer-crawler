"""What the platform APIs added, per shop."""
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

SQL = """
SELECT COALESCE(platform, '-')                                    AS platform,
       source,
       COUNT(*)                                                   AS rows,
       SUM(CASE WHEN sku IS NOT NULL AND sku <> '' THEN 1 ELSE 0 END)  AS sku,
       SUM(CASE WHEN in_stock IS NOT NULL THEN 1 ELSE 0 END)      AS stock_known,
       SUM(CASE WHEN stock_qty IS NOT NULL THEN 1 ELSE 0 END)     AS qty,
       SUM(CASE WHEN variants IS NOT NULL AND variants NOT IN ('', '[]') THEN 1 ELSE 0 END) AS variants,
       SUM(CASE WHEN review_count > 0 THEN 1 ELSE 0 END)          AS reviewed,
       SUM(CASE WHEN price_max IS NOT NULL THEN 1 ELSE 0 END)     AS ranged
FROM products
GROUP BY COALESCE(platform, '-'), source
ORDER BY COUNT(*) DESC
"""


def main() -> None:
    with Storage() as db:
        if db.is_pg:
            with db._conn.cursor() as cur:
                cur.execute(SQL)
                rows = cur.fetchall()
        else:
            rows = list(db._conn.execute(SQL))

    head = (f"{'PLATFORM':13} {'SHOP':20} {'ROWS':>5} {'SKU':>5} {'STOCK':>6} "
            f"{'QTY':>5} {'VARI':>5} {'REVW':>5} {'RANGE':>6}")
    print(head)
    print("-" * len(head))
    for platform, source, n, sku, stock, qty, variants, reviewed, ranged in rows:
        print(f"{platform:13} {source:20} {n:>5} {sku or 0:>5} {stock or 0:>6} "
              f"{qty or 0:>5} {variants or 0:>5} {reviewed or 0:>5} {ranged or 0:>6}")


if __name__ == "__main__":
    main()
