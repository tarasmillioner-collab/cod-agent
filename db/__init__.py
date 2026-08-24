"""SQLite-подключение: WAL, foreign keys, миграции из db/migrations/*.sql."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_utc TEXT NOT NULL)")
    applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.name in applied:
            continue
        sql = f.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
            for stmt in [x.strip() for x in sql.split(";") if x.strip()]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e2:
                    if "duplicate column" not in str(e2) and "already exists" not in str(e2):
                        raise
        conn.execute("INSERT INTO schema_migrations(name, applied_utc) VALUES (?, ?)", (f.name, now_utc()))
