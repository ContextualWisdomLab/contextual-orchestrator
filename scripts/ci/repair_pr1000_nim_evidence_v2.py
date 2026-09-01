"""Reconcile PR #1000 NIM evidence repair with the existing benchmark contract."""

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
        '''        if isinstance(value, bool) or not isinstance(value, (int, float)):\n            return None\n        if not math.isfinite(value) or value < 0:\n            return None\n        return int(value)\n''',
        '''        if isinstance(value, bool) or not isinstance(value, int) or value < 0:\n            return None\n        return value\n''',
        "provider usage integer contract",
    )
    replace_once(
        SOURCE,
        '''        self._exceeded = self.observed_tokens > self.total_token_budget\n        return usage\n''',
        '''        self._exceeded = self.observed_tokens > self.total_token_budget\n        if self._exceeded:\n            raise PolicyTokenBudgetExceeded(\n                "policy cell total-token allowance exceeded by provider-reported usage"\n            )\n        return usage\n''',
        "authoritative budget crossing",
    )
    replace_once(
        SOURCE,
        '''        usage = self._delegate.take_usage()\n        pending_model = self._pending_model\n        self._pending_model = None\n        if pending_model is None:\n            return usage\n        return self._record_reported_usage(pending_model, usage)\n''',
        '''        usage = self._delegate.take_usage()\n        pending_model = self._pending_model\n        self._pending_model = None\n        delegate_error = getattr(self._delegate, "benchmark_contract_error", None)\n        if isinstance(delegate_error, BenchmarkContractError):\n            self._contract_error = delegate_error\n            return usage\n        if pending_model is None:\n            return usage\n        return self._record_reported_usage(pending_model, usage)\n''',
        "preserve earlier transport contract",
    )
    replace_once(
        SOURCE,
        '''    if not priced:\n        return None\n''',
        '''    if len(priced) != len(agents):\n        return None\n''',
        "unknown price fail-closed",
    )
    replace_once(
        SOURCE,
        '''    if path.endswith("/responses"):\n        return json.dumps({"output_text": "OK"}).encode("utf-8")\n''',
        '''    if path.endswith("/responses"):\n        return json.dumps(\n            {\n                "output_text": "OK",\n                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},\n            }\n        ).encode("utf-8")\n''',
        "synthetic responses usage",
    )
    replace_once(
        SOURCE,
        '''    return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")\n''',
        '''    return json.dumps(\n        {\n            "choices": [{"message": {"content": "OK"}}],\n            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},\n        }\n    ).encode("utf-8")\n''',
        "synthetic chat usage",
    )


def patch_tests() -> None:
    """Update legacy assertions to the provider-usage fail-closed contract."""
    replace_once(
        TESTS,
        '''    response = cell.proxy_send_once(\n        _mock_agents("dryrun/chat-basic")[0], "responses", {"input": "judge"}\n    )\n    assert response["usage"]["prompt_tokens"] == "unknown"\n''',
        '''    with pytest.raises(nb.BenchmarkContractError, match="provider-reported"):\n        cell.proxy_send_once(\n            _mock_agents("dryrun/chat-basic")[0], "responses", {"input": "judge"}\n        )\n''',
        "malformed usage expectation",
    )
    replace_once(
        TESTS,
        '''    tight = nb.EqualBudgetModelClient(\n        ModelClient(), total_token_budget=1, maximum_calls=1\n    )\n    with pytest.raises(nb.PolicyTokenBudgetExceeded, match="total-token"):\n        tight.chat(\n            _mock_agents("dryrun/chat-basic")[0],\n            [{"role": "user", "content": "x" * 100}],\n        )\n''',
        '''    class ReportedUsageDelegate(ModelClient):\n        def chat(self, *args, **kwargs):  # type: ignore[override]\n            return "answer"\n\n        def take_usage(self):  # type: ignore[override]\n            return {"prompt_tokens": 1, "completion_tokens": 1}\n\n    tight = nb.EqualBudgetModelClient(\n        ReportedUsageDelegate(), total_token_budget=1, maximum_calls=1\n    )\n    tight.chat(\n        _mock_agents("dryrun/chat-basic")[0],\n        [{"role": "user", "content": "any prompt length"}],\n    )\n    with pytest.raises(nb.PolicyTokenBudgetExceeded, match="provider-reported"):\n        tight.take_usage()\n''',
        "authoritative budget test",
    )
    tests = TESTS.read_text(encoding="utf-8")
    old = '        ModelClient._send = lambda self, agent, payload: "stub live answer"\n'
    if tests.count(old) != 2:
        raise RuntimeError(f"live synthetic usage patch: expected two matches, found {tests.count(old)}")
    new = '''        def _stub_live_send(self, agent, payload):\n            del agent, payload\n            self._local.usage = {\n                "prompt_tokens": 1,\n                "completion_tokens": 1,\n                "total_tokens": 2,\n            }\n            return "stub live answer"\n\n        ModelClient._send = _stub_live_send\n'''
    TESTS.write_text(tests.replace(old, new), encoding="utf-8")


def patch_docs() -> None:
    """Use the repository's actual unreleased heading and record measurement authority."""
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
    # Avoid v1's stale changelog marker while preserving its ADR/baseline text.
    adr_before = ADR.read_text(encoding="utf-8")
    baseline_before = v1.BASELINE_PATH.read_text(encoding="utf-8")
    try:
        v1.repair_docs()
    except RuntimeError as exc:
        if "CHANGELOG is missing the Unreleased section" not in str(exc):
            raise
    if ADR.read_text(encoding="utf-8") == adr_before:\n        raise RuntimeError("ADR amendment was not applied")
    if v1.BASELINE_PATH.read_text(encoding="utf-8") == baseline_before:\n        raise RuntimeError("product-gap amendment was not applied")
    patch_docs()


if __name__ == "__main__":
    main()
