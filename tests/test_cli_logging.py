"""`--log-level`/`--verbose`/`--debug` CLI wiring and env-var precedence."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import main  # noqa: E402

_ENV_VAR = "CONTEXTUAL_ORCHESTRATOR_LOG_LEVEL"


@contextmanager
def _restored_root_logger() -> Iterator[None]:
    """Snapshot/restore root logger level+handlers so a test cannot leak global state."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)


@contextmanager
def _no_log_level_env() -> Iterator[None]:
    """Ensure the env var is absent so a developer's shell cannot leak into a test."""
    previous = os.environ.pop(_ENV_VAR, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[_ENV_VAR] = previous


def _run_one_shot(extra_args: list[str]) -> None:
    with patch.object(
        sys,
        "argv",
        ["contextual-orchestrator", "--agents", "examples/agents.mock.json", *extra_args, "hello"],
    ):
        main()


def test_help_text_lists_log_level_flag() -> None:
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    help_text = stdout.getvalue()
    assert "--log-level" in help_text
    assert "--verbose" in help_text
    assert "--debug" in help_text


def test_register_credential_help_lists_log_level_flag() -> None:
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "register-credential", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    assert "--log-level" in stdout.getvalue()


def test_discover_models_help_lists_log_level_flag() -> None:
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "discover-models", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    assert "--log-level" in stdout.getvalue()


def test_default_level_is_warning_without_any_flag_or_env() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot([])
        assert logging.getLogger().getEffectiveLevel() == logging.WARNING


def test_explicit_log_level_flag_sets_effective_level() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot(["--log-level", "DEBUG"])
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_log_level_flag_is_case_insensitive() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot(["--log-level", "info"])
        assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_verbose_flag_is_equivalent_to_debug_log_level() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot(["--verbose"])
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_debug_flag_is_a_synonym_for_verbose() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot(["--debug"])
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_explicit_log_level_overrides_verbose_flag() -> None:
    with _restored_root_logger(), _no_log_level_env():
        _run_one_shot(["--verbose", "--log-level", "ERROR"])
        assert logging.getLogger().getEffectiveLevel() == logging.ERROR


def test_log_level_env_var_sets_default() -> None:
    with _restored_root_logger():
        os.environ[_ENV_VAR] = "DEBUG"
        try:
            _run_one_shot([])
        finally:
            del os.environ[_ENV_VAR]
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_explicit_flag_overrides_env_var() -> None:
    with _restored_root_logger():
        os.environ[_ENV_VAR] = "DEBUG"
        try:
            _run_one_shot(["--log-level", "WARNING"])
        finally:
            del os.environ[_ENV_VAR]
        assert logging.getLogger().getEffectiveLevel() == logging.WARNING


def test_invalid_log_level_exits_with_argparse_error_not_traceback() -> None:
    stderr = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "--log-level", "SUPER_VERBOSE", "hello"],
        ),
        patch.object(sys, "stderr", stderr),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an invalid log level must exit(2)")
    error_text = stderr.getvalue()
    assert "SUPER_VERBOSE" in error_text
    assert "Traceback" not in error_text


def test_invalid_log_level_env_var_exits_with_argparse_error() -> None:
    stderr = StringIO()
    with _restored_root_logger():
        os.environ[_ENV_VAR] = "SUPER_VERBOSE"
        try:
            with (
                patch.object(
                    sys, "argv", ["contextual-orchestrator", "--agents", "examples/agents.mock.json", "hello"]
                ),
                patch.object(sys, "stderr", stderr),
            ):
                try:
                    main()
                except SystemExit as exc:
                    assert exc.code == 2
                else:  # pragma: no cover
                    raise AssertionError("an invalid env-var log level must exit(2)")
        finally:
            del os.environ[_ENV_VAR]
    error_text = stderr.getvalue()
    assert "Traceback" not in error_text


def test_serve_path_configures_logging_before_serve_call() -> None:
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--serve",
                "--log-level",
                "DEBUG",
                "--auth-token",
                "local-token",
            ],
        ),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main()
        assert serve.called
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_discover_models_path_configures_logging() -> None:
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "discover-models", "--log-level", "DEBUG"],
        ),
        patch.object(sys, "stdout", StringIO()),
    ):
        main()
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_check_fast_mlsirm_path_configures_logging() -> None:
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "check-fast-mlsirm", "--verbose"],
        ),
        patch.object(sys, "stdout", StringIO()),
    ):
        try:
            main()
        except SystemExit:
            pass
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


if __name__ == "__main__":  # pragma: no cover
    test_help_text_lists_log_level_flag()
    test_register_credential_help_lists_log_level_flag()
    test_discover_models_help_lists_log_level_flag()
    test_default_level_is_warning_without_any_flag_or_env()
    test_explicit_log_level_flag_sets_effective_level()
    test_log_level_flag_is_case_insensitive()
    test_verbose_flag_is_equivalent_to_debug_log_level()
    test_debug_flag_is_a_synonym_for_verbose()
    test_explicit_log_level_overrides_verbose_flag()
    test_log_level_env_var_sets_default()
    test_explicit_flag_overrides_env_var()
    test_invalid_log_level_exits_with_argparse_error_not_traceback()
    test_invalid_log_level_env_var_exits_with_argparse_error()
    test_serve_path_configures_logging_before_serve_call()
    test_discover_models_path_configures_logging()
    test_check_fast_mlsirm_path_configures_logging()
    print("ok")
