"""Dev helper: print a stored product URL per shop, for probing."""
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

SQL = """
SELECT source, url, name
FROM products
WHERE ({filter})
ORDER BY source, id
"""


def main() -> None:
    want = sys.argv[1] if len(sys.argv) > 1 else None
    clause = "source = %s" if want else "TRUE"

    with Storage() as db:
        conn = db._conn
        if db.is_pg:
            with conn.cursor() as cur:
                cur.execute(SQL.format(filter=clause), (want,) if want else ())
                rows = cur.fetchall()
        else:
            rows = list(conn.execute(
                SQL.format(filter="source = ?" if want else "TRUE"),
                (want,) if want else (),
            ))

    seen: set[str] = set()
    for source, url, name in rows:
        if source in seen:
            continue
        seen.add(source)
        print(f"{source:22} {url}")
        print(f"{'':22} {name[:60]}")


if __name__ == "__main__":
    main()
