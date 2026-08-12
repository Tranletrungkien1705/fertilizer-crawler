"""Recompute derived fields (npk, pack_kg, unit) from already-stored text.

Parsing rules improve more often than the pages do, so re-deriving beats
re-crawling: it is instant and costs the sites nothing.
"""
import sqlite3
from pathlib import Path

from crawler.extract import parse_npk, parse_pack_kg, parse_unit

DB = Path(__file__).resolve().parent / "data" / "fertilizer.db"


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, name, description, npk, pack_kg FROM products").fetchall()

    changed = 0
    gained_npk = gained_kg = 0
    for r in rows:
        haystack = f"{r['name']} {r['description'] or ''}"
        npk = parse_npk(haystack)
        pack_kg = parse_pack_kg(r["name"], r["description"])
        unit = parse_unit(haystack)

        if npk == r["npk"] and pack_kg == r["pack_kg"]:
            continue
        if npk and not r["npk"]:
            gained_npk += 1
        if pack_kg and not r["pack_kg"]:
            gained_kg += 1
        con.execute(
            "UPDATE products SET npk = ?, pack_kg = ?, unit = ? WHERE id = ?",
            (npk, pack_kg, unit, r["id"]),
        )
        changed += 1

    con.commit()
    total = len(rows)
    npk_now = con.execute("SELECT COUNT(*) FROM products WHERE npk IS NOT NULL").fetchone()[0]
    kg_now = con.execute("SELECT COUNT(*) FROM products WHERE pack_kg IS NOT NULL").fetchone()[0]
    print(f"rows={total} updated={changed}")
    print(f"  npk     : {npk_now} ({npk_now / total:.0%})  newly parsed {gained_npk}")
    print(f"  pack_kg : {kg_now} ({kg_now / total:.0%})  newly parsed {gained_kg}")


if __name__ == "__main__":
    main()
