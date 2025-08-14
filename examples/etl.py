import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from pipeloom import logger, setup_logging
from pipeloom.engine import run_pipeline
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted


@dataclass(frozen=True)
class TaskDef:
    task_id: int
    name: str
    dataframe: pl.DataFrame
    stg_table: str
    prod_table: str


def extract(task: TaskDef):
    # Extract data from the source
    # in this example the data have already been extracted so just sleep for a second
    logger.info("Doing extract for task %s", task.task_id)
    time.sleep(task.task_id)  # Simulate time-consuming extraction
    return task.dataframe


def transform(task, data):
    logger.info("Doing transform for task %s", task.task_id)
    # Multiply the ID column by 2
    return task.dataframe.with_columns((pl.col("id") * 2).alias("id"))


def load(task, records):
    logger.info("Doing load for task %s", task.task_id)
    # Simulate loading data into the database
    time.sleep(task.task_id)  # Simulate time-consuming loading
    return True


def etl_worker(task: TaskDef, q) -> None:
    started = datetime.now(UTC).isoformat()
    q.put(MsgTaskStarted(task_id=task.task_id, name=task.name, started_at=started))

    try:
        # Do real work here: extract → transform → load
        total = 3
        # Extract
        data = extract(task)  # your code
        q.put(MsgTaskProgress(task.task_id, 1, total, "extracted"))

        # Transform
        records = transform(task, data)  # your code
        q.put(MsgTaskProgress(task.task_id, 2, total, "transformed"))

        # Load (NOT via SQLite here — emit a domain message instead; see below)
        load(task, records)
        q.put(MsgTaskProgress(task.task_id, 3, total, "loaded"))

        finished = datetime.now(UTC).isoformat()
        q.put(MsgTaskFinished(task.task_id, "done", finished, result=f"ok:{task.name}"))

    except Exception as e:
        finished = datetime.now(UTC).isoformat()
        q.put(MsgTaskFinished(task.task_id, "error", finished, message=str(e)))


def main() -> None:
    tasks = [
        TaskDef(
            task_id=1,
            name="etl-1",
            dataframe=pl.DataFrame(
                {
                    "id": list(range(1, 1_000_000)),
                    "name": [f"Item {i}" for i in range(1, 1_000_000)],
                }
            ),
            stg_table="staging_table_1",
            prod_table="production_table_1",
        ),
        TaskDef(
            task_id=2,
            name="etl-2",
            dataframe=pl.DataFrame(
                {
                    "id": list(range(1, 500_000)),
                    "name": [f"Item {i}" for i in range(1, 500_000)],
                }
            ),
            stg_table="staging_table_2",
            prod_table="production_table_2",
        ),
        TaskDef(
            task_id=3,
            name="etl-3",
            dataframe=pl.DataFrame(
                {
                    "id": list(range(1, 50_000_000)),
                    "name": [f"Item {i}" for i in range(1, 50_000_000)],
                }
            ),
            stg_table="staging_table_3",
            prod_table="production_table_3",
        ),
    ]

    run_pipeline(
        db_path=Path("etl.db"),
        tasks=iter(tasks),
        workers=4,
        wal=True,
        store_task_status=True,
        worker_fn=etl_worker,
    )


if __name__ == "__main__":
    setup_logging(1)
    try:
        logger.info("Starting ETL pipeline...")
        main()
    except KeyboardInterrupt:
        logger.info("ETL pipeline interrupted.")
