import sqlite3

import pytest

from pipeloom.messages import SENTINEL, MsgTaskFinished, MsgTaskProgress, MsgTaskStarted
from pipeloom.writer import SQLiteWriter


@pytest.mark.writer
def test_writer_persists_and_clears(tmp_path, monkeypatch):
    db = tmp_path / "writer.db"
    q = __import__("queue").Queue(maxsize=64)

    w = SQLiteWriter(
        db_path=db,
        msg_q=q,
        wal=True,
        store_task_status=True,
        task_progress=None,
        task_bar_map=None,
    )
    w.start()

    q.put(MsgTaskStarted(task_id=1, name="t1", started_at="2024-01-01T00:00:00Z"))
    q.put(MsgTaskProgress(task_id=1, step=1, total=2, message="half"))
    q.put(MsgTaskProgress(task_id=1, step=2, total=2, message="done"))
    q.put(MsgTaskFinished(task_id=1, status="done", finished_at="2024-01-01T00:00:01Z"))

    q.put(SENTINEL)
    w.join(timeout=10)

    con = sqlite3.connect(db)
    try:
        row = con.execute("SELECT status, progress FROM task_runs WHERE id=1").fetchone()
        assert row == ("done", 1.0)
    finally:
        con.close()
