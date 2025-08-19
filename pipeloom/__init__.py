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

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from .engine import run_pipeline
from .messages import (
    SENTINEL,
    Msg,
    MsgTaskFinished,
    MsgTaskProgress,
    MsgTaskStarted,
)
from .progress import (
    make_overall_progress,
    make_task_progress,
    preregister_task_bars,
)
from .writer import SQLiteWriter

# Ergonomic alias to match common naming used by callers
MsgTaskStart = MsgTaskStarted
MsgTaskFinish = MsgTaskFinished

__all__ = [  # noqa
    # Core orchestration
    "run_pipeline",
    # Writer
    "SQLiteWriter",
    # Messages
    "MsgTaskStarted",
    "MsgTaskStart",  # alias
    "MsgTaskProgress",
    "MsgTaskFinished",
    "MsgTaskFinish",  # alias
    "Msg",
    "SENTINEL",
    # Progress helpers
    "make_overall_progress",
    "make_task_progress",
    "preregister_task_bars",
    # Advanced: shared Console
    "console",
    "setup_logging",
]

__version__ = "0.0.7"

# Single shared console for logs and progress.
console = Console(log_path=False)

logger = logging.getLogger("pipeloom")


def setup_logging(verbose: int, log_file: Path | None = None) -> None:
    """
    Configure logging.

    Args:
        verbose (int): 0 = WARNING, 1 = INFO, 2+ = DEBUG
        log_file (Path | None): If provided, a plain (non-Rich) file handler is added for CI/grep.
    """
    level = logging.WARNING if verbose <= 0 else logging.INFO if verbose == 1 else logging.DEBUG
    handlers: list[logging.Handler] = [
        RichHandler(
            rich_tracebacks=True,
            show_time=False,
            show_level=True,
            show_path=False,
            console=console,  # IMPORTANT: share with Progress
            markup=True,
        ),
    ]

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ),
        )
        handlers.append(fh)

    logging.basicConfig(level=level, format="%(message)s", handlers=handlers)
    logger.setLevel(level)
