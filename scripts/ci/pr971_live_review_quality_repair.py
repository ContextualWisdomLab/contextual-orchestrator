#!/usr/bin/env python3
"""Apply the exact PR #971 owner repair from the temporary source-fix workflow."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact source fragment and fail closed on stale/concurrent state."""
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}")
    target.write_text(text.replace(old, new, 1))


def repair_embedding_privacy_identity() -> None:
    """Restore persisted request privacy and reject mixed execution identity."""
    replace_once(
        "contextual_orchestrator/cost_router.py",
        '''        if any(
            request.model != first.model or request.agent_id != first.agent_id
            for request in requests
        ):
            raise RuntimeError("provider embedding batch must retain one selected route")
        max_tokens, _max_chars, max_inputs = self._embedding_request_limits()
        vectors: List[List[float]] = []
        prompt_tokens = 0
        shard: List[EmbeddingBatchRequest] = []
        shard_tokens = 0
        for request in requests:
            request_tokens = request.token_count or len(request.input_text.encode("utf-8"))
            if shard and (
                len(shard) >= max_inputs or shard_tokens + request_tokens > max_tokens
            ):
                shard_vectors, shard_usage = self._run_embedding_shard(agent, shard)
                vectors.extend(shard_vectors)
                prompt_tokens += shard_usage
                shard = []
                shard_tokens = 0
            shard.append(request)
            shard_tokens += request_tokens
        if shard:
            shard_vectors, shard_usage = self._run_embedding_shard(agent, shard)
            vectors.extend(shard_vectors)
            prompt_tokens += shard_usage
        return vectors, prompt_tokens
''',
        '''        if any(
            request.model != first.model
            or request.agent_id != first.agent_id
            or request.zdr_only != first.zdr_only
            or request.provider_routing != first.provider_routing
            for request in requests
        ):
            raise RuntimeError(
                "provider embedding batch must retain one selected route and privacy policy"
            )
        max_tokens, _max_chars, max_inputs = self._embedding_request_limits()
        vectors: List[List[float]] = []
        prompt_tokens = 0
        shard: List[EmbeddingBatchRequest] = []
        shard_tokens = 0
        with self.orchestrator.request_policy(first.zdr_only):
            for request in requests:
                request_tokens = request.token_count or len(request.input_text.encode("utf-8"))
                if shard and (
                    len(shard) >= max_inputs or shard_tokens + request_tokens > max_tokens
                ):
                    shard_vectors, shard_usage = self._run_embedding_shard(agent, shard)
                    vectors.extend(shard_vectors)
                    prompt_tokens += shard_usage
                    shard = []
                    shard_tokens = 0
                shard.append(request)
                shard_tokens += request_tokens
            if shard:
                shard_vectors, shard_usage = self._run_embedding_shard(agent, shard)
                vectors.extend(shard_vectors)
                prompt_tokens += shard_usage
        return vectors, prompt_tokens
''',
    )


def repair_terminal_batch_health() -> None:
    """Treat terminal provider batch documents as failures before health success."""
    replace_once(
        "contextual_orchestrator/server.py",
        '''                        orchestrator._group_router.observe_success(
                            embedding_agent.id,
                            time.perf_counter() - attempt_started_at,
                        )
                        orchestrator._record_success(embedding_agent.id)
                        break
''',
        '''                        terminal_status = str(
                            document.get("status") or ""
                        ).strip().lower()
                        if terminal_status in {"failed", "cancelled", "canceled", "rejected"}:
                            terminal_error = RuntimeError(
                                "embedding batch returned terminal provider status "
                                f"{terminal_status!r}"
                            )
                            last_embedding_error = terminal_error
                            orchestrator._record_embedding_failure(
                                embedding_agent,
                                "/v1/batch/embeddings",
                                terminal_error,
                            )
                            document = None
                            continue
                        orchestrator._group_router.observe_success(
                            embedding_agent.id,
                            time.perf_counter() - attempt_started_at,
                        )
                        orchestrator._record_success(embedding_agent.id)
                        break
''',
    )


def repair_shared_discovery_deadlines() -> None:
    """Bound shared discovery metadata independently from model inference."""
    model_path = Path("contextual_orchestrator/model_discovery.py")
    model_text = model_path.read_text()
    marker = "\n\ndef discover_all_models(\n"
    if model_text.count(marker) != 1:
        raise SystemExit("model_discovery.py: discover_all_models marker was not unique")
    helper = '''

def _run_discovery_control_plane_bounded(
    operation,
    *,
    discovery_deadline: float | None,
    fallback: Any,
    operation_name: str,
) -> Any:
    """Run one shared discovery metadata operation under the discovery bound.

    Shared Models.dev, OpenRouter ZDR, and OpenRouter credit metadata are
    bootstrap control-plane calls just like per-provider catalog discovery.
    They deliberately do not inherit a model-inference timeout; instead this
    helper abandons a daemon worker after ``discovery_deadline`` so one hung
    shared dependency cannot starve every provider. ``None`` retains the
    explicit unbounded opt-in. A timeout returns a fail-closed caller-supplied
    fallback and never publishes positive capability/privacy/spend evidence.
    """
    if discovery_deadline is None:
        return operation()
    results: list[Any] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(operation())
        except BaseException as exc:  # noqa: BLE001 -- re-raised below
            failures.append(exc)

    worker = threading.Thread(
        target=run,
        name=f"discover-metadata-{operation_name}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=discovery_deadline)
    if worker.is_alive():
        _LOGGER.warning(
            "discovery_metadata_timeout operation=%s deadline_seconds=%s",
            operation_name,
            discovery_deadline,
        )
        return fallback
    if failures:
        raise failures[0]
    return results[0] if results else fallback
'''
    model_path.write_text(model_text.replace(marker, helper + marker, 1))

    replace_once(
        "contextual_orchestrator/model_discovery.py",
        "        models_dev_metadata = _fetch_models_dev_metadata(timeout=timeout)\n",
        '''        models_dev_metadata = _run_discovery_control_plane_bounded(
            lambda: _fetch_models_dev_metadata(timeout=timeout),
            discovery_deadline=discovery_deadline,
            fallback=None,
            operation_name="models-dev",
        )
''',
    )
    replace_once(
        "contextual_orchestrator/model_discovery.py",
        "        _openrouter_zdr_model_ids(timeout=timeout),\n",
        '''        _run_discovery_control_plane_bounded(
            lambda: _openrouter_zdr_model_ids(timeout=timeout),
            discovery_deadline=discovery_deadline,
            fallback=set(),
            operation_name="openrouter-zdr",
        ),
''',
    )
    replace_once(
        "contextual_orchestrator/model_discovery.py",
        "            openrouter_paid_inference_available(timeout=timeout),\n",
        '''            _run_discovery_control_plane_bounded(
                lambda: openrouter_paid_inference_available(timeout=timeout),
                discovery_deadline=discovery_deadline,
                fallback=None,
                operation_name="openrouter-credit",
            ),
''',
    )


def update_traceability() -> None:
    """Record the repaired operating contracts in changelog and product gap baseline."""
    changelog = Path("CHANGELOG.md")
    changelog_text = changelog.read_text()
    fixed_marker = "### Fixed\n\n"
    bullet = (
        "- Provider-embedding recovery now re-enters the persisted ZDR request-policy scope "
        "and rejects mixed privacy/routing identities before provider I/O; terminal "
        "failed/cancelled/rejected embedding-batch documents count as endpoint failures "
        "and fail over instead of clearing circuit health. Shared Models.dev, OpenRouter "
        "ZDR, and OpenRouter credit discovery metadata now use the same independent "
        "control-plane discovery deadline as provider catalogs, with fail-closed timeout "
        "fallbacks rather than model-inference deadlines (PR #971).\n"
    )
    if bullet not in changelog_text:
        if fixed_marker not in changelog_text:
            raise SystemExit("CHANGELOG.md: missing Fixed marker")
        changelog.write_text(changelog_text.replace(fixed_marker, fixed_marker + bullet, 1))

    baseline = Path("docs/product-technical-gap-baseline.md")
    baseline_text = baseline.read_text()
    section_title = "## PR #971 review-quality runtime boundary repair (2026-09-02)"
    if section_title not in baseline_text:
        baseline.write_text(
            baseline_text.rstrip()
            + "\n\n"
            + section_title
            + "\n\n"
            + "**Status: Proposed until one unchanged successor head is exact-head GREEN.** "
            "Current-head external review evidence proved four causal owner defects: durably "
            "recovered `zdr_only` embedding work revalidated tags but did not re-enter request-"
            "policy execution scope; coalesced embedding work compared only model/agent identity "
            "and could mix privacy/routing identity; terminal provider batch documents were "
            "recorded as endpoint success before terminal status was inspected; and shared "
            "Models.dev, OpenRouter ZDR, and credit metadata calls sat outside the per-provider "
            "discovery deadline and could starve all discovery under the default no-inference-"
            "timeout contract. The owner repair binds execution to persisted privacy/routing "
            "identity, treats terminal batch documents as failures that participate in failover, "
            "and bounds every shared discovery metadata call with a fail-closed control-plane "
            "deadline. `tests/test_pr971_review_quality_regressions.py` is the durable false-"
            "negative corpus for these exact defect classes.\n"
        )


def main() -> None:
    """Apply every causal production/config/docs repair exactly once."""
    repair_embedding_privacy_identity()
    repair_terminal_batch_health()
    repair_shared_discovery_deadlines()
    update_traceability()


if __name__ == "__main__":
    main()
