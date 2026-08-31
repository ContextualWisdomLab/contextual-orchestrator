"""`--verbose`/`CONTEXTUAL_ORCHESTRATOR_LOG_LEVEL` wiring in `__main__.py`.

`_configure_logging` is the one place that makes the package's already-safe
DEBUG/INFO audit-event evidence (see `test_verbose_debug_logging.py`)
actually visible in process output. These tests cover its own contract in
isolation, restoring the shared `contextual_orchestrator` logger's state
after each test so this file cannot leak configuration into any other test
in the suite.
"""

from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import (  # noqa: E402
    LOG_LEVEL_ENVIRONMENT_VARIABLE,
    _configure_logging,
    main,
)


@pytest.fixture(autouse=True)
def _restore_package_logger_state():
    """Snapshot and restore the shared package logger around every test here."""
    logger = logging.getLogger("contextual_orchestrator")
    original_level = logger.level
    original_handlers = list(logger.handlers)
    yield
    logger.setLevel(original_level)
    logger.handlers[:] = original_handlers


def test_configure_logging_noop_when_neither_env_nor_explicit_level_set(monkeypatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENVIRONMENT_VARIABLE, raising=False)
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    _configure_logging()
    assert logger.level == logging.NOTSET
    assert logger.handlers == []


def test_configure_logging_env_var_sets_level_and_attaches_handler(monkeypatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENVIRONMENT_VARIABLE, "DEBUG")
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    _configure_logging()
    assert logger.level == logging.DEBUG
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_configure_logging_explicit_level_wins_over_env_var(monkeypatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENVIRONMENT_VARIABLE, "WARNING")
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    _configure_logging("DEBUG")
    assert logger.level == logging.DEBUG


def test_configure_logging_is_idempotent_no_duplicate_handlers(monkeypatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENVIRONMENT_VARIABLE, "DEBUG")
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    _configure_logging()
    _configure_logging()
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1


def test_configure_logging_invalid_level_name_raises() -> None:
    with pytest.raises(ValueError, match="invalid"):
        _configure_logging("NOT_A_REAL_LEVEL")


def test_main_verbose_flag_enables_debug_level_logging(capsys) -> None:
    """`--verbose` on the main CLI path configures DEBUG before any routing runs."""
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    with patch.object(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "--verbose",
            "--agents",
            "examples/agents.mock.json",
            "hello",
        ],
    ):
        main()
    assert logger.level == logging.DEBUG
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_discover_models_verbose_flag_enables_debug_level_logging() -> None:
    """`--verbose` on the discover-models subcommand also configures DEBUG."""
    logger = logging.getLogger("contextual_orchestrator")
    logger.setLevel(logging.NOTSET)
    logger.handlers[:] = []
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "discover-models", "--verbose"]),
        patch.object(sys, "stdout", stdout),
    ):
        main()
    assert logger.level == logging.DEBUG
