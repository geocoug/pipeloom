#!/usr/bin/env python3
from __future__ import annotations

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
# Task definition (URL → table). Keep it tiny and generic.
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebTask:
    task_id: int
    name: str
    url: str
    table: str
    # DDL for the target table — small & explicit per-task
    schema_sql: str
    # Columns to select from the source data
    select_cols: Iterable[str]
    # Primary key column for UPSERT
    key: str = "id"


# ──────────────────────────────────────────────────────────────────────────────
# ETL steps — tiny functions, no custom pipeline code beyond pipeloom messages
# ──────────────────────────────────────────────────────────────────────────────


def extract_json(url: str) -> list[dict]:
    """Download JSON from the web (kept small and dependency-free)."""
    logger.info("GET %s", url)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    # Ensure array-of-objects; JSONPlaceholder returns that already
    if isinstance(data, dict):
        data = [data]
    return data  # list[dict]


def transform_to_df(data: list[dict], select_cols: Iterable[str]) -> pl.DataFrame:
    """Turn list[dict] into Polars; select only the columns we want."""
    if not data:
        return pl.DataFrame(schema=dict.fromkeys(select_cols, pl.Null))
    df = pl.DataFrame(data)
    keep = [c for c in select_cols if c in df.columns]
    # Add missing columns (if any) as Nulls to keep schema stable
    for missing in set(select_cols) - set(keep):
        df = df.with_columns(pl.lit(None).alias(missing))
        keep.append(missing)
    return df.select(keep)


def ensure_schema(conn, ddl: str) -> None:
    conn.execute(ddl)
    conn.commit()


def upsert_df(db_path: Path, table: str, key: str, df: pl.DataFrame) -> None:
    """UPSERT rows with a short-lived connection (keeps example simple)."""
    if df.is_empty():
        return
    conn = connect(db_path=db_path, wal=True)
    try:
        # reasonable defaults for concurrent demo writes
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        cols = df.columns
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)
        update_list = ", ".join([f"{c}=excluded.{c}" for c in cols if c != key])

        sql = f"""
            INSERT INTO {table}({col_list})
            VALUES ({placeholders})
            ON CONFLICT({key}) DO UPDATE SET
              {update_list}
        """

        # stream in modest chunks to keep memory small if data is large
        chunk = 100_000
        for offset in range(0, df.height, chunk):
            view = df.slice(offset, min(chunk, df.height - offset))
            rows = view.iter_rows()  # iterator of tuples
            conn.executemany(sql, rows)
            conn.commit()
    finally:
        wal_checkpoint(conn, "TRUNCATE")
        conn.close()


def make_worker(db_path: Path):
    """Return a (task, msg_q) -> None callable for pipeloom."""

    def worker(task: WebTask, msg_q) -> None:
        started = datetime.now(UTC).isoformat()
        msg_q.put(MsgTaskStarted(task.task_id, task.name, started))
        try:
            total = 3

            # 1) Extract
            raw = extract_json(task.url)
            msg_q.put(MsgTaskProgress(task.task_id, 1, total, "extracted"))

            # 2) Transform (choose the columns you want in the final table)
            # For JSONPlaceholder posts: id, userId, title, body
            df = transform_to_df(raw, select_cols=task.select_cols)
            msg_q.put(MsgTaskProgress(task.task_id, 2, total, "transformed"))

            # 3) Load (ensure schema, then UPSERT)
            conn = connect(db_path=db_path, wal=True)
            try:
                ensure_schema(
                    conn,
                    task.schema_sql,
                )
            finally:
                conn.close()

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


# ──────────────────────────────────────────────────────────────────────────────
# Main: define tiny tasks → let pipeloom orchestrate the rest
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    setup_logging(1)
    logger.info("Starting minimal web → SQLite ETL with pipeloom…")

    db = Path("etl.db")

    # Example 1: JSONPlaceholder posts
    posts = WebTask(
        task_id=1,
        name="posts",
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

    # Example 2: JSONPlaceholder todos (different schema, same boilerplate)
    todos = WebTask(
        task_id=2,
        name="todos",
        url="https://jsonplaceholder.typicode.com/todos",
        table="todos",
        schema_sql="""
          CREATE TABLE IF NOT EXISTS todos(
            id        INTEGER PRIMARY KEY,
            userId    INTEGER,
            title     TEXT,
            completed INTEGER  -- store booleans as 0/1
          );
        """,
        select_cols=("id", "userId", "title", "completed"),
        key="id",
    )

    # Use the same worker; columns selected in transform_to_df will adapt
    worker_fn = make_worker(db)
    run_pipeline(
        db_path=db,
        tasks=[posts, todos],
        workers=4,
        wal=True,
        store_task_status=True,
        worker_fn=worker_fn,
    )

    logger.info("Done. Open %s and query tables: posts, todos", db.resolve())


if __name__ == "__main__":
    main()
