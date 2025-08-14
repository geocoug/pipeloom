from dataclasses import FrozenInstanceError

import pytest

from pipeloom.messages import MsgTaskFinished, MsgTaskProgress, MsgTaskStarted, TaskDef


def test_taskdef_defaults() -> None:
    t = TaskDef(task_id=7, name="t7")
    assert t.steps == 20
    assert t.task_id == 7
    assert t.name == "t7"


def test_messages_are_frozen() -> None:
    s = MsgTaskStarted(task_id=1, name="t1", started_at="2024-01-01T00:00:00Z")
    with pytest.raises(FrozenInstanceError):
        # type: ignore[attr-defined]
        s.task_id = 2
    p = MsgTaskProgress(task_id=1, step=1, total=3)
    with pytest.raises(FrozenInstanceError):
        # type: ignore[attr-defined]
        p.step = 2
    f = MsgTaskFinished(task_id=1, status="done", finished_at="2024-01-01T00:00:01Z")
    with pytest.raises(FrozenInstanceError):
        # type: ignore[attr-defined]
        f.status = "error"
