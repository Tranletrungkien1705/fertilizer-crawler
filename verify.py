"""Sanity-check the crawled dataset."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "fertilizer.db"
con = sqlite3.connect(DB)

total = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
priced = con.execute("SELECT COUNT(*) FROM products WHERE price > 0").fetchone()[0]
npk = con.execute("SELECT COUNT(*) FROM products WHERE npk IS NOT NULL").fetchone()[0]
unit = con.execute("SELECT COUNT(*) FROM products WHERE unit IS NOT NULL").fetchone()[0]

print(f"rows            : {total}")
print(f"price parsed    : {priced} ({priced / total:.0%})")
print(f"npk parsed      : {npk} ({npk / total:.0%})")
print(f"unit parsed     : {unit} ({unit / total:.0%})")

dupes = con.execute(
    "SELECT name, COUNT(*) c FROM products GROUP BY name HAVING c > 1 ORDER BY c DESC"
).fetchall()
print(f"duplicate names : {len(dupes)}")
for name, c in dupes[:5]:
    print(f"    x{c}  {name[:60]}")

lo, hi, avg = con.execute(
    "SELECT MIN(price), MAX(price), AVG(price) FROM products WHERE price > 0"
).fetchone()
print(f"price range     : {lo:,.0f} - {hi:,.0f} (avg {avg:,.0f})")

print("\ntop NPK formulas:")
for formula, c in con.execute(
    "SELECT npk, COUNT(*) c FROM products WHERE npk IS NOT NULL "
    "GROUP BY npk ORDER BY c DESC LIMIT 8"
).fetchall():
    print(f"    {formula:12} {c}")
