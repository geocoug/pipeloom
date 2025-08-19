#!/usr/bin/env python3
"""
file_writer.py
====================

Pipeline example that writes binary files to disk:

- Each task generates a file of predictable size.
- Worker reports start/progress/finish events via pipeloom messages.
- Demonstrates safe tempfile handling, chunked writes, and file verification.

This is useful as a stress-test of I/O workloads or a template for file-based
pipelines.
"""

from __future__ import annotations

import logging
import os
import queue
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted
from pipeloom.rlog import setup_logging

logger = logging.getLogger(__name__)


class TaskFn(Protocol):
    def __call__(self, *, bytes_to_write: int, chunk_size: int = 1 << 20) -> Path: ...


@dataclass(frozen=True)
class Task:
    task_id: int
    name: str
    fn: TaskFn


def write_bytes(*, bytes_to_write: int, chunk_size: int = 1 << 20) -> Path:
    if bytes_to_write <= 0:
        raise ValueError("bytes_to_write must be > 0")
    with tempfile.NamedTemporaryFile(
        delete=False,
        mode="wb",
        prefix="pipeloom_",
        suffix=".bin",
    ) as f:
        remaining = bytes_to_write
        chunk = (b"Hello, world!\n" * 4096)[:chunk_size]
        while remaining > 0:
            to_write = chunk if remaining >= len(chunk) else chunk[:remaining]
            f.write(to_write)
            remaining -= len(to_write)
        f.flush()
        os.fsync(f.fileno())
        path = Path(f.name)
    actual = path.stat().st_size
    if actual != bytes_to_write:
        logger.warning(
            "Requested %d bytes but wrote %d bytes to %s",
            bytes_to_write,
            actual,
            path,
        )
    else:
        logger.info("Wrote %d bytes to %s", actual, path)
    return path


def make_worker() -> Callable[[Task, queue.Queue], None]:
    def worker(task: Task, msg_q) -> None:
        started_at = datetime.now(UTC).isoformat()
        msg_q.put(MsgTaskStarted(task.task_id, task.name, started_at))
        steps = 3
        try:
            workload_bytes = 1024 * 1024 * 1024 * task.task_id  # 1GB * id
            msg_q.put(
                MsgTaskProgress(task.task_id, 1, steps, f"plan:{workload_bytes}B"),
            )
            out_path = task.fn(bytes_to_write=workload_bytes, chunk_size=1 << 20)
            msg_q.put(MsgTaskProgress(task.task_id, 2, steps, "write"))
            size = out_path.stat().st_size
            msg_q.put(MsgTaskProgress(task.task_id, 3, steps, f"verify:{size}B"))
            finished_at = datetime.now(UTC).isoformat()
            msg_q.put(
                MsgTaskFinished(
                    task.task_id,
                    "done",
                    finished_at,
                    result=str(out_path),
                    message=f"wrote {size} bytes",
                ),
            )
        except Exception as e:
            finished_at = datetime.now(UTC).isoformat()
            msg_q.put(
                MsgTaskFinished(task.task_id, "error", finished_at, message=str(e)),
            )

    return worker


def main() -> None:
    setup_logging(1)
    tasks = [
        Task(1, "small-file", write_bytes),
        Task(2, "medium-file", write_bytes),
        Task(3, "larger-file", write_bytes),
    ]
    run_pipeline(
        db_path=Path("./pipeloom.db"),
        tasks=tasks,
        workers=4,
        wal=True,
        store_task_status=True,
        worker_fn=make_worker(),
    )


if __name__ == "__main__":
    main()
