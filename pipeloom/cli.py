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
from typing import Annotated

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
    db: Annotated[Path, typer.Option("--db", help="SQLite DB path.")] = Path("./wal_demo.db"),
    no_wal: Annotated[bool, typer.Option("--no-wal", help="Do not use SQLite WAL mode.")] = False,
    num_tasks: Annotated[int, typer.Option("-n", "--num-tasks", help="How many demo tasks to run.")] = 20,
    workers: Annotated[int, typer.Option("-w", "--workers", help="Max concurrent worker threads.")] = os.cpu_count()
    or 4,
    verbose: Annotated[
        int,
        typer.Option("-v", "--verbose", count=True, help="Increase log verbosity (-v, -vv)."),
    ] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file", help="Optional log file path.")] = None,
    store_task_status: Annotated[
        bool,
        typer.Option(
            "-s",
            "--store-task-status",
            help="Persist task status to SQLite (disable to only use DB for domain data).",
        ),
    ] = False,
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
        not no_wal,
        db,
    )
    tasks = [TaskDef(task_id=i, name=f"task-{i}", steps=20) for i in range(1, num_tasks + 1)]

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=workers,
        wal=not no_wal,
        store_task_status=store_task_status,
    )


if __name__ == "__main__":
    app()
