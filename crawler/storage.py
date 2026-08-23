"""Storage layer. SQLite by default; set DATABASE_URL to a postgres:// DSN
to write to a hosted free-tier Postgres (Neon / Supabase) instead.

The only difference between backends is the placeholder style and the
upsert syntax, so both live behind one small class.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DEFAULT_SQLITE = Path(__file__).resolve().parent.parent / "data" / "fertilizer.db"


@dataclass
class Product:
    """One fertilizer listing scraped from a public page."""

    source: str
    url: str
    name: str
    price: float | None = None
    currency: str = "VND"
    unit: str | None = None
    pack_kg: float | None = None
    brand: str | None = None
    category: str | None = None
    npk: str | None = None
    description: str | None = None
    # The four below hold JSON, kept as text so one insert statement serves
    # both SQLite and Postgres. Query them in Postgres with e.g. specs::jsonb.
    images: str | None = None
    videos: str | None = None
    specs: str | None = None
    sections: str | None = None
    content: str | None = None
    # From the shop's own JSON where it offers one; left null when only the
    # rendered page was available.
    sku: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    in_stock: int | None = None
    stock_qty: int | None = None
    rating: float | None = None
    review_count: int | None = None
    tags: str | None = None
    variants: str | None = None
    reviews: str | None = None
    platform: str | None = None
    crawled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


def _as_datetime(value):
    """ISO string -> datetime, leaving anything already converted alone."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
    return value


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    price       REAL,
    currency    TEXT DEFAULT 'VND',
    unit        TEXT,
    pack_kg     REAL,
    brand       TEXT,
    category    TEXT,
    npk         TEXT,
    description TEXT,
    images       TEXT,
    videos       TEXT,
    specs        TEXT,
    sections     TEXT,
    content      TEXT,
    sku          TEXT,
    price_min    REAL,
    price_max    REAL,
    in_stock     INTEGER,
    stock_qty    INTEGER,
    rating       REAL,
    review_count INTEGER,
    tags         TEXT,
    variants     TEXT,
    reviews      TEXT,
    platform     TEXT,
    crawled_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_products_name   ON products(name);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL,
    price       REAL,
    price_min   REAL,
    price_max   REAL,
    in_stock    INTEGER,
    stock_qty   INTEGER,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_url ON price_history(url, observed_at);
CREATE INDEX IF NOT EXISTS idx_history_at  ON price_history(observed_at);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS products (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    price       DOUBLE PRECISION,
    currency    TEXT DEFAULT 'VND',
    unit        TEXT,
    pack_kg     DOUBLE PRECISION,
    brand       TEXT,
    category    TEXT,
    npk         TEXT,
    description TEXT,
    images       TEXT,
    videos       TEXT,
    specs        TEXT,
    sections     TEXT,
    content      TEXT,
    sku          TEXT,
    price_min    DOUBLE PRECISION,
    price_max    DOUBLE PRECISION,
    in_stock     INTEGER,
    stock_qty    INTEGER,
    rating       DOUBLE PRECISION,
    review_count INTEGER,
    tags         TEXT,
    variants     TEXT,
    reviews      TEXT,
    platform     TEXT,
    crawled_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_products_name   ON products(name);

CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL,
    price       DOUBLE PRECISION,
    price_min   DOUBLE PRECISION,
    price_max   DOUBLE PRECISION,
    in_stock    INTEGER,
    stock_qty   INTEGER,
    observed_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_url ON price_history(url, observed_at);
CREATE INDEX IF NOT EXISTS idx_history_at  ON price_history(observed_at);
"""

HISTORY_COLUMNS = [
    "url", "source", "price", "price_min", "price_max",
    "in_stock", "stock_qty", "observed_at",
]

COLUMNS = [
    "source", "url", "name", "price", "currency",
    "unit", "pack_kg", "brand", "category", "npk", "description",
    "images", "videos", "specs", "sections", "content",
    "sku", "price_min", "price_max", "in_stock", "stock_qty",
    "rating", "review_count", "tags", "variants", "reviews", "platform",
    "crawled_at",
]

# Columns added after the first release, for databases created before them.
MIGRATIONS = {
    "pack_kg": "REAL",
    "images": "TEXT",
    "videos": "TEXT",
    "specs": "TEXT",
    "sections": "TEXT",
    "content": "TEXT",
    "sku": "TEXT",
    "price_min": "REAL",
    "price_max": "REAL",
    "in_stock": "INTEGER",
    "stock_qty": "INTEGER",
    "rating": "REAL",
    "review_count": "INTEGER",
    "tags": "TEXT",
    "variants": "TEXT",
    "reviews": "TEXT",
    "platform": "TEXT",
}


class Storage:
    def __init__(self, dsn: str | None = None) -> None:
        raw = dsn if dsn is not None else os.getenv("DATABASE_URL", "")
        # A DSN arriving through a CI secret can carry a BOM, stray quotes or
        # a trailing newline depending on how it was stored.
        self.dsn = (raw or "").strip().strip('"').strip("'").lstrip("﻿")
        self.is_pg = self.dsn.startswith(("postgres://", "postgresql://"))

        # Falling back to SQLite when a DATABASE_URL was clearly intended is
        # how a scheduled run writes to a throwaway file on the CI machine and
        # still reports success. Refuse instead.
        if self.dsn and not self.is_pg:
            raise SystemExit(
                "DATABASE_URL is set but is not a Postgres connection string.\n"
                f"  got: {self.dsn[:24]!r}... ({len(self.dsn)} chars)\n"
                "Expected it to start with postgresql:// - check for stray "
                "quotes, a BOM, or a truncated value."
            )
        self._conn: Any = None

    def __enter__(self) -> "Storage":
        if self.is_pg:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - depends on env
                raise SystemExit(
                    "DATABASE_URL is Postgres but psycopg is missing.\n"
                    "Install it with:  pip install \"psycopg[binary]\""
                ) from exc
            self._conn = psycopg.connect(self.dsn)
            self._exec_script(SCHEMA_PG)
            log.info("storage: Postgres")
        else:
            DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(DEFAULT_SQLITE)
            self._conn.executescript(SCHEMA_SQLITE)
            self._conn.commit()
            log.info("storage: SQLite at %s", DEFAULT_SQLITE)
        self._migrate()
        return self

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        if self.is_pg:
            for col, ddl in MIGRATIONS.items():
                pg_type = "DOUBLE PRECISION" if ddl == "REAL" else ddl
                with self._conn.cursor() as cur:
                    cur.execute(
                        f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col} {pg_type}"
                    )
            self._conn.commit()
            return

        existing = {
            row[1] for row in self._conn.execute("PRAGMA table_info(products)")
        }
        for col, ddl in MIGRATIONS.items():
            if col not in existing:
                self._conn.execute(f"ALTER TABLE products ADD COLUMN {col} {ddl}")
                log.info("migrated: added column %s", col)
        self._conn.commit()

    def __exit__(self, *exc) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()

    def _exec_script(self, script: str) -> None:
        # Executed one statement at a time: psycopg only tolerates several per
        # execute() under specific conditions, and splitting costs nothing.
        with self._conn.cursor() as cur:
            for statement in filter(None, (s.strip() for s in script.split(";"))):
                cur.execute(statement)
        self._conn.commit()

    def _reconnect(self) -> None:
        """Reopen a dropped Postgres connection.

        A crawl spends minutes fetching between writes, and a hosted database
        is entitled to close a connection that has been idle that long. The
        first write afterwards fails, which used to abandon every shop that
        had not been crawled yet.
        """
        import psycopg

        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = psycopg.connect(self.dsn)
        log.info("storage: reconnected to Postgres")

    def _with_retry(self, action):
        """Run a database call, once more on a fresh connection if it drops."""
        if not self.is_pg:
            return action()
        import psycopg

        try:
            return action()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            log.warning("database connection lost (%s), reconnecting", exc)
            self._reconnect()
            return action()

    def record_history(self, products: Iterable[Product]) -> int:
        """Append a row for every product whose price or stock moved.

        Must run before save_many, while the products table still holds the
        previous observation to compare against.

        Only changes are appended. Writing all 800 products on every nightly
        run would fill the free tier inside a year with rows that all say the
        same thing, and a chart drawn from it would look identical either way.
        """
        products = list(products)
        if not products:
            return 0

        by_url = {p.url: p for p in products}
        previous = self._previous_observations(list(by_url))

        rows = []
        suspicious = 0
        for url, product in by_url.items():
            before = previous.get(url)
            now = (product.price, product.in_stock, product.stock_qty)
            if before is not None and before == now:
                continue

            # A genuine price move is a few percent. An order of magnitude
            # means a parsing change, a currency-scale mistake or a broken
            # page - and once written it looks exactly like real movement in
            # every chart drawn afterwards. Record it, but say so.
            old_price = before[0] if before else None
            if old_price and product.price:
                ratio = max(product.price / old_price, old_price / product.price)
                if ratio >= 20:
                    suspicious += 1
                    log.warning(
                        "implausible price change %.0fx on %s: %s -> %s",
                        ratio, url, old_price, product.price)
            observed = (_as_datetime(product.crawled_at) if self.is_pg
                        else product.crawled_at)
            rows.append((
                url, product.source, product.price,
                product.price_min, product.price_max,
                product.in_stock, product.stock_qty, observed,
            ))

        if suspicious:
            log.warning("%d of %d recorded changes look implausible - check the "
                        "price scale for this shop before trusting the history",
                        suspicious, len(rows))

        if not rows:
            return 0

        cols = ", ".join(HISTORY_COLUMNS)
        ph = ", ".join(["%s" if self.is_pg else "?"] * len(HISTORY_COLUMNS))
        sql = f"INSERT INTO price_history ({cols}) VALUES ({ph})"

        def write() -> None:
            if self.is_pg:
                with self._conn.cursor() as cur:
                    cur.executemany(sql, rows)
            else:
                self._conn.executemany(sql, rows)
            self._conn.commit()

        self._with_retry(write)
        return len(rows)

    def _previous_observations(self, urls: list[str]) -> dict[str, tuple]:
        """Last stored price and stock per URL, for the batch about to save."""
        if not urls:
            return {}

        # Chunked so the statement stays within parameter limits on a large
        # shop, and so one oversized listing cannot fail the whole batch.
        out: dict[str, tuple] = {}
        chunk = 200
        for start in range(0, len(urls), chunk):
            part = urls[start:start + chunk]
            marks = ", ".join(["%s" if self.is_pg else "?"] * len(part))
            sql = (f"SELECT url, price, in_stock, stock_qty FROM products "
                   f"WHERE url IN ({marks})")

            def read(sql=sql, part=part):
                if self.is_pg:
                    with self._conn.cursor() as cur:
                        cur.execute(sql, part)
                        return cur.fetchall()
                return list(self._conn.execute(sql, part))

            for url, price, in_stock, stock_qty in self._with_retry(read):
                out[url] = (price, in_stock, stock_qty)
        return out

    def save_many(self, products: Iterable[Product]) -> int:
        rows = [tuple(asdict(p)[c] for c in COLUMNS) for p in products]
        if not rows:
            return 0

        if self.is_pg:
            # crawled_at travels as an ISO string, but the Postgres column is
            # TIMESTAMPTZ and the driver would hand it over as text, which
            # Postgres refuses to coerce on insert.
            at = COLUMNS.index("crawled_at")
            rows = [
                r[:at] + (_as_datetime(r[at]),) + r[at + 1:]
                for r in rows
            ]

        cols = ", ".join(COLUMNS)
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in COLUMNS if c != "url")

        if self.is_pg:
            ph = ", ".join(["%s"] * len(COLUMNS))
            sql = (
                f"INSERT INTO products ({cols}) VALUES ({ph}) "
                f"ON CONFLICT (url) DO UPDATE SET {updates}"
            )

            def write() -> None:
                with self._conn.cursor() as cur:
                    cur.executemany(sql, rows)
                self._conn.commit()

            self._with_retry(write)
        else:
            ph = ", ".join(["?"] * len(COLUMNS))
            sql = (
                f"INSERT INTO products ({cols}) VALUES ({ph}) "
                f"ON CONFLICT(url) DO UPDATE SET {updates}"
            )
            self._conn.executemany(sql, rows)
            self._conn.commit()

        return len(rows)

    def _scalar(self, sql: str):
        def run():
            with self._conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()

        if self.is_pg:
            return self._with_retry(run)
        return list(self._conn.execute(sql))

    def count(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM products")[0][0]

    def count_by_source(self) -> list[tuple[str, int]]:
        return list(self._scalar(
            "SELECT source, COUNT(*) FROM products "
            "GROUP BY source ORDER BY COUNT(*) DESC"
        ))
