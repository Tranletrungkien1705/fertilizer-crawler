"""Show everything stored for one product.

    python inspect_product.py                 # the most recently crawled row
    python inspect_product.py "urea"          # first match on name
"""
import json
import sys
import textwrap
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

FIELDS = ["source", "name", "price", "pack_kg", "npk", "brand", "url"]


def query(db, term):
    cols = ", ".join(FIELDS + ["images", "videos", "specs", "sections", "content"])
    if term:
        sql = (f"SELECT {cols} FROM products WHERE LOWER(name) LIKE "
               f"{'%s' if db.is_pg else '?'} ORDER BY crawled_at DESC LIMIT 1")
        args = (f"%{term.lower()}%",)
    else:
        sql = f"SELECT {cols} FROM products ORDER BY crawled_at DESC LIMIT 1"
        args = ()

    if db.is_pg:
        with db._conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()
    return db._conn.execute(sql, args).fetchone()


def show_json(label: str, raw: str | None, limit: int = 6) -> None:
    if not raw:
        print(f"\n{label}: (none)")
        return
    data = json.loads(raw)
    if isinstance(data, list):
        print(f"\n{label}: {len(data)}")
        for item in data[:limit]:
            print("   ", item[:104])
    else:
        print(f"\n{label}: {len(data)} keys")
        for key, value in list(data.items())[:limit]:
            body = " ".join(str(value).split())
            print(f"    {key:20} {body[:88]}")


def main() -> None:
    term = sys.argv[1] if len(sys.argv) > 1 else None
    with Storage() as db:
        row = query(db, term)

    if not row:
        raise SystemExit("no matching product")

    values = dict(zip(FIELDS, row))
    images, videos, specs, sections, content = row[len(FIELDS):]

    print("=" * 78)
    for key in FIELDS:
        print(f"{key:10} {values[key]}")
    print("=" * 78)

    show_json("images", images)
    show_json("videos", videos)
    show_json("specs", specs, limit=10)

    if sections:
        data = json.loads(sections)
        print(f"\nsections: {len(data)}")
        for key, value in data.items():
            print(f"\n  [{key}] {len(value)} chars")
            for line in textwrap.wrap(value[:340], 74):
                print("    " + line)
    else:
        print("\nsections: (none)")

    print(f"\ncontent: {len(content or '')} chars")
    if content:
        for line in textwrap.wrap(content[:300], 74):
            print("    " + line)


if __name__ == "__main__":
    main()
