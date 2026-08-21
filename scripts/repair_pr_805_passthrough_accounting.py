"""Apply and verify the narrow PR 805 passthrough accounting repair."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command and stream captured output on failure."""

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace exactly one known source fragment or fail closed."""

    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"refusing unknown {label} shape")
    return text.replace(old, new, 1)


def _add_regression() -> None:
    """Add the sequential budget regression before changing production code."""

    path = ROOT / "tests/test_openai_passthrough.py"
    text = path.read_text(encoding="utf-8")
    anchor = "def test_proxy_completion_forwards_response_format_and_returns_full_shape() -> None:\n"
    test = r'''def test_plain_proxy_completion_persists_reported_usage_before_next_budget_check() -> None:
    orch = _build(budget_max_output_tokens=3)
    raw = {
        "id": "chatcmpl-accounted",
        "object": "chat.completion",
        "model": "mock-planner",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "accounted"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "echo": {},
    }
    body = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "plain passthrough"}],
    }

    with patch.object(orch.client, "proxy_send", return_value=raw) as send:
        assert orch.proxy_completion(body)["id"] == "chatcmpl-accounted"
        analytics = orch.spend_analytics()
        assert analytics["totals"]["run_count"] == 1
        assert analytics["budget"]["spent_output_tokens"] == 3
        assert analytics["by_model"] == [
            {
                "model": "mock-planner",
                "estimated_output_tokens": 3,
                "output_tokens": 3,
                "usage_source": "reported",
                "step_count": 1,
                "price_per_million_usd": None,
                "estimated_cost_usd": None,
            }
        ]
        with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
            orch.proxy_completion(body)

    assert send.call_count == 1


'''
    if test not in text:
        if anchor not in text:
            raise SystemExit("refusing unknown passthrough test insertion point")
        text = text.replace(anchor, test + anchor, 1)
    path.write_text(text, encoding="utf-8")


def _apply_repair() -> None:
    """Persist ordinary provider responses in the same run-level spend ledger."""

    path = ROOT / "contextual_orchestrator/orchestrator.py"
    text = path.read_text(encoding="utf-8")
    old = '''        upstream["stream"] = False
        return self.client.proxy_send(agent, endpoint, upstream)
'''
    new = '''        upstream["stream"] = False
        passthrough_started = time.perf_counter()
        raw = self.client.proxy_send(agent, endpoint, upstream)
        passthrough_output = ""
        try:
            passthrough_output = ModelClient._response_content(agent, raw)
        except RuntimeError:
            # Tool-call-only responses are billable even without assistant text.
            pass
        passthrough_step = {
            "id": 0,
            "role": "worker",
            "agent_id": agent.id,
            "subtask": "Provider passthrough",
            "access": [],
            "latency_ms": round((time.perf_counter() - passthrough_started) * 1000, 2),
            "output": passthrough_output,
        }
        usage = raw.get("usage")
        if isinstance(usage, dict):
            passthrough_step["usage"] = usage
        self._persist_workflow_run(
            {
                "workflow_run_id": f"run_{uuid.uuid4().hex}",
                "created_at": int(time.time()),
                "mode": "route",
                "policy_mode": "route",
                "prompt_text": text,
                "answer": passthrough_output,
                "trace": [passthrough_step],
                "policy_snapshot": self.policy.as_dict(),
                "verification": {
                    "accepted": True,
                    "reason": "single provider passthrough",
                    "verifier_output": "",
                },
            }
        )
        return raw
'''
    text = _replace_once(text, old, new, label="ordinary proxy completion")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Prove RED, apply the repair, then prove focused and full GREEN."""

    _add_regression()
    red = _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_openai_passthrough.py::test_plain_proxy_completion_persists_reported_usage_before_next_budget_check",
        check=False,
    )
    if red.returncode == 0:
        raise SystemExit("regression unexpectedly passed before the product repair")
    _apply_repair()
    _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_openai_passthrough.py::test_plain_proxy_completion_persists_reported_usage_before_next_budget_check",
    )
    _run(sys.executable, "-m", "pytest", "-q")


if __name__ == "__main__":
    main()
