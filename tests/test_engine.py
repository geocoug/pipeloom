import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted, TaskDef


def deterministic_worker(task: TaskDef, q) -> None:
    q.put(MsgTaskStarted(task.task_id, task.name, datetime.now(UTC).isoformat()))
    q.put(MsgTaskProgress(task.task_id, 1, 3, "phase-1"))
    q.put(MsgTaskProgress(task.task_id, 2, 3, "phase-2"))
    q.put(MsgTaskProgress(task.task_id, 3, 3, "phase-3"))
    q.put(MsgTaskFinished(task.task_id, "done", datetime.now(UTC).isoformat()))


@pytest.mark.engine
def test_engine_smoke(tmp_path: Path) -> None:
    db = tmp_path / "engine.db"
    tasks = [TaskDef(i, f"t{i}", steps=3) for i in range(1, 6)]

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
