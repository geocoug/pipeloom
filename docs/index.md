# Pipeloom

**Threaded orchestration scaffold** with a single-writer pattern, [Rich] progress, and an optional SQLite (WAL) backend. Ideal for local ETL and task runners you can actually reason about.

- One **writer thread** owns the DB connection.
- Workers publish **typed messages** on a Queue.
- Clean **progress UI** (sticky overall + transient per-task).
- Fully typed, documented, and **extensible**.

[Rich]: https://github.com/Textualize/rich

!!! tip
    Not married to SQLite. Keep the pattern; swap the writer backend later.

## Quickstart

```bash
uv pip install -e ".[docs]"
uv run -m pipeloom.cli demo --db ./loom.db --num-tasks 8 -vv
```

You’ll see an overall “All tasks” bar and per-task bars that disappear when done, while the DB writer persists task state (toggle-able).
