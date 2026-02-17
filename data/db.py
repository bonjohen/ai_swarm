"""Database connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path("ai_swarm.db")


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with recommended pragmas."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes from schema.sql."""
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)


def get_initialized_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Convenience: open connection and ensure schema exists."""
    conn = get_connection(db_path)
    init_schema(conn)
    return conn
