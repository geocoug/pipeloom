from __future__ import annotations

import logging
import os
import queue
import signal
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from .messages import SENTINEL, Msg
from .progress import make_overall_progress, make_task_progress, preregister_task_bars
from .writer import SQLiteWriter

LOG = logging.getLogger(__name__)

TTask = TypeVar("TTask")


def _pick_workers[TTask](tasks: Iterable[TTask], explicit: int | None) -> int:
    """Determine the number of worker threads to use based on the task list and explicit count."""
    if explicit is not None:
        if explicit < 1:
            raise ValueError("workers must be >= 1")
        return explicit
    cpu = os.cpu_count() or 4
    try:
        n = len(tasks)  # type: ignore[arg-type]
        return max(1, min(cpu, n)) if n > 0 else max(1, cpu)
    except TypeError:
        return max(1, cpu)


def run_pipeline(
    tasks: Iterable[TTask],
    db_path: Path = Path("./pipeloom.db"),
    *,
    workers: int | None = None,
    wal: bool = True,
    store_task_status: bool = True,
    worker_fn: Callable[[TTask, queue.Queue[Msg]], None],
) -> None:
    """
    Execute a workload using a single-writer SQLite backend.

    Parameters
    ----------
    tasks : Iterable[TTask]
        Opaque task objects (functions, dataclasses, dicts, etc.). The engine
        does not inspect them; `worker_fn` knows how to run each.
    db_path : Path
        SQLite DB for pipeline metadata/observability.
    workers : int | None
        Max concurrent workers. Defaults to min(len(tasks), CPU count) when possible.
    wal : bool
        Enable SQLite WAL mode for better concurrency.
    store_task_status : bool
        Maintain `task_runs` table.
    worker_fn : Callable[[TTask, queue.Queue[Msg]], None]
        Invoked per task. Communicate via `msg_q`.

    Notes
    -----
    The writer thread is shut down *before* the per-task progress context exits,
    so the final frame shows only “All tasks 100%”.
    """
    all_tasks = list(tasks)
    n = len(all_tasks)
    workers = _pick_workers(all_tasks, workers)

    # Sized message queue; scale with worker count
    msg_q: queue.Queue[Msg] = queue.Queue(maxsize=max(64, workers * 8))

    # Gentle shutdown
    stop_event = threading.Event()

    def handle_sigint(signum, frame):  # type: ignore[override]
        LOG.warning("SIGINT received; finishing in-flight tasks, then exiting…")
        stop_event.set()

    # Install handler only in main thread
    try:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, handle_sigint)
    except Exception as e:
        LOG.debug("signal handler not installed: %r", e)

    overall_p = make_overall_progress()
    task_p = make_task_progress()

    start = time.time()
    writer: SQLiteWriter | None = None
    futures = []

    try:
        with overall_p:
            overall = overall_p.add_task("[cyan]All tasks", total=n)
            with task_p:
                bar_map = preregister_task_bars(task_p, n)

                # Start writer after bars exist
                writer = SQLiteWriter(
                    db_path=db_path,
                    msg_q=msg_q,
                    wal=wal,
                    store_task_status=store_task_status,
                    task_progress=task_p,
                    task_bar_map=bar_map,
                )
                writer.start()

                with ThreadPoolExecutor(
                    max_workers=workers,
                    thread_name_prefix="worker",
                ) as ex:
                    futures = [ex.submit(worker_fn, t, msg_q) for t in all_tasks]

                    try:
                        for fut in as_completed(futures):
                            if stop_event.is_set():
                                # Cancel whatever hasn't started yet
                                ex.shutdown(wait=False, cancel_futures=True)
                                break
                            # Surface exceptions here; let caller see failures
                            _ = fut.result()
                            overall_p.advance(overall, 1)
                    except KeyboardInterrupt:
                        LOG.warning("KeyboardInterrupt; requesting graceful stop…")
                        stop_event.set()
                        ex.shutdown(wait=False, cancel_futures=True)
                        # Drain any completed futures to surface exceptions
                        for fut in futures:
                            if fut.done():
                                try:
                                    _ = fut.result()
                                except (CancelledError, Exception) as e:
                                    LOG.error("Task error during shutdown: %s", e)

        # Ensure last UI refresh while task progress context is alive
        task_p.refresh()

    finally:
        # Always signal writer and join
        if writer is not None and writer.is_alive():
            try:
                msg_q.put(SENTINEL)
            except Exception as e:
                LOG.debug("Failed to enqueue SENTINEL: %s", e)
            writer.join(timeout=30)

        LOG.info("Elapsed: %.2fs", time.time() - start)
