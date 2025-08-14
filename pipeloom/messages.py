"""
messages.py
===========

Typed message contracts used on the in-memory **Queue** between worker threads
and the single SQLite writer thread.

Why messages?
-------------
Workers should **never** touch SQLite directly (SQLite connections are not
thread-safe across threads). Instead, workers publish *intent* via small,
immutable dataclasses. The writer is the only component that owns a SQLite
connection and it executes the requested changes in a single, serialized place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskDef:
    """
    Static definition of a unit of work.

    Attributes
    ----------
    task_id:
        Stable numeric identifier for the task. Used as the primary key in
        SQLite and as the key for progress bar lookups.
    name:
        Display-friendly name shown in logs and progress UI.
    steps:
        Number of progress steps the *demo* worker will simulate.
        In real code, you can ignore this and emit MsgTaskProgress at your own cadence.
    """

    task_id: int
    name: str
    steps: int = 20


@dataclass(frozen=True)
class MsgTaskStarted:
    """
    Signal that a task has begun.
    Posted by a worker thread as soon as the task is admitted for work.
    """

    task_id: int
    name: str
    started_at: str  # ISO 8601 UTC string (avoid tz-naive datetimes over queues)


@dataclass(frozen=True)
class MsgTaskProgress:
    """
    Incremental progress signal.
    The writer translates this into a fractional progress column and updates the Rich bar.
    """

    task_id: int
    step: int
    total: int
    message: str = ""


@dataclass(frozen=True)
class MsgTaskFinished:
    """
    Final status + optional result payload for a completed or failed task.
    """

    task_id: int
    status: str  # "done" | "error" | "cancelled"
    finished_at: str  # ISO 8601 UTC string
    result: str | None = None
    message: str = ""


# Special object placed on the queue to request the writer to shut down cleanly.
SENTINEL: object = object()
