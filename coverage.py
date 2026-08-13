"""How much of the rich data each shop actually yields.

Counting happens in SQL. Pulling the columns back to count them here means
dragging every write-up across the network - megabytes to answer a question
about presence.
"""
from pathlib import Path

from dotenv import load_dotenv

from crawler.storage import Storage

load_dotenv(Path(__file__).resolve().parent / ".env")

SECTION_LABELS = [
    ("thanh_phan", "composition"),
    ("cong_dung", "benefits"),
    ("huong_dan", "how to use"),
    ("lieu_luong", "dosage"),
    ("cong_nghe", "technology"),
    ("doi_tuong", "target crops"),
    ("bao_quan", "storage"),
    ("luu_y", "cautions"),
]


def _has(column: str) -> str:
    """1 when the column holds something other than an empty JSON container."""
    return (f"SUM(CASE WHEN {column} IS NOT NULL AND {column} NOT IN "
            f"('', '[]', '{{}}') THEN 1 ELSE 0 END)")


PER_SHOP = f"""
SELECT source,
       COUNT(*)              AS rows,
       {_has('images')}      AS with_images,
       {_has('videos')}      AS with_videos,
       {_has('specs')}       AS with_specs,
       {_has('content')}     AS with_content
FROM products
GROUP BY source
ORDER BY COUNT(*) DESC
"""


def main() -> None:
    with Storage() as db:
        def run(sql: str, args=()):
            if db.is_pg:
                with db._conn.cursor() as cur:
                    cur.execute(sql, args)
                    return cur.fetchall()
            return list(db._conn.execute(sql, args))

        rows = run(PER_SHOP)

        like = "%s" if db.is_pg else "?"
        section_counts = []
        for key, label in SECTION_LABELS:
            n = run(
                f"SELECT COUNT(*) FROM products WHERE sections LIKE {like}",
                (f'%"{key}"%',),
            )[0][0]
            section_counts.append((label, n))

        photos = run(
            "SELECT COUNT(*) FROM products WHERE images IS NOT NULL "
            "AND images NOT IN ('', '[]')"
        )[0][0]

    head = (f"{'SHOP':20} {'ROWS':>5} {'PHOTOS':>7} {'VIDEO':>6} "
            f"{'SPECS':>6} {'TEXT':>6}")
    print(head)
    print("-" * len(head))
    totals = [0, 0, 0, 0, 0]
    for source, n, img, vid, spec, content in rows:
        for i, v in enumerate((n, img, vid, spec, content)):
            totals[i] += v or 0
        print(f"{source:20} {n:>5} {img or 0:>7} {vid or 0:>6} "
              f"{spec or 0:>6} {content or 0:>6}")
    print("-" * len(head))
    print(f"{'TOTAL':20} {totals[0]:>5} {totals[1]:>7} {totals[2]:>6} "
          f"{totals[3]:>6} {totals[4]:>6}")

    print(f"\nproducts with at least one photo: {photos}")
    print("\nagronomic sections captured:")
    for label, n in section_counts:
        print(f"  {label:14} {n:>5}  {'#' * min(40, n // 5)}")


if __name__ == "__main__":
    main()
