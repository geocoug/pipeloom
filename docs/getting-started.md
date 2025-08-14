# Getting Started

## Install

```bash
uv pip install -e .
```

(Optional) docs:

```bash
uv pip install -e ".[docs]"
uv run mkdocs serve
```

## Hello, Pipeloom

```py
from pathlib import Path
from pipeloom import TaskDef, run_pipeline, setup_logging

setup_logging(verbose=1)

tasks = [TaskDef(task_id=i, name=f"task-{i}", steps=10) for i in range(1, 6)]
run_pipeline(
  db_path=Path("loom.db"),
  tasks=tasks,
  workers=4,
  wal=True,
  store_task_status=True,
)
```

Run:

```bash
uv run python my_flow.py
```
