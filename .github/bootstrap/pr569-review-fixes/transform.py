"""Apply test-first review fixes for PR #569."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]


def _replace_once(path: str, label: str, old: str, new: str) -> None:
    """Replace one exact source fragment and fail closed on drift."""
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old fragment, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def _write_tests() -> None:
    """Install RED tests for TLS production safety and retry policy bounds."""
    _replace_once(
        "tests/test_hourly_pr_maintenance_workflow.py",
        "literal scheduler event type",
        "    for expected in (\n"
        "        '\"target_repository\": \"ContextualWisdomLab/contextual-orchestrator\"',\n",
        "    for expected in (\n"
        "        '--arg event_type \"pr-review-fix-scheduler\"',\n"
        "        '\"target_repository\": \"ContextualWisdomLab/contextual-orchestrator\"',\n",
    )
    test_path = ROOT / "tests/test_tool_retry_tls_policy.py"
    test_path.write_text(
        '''"""Production TLS and bounded tool-retry policy contracts."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from contextual_orchestrator import (
    MAX_TOOL_RETRY_ATTEMPTS,
    ModelAgent,
    TaskOrchestrator,
)
from contextual_orchestrator.__main__ import main as cli_main
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.tool_fallback import ToolExecutionError, ToolFailureKind


@pytest.mark.parametrize("value", [None, 0, 1, 0.0, "", [], {}])
def test_provider_tls_verification_requires_an_exact_boolean(value: object) -> None:
    """Reject false-like non-booleans before an unverified context can be selected."""
    with pytest.raises(TypeError, match="verify_tls must be a boolean"):
        ModelClient(verify_tls=value)  # type: ignore[arg-type]


def test_http_serve_rejects_the_development_tls_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep the insecure provider path unavailable to the production HTTP server."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "contextual-orchestrator",
            "--serve",
            "--auth-token",
            "test-token",
            "--insecure-skip-tls-verify",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        cli_main()
    assert raised.value.code == 2
    assert "cannot be used with --serve" in capsys.readouterr().err


def _agents() -> list[ModelAgent]:
    """Return a deterministic primary and backup pair for retry-policy tests."""
    return [
        ModelAgent(
            "primary_worker",
            "mock",
            tags=("reasoning", "writing"),
            priority=10,
        ),
        ModelAgent(
            "backup_worker",
            "mock",
            tags=("reasoning", "writing"),
            priority=1,
        ),
    ]


class _AlwaysTransientPrimary(ModelClient):
    """Fail every primary call safely and recover through the backup."""

    def __init__(self) -> None:
        super().__init__(max_retries=0)
        self.calls: list[str] = []

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
    ) -> str:
        """Record calls and raise one explicitly idempotent tool timeout."""
        del messages, temperature
        self.calls.append(agent.id)
        if agent.id == "primary_worker":
            raise ToolExecutionError(
                "read timed out",
                tool_name="inspect_repository",
                kind=ToolFailureKind.TIMEOUT,
                idempotent=True,
            )
        return "backup recovered"


def test_tool_retry_attempts_rejects_values_above_the_shared_policy_cap() -> None:
    """Reject a configuration that could occupy one request indefinitely."""
    with pytest.raises(ValueError, match=rf"at most {MAX_TOOL_RETRY_ATTEMPTS}"):
        TaskOrchestrator(
            _agents(),
            tool_retry_attempts=MAX_TOOL_RETRY_ATTEMPTS + 1,
        )


def test_retry_loop_defends_the_cap_if_runtime_state_is_mutated() -> None:
    """Apply the shared cap again at execution time before agent failover."""
    client = _AlwaysTransientPrimary()
    orchestrator = TaskOrchestrator(
        _agents(),
        client=client,
        tool_retry_attempts=MAX_TOOL_RETRY_ATTEMPTS,
        tool_retry_backoff_seconds=0,
    )
    orchestrator.tool_retry_attempts = MAX_TOOL_RETRY_ATTEMPTS + 100

    result = orchestrator.route_once(
        [{"role": "user", "content": "inspect the repository"}]
    )

    assert result["answer"] == "backup recovered"
    assert client.calls == ["primary_worker"] * (
        MAX_TOOL_RETRY_ATTEMPTS + 1
    ) + ["backup_worker"]
''',
        encoding="utf-8",
    )


def _write_implementation() -> None:
    """Implement exact-boolean TLS and a shared retry-attempt ceiling."""
    _replace_once(
        "contextual_orchestrator/tool_fallback.py",
        "retry policy constant",
        "import urllib.error\n\n\nclass ToolFailureKind",
        "import urllib.error\n\n\nMAX_TOOL_RETRY_ATTEMPTS = 4\n"
        '"""Maximum same-agent retries allowed for one classified tool failure."""\n\n\n'
        "class ToolFailureKind",
    )
    _replace_once(
        "contextual_orchestrator/__init__.py",
        "public retry constant import",
        "from .tool_fallback import (\n    ToolExecutionError,\n",
        "from .tool_fallback import (\n    MAX_TOOL_RETRY_ATTEMPTS,\n    ToolExecutionError,\n",
    )
    _replace_once(
        "contextual_orchestrator/__init__.py",
        "public retry constant export",
        "    # tool fallback\n    \"ToolExecutionError\",\n",
        "    # tool fallback\n    \"MAX_TOOL_RETRY_ATTEMPTS\",\n    \"ToolExecutionError\",\n",
    )
    _replace_once(
        "contextual_orchestrator/orchestrator.py",
        "retry constant import",
        "from .tool_fallback import (\n    ToolFallbackAction,\n",
        "from .tool_fallback import (\n    MAX_TOOL_RETRY_ATTEMPTS,\n    ToolFallbackAction,\n",
    )
    _replace_once(
        "contextual_orchestrator/orchestrator.py",
        "exact boolean TLS selection",
        "    def _build_ssl_context(ca_bundle: str | None, verify_tls: bool) -> ssl.SSLContext:\n"
        "        if not verify_tls:\n",
        "    def _build_ssl_context(ca_bundle: str | None, verify_tls: bool) -> ssl.SSLContext:\n"
        "        if not isinstance(verify_tls, bool):\n"
        "            raise TypeError(\"verify_tls must be a boolean\")\n"
        "        if verify_tls is False:\n",
    )
    _replace_once(
        "contextual_orchestrator/orchestrator.py",
        "retry constructor cap",
        "            or not isinstance(tool_retry_attempts, int)\n"
        "            or tool_retry_attempts < 0\n"
        "        ):\n"
        "            raise ValueError(\"tool_retry_attempts must be a nonnegative integer\")\n",
        "            or not isinstance(tool_retry_attempts, int)\n"
        "            or tool_retry_attempts < 0\n"
        "            or tool_retry_attempts > MAX_TOOL_RETRY_ATTEMPTS\n"
        "        ):\n"
        "            raise ValueError(\n"
        "                \"tool_retry_attempts must be a nonnegative integer at most \"\n"
        "                f\"{MAX_TOOL_RETRY_ATTEMPTS}\"\n"
        "            )\n",
    )
    _replace_once(
        "contextual_orchestrator/orchestrator.py",
        "execution-time retry cap",
        "        candidates = self._failover_candidates(primary, text, role)\n"
        "        last_error: Exception | None = None\n",
        "        candidates = self._failover_candidates(primary, text, role)\n"
        "        retry_limit = min(self.tool_retry_attempts, MAX_TOOL_RETRY_ATTEMPTS)\n"
        "        last_error: Exception | None = None\n",
    )
    _replace_once(
        "contextual_orchestrator/orchestrator.py",
        "retry loop limit",
        "                        and retry_attempt < self.tool_retry_attempts\n",
        "                        and retry_attempt < retry_limit\n",
    )
    _replace_once(
        "contextual_orchestrator/__main__.py",
        "serve TLS opt-out rejection",
        "    args = parser.parse_args()\n\n"
        "    client = ModelClient(ca_bundle=args.provider_ca_bundle, verify_tls=not args.insecure_skip_tls_verify)\n",
        "    args = parser.parse_args()\n\n"
        "    if args.serve and args.insecure_skip_tls_verify:\n"
        "        parser.error(\n"
        "            \"--insecure-skip-tls-verify is development-only and cannot be used with --serve; \"\n"
        "            \"configure --provider-ca-bundle instead\"\n"
        "        )\n\n"
        "    client = ModelClient(ca_bundle=args.provider_ca_bundle, verify_tls=not args.insecure_skip_tls_verify)\n",
    )
    _replace_once(
        "docs/tool_execution_fallbacks.md",
        "retry cap documentation",
        "`TaskOrchestrator(..., tool_retry_attempts=1, tool_retry_backoff_seconds=0.25)` permits one same-agent retry when the classifier marks the operation `retry_safe`. Retries use full-jitter exponential backoff with a 30-second ceiling for each delay. Set `tool_retry_attempts=0` to disable same-agent retries; tests may set the backoff to `0`. Invalid retry counts and negative, non-finite, boolean, or non-numeric backoff values are rejected. The HTTP server deliberately retains the request's concurrency slot during the bounded delay: releasing it would let an unbounded population of sleeping requests bypass `max_concurrent_runs` and later stampede while reacquiring. Workloads that need nonblocking, long-delay retry belong on the durable batch path.\n",
        "`TaskOrchestrator(..., tool_retry_attempts=1, tool_retry_backoff_seconds=0.25)` permits one same-agent retry when the classifier marks the operation `retry_safe`. `MAX_TOOL_RETRY_ATTEMPTS` is the shared policy ceiling and currently limits one agent to four retries; the constructor rejects larger values and `_invoke` reapplies the cap defensively. Retries use full-jitter exponential backoff with a 30-second ceiling for each delay. Set `tool_retry_attempts=0` to disable same-agent retries; tests may set the backoff to `0`. Invalid retry counts and negative, non-finite, boolean, or non-numeric backoff values are rejected. The HTTP server deliberately retains the request's concurrency slot during the bounded delay: releasing it would let an unbounded population of sleeping requests bypass `max_concurrent_runs` and later stampede while reacquiring. Workloads that need nonblocking, long-delay retry belong on the durable batch path.\n",
    )
    _replace_once(
        "docs/doctoring/TOOL_EXECUTION_FALLBACKS.md",
        "doctoring retry and TLS policy",
        "| Retry only when replay is known safe | RFC 9110 §9.2.2 | `idempotent` metadata gates `retry_same_agent`. |\n",
        "| Retry only when replay is known safe | RFC 9110 §9.2.2 | `idempotent` metadata gates `retry_same_agent`; `MAX_TOOL_RETRY_ATTEMPTS` caps one agent at four retries in configuration and execution. |\n",
    )
    _replace_once(
        "docs/doctoring/TOOL_EXECUTION_FALLBACKS.md",
        "doctoring production TLS boundary",
        "The Semgrep suppressions in `cost_ledger.py` cover SQL assembled exclusively from package-owned constant table and column catalogs; user values remain positional bind parameters. The provider transport suppression covers a URL that has already passed the package's scheme, host allowlist, public-address, credential, and response-boundary checks. The unverified TLS context remains an explicit development-only operator opt-out, while verified TLS is the default. These annotations are deliberately attached to the exact audited call sites rather than weakening or excluding the repository-wide scanner rules.\n",
        "The Semgrep suppressions in `cost_ledger.py` cover SQL assembled exclusively from package-owned constant table and column catalogs; user values remain positional bind parameters. The provider transport suppression covers a URL that has already passed the package's scheme, host allowlist, public-address, credential, and response-boundary checks. TLS selection accepts only an exact boolean. The unverified context remains an explicit development-only CLI opt-out, while `--serve` rejects that opt-out and requires verified system trust or `--provider-ca-bundle`. These annotations are deliberately attached to the exact audited call sites rather than weakening or excluding the repository-wide scanner rules.\n",
    )
    _replace_once(
        "CHANGELOG.md",
        "retry cap changelog",
        "- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget.\n",
        "- Agent invocation now retries explicitly idempotent transient tool failures with bounded exponential backoff within a per-agent budget capped by the shared `MAX_TOOL_RETRY_ATTEMPTS` policy.\n",
    )
    _replace_once(
        "CHANGELOG.md",
        "production TLS changelog",
        "- The hourly caller remains read-only and model-secret-free while preserving exact-head checks, independent approval, and the existing reviewer credential scheme.\n",
        "- The hourly caller remains read-only and model-secret-free while preserving exact-head checks, independent approval, and the existing reviewer credential scheme.\n"
        "- Provider TLS selection rejects non-boolean values, and the production `--serve` path rejects the development-only certificate-verification opt-out.\n",
    )


def main() -> None:
    """Apply the requested test or implementation stage."""
    if len(sys.argv) != 2 or sys.argv[1] not in {"tests", "implementation"}:
        raise SystemExit("usage: transform.py tests|implementation")
    if sys.argv[1] == "tests":
        _write_tests()
    else:
        _write_implementation()


if __name__ == "__main__":
    main()
