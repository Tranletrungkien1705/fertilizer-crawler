"""Dev helper: show stored fields for products matching a name fragment."""
import sqlite3
import sys
from pathlib import Path

from crawler.extract import parse_pack_kg

DB = Path(__file__).resolve().parent / "data" / "fertilizer.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT source, name, price, pack_kg, npk, description FROM products "
    "WHERE name LIKE ? LIMIT 5",
    (f"%{sys.argv[1]}%",),
).fetchall()

for r in rows:
    print(f"source   : {r['source']}")
    print(f"name     : {r['name']}")
    print(f"price    : {r['price']}   pack_kg: {r['pack_kg']}   npk: {r['npk']}")
    desc = (r["description"] or "")[:180]
    print(f"desc     : {desc}")
    print(f"re-parse : {parse_pack_kg(r['name'], r['description'])}")
    print("-" * 70)
