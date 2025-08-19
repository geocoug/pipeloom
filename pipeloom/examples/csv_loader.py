#!/usr/bin/env python3
"""
csv_loader.py
====================

Batch load CSV files into a SQLite database with pipeloom:

- Each task corresponds to one CSV file in a folder.
- Worker reads the CSV with Python's csv.DictReader, then UPSERTs into SQLite.
- Demonstrates idempotent loads with ON CONFLICT, batching, and schema creation.

This example shows how pipeloom can manage classic "folder full of CSVs" ETL
scenarios without extra dependencies.
"""

from __future__ import annotations

import csv
import queue
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeloom.db import connect, wal_checkpoint
from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted
from pipeloom.rlog import setup_logging


@dataclass(frozen=True)
class CsvTask:
    task_id: int
    name: str
    csv_path: Path
    table: str
    key: str = "id"


DDL = """
CREATE TABLE IF NOT EXISTS items(
  id      TEXT PRIMARY KEY,
  name    TEXT,
  qty     INTEGER,
  price   REAL
);
"""


def upsert_rows(db_path: Path, table: str, key: str, rows: Iterable[dict]) -> int:
    con = connect(db_path=db_path, wal=True)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(DDL)
        con.commit()

        sample = next(iter(rows), None)
        if sample is None:
            return 0
        cols = list(sample.keys())
        col_list = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        update_list = ", ".join([f"{c}=excluded.{c}" for c in cols if c != key])
        sql = f"INSERT INTO {table}({col_list}) VALUES({placeholders}) ON CONFLICT({key}) DO UPDATE SET {update_list}"

        # reinsert sample then the rest in batches
        batch = [tuple(sample[c] for c in cols)]
        count = 1
        b = 5000

        def flush():
            nonlocal batch, count
            if batch:
                con.execute("BEGIN IMMEDIATE;")
                try:
                    con.executemany(sql, batch)
                    con.commit()
                except Exception:
                    con.rollback()
                    raise
                count += len(batch)
                batch = []

        for row in rows:
            batch.append(tuple(row.get(c) for c in cols))
            if len(batch) >= b:
                flush()
        flush()
        return count - 1  # minus the initial sample counted twice
    finally:
        wal_checkpoint(con, "TRUNCATE")
        con.close()


def make_worker(db_path: Path):
    def worker(task: CsvTask, msg_q: queue.Queue) -> None:
        started = datetime.now(UTC).isoformat()
        msg_q.put(MsgTaskStarted(task.task_id, task.name, started))
        try:
            total = 2
            msg_q.put(MsgTaskProgress(task.task_id, 1, total, "reading"))
            with task.csv_path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                # Clone iterable because upsert_rows peeks one row
                rows = list(reader)
            msg_q.put(MsgTaskProgress(task.task_id, 2, total, f"upserting:{len(rows)}"))
            n = upsert_rows(db_path, task.table, task.key, rows)
            finished = datetime.now(UTC).isoformat()
            msg_q.put(
                MsgTaskFinished(task.task_id, "done", finished, result=f"rows:{n}"),
            )
        except Exception as e:
            finished = datetime.now(UTC).isoformat()
            msg_q.put(MsgTaskFinished(task.task_id, "error", finished, message=str(e)))

    return worker


def main() -> None:
    setup_logging(1)
    db = Path("pipeloom.db")
    folder = Path("data")  # put your CSVs here
    tasks = [CsvTask(i, p.stem, p, "items") for i, p in enumerate(sorted(folder.glob("*.csv")), start=1)]
    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=4,
        wal=True,
        store_task_status=True,
        worker_fn=make_worker(db),
    )


if __name__ == "__main__":
    main()
