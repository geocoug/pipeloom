import sqlite3
from pathlib import Path

import pytest

from pipeloom.db import connect, init_schema, wal_checkpoint


def _pragma_as_str(conn: sqlite3.Connection, key: str) -> str:
    """Fetch PRAGMA value and normalize to a string."""
    val = conn.execute(f"PRAGMA {key};").fetchone()[0]
    return str(val)


@pytest.mark.db
def test_connect_in_memory_sets_memory_journal() -> None:
    conn = connect(Path(":memory:"), wal=True)
    try:
        assert _pragma_as_str(conn, "journal_mode").upper() == "MEMORY"
        # foreign_keys => 1 (enabled)
        assert _pragma_as_str(conn, "foreign_keys") in {"1", "True", "true"}
        # synchronous NORMAL may appear as "1" or "normal" across builds
        assert _pragma_as_str(conn, "synchronous").lower() in {"1", "normal"}
    finally:
        conn.close()


@pytest.mark.db
def test_connect_file_wal_and_delete(tmp_path: Path) -> None:
    db = tmp_path / "file.db"

    c1 = connect(db, wal=True)
    try:
        assert _pragma_as_str(c1, "journal_mode").upper() == "WAL"
        c1.execute("CREATE TABLE IF NOT EXISTS t(x INTEGER);")
        c1.commit()
    finally:
        c1.close()

    c2 = connect(db, wal=False)
    try:
        assert _pragma_as_str(c2, "journal_mode").upper() == "DELETE"
    finally:
        c2.close()


@pytest.mark.db
def test_init_schema_creates_and_writes(tmp_path: Path) -> None:
    db = tmp_path / "obs.db"
    conn = connect(db, wal=True)
    try:
        init_schema(conn, store_task_status=True)
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_runs';").fetchone()
        assert row is not None

        conn.execute(
            "INSERT INTO task_runs(id, name, status, progress) VALUES (?,?,?,?)",
            (1, "demo", "running", 0.0),
        )
        conn.commit()

        got = conn.execute("SELECT status, progress FROM task_runs WHERE id=1;").fetchone()
        assert got == ("running", 0.0)
    finally:
        conn.close()


@pytest.mark.db
def test_init_schema_noop_when_disabled(tmp_path: Path) -> None:
    db = tmp_path / "noop.db"
    conn = connect(db, wal=True)
    try:
        init_schema(conn, store_task_status=False)
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_runs';").fetchone()
        assert row is None
    finally:
        conn.close()


@pytest.mark.db
def test_wal_checkpoint_commits(tmp_path: Path) -> None:
    db = tmp_path / "ckpt.db"
    conn = connect(db, wal=True)
    try:
        conn.execute("BEGIN;")
        conn.execute("CREATE TABLE IF NOT EXISTS ck(x INTEGER);")
        conn.execute("INSERT INTO ck(x) VALUES (1),(2),(3);")
        wal_checkpoint(conn, mode="TRUNCATE")
        n = conn.execute("SELECT COUNT(*) FROM ck;").fetchone()[0]
        assert n == 3
        assert _pragma_as_str(conn, "journal_mode").upper() == "WAL"
    finally:
        conn.close()
