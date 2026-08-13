"""Show how recently each shop's rows were refreshed.

Counts alone cannot tell a working scheduled run from a silent no-op, because
re-crawling upserts on the URL and leaves the total unchanged. The timestamps
can.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

SQL = """
SELECT source,
       COUNT(*)        AS rows,
       MIN(crawled_at) AS oldest,
       MAX(crawled_at) AS newest
FROM products
GROUP BY source
ORDER BY MAX(crawled_at) DESC
"""


def main() -> None:
    with Storage() as db:
        conn = db._conn
        if db.is_pg:
            with conn.cursor() as cur:
                cur.execute(SQL)
                rows = cur.fetchall()
        else:
            rows = list(conn.execute(SQL))

    where = "Neon" if os.getenv("DATABASE_URL", "").startswith("postgres") else "SQLite"
    print(f"source: {where}\n")
    print(f"{'SHOP':22} {'ROWS':>5}  {'OLDEST':<20} {'NEWEST':<20}")
    print("-" * 72)
    for source, n, oldest, newest in rows:
        print(f"{source:22} {n:>5}  {str(oldest)[:19]:<20} {str(newest)[:19]:<20}")


if __name__ == "__main__":
    main()
