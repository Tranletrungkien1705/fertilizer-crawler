"""Compare fertilizer prices across suppliers.

Package sizes differ wildly between retailers (a 1 kg consumer bag vs a 50 kg
sack), so everything is normalised to price per kg before comparing.

Two views:
  by NPK formula  - same nutrient ratio from different suppliers
  by brand+name   - likely the same product on both sites
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "fertilizer.db"

STOPWORDS = {
    # packaging / generic nouns
    "phan", "bon", "goi", "bao", "tui", "chai", "kg", "gr", "gram", "te",
    "cho", "cay", "trong", "va", "loai", "moi", "voi", "cao", "cap", "chuyen",
    "dung", "nhap", "khau", "sieu", "the", "cac", "tot", "gia", "re",
    # marketing copy - shared by half the catalogue, so it pairs unrelated
    # products ("tang nang suat" appears on NPK sacks and on KNO3 alike)
    "tang", "nang", "suat", "kich", "thich", "giup", "dat", "chat", "luong",
    "manh", "khoe", "dinh", "duong", "tap", "hieu", "qua", "nhanh", "benh",
    "giai", "phap", "chinh", "hang", "san", "pham", "hoat", "tinh",
}


def strip_accents(text: str) -> str:
    table = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
        "ùúủũụưừứửữựỳýỷỹỵđ",
        "a" * 17 + "e" * 11 + "i" * 5 + "o" * 17 + "u" * 11 + "y" * 5 + "d",
    )
    return text.lower().translate(table)


def tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", strip_accents(name))
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def fmt(value: float | None) -> str:
    return f"{value:,.0f}" if value else "-"


def load(con) -> list[dict]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT source, name, price, pack_kg, npk, url FROM products "
        "WHERE price > 0 AND pack_kg > 0"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["per_kg"] = d["price"] / d["pack_kg"]
        out.append(d)
    return out


def compare_by_npk(items: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        if it["npk"]:
            groups[it["npk"]].append(it)

    multi = {k: v for k, v in groups.items()
             if len({i["source"] for i in v}) > 1}

    print("=" * 78)
    print("SAME NPK FORMULA, DIFFERENT SUPPLIERS   (price per kg)")
    print("=" * 78)
    if not multi:
        print("no NPK formula is stocked by more than one supplier yet")
        return

    for formula in sorted(multi, key=lambda f: -len(multi[f])):
        entries = sorted(multi[formula], key=lambda i: i["per_kg"])
        print(f"\nNPK {formula}")
        best = entries[0]["per_kg"]
        for e in entries:
            gap = (e["per_kg"] / best - 1) * 100
            mark = " <-- cheapest" if e is entries[0] else f"  +{gap:.0f}%"
            print(f"  {e['source']:16} {fmt(e['per_kg']):>9}d/kg "
                  f"({fmt(e['price'])}d / {e['pack_kg']:g}kg)  "
                  f"{e['name'][:34]:36}{mark}")


MAX_PRICE_RATIO = 4.0


def compatible(a: dict, b: dict) -> bool:
    """Reject pairs that share only brand words or cannot be the same goods.

    Brand names like "dau trau npk" overlap across a supplier's whole range,
    so token overlap alone happily pairs 16-16-8 with 20-20-15. When both
    sides declare an NPK ratio it must be the same one.

    The price guard catches what keywords cannot: wholesale-versus-retail on
    one product tops out near 2x per kg, so a wider gap means two different
    goods that merely describe themselves alike ("thuoc tru oc" against
    "thuoc kich re").
    """
    if a["npk"] and b["npk"] and a["npk"] != b["npk"]:
        return False
    hi, lo = max(a["per_kg"], b["per_kg"]), min(a["per_kg"], b["per_kg"])
    if lo > 0 and hi / lo > MAX_PRICE_RATIO:
        return False
    return True


def required_overlap(a: dict, b: dict, base: int) -> int:
    """An identical NPK ratio is strong evidence on its own.

    Shops that name products tersely ("NPK 10-60-10 Hu 500g") never reach the
    normal keyword threshold, so matching them would be impossible otherwise.
    """
    if a["npk"] and b["npk"] and a["npk"] == b["npk"]:
        return 1
    return base


NPK_BONUS = 5


def best_match(item: dict, pool: list[dict], base: int) -> tuple[dict | None, int]:
    """Pick the strongest candidate, ranking a shared NPK ratio above keywords.

    Without the bonus a candidate that merely repeats a few marketing words
    can outrank the product carrying the very same NPK formula.
    """
    ti = tokens(item["name"])
    best, best_rank, best_score = None, 0, 0
    for other in pool:
        if not compatible(item, other):
            continue
        score = len(ti & tokens(other["name"]))
        if score < required_overlap(item, other, base):
            continue
        same_npk = bool(item["npk"] and other["npk"] and item["npk"] == other["npk"])
        rank = score + (NPK_BONUS if same_npk else 0)
        if rank > best_rank:
            best, best_rank, best_score = other, rank, score
    return best, best_score


def compare_by_name(items: list[dict], min_overlap: int = 3) -> None:
    """Cluster the same product across every supplier, not just two.

    Mutual best matches are computed for each pair of sources, then linked
    transitively: if A matches B and B matches C, all three are one product.
    """
    print("\n" + "=" * 78)
    print("SAME PRODUCT ACROSS SUPPLIERS   (name keywords + same NPK)")
    print("=" * 78)

    by_source: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_source[it["source"]].append(it)

    sources = sorted(by_source)
    if len(sources) < 2:
        print("need at least two sources")
        return

    for i, it in enumerate(items):
        it["_id"] = i

    pairs: dict[frozenset[int], int] = {}
    for i, src_a in enumerate(sources):
        for src_b in sources[i + 1:]:
            left, right = by_source[src_a], by_source[src_b]
            for a in left:
                b, score = best_match(a, right, min_overlap)
                if not b:
                    continue
                back, _ = best_match(b, left, min_overlap)
                if back is a:
                    pairs[frozenset((a["_id"], b["_id"]))] = score

    # Complete linkage, not transitive chaining. Chaining ("A~B, B~C, so
    # A~B~C") collapsed unrelated goods into one cluster once there were many
    # shops: a single weak link dragged a pesticide in beside a fertilizer.
    # Here a product joins a cluster only if it matches *every* member.
    by_id = {it["_id"]: it for it in items}
    clusters: list[set[int]] = []
    for pair, _score in sorted(pairs.items(), key=lambda kv: -kv[1]):
        a, b = tuple(pair)
        placed = False
        for cluster in clusters:
            if a in cluster or b in cluster:
                new = {a, b} - cluster
                if all(frozenset((n, m)) in pairs
                       for n in new for m in cluster):
                    cluster |= new
                    placed = True
                    break
        if not placed and a not in {x for c in clusters for x in c} \
                and b not in {x for c in clusters for x in c}:
            clusters.append({a, b})

    groups = [[by_id[i] for i in c] for c in clusters]
    groups = [g for g in groups if len({i["source"] for i in g}) > 1]

    def confidence(cluster: list[dict]) -> str:
        """Fertilizer has an NPK anchor; pesticides and biologicals do not.

        Their names lean on shared descriptive words ("thuoc tru sau", "che
        pham"), which keyword overlap cannot separate reliably, so those
        clusters are labelled rather than silently presented as facts.
        """
        npks = {i["npk"] for i in cluster if i["npk"]}
        if len(npks) == 1 and all(i["npk"] for i in cluster):
            return "HIGH"
        ids = [i["_id"] for i in cluster]
        worst = min((pairs.get(frozenset((x, y)), 0)
                     for k, x in enumerate(ids) for y in ids[k + 1:]),
                    default=0)
        return "HIGH" if worst >= 5 else "CHECK"
    if not groups:
        print("no confident matches - suppliers stock different lines")
        return

    # Widest price spread first: that is where the money is.
    def spread(c: list[dict]) -> float:
        per = [i["per_kg"] for i in c]
        return max(per) / min(per)

    multi = [c for c in groups if len({i["source"] for i in c}) >= 3]

    # Trustworthy matches first, then by how much money the gap represents.
    def order(c: list[dict]) -> tuple:
        return (0 if confidence(c) == "HIGH" else 1, -spread(c))

    for cluster in sorted(groups, key=order):
        entries = sorted(cluster, key=lambda i: i["per_kg"])
        n_src = len({i["source"] for i in cluster})
        flag = f"  [{n_src} SHOPS]" if n_src >= 3 else ""
        print(f"\n  [{confidence(cluster)}] {entries[0]['name'][:54]}{flag}")
        best = entries[0]["per_kg"]
        for e in entries:
            gap = "" if e is entries[0] else f"  +{(e['per_kg'] / best - 1) * 100:.0f}%"
            tag = "  CHEAPEST" if e is entries[0] else ""
            print(f"       {e['source']:16} {fmt(e['per_kg']):>9}d/kg "
                  f"({fmt(e['price'])}d / {e['pack_kg']:g}kg){tag}{gap}")
            if e is not entries[0]:
                print(f"       {'':16} {e['name'][:56]}")

    high = [c for c in groups if confidence(c) == "HIGH"]
    print(f"\n{len(groups)} matched products "
          f"({len(high)} HIGH confidence, {len(groups) - len(high)} need a look), "
          f"{len(multi)} carried by three or more shops")


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"no database at {DB}")
    con = sqlite3.connect(DB)
    items = load(con)

    total = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    print(f"{len(items)} of {total} products have both a price and a pack weight\n")

    for src, n in con.execute(
        "SELECT source, COUNT(*) FROM products GROUP BY source"
    ).fetchall():
        print(f"  {src:18} {n}")
    print()

    compare_by_npk(items)
    compare_by_name(items)


if __name__ == "__main__":
    main()
