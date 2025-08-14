"""
writer.py
=========

The **single** SQLite writer thread. It:

- Opens and owns the only SQLite connection (configured for WAL).
- Consumes message objects from a thread-safe Queue.
- Writes task status/progress to SQLite (optional).
- Updates/removes Rich per-task progress bars safely.

Why a single writer?
--------------------
SQLite allows multiple writers *serially*, but a single connection and a single
owning thread is the least surprising, highest-reliability approach. It also
avoids cross-thread connection misuse, which is a common source of bugs.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading

from rich.progress import Progress, TaskID

from . import db as dbmod
from .messages import SENTINEL, MsgTaskFinished, MsgTaskProgress, MsgTaskStarted

LOG = logging.getLogger(__name__)


class SQLiteWriter(threading.Thread):
    """
    Dedicated thread that exclusively writes to SQLite and manages per-task bars.

    Args:
        db_path (str): Path to the SQLite database file (or ':memory:').
        msg_q (queue.Queue[object]): Thread-safe queue from which this writer consumes message objects.
        wal (bool): Whether to enable WAL on file-backed databases.
        store_task_status (bool): Toggle persistence of task status into the `task_runs` table.
        task_progress (Progress | None): Rich Progress manager used for per-task bars (transient).
        task_bar_map (dict[int, TaskID] | None): Pre-registered mapping: task_id -> Rich TaskID (prevents render races).
    """

    def __init__(
        self,
        db_path: str,
        msg_q: queue.Queue[object],
        *,
        wal: bool = True,
        store_task_status: bool = True,
        task_progress: Progress | None = None,
        task_bar_map: dict[int, TaskID] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.db_path = db_path
        self.msg_q = msg_q
        self._use_wal = wal
        self._store = store_task_status
        self._progress = task_progress
        self._progress_tasks: dict[int, TaskID] = dict(task_bar_map or {})
        self._conn: sqlite3.Connection | None = None
        self._stop_flag = threading.Event()

    # --- message handlers --------------------------------------------------------------
    def _on_started(self, m: MsgTaskStarted) -> None:
        """Persist that a task has started (if enabled).

        Args:
            m (MsgTaskStarted): The message object containing task information.
        """
        assert self._conn is not None
        if self._store:
            self._conn.execute(
                """
                INSERT INTO task_runs (id,name,status,progress,started_at,message)
                VALUES (?,?, 'running', 0.0, ?, '')
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name, status='running', progress=0.0, started_at=excluded.started_at, message=''
                """,
                (m.task_id, m.name, m.started_at),
            )
            self._conn.commit()

    def _on_progress(self, m: MsgTaskProgress) -> None:
        """Update DB progress as fraction and drive the Rich bar.

        Args:
            m (MsgTaskProgress): The message object containing task progress information.
        """
        assert self._conn is not None
        pct = round(100.0 * (m.step / max(1, m.total)), 2)

        if self._store:
            self._conn.execute(
                "UPDATE task_runs SET progress=?, message=? WHERE id=?",
                (pct / 100.0, m.message, m.task_id),
            )
            self._conn.commit()

        # IMPORTANT: Rich TaskID can be 0; do not use `if tid:` or walrus in condition.
        if self._progress:
            tid = self._progress_tasks.get(m.task_id)
            if tid is not None:
                self._progress.update(tid, completed=int(pct))

    def _on_finished(self, m: MsgTaskFinished) -> None:
        """Write final status and remove the per-task bar cleanly.

        Args:
            m (MsgTaskFinished): The message object containing task information.
        """
        assert self._conn is not None
        if self._store:
            final = 1.0 if m.status == "done" else 0.0
            self._conn.execute(
                """
                UPDATE task_runs SET status=?, finished_at=?, progress=?, result=?, message=? WHERE id=?
                """,
                (m.status, m.finished_at, final, m.result, m.message, m.task_id),
            )
            self._conn.commit()

        if self._progress:
            tid = self._progress_tasks.pop(m.task_id, None)
            if tid is not None:
                self._progress.update(tid, completed=100)
                self._progress.remove_task(tid)
                self._progress.refresh()

    # --- thread run loop ---------------------------------------------------------------
    def run(self) -> None:
        """
        Lifecycle:
        - open connection
        - initialize schema (optional)
        - consume messages until SENTINEL arrives
        - checkpoint and close
        """
        try:
            self._conn = dbmod.connect(self.db_path, wal=self._use_wal)
            dbmod.init_schema(self._conn, store_task_status=self._store)
            LOG.info("DB writer started → %s (WAL=%s)", self.db_path, self._use_wal)

            while not self._stop_flag.is_set():
                try:
                    item = self.msg_q.get(timeout=0.5)  # small timeout to enable graceful exit
                except queue.Empty:
                    continue

                if item is SENTINEL:
                    self.msg_q.task_done()
                    break

                if isinstance(item, MsgTaskStarted):
                    self._on_started(item)
                elif isinstance(item, MsgTaskProgress):
                    self._on_progress(item)
                elif isinstance(item, MsgTaskFinished):
                    self._on_finished(item)
                else:
                    LOG.warning("Unknown message: %r", type(item))

                self.msg_q.task_done()

        finally:
            # Best-effort cleanup & checkpoint
            try:
                if self._conn:
                    self._conn.execute("ANALYZE;")
            except Exception:
                LOG.debug("ANALYZE failed", exc_info=True)

            if self._conn:
                with _Suppress(sqlite3.OperationalError):
                    dbmod.wal_checkpoint(self._conn, "TRUNCATE")
                    self._conn.close()
                self._conn = None

            LOG.info("DB writer stopped")


class _Suppress:
    """Minimal suppress helper to avoid importing contextlib."""

    def __init__(self, *exc_types):
        self.exc_types = exc_types

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, self.exc_types or (Exception,))
