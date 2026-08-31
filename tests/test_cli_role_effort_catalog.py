"""`--role-effort-catalog` is a real CLI on-ramp for the issue #568 catalog.

Before this test existed, ``TaskOrchestrator`` accepted ``role_effort_catalog``
(ADR 0021) but no caller in ``__main__.py`` ever passed a non-``None`` value:
the constructor kwarg was reachable only from direct Python callers, never
from the shipped CLI/server entrypoint. These tests pin the opt-in flag so a
regression (the flag silently stops reaching the constructor) fails CI.
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
