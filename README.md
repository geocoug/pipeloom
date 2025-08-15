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

## Why pipeloom?

Many workflows require concurrency, persistence, and monitoring — but existing solutions can be burdonsome to spin up, maintain, and integrate with your workflow. `pipeloom` aims to simplify this with a message-driven, single-writer model that’s safe, observable, and extensible.

### Who is it for?

- Data engineers needing lightweight pipelines without Airflow/Kubernetes.
- Analysts automating ETL locally or on servers.
- Developers who want concurrency + persistence without database lock headaches.

## Quickstart

Run the demo locally:

```bash
uv run pipeloom demo --db ./wal_demo.db --num-tasks 10 -vv
```

Or with Docker:

```bash
docker run -it --rm ghcr.io/geocoug/pipeloom:latest demo --db ./wal_demo.db --num-tasks 10 -vv
```

Example output (Rich progress bars):
![progress demo](https://raw.githubusercontent.com/geocoug/pipeloom/refs/heads/main/docs/assets/demo.gif)

## Features

- **Concurrent task orchestration** → Run many jobs at once safely.
- **Single-writer persistence** → No more SQLite `database locked` errors.
- **Live progress tracking** → Always know what’s running, failed, or complete.
- **Declarative API** → Define tasks and pipelines with minimal boilerplate.
- **CLI-first** → Run pipelines from the terminal with a Typer-powered CLI.

## Design Principles

- All SQLite access happens in one thread (`SQLiteWriter`).
- Two progress managers:
  - **Overall** (remains after completion).
  - **Per-task** (clears on finish).
- Workers never write to the DB directly; they send typed messages to the writer.

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

**Why this works**:

Only the writer thread touches SQLite. WAL mode allows concurrent reads during writes. Workers communicate via typed messages.

## Using pipeloom in Your ETL

1. Define tasks with `TaskDef(...)`.
2. Provide a `worker_fn(task, msg_q)` that emits:
   - `MsgTaskStarted`
   - `MsgTaskProgress`
   - `MsgTaskFinished`
3. Run:

```python
run_pipeline(db_path, tasks, workers=..., wal=True, store_task_status=True)
```

> Pass `store_task_status=False` if you don’t want the `task_runs` table.

## Extending pipeloom

### Custom worker logic

Workers perform the actual work, then publish messages.

### Custom message types

Add domain-specific messages and handle them in the writer.

Example: domain-specific upsert:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MsgUpsertRecord:
    table: str
    key: str
    payload: dict
```

Emit from worker:

```python
q.put(MsgUpsertRecord(table="users", key="abc123", payload={"name": "Caleb", "active": 1}))
```

Handle in writer:

```python
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

## Observability

Keep `task_runs` enabled unless you have a strong reason not to.

```sql
SELECT status, COUNT(*) FROM task_runs GROUP BY status;
SELECT * FROM task_runs WHERE status <> 'done';
```
