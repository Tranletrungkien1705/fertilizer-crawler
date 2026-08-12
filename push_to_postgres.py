"""Copy the local SQLite catalogue into the hosted Postgres in DATABASE_URL.

Run once after pointing .env at Neon, so the work already crawled locally is
not thrown away. Safe to re-run: rows are upserted on their URL.

    python push_to_postgres.py --check   # connection + row counts only
    python push_to_postgres.py           # copy everything across
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import COLUMNS, Product, Storage

ROOT = Path(__file__).resolve().parent
SQLITE_DB = ROOT / "data" / "fertilizer.db"

load_dotenv(ROOT / ".env")


def local_rows() -> list[Product]:
    if not SQLITE_DB.exists():
        raise SystemExit(f"no local database at {SQLITE_DB}")
    con = sqlite3.connect(SQLITE_DB)
    con.row_factory = sqlite3.Row
    cols = ", ".join(COLUMNS)
    return [Product(**{c: r[c] for c in COLUMNS})
            for r in con.execute(f"SELECT {cols} FROM products")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify the connection without writing")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn.startswith(("postgres://", "postgresql://")):
        raise SystemExit(
            "DATABASE_URL is not set to a Postgres connection string.\n"
            "Copy .env.example to .env and paste the Neon string into it."
        )

    host = dsn.split("@")[-1].split("/")[0]
    print(f"target : {host}")

    rows = local_rows()
    print(f"local  : {len(rows)} products in SQLite")

    with Storage(dsn) as db:
        before = db.count()
        print(f"remote : {before} products before")

        if args.check:
            print("\nconnection OK (nothing written)")
            return

        saved = db.save_many(rows)
        after = db.count()

    print(f"pushed : {saved} rows upserted")
    print(f"remote : {after} products now")
    if after < len(rows):
        print("note   : remote total is lower than local, which means some "
              "URLs already existed and were updated in place", file=sys.stderr)


if __name__ == "__main__":
    main()
