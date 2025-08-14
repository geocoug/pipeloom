# Components & Flow

## High-level components

```mermaid
flowchart LR
  subgraph App["Your App / CLI (Typer)"]
    CLI["CLI"]
    ENG["Engine (orchestrator)"]
  end

  subgraph Work["Worker Threads (N)"]
    W1["Worker #1"]
    Wn["Worker #N"]
  end

  subgraph Writer["Writer Thread (single owner)"]
    Q["Queue[object]"]
    SW["SQLiteWriter (owns sqlite3.Connection)"]
  end

  subgraph DB["SQLite (optional)"]
    WAL["db-wal / db-shm"]
    MAIN["main db file"]
  end

  CLI --> ENG
  ENG -->|ThreadPoolExecutor| Work
  Work -->|Msg*| Q
  ENG -->|start| SW
  SW -->|consume| Q
  SW -->|INSERT/UPDATE| DB
  DB <--> WAL
```

## Key ideas

- Single writer: no cross-thread SQLite usage.
- Typed messages: workers emit intent; writer persists.
- Two progress managers: sticky overall, transient per-task.
