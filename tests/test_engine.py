# tests/test_engine.py
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeloom.demo import DemoTask
from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted

# ──────────────────────────────────────────────────────────────────────────────
# Helpers (deterministic workers for the tests)
# ──────────────────────────────────────────────────────────────────────────────


def deterministic_worker(task: DemoTask, q) -> None:
    """Happy-path worker: emits start → progress(1..steps) → finished(done)."""
    now = datetime.now(UTC).isoformat()
    q.put(MsgTaskStarted(task.task_id, task.name, now))
    steps = getattr(task, "steps", 3) or 3
    for i in range(1, steps + 1):
        q.put(MsgTaskProgress(task.task_id, i, steps, f"phase-{i}"))
    q.put(MsgTaskFinished(task.task_id, "done", datetime.now(UTC).isoformat()))


def error_worker(task: DemoTask, q) -> None:
    """Error-path worker: emits start, then finishes with status='error'."""
    q.put(MsgTaskStarted(task.task_id, task.name, datetime.now(UTC).isoformat()))
    q.put(
        MsgTaskFinished(
            task.task_id,
            "error",
            datetime.now(UTC).isoformat(),
            message="boom",
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.engine
def test_engine_smoke(tmp_path: Path) -> None:
    """All tasks finish successfully and are recorded as done."""
    db = tmp_path / "engine.db"
    tasks: list[DemoTask] = [DemoTask(i, f"t{i}", steps=3) for i in range(1, 6)]

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=3,
        wal=True,
        store_task_status=True,
        worker_fn=deterministic_worker,
    )

    con = sqlite3.connect(db)
    try:
        total, done = con.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) FROM task_runs",
        ).fetchone()
        assert total == 5
        assert done == 5
    finally:
        con.close()


@pytest.mark.engine
def test_engine_records_error_status(tmp_path: Path) -> None:
    """Engine/writer should persist error statuses when a worker reports them."""
    db = tmp_path / "engine.db"
    tasks: list[DemoTask] = [
        DemoTask(1, "ok-1", steps=2),
        DemoTask(2, "err-2", steps=2),
        DemoTask(3, "ok-3", steps=2),
    ]

    # Mixed workload: two succeed, one fails (by message)
    def mixed_worker(task: DemoTask, q) -> None:
        if task.name.startswith("err"):
            return error_worker(task, q)
        return deterministic_worker(task, q)

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=2,
        wal=True,
        store_task_status=True,
        worker_fn=mixed_worker,
    )

    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT name, status FROM task_runs ORDER BY name",
        ).fetchall()
        # Expect three rows with statuses: done, error, done
        assert len(rows) == 3
        status_by_name = dict(rows)
        assert status_by_name["ok-1"] == "done"
        assert status_by_name["ok-3"] == "done"
        assert status_by_name["err-2"] == "error"
    finally:
        con.close()


@pytest.mark.engine
def test_engine_workers_default_none(tmp_path: Path) -> None:
    """`workers=None` should still execute the pipeline successfully."""
    db = tmp_path / "engine.db"
    tasks: list[DemoTask] = [DemoTask(i, f"t{i}", steps=1) for i in range(1, 4)]

    # Use the engine's default worker-count logic
    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=None,  # type: ignore[arg-type]  # allow None for this test path
        wal=True,
        store_task_status=True,
        worker_fn=deterministic_worker,
    )

    con = sqlite3.connect(db)
    try:
        total, done = con.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) FROM task_runs",
        ).fetchone()
        assert total == 3
        assert done == 3
    finally:
        con.close()


@pytest.mark.engine
def test_engine_empty_task_list(tmp_path: Path) -> None:
    """Empty task list should be a no-op but still produce a healthy DB."""
    db = tmp_path / "engine.db"
    tasks: list[DemoTask] = []

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=1,
        wal=True,
        store_task_status=True,
        worker_fn=deterministic_worker,  # wont be called
    )

    con = sqlite3.connect(db)
    try:
        # Table may or may not exist depending on writer init logic.
        # If it exists, it should be empty; if not, DB is still valid.
        tables = {
            name
            for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).fetchall()
        }
        if "task_runs" in tables:
            (count,) = con.execute("SELECT COUNT(*) FROM task_runs").fetchone()
            assert count == 0
        # Basic sanity: DB opens and accepts pragma — writer shut down cleanly.
        con.execute("PRAGMA user_version")
    finally:
        con.close()
