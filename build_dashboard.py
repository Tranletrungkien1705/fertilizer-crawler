"""Inject the queried data into the dashboard template.

The page ships as one self-contained file: no database credentials in it, no
network calls when it is viewed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

template = ROOT / "dashboard_template.html"
data_file = ROOT / "dashboard_data.json"
out = ROOT / "dashboard.html"

if not data_file.exists():
    raise SystemExit("run chart_data.py first")

data = json.loads(data_file.read_text(encoding="utf-8"))
html = template.read_text(encoding="utf-8")

if "__DATA__" not in html:
    raise SystemExit("template has no __DATA__ placeholder")

# The payload sits in a <script type="application/json"> block, so the only
# sequence that can break out of it is a literal </script>.
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
payload = payload.replace("</", "<\\/")

rendered = html.replace("__DATA__", payload)
out.write_text(rendered, encoding="utf-8")

# Also publish to docs/ so GitHub Pages serves it at the repo root URL.
pages = ROOT / "docs" / "index.html"
pages.parent.mkdir(exist_ok=True)
pages.write_text(rendered, encoding="utf-8")

print(f"wrote {out.name} + docs/index.html ({out.stat().st_size / 1024:.0f} KB)")
print(f"  {data['totals']['products']} products, {len(data['npk'])} npk rows, "
      f"{len(data['per_shop'])} shops, {data['history']['days']} day(s) of history")
