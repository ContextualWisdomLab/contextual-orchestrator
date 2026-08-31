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

from contextual_orchestrator.__main__ import _configure_logging_from_cli, main  # noqa: E402

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


def test_log_level_flag_after_option_terminator_is_not_consumed() -> None:
    """A literal `--` stops the logging pre-scan from treating what follows as a flag.

    Confirms a Devin automated-review finding here ("parse_known_args still
    consumes --log-level after --") was a false positive: `parse_known_args`
    already respects stdlib argparse's `--` option-terminator semantics with
    no special-casing needed in `_configure_logging_from_cli` -- verified
    directly against the real pre-scan parser, not just argparse in the
    abstract.
    """
    with _restored_root_logger(), _no_log_level_env():
        _configure_logging_from_cli(["--", "--log-level", "DEBUG"])
        assert logging.getLogger().getEffectiveLevel() == logging.WARNING


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


def test_leading_verbose_flag_before_discover_models_still_dispatches() -> None:
    """A logging flag before the subcommand must not bypass subcommand dispatch.

    `main` used to locate the subcommand by checking only `arguments[0]`; a
    global logging flag placed first (e.g.
    ``python -m contextual_orchestrator --verbose discover-models``) would
    then occupy that position, so the actual subcommand name fell through
    unrecognized into the default one-shot completion parser and was parsed
    as if it were a prompt string instead.
    """
    stdout = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(sys, "argv", ["contextual-orchestrator", "--verbose", "discover-models", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    help_text = stdout.getvalue()
    assert "python -m contextual_orchestrator discover-models" in help_text
    assert "--agents-db" in help_text


def test_leading_log_level_flag_before_register_credential_still_dispatches() -> None:
    """Same bypass, exercised with `--log-level` (a value-taking flag) instead of a boolean one."""
    stdout = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "--log-level", "DEBUG", "register-credential", "--help"],
        ),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    help_text = stdout.getvalue()
    assert "python -m contextual_orchestrator register-credential" in help_text
    assert "--name NAME" in help_text


def test_leading_debug_flag_before_check_fast_mlsirm_still_dispatches() -> None:
    """`check-fast-mlsirm` takes no args of its own, but must still be reached."""
    stdout = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(sys, "argv", ["contextual-orchestrator", "--debug", "check-fast-mlsirm"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit:
            pass
    # _fast_mlsirm_runtime_status() always reports this key, whether or not
    # the optional fast-mlsirm dependency is installed in this interpreter --
    # its presence proves check-fast-mlsirm actually ran, rather than
    # "check-fast-mlsirm" being swallowed as a one-shot completion prompt.
    assert '"package": "fast-mlsirm"' in stdout.getvalue()


def test_check_fast_mlsirm_help_shows_help_without_running_diagnostic() -> None:
    """`check-fast-mlsirm --help` must show help and exit, not run the diagnostic.

    Regression test: before this fix, `_check_fast_mlsirm_command` took no
    arguments and ignored everything after the subcommand token, so
    `--help` silently ran the real diagnostic (and its process-exit code)
    instead of printing usage -- the one CLI subcommand where `--help`
    did something other than show help.
    """
    stdout = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(sys, "argv", ["contextual-orchestrator", "check-fast-mlsirm", "--help"]),
        patch.object(sys, "stdout", stdout),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:  # pragma: no cover
            raise AssertionError("--help must exit")
    help_text = stdout.getvalue()
    assert "python -m contextual_orchestrator check-fast-mlsirm" in help_text
    assert '"package": "fast-mlsirm"' not in help_text


def test_check_fast_mlsirm_rejects_unknown_option() -> None:
    """An unrecognized trailing option must fail closed, not be silently ignored."""
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "check-fast-mlsirm", "--not-a-real-option"],
        ),
        patch.object(sys, "stderr", StringIO()),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an unrecognized option must exit non-zero")


def test_leading_log_level_flag_before_serve_still_configures_and_serves() -> None:
    """`--serve` is a plain optional flag on the main parser, so it is unaffected by the
    subcommand-token bypass -- this locks that in as a regression guard.
    """
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--log-level",
                "DEBUG",
                "--serve",
                "--auth-token",
                "local-token",
            ],
        ),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main()
        assert serve.called
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_abbreviated_value_flag_before_subcommand_fails_closed_not_misrouted() -> None:
    """An abbreviated `--log-level` (e.g. `--log-l`) before a subcommand must fail closed.

    argparse's abbreviation matching and `_subcommand_token_index`'s plain
    string comparison used to disagree: argparse would accept `--log-l` as
    shorthand for `--log-level`, but the locator did not recognize it as a
    flag to skip past, so it treated `--log-l` itself as a (non-matching)
    subcommand token and fell through to the one-shot completion parser with
    the real subcommand name parsed as a prompt -- silently wrong, not an
    error. `allow_abbrev=False` on every parser here removes the
    disagreement instead: an abbreviated flag is now rejected everywhere
    with a clear argparse `SystemExit(2)`, never silently accepted by one
    parser and not the other.
    """
    stderr = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "--log-l", "DEBUG", "discover-models"],
        ),
        patch.object(sys, "stderr", stderr),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an abbreviated flag before a subcommand must exit(2)")
    assert "unrecognized arguments" in stderr.getvalue()


def test_abbreviated_boolean_flag_before_subcommand_fails_closed_not_misrouted() -> None:
    """Same property as above, for a boolean flag abbreviation (`--ver` for `--verbose`)."""
    stderr = StringIO()
    with (
        _restored_root_logger(),
        _no_log_level_env(),
        patch.object(sys, "argv", ["contextual-orchestrator", "--ver", "discover-models"]),
        patch.object(sys, "stderr", stderr),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an abbreviated flag before a subcommand must exit(2)")
    assert "unrecognized arguments" in stderr.getvalue()


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
