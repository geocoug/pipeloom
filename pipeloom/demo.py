"""
demo.py
=========

Demo task definitions and a demo worker function.
"""

from __future__ import annotations

import logging
import queue
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from .messages import (
    Msg,
    MsgTaskFinished,
    MsgTaskProgress,
    MsgTaskStarted,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DemoTask:
    """
    Static definition of a unit of work.

    Attributes:
        task_id (int): Stable numeric identifier for the task. Used as the
            primary key in SQLite and as the key for progress bar lookups.
        name (str): Display-friendly name shown in logs and progress UI.
        steps (int): Number of progress steps the *demo* worker will simulate.
            In real code, you can ignore this and emit MsgTaskProgress at your own cadence.
    """

    task_id: int
    name: str
    steps: int = 20


def demo_worker(task: DemoTask, msg_q: queue.Queue[Msg]) -> None:
    """
    Demo worker function.
    Replace this in your projects with real work (ETL steps, API calls, etc.).

    Args:
        task (DemoTask): The task definition containing metadata about the task.
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
