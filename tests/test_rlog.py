import logging

import pytest
from rich.logging import RichHandler

import pipeloom.rlog as rlog


@pytest.mark.parametrize(
    "verbose,expected",
    [
        (0, logging.WARNING),
        (1, logging.INFO),
        (2, logging.DEBUG),
        (3, logging.DEBUG),  # 2+ -> DEBUG
    ],
)
def test_setup_logging_sets_levels_and_rich_handler(verbose: int, expected: int) -> None:
    # Reset root for a clean slate
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    logging.root.setLevel(logging.NOTSET)

    rlog.setup_logging(verbose, log_file=None)

    # Root now has a RichHandler using the shared console
    rich_handlers = [h for h in logging.root.handlers if isinstance(h, RichHandler)]
    assert rich_handlers, "Expected at least one RichHandler on root logger"
    for h in rich_handlers:
        assert getattr(h, "console", None) is rlog.console

    # Named logger level matches expectation
    assert rlog.logger.level == expected

    # Emit a message and ensure no exceptions; we won't rely on caplog here
    rlog.logger.debug("debug-ok")
    rlog.logger.info("info-ok")
    rlog.logger.warning("warn-ok")


def test_shared_console_is_used_by_richhandler() -> None:
    # Clean root
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    logging.root.setLevel(logging.NOTSET)

    rlog.setup_logging(1, log_file=None)
    rhs = [h for h in logging.root.handlers if isinstance(h, RichHandler)]
    assert rhs, "No RichHandler configured"
    for h in rhs:
        assert getattr(h, "console", None) is rlog.console
