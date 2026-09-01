"""One-shot exact-head repair for PR #1000 NIM benchmark evidence heuristics."""

from __future__ import annotations

from pathlib import Path


SOURCE_PATH = Path("contextual_orchestrator/nim_benchmark.py")
TEST_PATH = Path("tests/test_nim_benchmark.py")
ADR_PATH = Path("docs/planning/adrs/0034-anti-heuristic-routing-evidence.md")
BASELINE_PATH = Path("docs/product-technical-gap-baseline.md")
CHANGELOG_PATH = Path("CHANGELOG.md")


def replace_section(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """Replace one uniquely delimited source section or fail closed."""
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one expected contract fragment or fail closed."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def repair_source() -> None:
    """Remove character-token and weighted-price decision authority."""
    source = SOURCE_PATH.read_text(encoding="utf-8")

    source = replace_section(
        source,
        "def estimate_tokens(text: str) -> int:\n",
        "\n\nBENCHMARK_SCHEMA_VERSION",
        '''def estimate_tokens(text: str) -> int:\n    """Reject character-count token estimation at the benchmark boundary.\n\n    Provider chat framing, tool schemas, and multimodal serialization are\n    provider-owned. Text length is not token evidence and must never affect\n    benchmark admission, allowance, cost, or quality evidence.\n    """\n    del text\n    raise BenchmarkContractError(\n        "heuristic token estimation is prohibited; provider-reported usage is required"\n    )\n''',
    )

    source = replace_section(
        source,
        "class EqualBudgetModelClient:\n",
        "# --------------------------------------------------------------------------\n# Catalog discovery",
        '''class EqualBudgetModelClient:\n    """Delegate model calls using only complete provider-reported token evidence."""\n\n    def __init__(\n        self,\n        delegate: ModelClient,\n        total_token_budget: int,\n        maximum_calls: int,\n    ) -> None:\n        if (\n            isinstance(total_token_budget, bool)\n            or not isinstance(total_token_budget, int)\n            or total_token_budget < 1\n        ):\n            raise ValueError("total_token_budget must be a positive integer")\n        if (\n            isinstance(maximum_calls, bool)\n            or not isinstance(maximum_calls, int)\n            or maximum_calls < 1\n        ):\n            raise ValueError("maximum_calls must be a positive integer")\n        self._delegate = delegate\n        self.total_token_budget = total_token_budget\n        self.maximum_calls = maximum_calls\n        self.observed_calls = 0\n        self.reported_usage_calls = 0\n        self.observed_tokens = 0\n        self.observed_prompt_tokens = 0\n        self.observed_completion_tokens = 0\n        self.attempted_models: list[dict[str, Any]] = []\n        self.reported_usage_by_model: dict[str, dict[str, int]] = {}\n        self._pending_model: str | None = None\n        self._exceeded = False\n        self._contract_error: BenchmarkContractError | None = None\n\n    def __getattr__(self, name: str) -> Any:\n        """Forward provider-client capabilities not owned by the cell limiter."""\n        return getattr(self._delegate, name)\n\n    @property\n    def max_output_tokens(self) -> int:\n        """Expose the delegate cap for compatibility with orchestration clients."""\n        return int(self._delegate.max_output_tokens)\n\n    @max_output_tokens.setter\n    def max_output_tokens(self, value: int) -> None:\n        """Forward explicit cap changes to the delegated model client."""\n        self._delegate.max_output_tokens = value\n\n    @property\n    def remaining_tokens(self) -> int:\n        """Return the allowance remaining after authoritative observed usage."""\n        return max(0, self.total_token_budget - self.observed_tokens)\n\n    @property\n    def exceeded(self) -> bool:\n        """Return whether authoritative observed usage crossed the cell allowance."""\n        return self._exceeded\n\n    @property\n    def contract_error(self) -> BenchmarkContractError | None:\n        """Return a transport/evidence contract failure swallowed by failover."""\n        return self._contract_error\n\n    @staticmethod\n    def _coerce_usage_count(value: Any) -> int | None:\n        """Return one valid non-negative provider token count, else ``None``."""\n        if isinstance(value, bool) or not isinstance(value, (int, float)):\n            return None\n        if not math.isfinite(value) or value < 0:\n            return None\n        return int(value)\n\n    def _record_reported_usage(self, model_id: str, usage: Any) -> dict[str, Any]:\n        """Record complete provider usage or fail closed without estimation."""\n        if not isinstance(usage, dict):\n            error = BenchmarkContractError(\n                "provider-reported prompt and completion token usage is required"\n            )\n            self._contract_error = error\n            raise error\n        prompt_tokens = self._coerce_usage_count(usage.get("prompt_tokens"))\n        completion_tokens = self._coerce_usage_count(usage.get("completion_tokens"))\n        if prompt_tokens is None or completion_tokens is None:\n            error = BenchmarkContractError(\n                "provider-reported prompt and completion token usage is required"\n            )\n            self._contract_error = error\n            raise error\n        self.reported_usage_calls += 1\n        self.observed_prompt_tokens += prompt_tokens\n        self.observed_completion_tokens += completion_tokens\n        self.observed_tokens += prompt_tokens + completion_tokens\n        bucket = self.reported_usage_by_model.setdefault(\n            model_id, {"prompt_tokens": 0, "completion_tokens": 0}\n        )\n        bucket["prompt_tokens"] += prompt_tokens\n        bucket["completion_tokens"] += completion_tokens\n        self._exceeded = self.observed_tokens > self.total_token_budget\n        return usage\n\n    def _begin_call(self, agent: ModelAgent) -> int:\n        """Admit one call using only observed budget state and the declared call cap."""\n        if self._exceeded or self.observed_calls >= self.maximum_calls:\n            raise PolicyTokenBudgetExceeded(\n                "policy cell maximum-call allowance exhausted"\n            )\n        if self.remaining_tokens < 1:\n            raise PolicyTokenBudgetExceeded(\n                "policy cell total-token allowance exhausted"\n            )\n        self.observed_calls += 1\n        self.attempted_models.append(\n            {"role": "attempted", "agent_id": agent.id, "model_id": agent.model}\n        )\n        return min(int(self._delegate.max_output_tokens), self.remaining_tokens)\n\n    def chat(\n        self,\n        agent: ModelAgent,\n        messages: list[dict[str, Any]],\n        temperature: float | None = None,\n        top_p: float | None = None,\n        effort_profile: ReasoningEffortProfile | None = None,\n    ) -> str:\n        """Perform one call; accounting completes only from ``take_usage``."""\n        output_cap = self._begin_call(agent)\n        self._pending_model = agent.model\n        try:\n            with self._delegate.request_settings(max_output_tokens=output_cap):\n                return self._delegate.chat(\n                    agent, messages, temperature, top_p, effort_profile\n                )\n        finally:\n            delegate_error = getattr(self._delegate, "benchmark_contract_error", None)\n            if isinstance(delegate_error, BenchmarkContractError):\n                self._contract_error = delegate_error\n\n    def proxy_send(\n        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]\n    ) -> dict[str, Any]:\n        """Apply the same evidence-only envelope to structured judge requests."""\n        output_cap = self._begin_call(agent)\n        request = dict(payload)\n        requested_cap = request.get("max_tokens")\n        request["max_tokens"] = min(\n            requested_cap\n            if type(requested_cap) is int and requested_cap > 0\n            else output_cap,\n            output_cap,\n        )\n        response = self._delegate.proxy_send(agent, endpoint, request)\n        self._record_reported_usage(agent.model, response.get("usage"))\n        return response\n\n    def proxy_send_once(\n        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]\n    ) -> dict[str, Any]:\n        """Keep endpoint-race sends inside the same evidence-only boundary."""\n        return self.proxy_send(agent, endpoint, payload)\n\n    def take_usage(self) -> dict[str, Any] | None:\n        """Require complete provider usage for the preceding chat call."""\n        usage = self._delegate.take_usage()\n        pending_model = self._pending_model\n        self._pending_model = None\n        if pending_model is None:\n            return usage\n        return self._record_reported_usage(pending_model, usage)\n\n\n''',
    )

    source = replace_section(
        source,
        "def _cell_usage(\n",
        "def _classify_run_error(",
        '''def _cell_usage(\n    trace: list[dict[str, Any]],\n    agents_by_id: dict[str, str],\n    task_prompt: str,\n) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:\n    """Aggregate complete provider-reported usage for one evaluation cell."""\n    del task_prompt\n    usage_by_model: dict[str, dict[str, int]] = {}\n    models_used: list[dict[str, Any]] = []\n    for row in trace:\n        agent_id = row.get("served_agent_id") or row["agent_id"]\n        try:\n            model_id = agents_by_id[agent_id]\n        except (KeyError, TypeError) as exc:\n            raise BenchmarkContractError(\n                f"trace references unknown agent {agent_id!r}"\n            ) from exc\n        models_used.append(\n            {\n                "step_id": row["id"],\n                "role": row["role"],\n                "agent_id": agent_id,\n                "model_id": model_id,\n            }\n        )\n        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}\n        prompt_tokens = _coerce_token_count(usage.get("prompt_tokens"))\n        completion_tokens = _coerce_token_count(usage.get("completion_tokens"))\n        if prompt_tokens is None or completion_tokens is None:\n            raise BenchmarkContractError(\n                "provider-reported prompt and completion token usage is required"\n            )\n        bucket = usage_by_model.setdefault(\n            model_id, {"prompt_tokens": 0, "completion_tokens": 0}\n        )\n        bucket["prompt_tokens"] += prompt_tokens\n        bucket["completion_tokens"] += completion_tokens\n    prompt_total = sum(bucket["prompt_tokens"] for bucket in usage_by_model.values())\n    completion_total = sum(\n        bucket["completion_tokens"] for bucket in usage_by_model.values()\n    )\n    return usage_by_model, {\n        "prompt_tokens": prompt_total,\n        "completion_tokens": completion_total,\n        "total_tokens": prompt_total + completion_total,\n        "token_usage_source": "reported",\n        "models_used": models_used,\n    }\n\n\n''',
    )

    source = replace_section(
        source,
        "def _combined_rate(",
        "def planned_evaluation_requests(",
        '''def _price_vector(\n    pricing_scenario: dict[str, Any], model_id: str\n) -> tuple[float, float] | None:\n    """Return the explicit (input, output) USD/1M price vector, or ``None``."""\n    rate = pricing_scenario["usd_per_million_tokens"].get(model_id)\n    if rate is None:\n        return None\n    return float(rate["input"]), float(rate["output"])\n\n\ndef cheapest_priced_agent(\n    agents: list[ModelAgent], pricing_scenario: dict[str, Any] | None\n) -> ModelAgent | None:\n    """Return a uniquely component-wise price-dominant worker, if identified."""\n    if pricing_scenario is None:\n        return None\n    priced = [\n        (vector, agent)\n        for agent in agents\n        for vector in [_price_vector(pricing_scenario, agent.model)]\n        if vector is not None\n    ]\n    if not priced:\n        return None\n    winners: list[ModelAgent] = []\n    for vector, agent in priced:\n        if all(\n            other_agent is agent\n            or (\n                vector[0] <= other[0]\n                and vector[1] <= other[1]\n                and (vector[0] < other[0] or vector[1] < other[1])\n            )\n            for other, other_agent in priced\n        ):\n            winners.append(agent)\n    return winners[0] if len(winners) == 1 else None\n\n\n''',
    )

    source = replace_once(
        source,
        '"token_usage_source": "estimated" if incurred else "unavailable",',
        '"token_usage_source": incurred.get("token_usage_source", "unavailable"),',
        "failed-cell usage source",
    )
    source = replace_once(
        source,
        '''                "models_used": cell_client.attempted_models,\n            },\n''',
        '''                "models_used": cell_client.attempted_models,\n                "token_usage_source": (\n                    "reported"\n                    if cell_client.reported_usage_calls == cell_client.observed_calls\n                    else "unavailable"\n                ),\n            },\n''',
        "failure-evidence usage source",
    )
    estimated_branch = '''        if cell["token_usage_source"] == "estimated" and cell_client.observed_calls:\n            cell.update(\n                {\n                    "prompt_tokens": cell_client.observed_prompt_tokens,\n                    "completion_tokens": cell_client.observed_completion_tokens,\n                    "total_tokens": cell_client.observed_tokens,\n                    "hypothetical_cost_usd": hypothetical_cost_usd(\n                        pricing_scenario, cell_client.estimated_usage_by_model\n                    ),\n                }\n            )\n'''
    source = replace_once(source, estimated_branch, "", "estimated run-cell fallback")

    source = source.replace(
        '"no_worker_priced_by_scenario"',
        '"no_uniquely_price_dominant_worker"',
    )
    SOURCE_PATH.write_text(source, encoding="utf-8")


def repair_tests() -> None:
    """Update legacy tests that asserted the retired heuristics."""
    tests = TEST_PATH.read_text(encoding="utf-8")
    old_adversarial = '''    adversarial_trace = [\n        {\n            "id": 0,\n            "role": "worker",\n            "agent_id": "worker_one",\n            "output": "answer text",\n            "usage": {"prompt_tokens": float("nan"), "completion_tokens": float("inf")},\n        },\n        {\n            "id": 1,\n            "role": "worker",\n            "agent_id": "worker_one",\n            "output": None,\n            "usage": "corrupted",\n        },\n    ]\n    _usage, summary = nb._cell_usage(adversarial_trace, agents_by_id, "prompt text")\n    assert summary["token_usage_source"] == "estimated"\n    assert summary["total_tokens"] > 0\n'''
    new_adversarial = '''    adversarial_trace = [\n        {\n            "id": 0,\n            "role": "worker",\n            "agent_id": "worker_one",\n            "output": "answer text",\n            "usage": {"prompt_tokens": float("nan"), "completion_tokens": float("inf")},\n        }\n    ]\n    with pytest.raises(nb.BenchmarkContractError, match="provider-reported"):\n        nb._cell_usage(adversarial_trace, agents_by_id, "prompt text")\n'''
    tests = replace_once(tests, old_adversarial, new_adversarial, "adversarial token fallback test")

    tests = replace_once(
        tests,
        '''                    "agent_id": "worker_one",\n                    "output": "a zebra appears",\n                }\n''',
        '''                    "agent_id": "worker_one",\n                    "output": "a zebra appears",\n                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},\n                }\n''',
        "run-policy success usage",
    )
    tests = replace_once(
        tests,
        '''    # Deterministic tiebreak: equal combined rate resolves by model id.\n    assert nb.cheapest_priced_agent(agents, scenario).model == "vendor/model-b"\n''',
        '''    # Equal price vectors are unresolved; model identity is not routing evidence.\n    assert nb.cheapest_priced_agent(agents, scenario) is None\n''',
        "cheapest-worker tie test",
    )
    tests = tests.replace("estimated_usage_by_model", "reported_usage_by_model")

    old_oversized = '''    class OversizedAnswerClient(ModelClient):\n        def chat(self, *args, **kwargs) -> str:  # type: ignore[override]\n            del args, kwargs\n            return "x" * 5000\n'''
    new_oversized = '''    class OversizedAnswerClient(ModelClient):\n        def chat(self, *args, **kwargs) -> str:  # type: ignore[override]\n            del args, kwargs\n            return "x" * 5000\n\n        def take_usage(self):\n            return {"prompt_tokens": 300, "completion_tokens": 300}\n'''
    tests = replace_once(tests, old_oversized, new_oversized, "observed overflow usage")
    tests = tests.replace(
        'assert evaluation["cheapest_worker_skip_reason"] == "no_worker_priced_by_scenario"',
        'assert evaluation["cheapest_worker_skip_reason"] == "no_uniquely_price_dominant_worker"',
    )
    TEST_PATH.write_text(tests, encoding="utf-8")


def repair_docs() -> None:
    """Record the evidence boundary without inventing a substitute heuristic."""
    adr = ADR_PATH.read_text(encoding="utf-8")
    marker = "## 2026-09-01 NIM benchmark token-evidence amendment"
    if marker not in adr:
        adr += '''\n\n## 2026-09-01 NIM benchmark token-evidence amendment\n\nThe NIM benchmark MUST NOT reconstruct chat prompt or completion usage from character length. ADR-0006 is authoritative: provider chat framing, tool schemas, and multimodal serialization are provider-owned and cannot be recovered from a raw tokenizer or text-length proxy. Equal-budget evaluation therefore records and enforces only complete provider-reported `prompt_tokens` and `completion_tokens`; missing or malformed usage fails closed. Cost evidence is unavailable rather than estimated. The cheapest-worker baseline likewise uses component-wise dominance over the explicit input/output price vector and leaves equal or crossing vectors unresolved instead of imposing an unstated prompt/completion mixture or model-id tie-break.\n'''
        ADR_PATH.write_text(adr, encoding="utf-8")

    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    marker = "## 2026-09-01 no-heuristic NIM benchmark accounting repair"
    if marker not in baseline:
        baseline += '''\n\n## 2026-09-01 no-heuristic NIM benchmark accounting repair\n\nCausal owner: `contextual_orchestrator/nim_benchmark.py`. The benchmark previously used an explicit `~4 chars/token` approximation to admit calls, lower output allowances, enforce equal-token cells, calculate hypothetical cost, and backfill missing trace usage. That violates ADR-0006 and the organization no-heuristics contract. PR #1000 removes the approximation from every benchmark decision/evidence path: complete provider-reported prompt/completion usage is now mandatory, missing evidence fails closed, and cost remains unknown rather than inferred. The same repair removes the benchmark's implicit 1:1 input/output price weight and model-id tie-break; automatic cheapest-worker selection now requires a uniquely component-wise dominant published price vector. Hosted exact-head tests/security/review remain required before protected-main integration.\n'''
        BASELINE_PATH.write_text(baseline, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    entry = "- Remove the NIM benchmark character-count token heuristic and weighted cheapest-worker selector. Benchmark token/cost evidence now requires complete provider-reported usage, and ambiguous price vectors fail closed.\n"
    if entry not in changelog:
        marker = "## [Unreleased]\n"
        if marker not in changelog:
            raise RuntimeError("CHANGELOG is missing the Unreleased section")
        changelog = changelog.replace(marker, marker + entry, 1)
        CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the exact one-shot repair."""
    repair_source()
    repair_tests()
    repair_docs()


if __name__ == "__main__":
    main()
