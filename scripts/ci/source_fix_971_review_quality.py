#!/usr/bin/env python3
"""One-shot PR #971 reviewer-quality RED/GREEN materializer.

The owning workflow deletes this helper and itself after all focused and broad
verification succeeds on the exact unchanged writer head.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact anchor, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def _append_once(path: str, marker: str, snippet: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + snippet.strip() + "\n", encoding="utf-8")


def materialize_red() -> None:
    """Add durable executable regressions for demonstrated external-review misses."""
    _append_once(
        "tests/test_batch_job_registry.py",
        "def test_recovered_provider_embedding_restores_persisted_request_context() -> None:",
        r'''
def test_recovered_provider_embedding_restores_persisted_request_context() -> None:
    """Restart recovery re-enters persisted privacy authority before provider I/O."""
    client = FakeValkeyClient()
    client.lose_execution_extension = False
    registry = JobRegistryFactory(client)
    events: list[tuple[str, bool]] = []

    class RequestScope:
        def __init__(self, zdr_only: bool) -> None:
            self.zdr_only = zdr_only

        def __enter__(self):
            events.append(("enter", self.zdr_only))
            return self

        def __exit__(self, *_exc) -> None:
            events.append(("exit", self.zdr_only))

    def request_context(request: EmbeddingBatchRequest):
        return RequestScope(request.zdr_only)

    def runner(requests):
        assert events[-1] == ("enter", True)
        return [[1.0] for _request in requests], len(requests)

    original = ProviderEmbeddingBatchBackend(
        runner,
        job_registry=registry,
        claim_lease_seconds=1,
        request_context=request_context,
    )
    job = original.reserve(
        [EmbeddingBatchRequest(input_text="private", model="synthetic-model", zdr_only=True)]
    )
    original._states[job.job_id] = "queued"
    original.close()

    recovered = ProviderEmbeddingBatchBackend(
        runner,
        job_registry=registry,
        claim_lease_seconds=1,
        request_context=request_context,
    )
    try:
        assert recovered.wait(job, timeout=1)["status"] == "completed"
        assert events == [("enter", True), ("exit", True)]
    finally:
        recovered.close()


def test_provider_embedding_rejects_mixed_zdr_policy_before_provider_io() -> None:
    """One durable batch cannot inherit one request's privacy identity for another."""
    client = FakeValkeyClient()
    client.lose_execution_extension = False
    calls = 0

    def runner(requests):
        nonlocal calls
        calls += 1
        return [[1.0] for _request in requests], len(requests)

    backend = ProviderEmbeddingBatchBackend(
        runner,
        job_registry=JobRegistryFactory(client),
        claim_lease_seconds=1,
    )
    job = backend.submit(
        [
            EmbeddingBatchRequest(input_text="private", zdr_only=True),
            EmbeddingBatchRequest(input_text="public", zdr_only=False),
        ]
    )
    try:
        document = backend.wait(job, timeout=1)
        assert document["status"] == "failed"
        assert document["failure"]["error_type"] == "ValueError"
        assert calls == 0
    finally:
        backend.close()
''',
    )
    _append_once(
        "tests/test_embeddings_model_pool_http_honesty.py",
        "def test_batch_terminal_failure_fails_over_without_restoring_endpoint_health() -> None:",
        r'''
def test_batch_terminal_failure_fails_over_without_restoring_endpoint_health() -> None:
    """A terminal failed batch is failure evidence, never endpoint-success evidence."""
    first = ModelAgent(
        "failed_embedding", "embed-v1", tags=("embedding",), priority=1
    )
    second = ModelAgent("healthy_embedding", "embed-v1", tags=("embedding",))
    orchestrator = TaskOrchestrator([first, second])
    coordinator = CostRoutingCoordinator(orchestrator)
    attempted: list[str] = []

    def complete_embeddings_batch(_inputs, *, agent_id, **_kwargs):
        attempted.append(agent_id)
        if agent_id == first.id:
            return {
                "status": "failed",
                "batch_id": "failed_batch",
                "backend": "remote",
                "failure": {"error_type": "SyntheticProviderFailure"},
            }
        return {
            "status": "validating",
            "batch_id": "healthy_batch",
            "backend": "remote",
        }

    coordinator.complete_embeddings_batch = complete_embeddings_batch
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
        coordinator=coordinator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            "/v1/batch/embeddings",
            {"model": "embed-v1", "input": "invoice search chunk"},
        )
        assert status == 202, body
        assert body["batch_id"] == "healthy_batch"
        assert attempted == [first.id, second.id]
        failures = [
            event
            for event in orchestrator._analytics_events
            if event["event_name"] == "embedding_endpoint_failed"
        ]
        assert len(failures) == 1
        assert failures[0]["event_detail"]["agent_id"] == first.id
        assert first.id in orchestrator._circuit
    finally:
        server.shutdown()
        thread.join(timeout=5)
''',
    )
    _append_once(
        "tests/test_model_discovery.py",
        "def test_discovery_default_has_independent_finite_network_deadline() -> None:",
        r'''
def test_discovery_default_has_independent_finite_network_deadline() -> None:
    """Catalog I/O is bounded independently from unbounded model inference."""
    from contextual_orchestrator import model_discovery

    assert model_discovery.DISCOVERY_TIMEOUT_SECONDS == 15.0
''',
    )
    _append_once(
        "tests/test_provider_bootstrap.py",
        "def test_bootstrap_first_pass_preserves_provider_failure_domain_diversity() -> None:",
        r'''
def test_bootstrap_first_pass_preserves_provider_failure_domain_diversity() -> None:
    """Available provider alternatives occupy independent bootstrap failure domains."""
    cheapest = _model("openai", "OPENAI_API_KEY", "gpt-cheapest", 0.01)
    same_provider = _model("openai", "OPENAI_API_KEY", "gpt-second", 0.02)
    independent = _model("openrouter", "OPENROUTER_API_KEY", "qwen-independent", 0.50)

    selected = provider_bootstrap.select_model_group_diverse_models(
        [same_provider, independent, cheapest], limit=2
    )

    assert [(item.provider_name, item.model_id) for item in selected] == [
        ("openai", "gpt-cheapest"),
        ("openrouter", "qwen-independent"),
    ]
''',
    )


def apply_green() -> None:
    """Apply the smallest causal owner fixes after every RED is observed."""
    _replace_once(
        "contextual_orchestrator/batch_routing.py",
        "        execution_timeout_seconds: float | None = None,\n    ) -> None:\n",
        "        execution_timeout_seconds: float | None = None,\n"
        "        request_context: Callable[[EmbeddingBatchRequest], Any] | None = None,\n"
        "    ) -> None:\n",
    )
    _replace_once(
        "contextual_orchestrator/batch_routing.py",
        "        self._runner = runner\n        self._max_concurrency = max_concurrency\n",
        "        self._runner = runner\n"
        "        self._request_context = request_context\n"
        "        self._max_concurrency = max_concurrency\n",
    )
    _replace_once(
        "contextual_orchestrator/batch_routing.py",
        "        requests = list(self._requests[job_id])\n"
        "        try:\n"
        "            vectors, prompt_tokens = self._runner(requests)\n",
        "        requests = list(self._requests[job_id])\n"
        "        try:\n"
        "            if requests and any(\n"
        "                request.zdr_only != requests[0].zdr_only for request in requests\n"
        "            ):\n"
        "                raise ValueError(\"provider embedding batch cannot mix ZDR policies\")\n"
        "            request_scope = (\n"
        "                self._request_context(requests[0])\n"
        "                if self._request_context is not None and requests\n"
        "                else nullcontext()\n"
        "            )\n"
        "            with request_scope:\n"
        "                vectors, prompt_tokens = self._runner(requests)\n",
    )
    _replace_once(
        "contextual_orchestrator/cost_router.py",
        "            execution_timeout_seconds=client_timeout if client_timeout > 0 else None,\n"
        "        )\n",
        "            execution_timeout_seconds=client_timeout if client_timeout > 0 else None,\n"
        "            request_context=lambda request: self.orchestrator.request_policy(\n"
        "                request.zdr_only\n"
        "            ),\n"
        "        )\n",
    )
    _replace_once(
        "contextual_orchestrator/server.py",
        "                        orchestrator._group_router.observe_success(\n"
        "                            embedding_agent.id,\n"
        "                            time.perf_counter() - attempt_started_at,\n"
        "                        )\n"
        "                        orchestrator._record_success(embedding_agent.id)\n"
        "                        break\n",
        "                        terminal_status = str(document.get(\"status\") or \"\").lower()\n"
        "                        if terminal_status in {\"failed\", \"cancelled\", \"rejected\"}:\n"
        "                            terminal_error = RuntimeError(\n"
        "                                f\"embedding batch returned terminal status {terminal_status!r}\"\n"
        "                            )\n"
        "                            failure = document.get(\"failure\")\n"
        "                            if isinstance(failure, dict):\n"
        "                                provider_status = failure.get(\"http_status\")\n"
        "                                if type(provider_status) is int:\n"
        "                                    terminal_error.provider_status = provider_status  # type: ignore[attr-defined]\n"
        "                            last_embedding_error = terminal_error\n"
        "                            orchestrator._record_embedding_failure(\n"
        "                                embedding_agent, \"/v1/batch/embeddings\", terminal_error\n"
        "                            )\n"
        "                            document = None\n"
        "                            continue\n"
        "                        orchestrator._group_router.observe_success(\n"
        "                            embedding_agent.id,\n"
        "                            time.perf_counter() - attempt_started_at,\n"
        "                        )\n"
        "                        orchestrator._record_success(embedding_agent.id)\n"
        "                        break\n",
    )
    _replace_once(
        "contextual_orchestrator/model_discovery.py",
        "DISCOVERY_TIMEOUT_SECONDS: float | None = None\n"
        "_LOGGER = logging.getLogger(__name__)\n"
        "# One retry for a provider's primary model-list fetch, reusing the same\n"
        "# transient-vs-terminal classification completion calls already trust\n"
        "# (is_transient_error). Discovery has no default wall-clock deadline: a slow\n"
        "# provider catalog must not be mistaken for an unavailable provider.\n",
        "DISCOVERY_TIMEOUT_SECONDS: float = 15.0\n"
        "_LOGGER = logging.getLogger(__name__)\n"
        "# One retry for a provider's primary model-list fetch, reusing the same\n"
        "# transient-vs-terminal classification completion calls already trust\n"
        "# (is_transient_error). Catalog and policy metadata I/O retains its independent\n"
        "# finite control-plane deadline; this does not impose a model-generation timeout.\n",
    )
    _replace_once(
        "contextual_orchestrator/provider_bootstrap.py",
        "    \"\"\"Choose a bounded compatible pool with one first-pass endpoint per model group.\"\"\"\n"
        "    if limit < 1:\n"
        "        raise ValueError(\"provider bootstrap model limit must be positive\")\n"
        "    unique: dict[tuple[str, str, str], DiscoveredModel] = {}\n"
        "    for model in discovered:\n"
        "        if not is_chat_serving_candidate(model):\n"
        "            continue\n"
        "        unique[(model.provider_name, model.credential_name, model.model_id)] = model\n"
        "    ordered = sorted(unique.values(), key=_known_cost_sort_key)\n"
        "    selected: list[DiscoveredModel] = []\n"
        "    seen_model_groups: set[str] = set()\n"
        "    for model in ordered:\n"
        "        model_group = model_group_name_for(model)\n"
        "        if model_group in seen_model_groups:\n"
        "            continue\n"
        "        selected.append(model)\n"
        "        seen_model_groups.add(model_group)\n"
        "        if len(selected) >= limit:\n"
        "            return selected\n"
        "    selected_keys = {\n"
        "        (item.provider_name, item.credential_name, item.model_id)\n"
        "        for item in selected\n"
        "    }\n"
        "    for model in ordered:\n"
        "        key = (model.provider_name, model.credential_name, model.model_id)\n"
        "        if key in selected_keys:\n"
        "            continue\n"
        "        selected.append(model)\n"
        "        if len(selected) >= limit:\n"
        "            break\n"
        "    return selected\n",
        "    \"\"\"Choose a bounded pool diversified by provider and exact model group.\"\"\"\n"
        "    if limit < 1:\n"
        "        raise ValueError(\"provider bootstrap model limit must be positive\")\n"
        "    unique: dict[tuple[str, str, str], DiscoveredModel] = {}\n"
        "    for model in discovered:\n"
        "        if not is_chat_serving_candidate(model):\n"
        "            continue\n"
        "        unique[(model.provider_name, model.credential_name, model.model_id)] = model\n"
        "    ordered = sorted(unique.values(), key=_known_cost_sort_key)\n"
        "    selected: list[DiscoveredModel] = []\n"
        "    selected_keys: set[tuple[str, str, str]] = set()\n"
        "    seen_model_groups: set[str] = set()\n"
        "    seen_providers: set[str] = set()\n"
        "\n"
        "    def select(model: DiscoveredModel) -> None:\n"
        "        key = (model.provider_name, model.credential_name, model.model_id)\n"
        "        selected.append(model)\n"
        "        selected_keys.add(key)\n"
        "        seen_model_groups.add(model_group_name_for(model))\n"
        "        seen_providers.add(model.provider_name)\n"
        "\n"
        "    # First preserve independent provider failure domains while also avoiding\n"
        "    # duplicate exact-model groups. Cost order decides within each new domain.\n"
        "    for model in ordered:\n"
        "        if model.provider_name in seen_providers:\n"
        "            continue\n"
        "        if model_group_name_for(model) in seen_model_groups:\n"
        "            continue\n"
        "        select(model)\n"
        "        if len(selected) >= limit:\n"
        "            return selected\n"
        "\n"
        "    # Then maximize exact-model-group diversity across already represented\n"
        "    # providers before filling any remaining capacity by ordinary cost order.\n"
        "    for model in ordered:\n"
        "        key = (model.provider_name, model.credential_name, model.model_id)\n"
        "        if key in selected_keys or model_group_name_for(model) in seen_model_groups:\n"
        "            continue\n"
        "        select(model)\n"
        "        if len(selected) >= limit:\n"
        "            return selected\n"
        "    for model in ordered:\n"
        "        key = (model.provider_name, model.credential_name, model.model_id)\n"
        "        if key in selected_keys:\n"
        "            continue\n"
        "        select(model)\n"
        "        if len(selected) >= limit:\n"
        "            break\n"
        "    return selected\n",
    )

    baseline = Path("docs/product-technical-gap-baseline.md")
    text = baseline.read_text(encoding="utf-8")
    marker = "## 2026-09-02 — recovered privacy, discovery, and failure-domain authority"
    if marker not in text:
        text = text.rstrip() + (
            "\n\n" + marker + "\n\n"
            "PR #971 now treats persisted `zdr_only` as execution authority that must be "
            "re-entered at the provider I/O boundary after restart. Durable provider "
            "embedding batches reject mixed privacy identities before any runner call. "
            "The HTTP batch-embedding failover path classifies terminal "
            "`failed`/`cancelled`/`rejected` documents as endpoint failure evidence and "
            "never clears circuit state for them; accepted non-terminal submissions remain "
            "responsiveness evidence. Provider catalog/control-plane I/O restores its "
            "independent 15-second default deadline without imposing a generation timeout, "
            "and bootstrap selection reserves independent provider failure domains before "
            "adding same-provider model-group capacity. Executable restart, mixed-policy, "
            "terminal-health, discovery-deadline, provider-diversity, and endpoint-race "
            "provenance regressions are required on the exact head.\n"
        )
        baseline.write_text(text, encoding="utf-8")

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text(encoding="utf-8")
    entry = (
        "- Restore persisted ZDR execution scope after provider-batch restart, reject "
        "mixed privacy identity batches before provider I/O, preserve endpoint-race "
        "terminal failure provenance, prevent terminal failed embedding batches from "
        "restoring endpoint health, restore the independent provider-discovery network "
        "deadline, and preserve provider failure-domain diversity during bootstrap.\n"
    )
    if entry not in text:
        if "## [Unreleased]\n" in text:
            text = text.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
        elif "## Unreleased\n" in text:
            text = text.replace("## Unreleased\n", "## Unreleased\n" + entry, 1)
        else:
            text = entry + "\n" + text
        changelog.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("red", "green"))
    args = parser.parse_args()
    if args.mode == "red":
        materialize_red()
    else:
        apply_green()


if __name__ == "__main__":
    main()
