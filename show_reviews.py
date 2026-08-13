"""Print the customer reviews collected so far."""
import json
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

SQL = ("SELECT source, name, rating, review_count, reviews FROM products "
       "WHERE review_count > 0 ORDER BY review_count DESC")


def main() -> None:
    with Storage() as db:
        if db.is_pg:
            with db._conn.cursor() as cur:
                cur.execute(SQL)
                rows = cur.fetchall()
        else:
            rows = list(db._conn.execute(SQL))

    if not rows:
        print("no product carries a review yet")
        return

    for source, name, rating, count, raw in rows:
        print(f"\n{source} — {name[:60]}")
        print(f"  rating {rating}  ({count} reviews)")
        for r in json.loads(raw or "[]"):
            stars = "*" * int(r.get("rating") or 0)
            print(f"    [{stars:5}] {r.get('author') or '?'} "
                  f"({str(r.get('date'))[:10]})")
            print(f"            {(r.get('text') or '')[:100]}")


if __name__ == "__main__":
    main()
