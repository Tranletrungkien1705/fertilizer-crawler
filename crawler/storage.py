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
    crawled_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_products_name   ON products(name);
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
    crawled_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_products_name   ON products(name);
"""

COLUMNS = [
    "source", "url", "name", "price", "currency",
    "unit", "pack_kg", "brand", "category", "npk", "description", "crawled_at",
]

# Columns added after the first release, for databases created before them.
MIGRATIONS = {"pack_kg": "REAL"}


class Storage:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("DATABASE_URL") or ""
        self.is_pg = self.dsn.startswith(("postgres://", "postgresql://"))
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
            with self._conn.cursor() as cur:
                cur.executemany(sql, rows)
        else:
            ph = ", ".join(["?"] * len(COLUMNS))
            sql = (
                f"INSERT INTO products ({cols}) VALUES ({ph}) "
                f"ON CONFLICT(url) DO UPDATE SET {updates}"
            )
            self._conn.executemany(sql, rows)

        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        if self.is_pg:
            with self._conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM products")
                return cur.fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def count_by_source(self) -> list[tuple[str, int]]:
        sql = ("SELECT source, COUNT(*) FROM products "
               "GROUP BY source ORDER BY COUNT(*) DESC")
        if self.is_pg:
            with self._conn.cursor() as cur:
                cur.execute(sql)
                return list(cur.fetchall())
        return list(self._conn.execute(sql))
