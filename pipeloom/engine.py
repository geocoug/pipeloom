"""
engine.py
=========

Pipeline orchestration:

- Builds two Rich progress managers (overall sticky / per-task transient).
- Pre-registers per-task bars to avoid UI races.
- Starts the SQLite writer thread.
- Submits work to a ThreadPoolExecutor.
- Signals the writer with SENTINEL and joins while the transient progress
  is still live, so bars vanish before the final frame is rendered.
"""

from __future__ import annotations

import logging
import queue
import random
import signal
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from .messages import (
    SENTINEL,
    MsgTaskFinished,
    MsgTaskProgress,
    MsgTaskStarted,
    TaskDef,
)
from .progress import make_overall_progress, make_task_progress, preregister_task_bars
from .writer import SQLiteWriter

LOG = logging.getLogger(__name__)


def default_worker(task: TaskDef, msg_q: queue.Queue[object]) -> None:
    """
    Demo worker function.
    Replace this in your projects with real work (ETL steps, API calls, etc.).

    Args:
        task (TaskDef): The task definition containing metadata about the task.
        msg_q (queue.Queue[object]): The message queue to send progress updates and results.
    """
    started = datetime.now(UTC).isoformat()
    msg_q.put(MsgTaskStarted(task_id=task.task_id, name=task.name, started_at=started))
    try:
        for step in range(1, task.steps + 1):
            time.sleep(0.05 + random.random() * 0.05)  # noqa
            msg_q.put(
                MsgTaskProgress(
                    task_id=task.task_id,
                    step=step,
                    total=task.steps,
                    message=f"step {step}/{task.steps}",
                ),
            )
        finished = datetime.now(UTC).isoformat()
        msg_q.put(
            MsgTaskFinished(
                task_id=task.task_id,
                status="done",
                finished_at=finished,
                result=f"ok:{task.name}",
                message="completed",
            ),
        )
    except Exception as e:
        finished = datetime.now(UTC).isoformat()
        msg_q.put(
            MsgTaskFinished(
                task_id=task.task_id,
                status="error",
                finished_at=finished,
                result=None,
                message=str(e),
            ),
        )


def run_pipeline(
    db_path: Path,
    tasks: Iterable[TaskDef],
    *,
    workers: int,
    wal: bool = True,
    store_task_status: bool = True,
    worker_fn: Callable[[TaskDef, queue.Queue[object]], None] = default_worker,
) -> None:
    """
    Execute an ETL-style workload using a single-writer SQLite backend.

    Args:
        db_path (Path): Target SQLite database path.
        tasks (Iterable[TaskDef]): Iterable of TaskDef instances (one per unit of work).
        workers (int): Maximum number of concurrent worker threads.
        wal (bool): Enable WAL mode for the writer (recommended for file-backed DBs).
        store_task_status (bool): If True, create and maintain the `task_runs` table for observability.
        worker_fn (Callable[[TaskDef, queue.Queue[object]], None]): Custom worker function.
        Callable invoked for each TaskDef (signature: (task, queue) -> None).

    Notes
    -----
    The writer thread is shut down *before* the per-task progress context exits,
    guaranteeing that all bars are removed and the final frame shows only the
    “All tasks 100%” line.
    """
    all_tasks = list(tasks)
    n = len(all_tasks)

    # Workers → Queue → Writer
    msg_q: queue.Queue[object] = queue.Queue(maxsize=max(64, workers * 8))

    # Gentle shutdown: we don't hard-kill threads; we let in-flight tasks finish.
    stop_event = threading.Event()

    def handle_sigint(signum, frame):  # type: ignore[override]
        LOG.warning("SIGINT received; finishing in-flight tasks, then exiting…")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    # Build progress managers that share the same Console (see rlog.py).
    overall_p = make_overall_progress()
    task_p = make_task_progress()

    with overall_p:
        overall = overall_p.add_task("[cyan]All tasks", total=n)
        with task_p:
            # Pre-register bars to avoid creation races.
            bar_map = preregister_task_bars(task_p, n)

            # Start the writer *after* bars are created, passing the mapping.
            writer = SQLiteWriter(
                db_path=db_path,
                msg_q=msg_q,
                wal=wal,
                store_task_status=store_task_status,
                task_progress=task_p,
                task_bar_map=bar_map,
            )
            writer.start()

            start = time.time()

            # Submit work to a thread pool.
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="worker") as ex:
                futures = [ex.submit(worker_fn, t, msg_q) for t in all_tasks]
                try:
                    for fut in as_completed(futures):
                        _ = fut.result()  # surface exceptions
                        overall_p.advance(overall, 1)  # advance only when a task finishes
                        if stop_event.is_set():
                            break
                except KeyboardInterrupt:
                    LOG.warning("KeyboardInterrupt; letting in-flight tasks finish…")

            # Shut down writer while the transient progress is still alive
            # so the last bar removal appears before the final frame.
            msg_q.put(SENTINEL)
            writer.join(timeout=30)
            task_p.refresh()

    LOG.info("Elapsed: %.2fs", time.time() - start)
