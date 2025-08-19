#!/usr/bin/env python3
"""
http_downloader.py
=========================

Download remote files and record a manifest table with pipeloom:

- Each task downloads a URL to a local path.
- Worker computes SHA256 and size, then records metadata in SQLite.
- Demonstrates reproducible file pipelines and idempotent manifest tracking.

This pattern is common for data lakes or archival tasks, where provenance and
hashing are as important as the download itself.
"""

from __future__ import annotations

import hashlib
import queue
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeloom.db import connect
from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted
from pipeloom.rlog import setup_logging


@dataclass(frozen=True)
class DownloadTask:
    task_id: int
    name: str
    url: str
    dest: Path


DDL = """
CREATE TABLE IF NOT EXISTS manifest(
  url     TEXT PRIMARY KEY,
  path    TEXT NOT NULL,
  sha256  TEXT NOT NULL,
  size    INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
);
"""


def fetch(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(url, timeout=30) as r,  # noqa: S310
        dest.open("wb") as f,
    ):
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return dest


def sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def record(db: Path, url: str, dest: Path, digest: str, size: int) -> None:
    con = connect(db_path=db, wal=True)
    try:
        con.execute(DDL)
        con.execute(
            "INSERT INTO manifest(url, path, sha256, size, fetched_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET path=excluded.path, sha256=excluded.sha256, size=excluded.size, fetched_at=excluded.fetched_at",  # noqa: E501
            (url, str(dest), digest, size, datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def make_worker(db: Path):
    def worker(task: DownloadTask, msg_q: queue.Queue) -> None:
        msg_q.put(
            MsgTaskStarted(task.task_id, task.name, datetime.now(UTC).isoformat()),
        )
        try:
            total = 3
            msg_q.put(MsgTaskProgress(task.task_id, 1, total, "download"))
            out = fetch(task.url, task.dest)
            msg_q.put(MsgTaskProgress(task.task_id, 2, total, "hash"))
            digest, size = sha256(out)
            msg_q.put(MsgTaskProgress(task.task_id, 3, total, "record"))
            record(Path("downloads.db"), task.url, out, digest, size)
            msg_q.put(
                MsgTaskFinished(
                    task.task_id,
                    "done",
                    datetime.now(UTC).isoformat(),
                    result=f"{out.name}:{size}B",
                ),
            )
        except Exception as e:
            msg_q.put(
                MsgTaskFinished(
                    task.task_id,
                    "error",
                    datetime.now(UTC).isoformat(),
                    message=str(e),
                ),
            )

    return worker


def main() -> None:
    setup_logging(1)
    db = Path("pipeloom.db")
    out = Path("downloads")
    tasks = [
        DownloadTask(
            1,
            "robots-txt",
            "https://www.example.com/robots.txt",
            out / "robots.txt",
        ),
        DownloadTask(
            2,
            "iana-domains",
            "https://www.iana.org/domains/reserved",
            out / "reserved.html",
        ),
    ]
    run_pipeline(
        db_path=db,
        tasks=tasks,
        workers=3,
        wal=True,
        store_task_status=True,
        worker_fn=make_worker(db),
    )


if __name__ == "__main__":
    main()
