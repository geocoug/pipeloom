import pytest
from rich.progress import Progress

from pipeloom.progress import (
    make_overall_progress,
    make_task_progress,
    preregister_task_bars,
)


@pytest.mark.progress
def test_progress_factories_return_progress_instances() -> None:
    overall = make_overall_progress()
    tasks = make_task_progress()
    try:
        assert isinstance(overall, Progress)
        assert isinstance(tasks, Progress)
        # Don't assert internal attributes like 'transient' (not part of public API)
    finally:
        overall.stop()
        tasks.stop()


@pytest.mark.progress
def test_preregister_task_bars_creates_expected_mapping() -> None:
    p = make_task_progress()
    try:
        mapping = preregister_task_bars(p, 5)
        assert set(mapping.keys()) == {1, 2, 3, 4, 5}
        # TaskID is an int (may be 0); ensure presence and updatability
        for i in range(1, 6):
            tid = mapping[i]
            assert isinstance(tid, int)
            p.update(tid, advance=0)  # should not raise
    finally:
        p.stop()
