"""
cli.py
======

Typer-powered CLI that exposes a simple `pipeloom demo` command and serves as
a blueprint for wiring your own task definitions and worker functions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import typer

from .engine import run_pipeline
from .messages import TaskDef
from .rlog import setup_logging

LOG = logging.getLogger(__name__)

app = typer.Typer(
    help="Threaded ETL scaffolding with a single-writer SQLite (WAL).",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """
    Pipeloom: Threaded ETL scaffolding with a single-writer SQLite (WAL).

    Use one of the subcommands below to run a pipeline or perform other tasks.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command(name="demo")
def demo(
    db: Path = typer.Option(Path("./wal_demo.db"), help="SQLite DB path."),
    wal: bool = typer.Option(True, help="Use SQLite WAL mode."),
    num_tasks: int = typer.Option(20, min=1, help="How many demo tasks to run."),
    workers: int = typer.Option(
        os.cpu_count() or 4, min=1, help="Max concurrent worker threads."
    ),
    verbose: int = typer.Option(
        1, "--verbose", "-v", count=True, help="Increase log verbosity (-v, -vv)."
    ),
    log_file: Path | None = typer.Option(None, help="Optional log file path."),
    store_task_status: bool = typer.Option(
        True,
        help="Persist task status to SQLite (disable to only use DB for domain data).",
    ),
):
    """
    Run a demonstration pipeline that exercises the entire stack:

    - Worker threads emit progress and results to a Queue
    - A single writer thread updates SQLite in WAL mode
    - Rich renders per-task and overall progress cleanly
    """
    setup_logging(verbose, log_file)
    LOG.info(
        "Starting demo (tasks=%s, workers=%s, WAL=%s) → DB: %s",
        num_tasks,
        workers,
        wal,
        db,
    )

    tasks = [
        TaskDef(task_id=i, name=f"task-{i}", steps=20) for i in range(1, num_tasks + 1)
    ]

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=workers,
        wal=wal,
        store_task_status=store_task_status,
    )


if __name__ == "__main__":
    app()
