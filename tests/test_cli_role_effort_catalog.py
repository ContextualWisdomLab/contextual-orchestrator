"""`--role-effort-catalog` is a real CLI on-ramp for the issue #568 catalog.

Before this test existed, ``TaskOrchestrator`` accepted ``role_effort_catalog``
(ADR 0021) but no caller in ``__main__.py`` ever passed a non-``None`` value:
the constructor kwarg was reachable only from direct Python callers, never
from the shipped CLI/server entrypoint. These tests pin the opt-in flag so a
regression (the flag silently stops reaching the constructor) fails CI.

They also pin a follow-up finding: ``default_role_effort_catalog()`` fails
closed (``unsupported_provider_fallback="abstain"``) for every role, while
ordinary real-provider agent configs and auto-discovered agents never set
``reasoning_effort_supported``. Wiring the flag straight into
``TaskOrchestrator`` without a startup check would let it construct
successfully and then raise ``EffortProfileError`` on every subsequent
request for any non-mock pool. The startup guard in
``_require_eligible_role_effort_agents`` rejects that combination up front,
for both the one-shot CLI prompt and `--serve`.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.__main__ import main  # noqa: E402
from contextual_orchestrator.orchestrator import TaskOrchestrator  # noqa: E402
from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402
    default_role_effort_catalog,
)


def test_role_effort_catalog_default_flag_reaches_task_orchestrator() -> None:
    """``--role-effort-catalog default`` must construct the orchestrator with it."""
    stdout = StringIO()
    with (
        patch.object(
            sys,
            "argv",
            ["contextual-orchestrator", "--role-effort-catalog", "default", "hi"],
        ),
        patch.object(sys, "stdout", stdout),
        patch(
            "contextual_orchestrator.__main__.TaskOrchestrator", side_effect=TaskOrchestrator
        ) as orchestrator_cls,
    ):
        main()
    assert orchestrator_cls.call_args.kwargs["role_effort_catalog"] == default_role_effort_catalog()
    result = json.loads(stdout.getvalue())
    assert result["reasoning_effort_snapshot"]["profile_version"]


def test_role_effort_catalog_omitted_keeps_catalog_none() -> None:
    """Omitting the flag must keep production payloads unchanged (catalog is None)."""
    stdout = StringIO()
    with (
        patch.object(sys, "argv", ["contextual-orchestrator", "hi"]),
        patch.object(sys, "stdout", stdout),
        patch(
            "contextual_orchestrator.__main__.TaskOrchestrator", side_effect=TaskOrchestrator
        ) as orchestrator_cls,
    ):
        main()
    assert orchestrator_cls.call_args.kwargs["role_effort_catalog"] is None
    result = json.loads(stdout.getvalue())
    assert "reasoning_effort_snapshot" not in result


def test_role_effort_catalog_rejects_unknown_value() -> None:
    """Only the documented 'default' catalog name is accepted; anything else fails closed."""
    with patch.object(
        sys,
        "argv",
        ["contextual-orchestrator", "--role-effort-catalog", "bogus"],
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an unknown --role-effort-catalog value must be rejected")


def _write_real_provider_agent_config(tmp_path: Path, *, reasoning_effort_supported: bool | None) -> Path:
    """Write a non-mock (real-provider-shaped) single-agent config for a test.

    Mirrors ``examples/agents.openai.json``: a real ``https://`` ``base_url``,
    which never auto-passes the mock:// support carve-out in
    ``agent_proves_reasoning_effort_support``. ``reasoning_effort_supported``
    is omitted entirely when ``None``, matching every shipped example config
    and every auto-discovered agent today.
    """
    agent: dict[str, object] = {
        "id": "general_agent",
        "model": "gpt-5.5",
        "base_url": "https://api.openai.com/v1",
        "credential_key": "OPENAI_API_KEY",
        "tags": ["reasoning", "writing", "planning", "analysis"],
        "priority": 1,
    }
    if reasoning_effort_supported is not None:
        agent["reasoning_effort_supported"] = reasoning_effort_supported
    config_path = tmp_path / "agents.json"
    config_path.write_text(json.dumps({"agents": [agent]}), encoding="utf-8")
    return config_path


def test_role_effort_catalog_default_rejects_unproven_real_provider_pool(tmp_path: Path) -> None:
    """A non-mock agent with unknown support must fail at startup, not per-request.

    Regression for the finding on PR #958: ``default_role_effort_catalog()``
    fails closed (``unsupported_provider_fallback="abstain"``) for every role,
    while an ordinary real-provider agent config never sets
    ``reasoning_effort_supported``. Before this guard, ``main()`` would
    construct successfully and only raise ``EffortProfileError`` deep inside
    the first ``apply_effort_profile`` call -- i.e. it would appear to work
    and then fail every request. It must instead be rejected here, before any
    request is attempted.
    """
    config_path = _write_real_provider_agent_config(tmp_path, reasoning_effort_supported=None)
    stderr = StringIO()
    with (
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--role-effort-catalog",
                "default",
                "--agents",
                str(config_path),
                "hi",
            ],
        ),
        patch.object(sys, "stderr", stderr),
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("an unproven real-provider pool must be rejected at startup")
    message = stderr.getvalue()
    assert "reasoning_effort_supported" in message
    assert str(config_path) in message


def test_role_effort_catalog_default_rejects_unproven_pool_before_serving() -> None:
    """The same startup guard covers `--serve`, not just the one-shot CLI prompt."""
    with (
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--serve",
                "--auth-token",
                "token",
                "--role-effort-catalog",
                "default",
                "--agents",
                "examples/agents.openai.json",
            ],
        ),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover
            raise AssertionError("--serve must not start with an unproven role-effort pool")
    assert not serve.called


def test_role_effort_catalog_default_allows_pool_with_explicit_support(tmp_path: Path) -> None:
    """A non-mock agent that explicitly declares support is enough to unlock the flag."""
    config_path = _write_real_provider_agent_config(tmp_path, reasoning_effort_supported=True)
    with (
        patch.object(
            sys,
            "argv",
            [
                "contextual-orchestrator",
                "--serve",
                "--auth-token",
                "token",
                "--role-effort-catalog",
                "default",
                "--agents",
                str(config_path),
            ],
        ),
        patch("contextual_orchestrator.__main__.serve") as serve,
    ):
        main()
    assert serve.called
