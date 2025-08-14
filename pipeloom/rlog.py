"""
rlog.py
=======

Rich-aware logging. We create **one Console** and share it between RichHandler
(logging) and Rich Progress (live bars). Without a shared console, Rich would
render duplicate live regions and your terminal would flicker or show
repeated “All tasks” bars.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

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
