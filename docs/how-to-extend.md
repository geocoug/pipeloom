# How to Extend

You control two things:

1. **What work is done** — your worker function.
2. **What gets stored** — domain tables + optional `task_runs`.

## Custom worker

Workers never touch SQLite. They publish messages.

```python
from pipeloom.messages import TaskDef, MsgTaskStarted, MsgTaskProgress, MsgTaskFinished
from datetime import UTC, datetime
import time

def my_worker(task: TaskDef, q) -> None:
    q.put(MsgTaskStarted(task.task_id, task.name, datetime.now(UTC).isoformat()))
    try:
        total = 3
        # Extract
        time.sleep(0.1)
        q.put(MsgTaskProgress(task.task_id, 1, total, "extracted"))
        # Transform
        time.sleep(0.1)
        q.put(MsgTaskProgress(task.task_id, 2, total, "transformed"))
        # Load (emit a domain message for writer to persist)
        time.sleep(0.1)
        q.put(MsgTaskProgress(task.task_id, 3, total, "loaded"))

        q.put(MsgTaskFinished(task.task_id, "done", datetime.now(UTC).isoformat()))
    except Exception as e:
        q.put(MsgTaskFinished(task.task_id, "error", datetime.now(UTC).isoformat(), message=str(e)))
```

Run with your worker:

```py
from pathlib import Path
from pipeloom import run_pipeline, TaskDef, setup_logging

setup_logging(2, None)
tasks = [TaskDef(i, f"etl-{i}", steps=3) for i in range(1, 6)]
run_pipeline(Path("etl.db"), tasks, workers=4, wal=True, store_task_status=True, worker_fn=my_worker)
```

## Persist your domain data

Define a message:

```py
from dataclasses import dataclass

@dataclass(frozen=True)
class MsgUpsertUsersBatch:
    rows: list[tuple[str, str, int]]  # (key, name, active)
```

Emit from worker:

```py
q.put(MsgUpsertUsersBatch(rows))
```

Handle in writer:

```py
elif isinstance(item, MsgUpsertUsersBatch):
    self._conn.executemany(
        "INSERT INTO users(key, name, active) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, active=excluded.active",
        item.rows,
    )
    self._conn.commit()
```

Create your table via a schema helper called from the writer at startup.

## Tuning & tips

- Pre-register per-task bars and check tid is not None (TaskID 0 is valid).
- Keep task_runs on for observability; disable via store_task_status=False if you must.
- Batch inserts (executemany) for throughput.
- WAL is great for read concurrency; for max durability use PRAGMA synchronous=FULL.
