"""
db.py
=====

Low-level, thread-bound SQLite helpers (connection + schema + checkpoint).

Design rules:
-------------
- Create **one** connection in the writer thread; never share it across threads.
- Prefer WAL for on-disk DBs to allow concurrent readers during writes.
- Keep pragmas pragmatic: good performance without wrecking durability.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal


def connect(db_path: Path, *, wal: bool = True) -> sqlite3.Connection:
    """
    Create and configure a **thread-bound** SQLite connection.

    Must be called from the writer thread. The connection is not safe to pass
    to worker threads.

    Args:
        db_path (Path): Path to SQLite database (may be :memory:).
        wal (bool): Enable WAL mode for file-backed databases.

    Returns:
        sqlite3.Connection
    """
    conn = sqlite3.connect(db_path, timeout=60, check_same_thread=True)

    # Journal mode:
    if db_path == Path(":memory:"):
        conn.execute("PRAGMA journal_mode=MEMORY")
    else:
        conn.execute(f"PRAGMA journal_mode={'WAL' if wal else 'DELETE'}")

    # Pragmas: balanced defaults suitable for ETL-like workloads.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-100000")  # ~100MB page cache (negative means KB)
    conn.execute("PRAGMA wal_autocheckpoint=1000")  # periodic auto-checkpoints

    return conn


def init_schema(conn: sqlite3.Connection, *, store_task_status: bool) -> None:
    """
    Create optional tables used for observability (task_runs).

    If you set `store_task_status=False`, this becomes a no-op and the DB is
    entirely yours for domain tables (e.g., ETL outputs).

    Args:
        conn (sqlite3.Connection): The SQLite connection to use.
        store_task_status (bool): If True, create the `task_runs` table.
    """
    if not store_task_status:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_runs (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          status TEXT NOT NULL,          -- queued|running|done|error|cancelled
          progress REAL NOT NULL DEFAULT 0.0,  -- fraction 0..1
          message TEXT,
          started_at TEXT,
          finished_at TEXT,
          result TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);
        """,
    )
    conn.commit()


def wal_checkpoint(
    conn: sqlite3.Connection,
    mode: Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"] = "TRUNCATE",
) -> None:
    """
    Manually checkpoint the WAL into the main DB and (optionally) truncate -wal.

    Useful at shutdown or between phases to keep the main file tidy.

    Args:
        conn (sqlite3.Connection): The SQLite connection to use.
        mode (Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"]): The checkpoint mode.
    """
    conn.commit()
    conn.execute(f"PRAGMA wal_checkpoint({mode});").fetchone()
