# tests/test_demo.py
from __future__ import annotations

import queue
from dataclasses import FrozenInstanceError
from datetime import datetime
from typing import Any

import pytest

from pipeloom.demo import DemoTask, demo_worker
from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted


def drain(q: queue.Queue[Any]) -> list[Any]:
    items = []
    try:
        while True:
            items.append(q.get_nowait())
    except queue.Empty:
        pass
    return items


def test_demotask_defaults_and_immutability() -> None:
    t = DemoTask(task_id=1, name="demo")
    assert t.steps == 20  # default
    # frozen dataclass should not allow mutation
    with pytest.raises(FrozenInstanceError):
        # type: ignore[attr-defined]
        t.steps = 99


def test_demo_worker_happy_path(monkeypatch) -> None:
    # Make the worker deterministic & fast
    monkeypatch.setattr("pipeloom.demo.time.sleep", lambda *_: None)
    monkeypatch.setattr("pipeloom.demo.random.random", lambda: 0.0)

    q: queue.Queue[object] = queue.Queue()
    task = DemoTask(task_id=7, name="alpha", steps=3)

    demo_worker(task, q)
    msgs = drain(q)

    # Expect: 1 start + 3 progress + 1 finished = 5
    assert len(msgs) == 5
    assert isinstance(msgs[0], MsgTaskStarted)
    assert msgs[0].task_id == 7
    assert msgs[0].name == "alpha"
    assert isinstance(msgs[0].started_at, str) and msgs[0].started_at

    # Progress steps are 1..3
    progress = [m for m in msgs if isinstance(m, MsgTaskProgress)]
    assert [m.step for m in progress] == [1, 2, 3]
    assert all(m.total == 3 for m in progress)
    assert all(m.task_id == 7 for m in progress)
    assert progress[0].message.startswith("step 1/3")

    # Finished
    assert isinstance(msgs[-1], MsgTaskFinished)
    done = msgs[-1]
    assert done.status == "done"
    assert done.task_id == 7
    assert done.result == "ok:alpha"
    assert done.message == "completed"
    assert isinstance(done.finished_at, str) and done.finished_at
    # Basic ISO sanity (won't explode on parse)
    _ = datetime.fromisoformat(done.finished_at)


def test_demo_worker_error_path(monkeypatch) -> None:
    monkeypatch.setattr("pipeloom.demo.time.sleep", lambda *_: None)

    # Raise during the first loop iteration to trigger error handling
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return 0.0

    monkeypatch.setattr("pipeloom.demo.random.random", boom)

    q: queue.Queue[object] = queue.Queue()
    task = DemoTask(task_id=2, name="err", steps=5)

    demo_worker(task, q)
    msgs = drain(q)

    # Expect: start, then immediate finished(error). No progress.
    assert len(msgs) == 2
    assert isinstance(msgs[0], MsgTaskStarted)
    assert isinstance(msgs[1], MsgTaskFinished)
    fin = msgs[1]
    assert fin.status == "error"
    assert fin.task_id == 2
    assert fin.result is None
    assert "boom" in (fin.message or "")


def test_demo_worker_zero_steps(monkeypatch) -> None:
    monkeypatch.setattr("pipeloom.demo.time.sleep", lambda *_: None)
    monkeypatch.setattr("pipeloom.demo.random.random", lambda: 0.0)

    q: queue.Queue[object] = queue.Queue()
    task = DemoTask(task_id=3, name="zero", steps=0)

    demo_worker(task, q)
    msgs = drain(q)

    # Expect: start + finished, no progress
    assert len(msgs) == 2
    assert isinstance(msgs[0], MsgTaskStarted)
    assert isinstance(msgs[1], MsgTaskFinished)
    assert not any(isinstance(m, MsgTaskProgress) for m in msgs)
