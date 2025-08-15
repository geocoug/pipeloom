<div align="center">
    <img alt="pipeloom" title="pipeloom" width="120" src="https://raw.githubusercontent.com/geocoug/pipeloom/refs/heads/main/docs/assets/logo.png">
    <h1>pipeloom</h1>
    <p>Lightweight Python framework for orchestrating concurrent tasks with a single-writer persistence model and live progress tracking.</p>
</div>

<div align="center">
    <img alt="CI/CD" src="https://github.com/geocoug/pipeloom/actions/workflows/ci-cd.yaml/badge.svg">
    <img alt="Docs" src="https://readthedocs.org/projects/pipeloom/badge/?version=latest">
    <img alt="PyPI" src="https://img.shields.io/pypi/v/pipeloom.svg">
    <img alt="Downloads" src="https://img.shields.io/pypi/dm/pipeloom.svg?label=pypi%20downloads">
    <img alt="Python Version Support" src="https://img.shields.io/pypi/pyversions/pipeloom.svg">
</div>

<br />

## Features

- Orchestrate concurrent tasks using Python’s threading model.
- Persist results safely with a dedicated single-writer thread and SQLite in Write-Ahead Logging (WAL) mode.
- Track progress in real-time with Rich-powered progress bars.
- Define tasks and pipelines using a simple, declarative Python API.
- Run pipelines from the command line with a clean Typer-powered CLI.

## Quickstart

```bash
uv run pipeloom demo --db ./wal_demo.db --num-tasks 10 -vv
```

Or with Docker:

```bash
docker run -it --rm ghcr.io/geocoug/pipeloom:latest demo --db ./wal_demo.db --num-tasks 10 -vv
```

## Using pipeloom in Your ETL

1. Define tasks with `TaskDef(...)`.
2. Provide a `worker_fn(task, msg_q)` that emits:
   - `MsgTaskStarted`
   - `MsgTaskProgress` (at your own cadence)
   - `MsgTaskFinished`
3. Call:

```python
run_pipeline(db_path, tasks, workers=..., wal=True, store_task_status=True)
```

> Pass `store_task_status=False` if you don’t want the `task_runs` table.

## Design Principles

- All SQLite access happens in `SQLiteWriter` (one thread, one connection).
- Two progress managers:
  - **Overall**: remains after completion.
  - **Per-task**: disappears when done.
- Per-task bars are pre-registered to avoid race conditions.
- Task IDs can be `0` (falsy) — always check `task_id is not None`.

## Architecture

```mermaid
flowchart LR
  subgraph App["Your App / CLI (Typer)"]
    CLI["CLI (Typer)"]
    Engine["Engine (orchestrator)"]
  end

  subgraph Work["Worker Threads (N)"]
    W1["Worker #1"]
    Wn["Worker #N"]
  end

  subgraph Writer["SQLite Writer Thread"]
    Q["Queue[object]"]
    SW["SQLiteWriter (single sqlite3.Connection)"]
  end

  subgraph DB["SQLite Database"]
    WAL["db-wal / db-shm"]
    Main["main.db"]
  end

  CLI --> Engine
  Engine -->|ThreadPoolExecutor| Work
  Work -->|Messages| Q
  Engine -->|start| SW
  SW -->|consume| Q
  SW -->|INSERT/UPDATE| DB
  DB <--> WAL
```

**Why this works:**

Only the writer thread touches SQLite, avoiding cross-thread issues. WAL allows concurrent reads during writes. Workers communicate with the writer via typed messages in a queue.

## Extending

Two main extension points:

1. **Custom worker logic** — Workers do the work, then publish messages to the queue.
2. **Custom message types** — Add domain-specific messages and handle them in the writer.

Example: Adding a domain-specific message for upserts:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MsgUpsertRecord:
    table: str
    key: str
    payload: dict
```

Emit from a worker:

```python
q.put(MsgUpsertRecord(table="users", key="abc123", payload={"name": "Caleb", "active": 1}))
```

Handle in the writer:

```python
...
elif isinstance(item, MsgUpsertRecord):
    self._on_upsert(item)

def _on_upsert(self, m: MsgUpsertRecord):
    self._conn.execute(
        "INSERT INTO users(key, name, active) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, active=excluded.active",
        (m.key, m.payload["name"], m.payload["active"]),
    )
    self._conn.commit()
```

## Tuning for Performance

- Use **UPSERT** for idempotency.
- Batch inserts when possible.
- Adjust WAL checkpoints and cache size for workload.
- Use `synchronous=OFF` only for disposable datasets.

## Observability

Keep `task_runs` enabled unless you have a strong reason not to. Example queries:

```sql
SELECT status, COUNT(*) FROM task_runs GROUP BY status;
SELECT * FROM task_runs WHERE status <> 'done';
```

---

`pipeloom` is message-driven and single-writer by design, making it safe, extensible, and efficient for local ETL workloads.
