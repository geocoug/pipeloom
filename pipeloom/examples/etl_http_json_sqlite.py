#!/usr/bin/env python3
"""
etl_http_json_sqlite.py
=======================

Minimal ETL pipeline using pipeloom:

- Extract: fetch JSON from an HTTP API (JSONPlaceholder).
- Transform: select and normalize columns into a Polars DataFrame.
- Load: create/ensure SQLite tables, then UPSERT rows in batches.

This demonstrates how to orchestrate a realistic ETL workflow with pipeloom,
including progress reporting, schema enforcement, and retry handling.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import requests

from pipeloom.db import connect, wal_checkpoint
from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted
from pipeloom.rlog import logger, setup_logging

# ──────────────────────────────────────────────────────────────────────────────
# Task definition
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    task_id: int
    name: str
    url: str
    table: str
    schema_sql: str  # explicit CREATE TABLE IF NOT EXISTS ...
    select_cols: Iterable[str]
    key: str = "id"  # upsert key


# ──────────────────────────────────────────────────────────────────────────────
# ETL helpers
# ──────────────────────────────────────────────────────────────────────────────


def http_get_json(url: str, *, retries: int = 3, timeout: float = 15.0) -> list[dict]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("GET %s (attempt %d/%d)", url, attempt, retries)
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else [data]
        except (requests.RequestException, ValueError) as e:
            last_exc = e
            # simple backoff: 0.5, 1.0, 2.0
            time.sleep(0.5 * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


def transform_to_df(data: list[dict], select_cols: Iterable[str]) -> pl.DataFrame:
    if not data:
        # build empty DF with desired columns (all Null)
        return pl.DataFrame(schema=dict.fromkeys(select_cols, pl.Null))
    df = pl.DataFrame(data)
    # keep only the requested columns (create missing as Null)
    keep = []
    for c in select_cols:
        if c in df.columns:
            keep.append(c)
        else:
            df = df.with_columns(pl.lit(None).alias(c))
            keep.append(c)
    out = df.select(keep)
    # normalize some common types (optional but nice for demos)
    if "completed" in out.columns:
        out = out.with_columns(
            pl.col("completed")
            .cast(pl.Boolean, strict=False)
            .fill_null(False)
            .cast(pl.Int8),  # store as 0/1 per your schema
        )
    for c in ("id", "userId"):
        if c in out.columns:
            out = out.with_columns(pl.col(c).cast(pl.Int64, strict=False))
    return out


def ensure_schema(db_path: Path, ddl: str) -> None:
    con = connect(db_path=db_path, wal=True)
    try:
        con.execute(ddl)
        con.commit()
    finally:
        con.close()


def upsert_df(db_path: Path, table: str, key: str, df: pl.DataFrame) -> None:
    if df.is_empty():
        return
    con = connect(db_path=db_path, wal=True)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        cols = df.columns
        col_list = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        update_list = ", ".join([f"{c}=excluded.{c}" for c in cols if c != key])
        sql = f"""
            INSERT INTO {table}({col_list})
            VALUES ({placeholders})
            ON CONFLICT({key}) DO UPDATE SET
              {update_list}
        """
        chunk = 100_000
        for offset in range(0, df.height, chunk):
            view = df.slice(offset, min(chunk, df.height - offset))
            con.execute("BEGIN IMMEDIATE;")
            try:
                con.executemany(sql, view.iter_rows())
                con.commit()
            except Exception:
                con.rollback()
                raise
    finally:
        wal_checkpoint(con, "TRUNCATE")
        con.close()


# ──────────────────────────────────────────────────────────────────────────────
# Pipeloom worker config
# ──────────────────────────────────────────────────────────────────────────────


def make_worker(db_path: Path):
    def worker(task: Task, msg_q) -> None:
        started = datetime.now(UTC).isoformat()
        msg_q.put(MsgTaskStarted(task.task_id, task.name, started))
        try:
            total = 3
            raw = http_get_json(task.url)
            msg_q.put(MsgTaskProgress(task.task_id, 1, total, "extracted"))

            df = transform_to_df(raw, select_cols=task.select_cols)
            msg_q.put(MsgTaskProgress(task.task_id, 2, total, "transformed"))

            ensure_schema(db_path, task.schema_sql)
            upsert_df(db_path, task.table, task.key, df)
            msg_q.put(MsgTaskProgress(task.task_id, 3, total, "loaded"))

            finished = datetime.now(UTC).isoformat()
            msg_q.put(
                MsgTaskFinished(
                    task.task_id,
                    "done",
                    finished,
                    result=f"ok:{task.name}",
                ),
            )
        except Exception as e:
            finished = datetime.now(UTC).isoformat()
            msg_q.put(MsgTaskFinished(task.task_id, "error", finished, message=str(e)))

    return worker


def main() -> None:
    setup_logging(1)
    db = Path("pipeloom.db")

    posts = Task(
        1,
        "posts",
        url="https://jsonplaceholder.typicode.com/posts",
        table="posts",
        schema_sql="""
          CREATE TABLE IF NOT EXISTS posts(
            id      INTEGER PRIMARY KEY,
            userId  INTEGER,
            title   TEXT,
            body    TEXT
          );
        """,
        select_cols=("id", "userId", "title", "body"),
        key="id",
    )

    todos = Task(
        2,
        "todos",
        url="https://jsonplaceholder.typicode.com/todos",
        table="todos",
        schema_sql="""
          CREATE TABLE IF NOT EXISTS todos(
            id        INTEGER PRIMARY KEY,
            userId    INTEGER,
            title     TEXT,
            completed INTEGER
          );
        """,
        select_cols=("id", "userId", "title", "completed"),
        key="id",
    )

    run_pipeline(
        db_path=db,
        tasks=[posts, todos],
        workers=4,
        wal=True,
        store_task_status=True,
        worker_fn=make_worker(db),
    )


if __name__ == "__main__":
    main()
