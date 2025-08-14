from pathlib import Path

from typer.testing import CliRunner

import pipeloom.cli as cli

runner = CliRunner()


def test_cli_demo_invokes_pipeline_with_flags(monkeypatch, tmp_path: Path):
    called = {}

    def fake_setup_logging(verbose, log_file):
        called["setup_logging"] = (verbose, log_file)

    def fake_run_pipeline(*, db_path, tasks, workers, store_task_status, **_):
        called["run_pipeline"] = {
            "db_path": Path(db_path),
            "num_tasks": len(list(tasks)),
            "workers": workers,
            "store_task_status": store_task_status,
        }

    # Patch within the cli module's namespace
    monkeypatch.setattr(cli, "setup_logging", fake_setup_logging, raising=True)
    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline, raising=True)

    db = tmp_path / "cli_demo.db"

    # Keep args minimal to avoid CLI quirks: no "-v/-vv", no "--no-wal"
    result = runner.invoke(
        cli.app,
        [
            "demo",
            "--db",
            str(db),
            "--num-tasks",
            "7",
            "--workers",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output

    # Default verbose=1 when we don't pass -v
    assert called.get("setup_logging") == (1, None)
    rp = called.get("run_pipeline")
    assert rp is not None
    assert rp["db_path"] == db
    assert rp["num_tasks"] == 7
    assert rp["workers"] == 3
    # Default flags when not provided
    assert rp["store_task_status"] is False


def test_cli_demo_disable_task_status(monkeypatch, tmp_path: Path):
    called = {}
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **k: called.setdefault("setup_logging", True))

    def fake_run_pipeline(*, db_path, tasks, workers, store_task_status, **_):
        called["args"] = {
            "db_path": Path(db_path),
            "num_tasks": len(list(tasks)),
            "store_task_status": store_task_status,
        }

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline, raising=True)

    db = tmp_path / "cli_demo2.db"
    result = runner.invoke(
        cli.app,
        [
            "demo",
            "--db",
            str(db),
            "--num-tasks",
            "2",
            "--workers",
            "1",
            "--store-task-status",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["args"]["db_path"] == db
    assert called["args"]["num_tasks"] == 2
    assert called["args"]["store_task_status"] is True
