"""
progress.py
===========

Factory helpers for Rich progress managers.

We intentionally separate **overall** progress (sticky, remains visible at 100%)
from **per-task** progress (transient, disappears once all tasks complete).
Both share the same Console (see rlog.console).
"""

from __future__ import annotations

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from .rlog import console


def make_overall_progress() -> Progress:
    """
    Create the overall persistent progress manager.

    This remains visible after completion and is ideal for a single “All tasks: 100%”
    summary line once per-task bars disappear.

    Returns:
        Progress: The Rich Progress instance managing overall progress.
    """
    return Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        "•",
        TimeElapsedColumn(),
        "•",
        TimeRemainingColumn(),
        transient=False,  # keep final frame visible
        console=console,
        refresh_per_second=8,  # throttle repaints to avoid log spam jitter
        disable=not console.is_terminal,
    )


def make_task_progress() -> Progress:
    """
    Create the transient per-task progress manager.

    This hides when the context exits so your terminal remains tidy.

    Returns:
        Progress: The Rich Progress instance managing task bars.
    """
    return Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=True,  # auto-hide on exit
        console=console,
        refresh_per_second=8,
        disable=not console.is_terminal,
    )


def preregister_task_bars(task_progress: Progress, num_tasks: int) -> dict[int, TaskID]:
    """
    Pre-create one Rich bar per task and return a mapping {task_id -> TaskID}.

    Args:
        task_progress (Progress): The Rich Progress instance managing task bars.
        num_tasks (int): The total number of tasks to create bars for.

    Returns:
        dict[int, TaskID]: A mapping of task IDs to their Rich TaskIDs.

    Why up-front?
    -------------
    If a worker publishes a MsgTaskProgress before the writer has created the bar,
    updates can be lost. Pre-registering eliminates this race completely.
    """
    mapping: dict[int, TaskID] = {}
    for i in range(1, num_tasks + 1):
        mapping[i] = task_progress.add_task(f"[bold]task-{i}", total=100)
    return mapping
