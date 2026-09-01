"""Reconcile PR #1000 NIM evidence repair with the live benchmark contract."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import repair_pr1000_nim_evidence as v1

SOURCE = Path("contextual_orchestrator/nim_benchmark.py")
TESTS = Path("tests/test_nim_benchmark.py")
CHANGELOG = Path("CHANGELOG.md")
ADR = Path("docs/planning/adrs/0034-anti-heuristic-routing-evidence.md")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    """Replace one exact post-v1 fragment or fail closed on source drift."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_source() -> None:
    """Close authoritative-usage and synthetic-provider gaps left by v1."""
    replace_once(
        SOURCE,
        """        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return int(value)
""",
        """        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
""",
        "provider usage integer contract",
    )
    replace_once(
        SOURCE,
        """        self._exceeded = self.observed_tokens > self.total_token_budget
        return usage
""",
        """        self._exceeded = self.observed_tokens > self.total_token_budget
        if self._exceeded:
            raise PolicyTokenBudgetExceeded(
                "policy cell total-token allowance exceeded by provider-reported usage"
            )
        return usage
""",
        "authoritative budget crossing",
    )
    replace_once(
        SOURCE,
        """        usage = self._delegate.take_usage()
        pending_model = self._pending_model
        self._pending_model = None
        if pending_model is None:
            return usage
        return self._record_reported_usage(pending_model, usage)
""",
        """        usage = self._delegate.take_usage()
        pending_model = self._pending_model
        self._pending_model = None
        delegate_error = getattr(self._delegate, "benchmark_contract_error", None)
        if isinstance(delegate_error, BenchmarkContractError):
            self._contract_error = delegate_error
            return usage
        if pending_model is None:
            return usage
        return self._record_reported_usage(pending_model, usage)
""",
        "preserve earlier transport contract",
    )
    replace_once(
        SOURCE,
        """    if not priced:
        return None
""",
        """    if len(priced) != len(agents):
        return None
""",
        "unknown price fail-closed",
    )
    replace_once(
        SOURCE,
        """    if path.endswith("/responses"):
        return json.dumps({"output_text": "OK"}).encode("utf-8")
""",
        """    if path.endswith("/responses"):
        return json.dumps(
            {
                "output_text": "OK",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
        ).encode("utf-8")
""",
        "synthetic responses usage",
    )
    replace_once(
        SOURCE,
        """    return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")
""",
        """    return json.dumps(
        {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    ).encode("utf-8")
""",
        "synthetic chat usage",
    )


def patch_tests() -> None:
    """Update legacy assertions to the provider-usage fail-closed contract."""
    replace_once(
        TESTS,
        """    response = cell.proxy_send_once(
        _mock_agents("dryrun/chat-basic")[0], "responses", {"input": "judge"}
    )
    assert response["usage"]["prompt_tokens"] == "unknown"
""",
        """    with pytest.raises(nb.BenchmarkContractError, match="provider-reported"):
        cell.proxy_send_once(
            _mock_agents("dryrun/chat-basic")[0], "responses", {"input": "judge"}
        )
""",
        "malformed usage expectation",
    )
    replace_once(
        TESTS,
        """    tight = nb.EqualBudgetModelClient(
        ModelClient(), total_token_budget=1, maximum_calls=1
    )
    with pytest.raises(nb.PolicyTokenBudgetExceeded, match="total-token"):
        tight.chat(
            _mock_agents("dryrun/chat-basic")[0],
            [{"role": "user", "content": "x" * 100}],
        )
""",
        """    class ReportedUsageDelegate(ModelClient):
        def chat(self, *args, **kwargs):  # type: ignore[override]
            return "answer"

        def take_usage(self):  # type: ignore[override]
            return {"prompt_tokens": 1, "completion_tokens": 1}

    tight = nb.EqualBudgetModelClient(
        ReportedUsageDelegate(), total_token_budget=1, maximum_calls=1
    )
    tight.chat(
        _mock_agents("dryrun/chat-basic")[0],
        [{"role": "user", "content": "any prompt length"}],
    )
    with pytest.raises(nb.PolicyTokenBudgetExceeded, match="provider-reported"):
        tight.take_usage()
""",
        "authoritative budget test",
    )
    tests = TESTS.read_text(encoding="utf-8")
    old = '    ModelClient._send = lambda self, agent, payload: "stub live answer"\n'
    if tests.count(old) != 2:
        raise RuntimeError(f"live synthetic usage patch: expected two matches, found {tests.count(old)}")
    new = """    def _stub_live_send(self, agent, payload):
        del agent, payload
        self._local.usage = {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        }
        return "stub live answer"

    ModelClient._send = _stub_live_send
"""
    TESTS.write_text(tests.replace(old, new), encoding="utf-8")


def patch_docs() -> None:
    """Use the live release heading and record the provider measurement authority."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry = (
        "- Remove the NIM benchmark character-count token heuristic and weighted cheapest-worker "
        "selector. Benchmark token/cost evidence now requires complete provider-reported usage, "
        "and ambiguous or incomplete price vectors fail closed.\n"
    )
    if entry not in changelog:
        marker = "## [0.2.0] - Unreleased\n"
        if marker not in changelog:
            raise RuntimeError("CHANGELOG is missing the current unreleased release heading")
        CHANGELOG.write_text(changelog.replace(marker, marker + "\n" + entry, 1), encoding="utf-8")
    adr = ADR.read_text(encoding="utf-8")
    citation = (
        "\nNVIDIA. (2026). *NVIDIA NIM for large language models: OpenAI-compatible APIs*. "
        "NVIDIA Developer Documentation. The chat-completions response contract exposes provider "
        "`usage.prompt_tokens`, `usage.completion_tokens`, and `usage.total_tokens`; these reported "
        "counts are the benchmark authority rather than character-length reconstruction.\n"
    )
    if citation not in adr:
        ADR.write_text(adr.rstrip() + "\n" + citation, encoding="utf-8")


def main() -> None:
    """Run v1 source/test repair, reconcile discovered regressions, then update docs."""
    v1.repair_source()
    v1.repair_tests()
    patch_source()
    patch_tests()
    adr_before = ADR.read_text(encoding="utf-8")
    baseline_before = v1.BASELINE_PATH.read_text(encoding="utf-8")
    try:
        v1.repair_docs()
    except RuntimeError as exc:
        if "CHANGELOG is missing the Unreleased section" not in str(exc):
            raise
    if ADR.read_text(encoding="utf-8") == adr_before:
        raise RuntimeError("ADR amendment was not applied")
    if v1.BASELINE_PATH.read_text(encoding="utf-8") == baseline_before:
        raise RuntimeError("product-gap amendment was not applied")
    patch_docs()


if __name__ == "__main__":
    main()
