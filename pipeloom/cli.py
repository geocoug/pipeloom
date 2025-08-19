"""
cli.py
======

Typer-powered CLI.

Commands:
- pipeloom demo               → run the built-in progress demo
- pipeloom examples etl       → HTTP JSON → Polars → SQLite
- pipeloom examples file-writer
- pipeloom examples csv       → CSV folder → SQLite upsert
- pipeloom examples download  → HTTP download → SHA256 manifest
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from .db import connect, init_schema, wal_checkpoint
from .demo import DemoTask, demo_worker
from .engine import run_pipeline
from .examples import (
    csv_loader,
    etl_http_json_sqlite,
    file_writer,
    http_downloader,
)
from .rlog import console, setup_logging

LOG = logging.getLogger(__name__)


# Status format enum
class StatusFormat(str, Enum):
    json = "json"
    table = "table"


app = typer.Typer(
    help="Lightweight Python framework for orchestrating concurrent tasks with a single-writer persistence model and live progress tracking.",  # noqa: E501
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

examples_app = typer.Typer(
    name="examples",
    help="Run bundled pipeloom examples. Each subcommand runs a self-contained demo.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(examples_app, name="examples")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """
    Pipeloom: Lightweight Python framework for orchestrating concurrent
    tasks with a single-writer persistence model and live progress tracking.

    Use one of the subcommands below to run a pipeline or perform other tasks.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ──────────────────────────────────────────────────────────────────────────────
# demo
# ──────────────────────────────────────────────────────────────────────────────


@app.command(name="demo")
def demo(
    db: Annotated[Path, typer.Option("--db", help="SQLite DB path.")] = Path(
        "./wal_demo.db",
    ),
    no_wal: Annotated[
        bool,
        typer.Option("--no-wal", help="Do not use SQLite WAL mode."),
    ] = False,
    num_tasks: Annotated[
        int,
        typer.Option("-n", "--num-tasks", help="How many demo tasks to run."),
    ] = 20,
    workers: Annotated[
        int,
        typer.Option("-w", "--workers", help="Max concurrent worker threads."),
    ] = os.cpu_count() or 4,
    verbose: Annotated[
        int,
        typer.Option(
            "-v",
            "--verbose",
            count=True,
            help="Increase log verbosity (-v, -vv).",
        ),
    ] = 1,
    log_file: Annotated[
        Path | None,
        typer.Option("-l", "--log-file", help="Optional log file path."),
    ] = None,
    store_task_status: Annotated[
        bool,
        typer.Option(
            "-s",
            "--store-task-status",
            help="Persist task status to SQLite (disable to only use DB for domain data).",
        ),
    ] = False,
):
    """Run a demonstration pipeline that exercises the entire stack."""
    setup_logging(verbose, log_file)
    LOG.info(
        "Starting demo (tasks=%s, workers=%s, WAL=%s) → DB: %s",
        num_tasks,
        workers,
        not no_wal,
        db,
    )
    tasks = [DemoTask(task_id=i, name=f"task-{i}", steps=20) for i in range(1, num_tasks + 1)]

    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=workers,
        wal=not no_wal,
        store_task_status=store_task_status,
        worker_fn=demo_worker,
    )


# ──────────────────────────────────────────────────────────────────────────────
# examples group
# ──────────────────────────────────────────────────────────────────────────────


@examples_app.command("etl")
def examples_etl(
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file")] = None,
):
    """HTTP JSON → Polars → SQLite (posts, todos)."""
    setup_logging(verbose, log_file)
    etl_http_json_sqlite.main()


@examples_app.command("file-writer")
def examples_file_writer(
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file")] = None,
):
    """Write deterministic-size binary files and record progress."""
    setup_logging(verbose, log_file)
    file_writer.main()


@examples_app.command("csv")
def examples_csv(
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file")] = None,
):
    """Load a folder of CSVs into SQLite with UPSERT."""
    setup_logging(verbose, log_file)
    csv_loader.main()


@examples_app.command("download")
def examples_download(
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file")] = None,
):
    """Download files, compute SHA256, and record a manifest."""
    setup_logging(verbose, log_file)
    http_downloader.main()


# ──────────────────────────────────────────────────────────────────────────────
# run
# ──────────────────────────────────────────────────────────────────────────────


def _parse_kwargs(items: tuple[str]) -> dict[str, Any]:
    out = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"Invalid arg '{item}', expected key=value")
        k, v = item.split("=", 1)
        # simple coercion: ints/bools
        if v.lower() in {"true", "false"}:
            v = v.lower() == "true"
        else:
            try:
                v = int(v)
            except ValueError as e:
                typer.echo(f"Failed to parse '{v}' as int: {e}")
        out[k] = v
    return out


@app.command("run")
def run(
    target: Annotated[
        str,
        typer.Argument(help="Import path, e.g. 'mypkg.mymodule:main'"),
    ],
    arg: Annotated[
        tuple[str] | None,
        typer.Option("--arg", help="Pass key=value to target."),
    ] = None,
    verbose: Annotated[int, typer.Option("-v", "--verbose", count=True)] = 1,
    log_file: Annotated[Path | None, typer.Option("-l", "--log-file")] = None,
):
    """
    Dynamically import and run a user-specified function.

    Example:
        pipeloom run mypackage.mypipeline:main
    """
    setup_logging(verbose, log_file)

    if ":" not in target:
        typer.echo("Target must be in form 'module:function'", err=True)
        raise typer.Exit(1)

    module_name, func_name = target.split(":", 1)
    try:
        mod = importlib.import_module(module_name)
        fn: Callable = getattr(mod, func_name)
    except Exception as e:
        typer.echo(f"Import error: {e}", err=True)
        raise typer.Exit(1) from e

    kwargs = _parse_kwargs(arg)
    LOG.info("Running %s:%s(%s)", module_name, func_name, kwargs)
    try:
        rc = fn(**kwargs)
        raise typer.Exit(0 if (rc in (None, 0)) else int(rc))
    except Exception as e:
        typer.echo(f"Pipeline failed: {e}", err=True)
        raise typer.Exit(1) from e


# ──────────────────────────────────────────────────────────────────────────────
# status
# ──────────────────────────────────────────────────────────────────────────────


@app.command("status")
def status(
    db: Annotated[Path, typer.Option("--db", help="SQLite DB path.")] = Path(
        "./pipeloom.db",
    ),
    limit: Annotated[int, typer.Option("-n", "--limit", help="Rows to show.")] = 20,
    format: Annotated[
        StatusFormat,
        typer.Option("--format", "-f"),
    ] = StatusFormat.table,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Refresh every second."),
    ] = False,
):
    """
    Show recent task runs and a status summary.
    """

    def _fetch(con):
        cur = con.cursor()
        cur.execute(
            "SELECT id, name, status, started_at, finished_at, message FROM task_runs ",
            "ORDER BY COALESCE(finished_at, started_at) DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    if not db.exists():
        typer.echo(f"No database found at {db}")
        raise typer.Exit(1)

    last_signature = None
    while True:
        con = sqlite3.connect(db)
        try:
            rows = _fetch(con)
        finally:
            con.close()

        signature = tuple(rows)
        if signature != last_signature:
            last_signature = signature
            if format == "json":
                payload = {
                    "rows": [
                        {
                            "id": r[0],
                            "name": r[1],
                            "status": r[2],
                            "started_at": r[3],
                            "finished_at": r[4],
                            "message": r[5],
                        }
                        for r in rows
                    ],
                }
                typer.echo(json.dumps(payload, indent=2))
            else:
                console.clear()
                table = Table(title=f"Recent Task Runs (latest {len(rows)})")
                for col in ["ID", "Name", "Status", "Started", "Finished", "Message"]:
                    table.add_column(col)
                for r in rows:
                    table.add_row(*(str(x) if x is not None else "" for x in r))
                console.print(table)

        if not watch:
            break
        time.sleep(1)


# ──────────────────────────────────────────────────────────────────────────────
# Initialize pipeloom database
# ──────────────────────────────────────────────────────────────────────────────


@app.command("init-db")
def init_db(
    db: Annotated[Path, typer.Option("--db", help="SQLite DB path.")] = Path(
        "./pipeloom.db",
    ),
):
    """Create observability tables if they do not exist."""
    with connect(db, wal=True) as con:
        init_schema(con, store_task_status=True)
        wal_checkpoint(con, "FULL")
    typer.echo(f"Initialized observability schema in {db}")


if __name__ == "__main__":
    app()
