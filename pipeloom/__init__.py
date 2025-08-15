"""
pipeloom
=======

Reusable scaffolding for ETL-style, multi-threaded pipelines with:

- One SQLite writer thread in WAL mode
- Workers publishing progress/results over a Queue
- Rich progress (sticky overall + transient per-task)
- Typer CLI

Top-level exports are provided for convenience so you can do:

    from pipeloom import (
        run_pipeline,
        SQLiteWriter,
        TaskDef,
        MsgTaskStarted,  # or alias: MsgTaskStart
        MsgTaskProgress,
        MsgTaskFinished,
        SENTINEL,
        make_overall_progress,
        make_task_progress,
        preregister_task_bars,
        console,
        logger
    )
"""

from .engine import run_pipeline
from .messages import (
    SENTINEL,
    MsgTaskFinished,
    MsgTaskProgress,
    MsgTaskStarted,
    TaskDef,
)
from .progress import (
    make_overall_progress,
    make_task_progress,
    preregister_task_bars,
)
from .rlog import (
    console,
    logger,
    setup_logging,
)  # shared Console and logger, useful for advanced usage
from .writer import SQLiteWriter

# Ergonomic alias to match common naming used by callers
MsgTaskStart = MsgTaskStarted

__all__ = [  # noqa
    # Core orchestration
    "run_pipeline",
    # Writer
    "SQLiteWriter",
    # Messages
    "TaskDef",
    "MsgTaskStarted",
    "MsgTaskStart",  # alias
    "MsgTaskProgress",
    "MsgTaskFinished",
    "SENTINEL",
    # Progress helpers
    "make_overall_progress",
    "make_task_progress",
    "preregister_task_bars",
    # Advanced: shared Console
    "console",
    "logger",
    "setup_logging",
]

__version__ = "0.0.5"
