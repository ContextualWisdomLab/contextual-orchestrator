#!/usr/bin/env python3
"""Materialize the remaining exact-head PR #971 review-quality repair."""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact source fragment and fail closed on concurrent drift."""
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}")
    target.write_text(text.replace(old, new, 1))


def install_red_tests() -> None:
    """Add executable regressions for the two still-live external findings."""
    path = Path("tests/test_pr971_review_quality_regressions.py")
    text = path.read_text()
    import_line = "from contextual_orchestrator import model_discovery as model_discovery_module\n"
    anchor = "from contextual_orchestrator import CostRoutingCoordinator, ModelAgent, TaskOrchestrator\n"
    if import_line not in text:
        if anchor not in text:
            raise SystemExit("review regression import anchor missing")
        text = text.replace(anchor, anchor + import_line, 1)

    provider_test = '''\n\ndef test_provider_embedding_batch_rejects_mixed_provider_routing_identity() -> None:\n    """Equal ZDR flags cannot hide different persisted provider-routing identities."""\n    coordinator, _orchestrator, agent = _embedding_coordinator()\n    first = EmbeddingBatchRequest(\n        input_text="first",\n        model=agent.model,\n        token_count=1,\n        zdr_only=True,\n        agent_id=agent.id,\n        provider_routing={"zdr": True, "order": ["provider-a"]},\n    )\n    second = EmbeddingBatchRequest(\n        input_text="second",\n        model=agent.model,\n        token_count=1,\n        zdr_only=True,\n        agent_id=agent.id,\n        provider_routing={"zdr": True, "order": ["provider-b"]},\n    )\n\n    with pytest.raises(RuntimeError, match="privacy policy"):\n        coordinator._run_provider_embeddings([first, second])\n'''
    if "test_provider_embedding_batch_rejects_mixed_provider_routing_identity" not in text:
        text += provider_test

    worker_test = '''\n\ndef test_openrouter_endpoint_enrichment_caps_daemon_workers(monkeypatch) -> None:\n    """A large free-model catalog must not allocate one thread per model row."""\n    payload = {\n        "data": [\n            {\n                "id": f"vendor/model-{index}",\n                "pricing": {"prompt": "0", "completion": "0"},\n            }\n            for index in range(24)\n        ]\n    }\n    real_thread = model_discovery_module.threading.Thread\n    created = []\n\n    def tracked_thread(*args, **kwargs):\n        thread = real_thread(*args, **kwargs)\n        created.append(thread)\n        return thread\n\n    monkeypatch.setattr(model_discovery_module.threading, "Thread", tracked_thread)\n    monkeypatch.setattr(\n        model_discovery_module,\n        "_fetch_json",\n        lambda *_args, **_kwargs: {"data": []},\n    )\n\n    result = model_discovery_module._openrouter_free_model_endpoints(\n        payload,\n        api_key="synthetic",\n        timeout=0.1,\n    )\n\n    assert set(result) == {f"vendor/model-{index}" for index in range(24)}\n    assert 1 <= len(created) <= 8\n    assert all(thread.daemon for thread in created)\n'''
    if "test_openrouter_endpoint_enrichment_caps_daemon_workers" not in text:
        text += worker_test
    path.write_text(text)


def repair_provider_routing_identity() -> None:
    """Make persisted provider-routing metadata part of batch execution identity."""
    replace_once(
        "contextual_orchestrator/cost_router.py",
        '''            or request.zdr_only != first.zdr_only\n            for request in requests\n''',
        '''            or request.zdr_only != first.zdr_only\n            or request.provider_routing != first.provider_routing\n            for request in requests\n''',
    )


def repair_openrouter_endpoint_worker_bound() -> None:
    """Use at most eight daemon workers regardless of free-model catalog size."""
    replace_once(
        "contextual_orchestrator/model_discovery.py",
        '''    results: dict[str, Any] = {}\n    results_lock = threading.Lock()\n    concurrency_limit = threading.Semaphore(min(8, len(model_ids) or 1))\n\n    def run(model_id: str) -> None:\n        with concurrency_limit:\n            value = fetch(model_id)\n        with results_lock:\n            results[model_id] = value\n\n    workers = [\n        threading.Thread(\n            target=run,\n            args=(model_id,),\n            name=f"openrouter-endpoints-{model_id}",\n            daemon=True,\n        )\n        for model_id in model_ids\n    ]\n    for worker in workers:\n        worker.start()\n    for worker in workers:\n        # No join timeout: this whole call already executes inside an\n        # already-bounded, already-daemonized caller (see the docstring\n        # above), so blocking this thread forever on an abandoned peer is\n        # the same accepted tradeoff already documented for\n        # `_run_bounded_by_deadline` -- the daemon property is what matters\n        # for shutdown, not how long this particular thread blocks.\n        worker.join()\n    return results\n''',
        '''    results: dict[str, Any] = {}\n    results_lock = threading.Lock()\n    pending = iter(model_ids)\n    pending_lock = threading.Lock()\n\n    def run() -> None:\n        while True:\n            with pending_lock:\n                try:\n                    model_id = next(pending)\n                except StopIteration:\n                    return\n            value = fetch(model_id)\n            with results_lock:\n                results[model_id] = value\n\n    workers = [\n        threading.Thread(\n            target=run,\n            name=f"openrouter-endpoints-worker-{index}",\n            daemon=True,\n        )\n        for index in range(min(8, len(model_ids)))\n    ]\n    for worker in workers:\n        worker.start()\n    for worker in workers:\n        # The enclosing discovery operation is independently deadline-bounded\n        # and daemon-owned. Keeping this inner pool daemon-only lets the outer\n        # caller abandon a stalled transport without registering interpreter-\n        # shutdown joins, while the fixed cardinality prevents a large catalog\n        # from allocating one blocked thread per model row.\n        worker.join()\n    return results\n''',
    )
    replace_once(
        "contextual_orchestrator/model_discovery.py",
        '''    ``daemon=True`` thread. Plain ``threading.Thread(daemon=True)`` workers\n    carry none of that registration, so a hung fetch is abandoned exactly\n    like every other stalled discovery-time network call in this module:\n    the thread is silently discarded at interpreter exit, and shutdown is\n    never blocked on it. ``max_workers``-equivalent concurrency (at most 8\n    fetches in flight at a time) is preserved via a bounding semaphore.\n''',
        '''    ``daemon=True`` thread. Plain ``threading.Thread(daemon=True)`` workers\n    carry none of that registration, so a hung fetch is abandoned exactly\n    like every other stalled discovery-time network call in this module:\n    the thread is silently discarded at interpreter exit, and shutdown is\n    never blocked on it. A fixed pool of at most eight daemon workers consumes\n    the catalog through a shared iterator, so catalog cardinality cannot become\n    thread cardinality while preserving the same eight-fetch concurrency cap.\n''',
    )


def repair_comment_contract() -> None:
    """Keep the bootstrap-diversity fixture explanation consistent with its oracle."""
    replace_once(
        "tests/test_discovery_bootstrap_selection.py",
        '''    # nim_duplicate (0.03) beats openai_model (1.0) on price alone, but\n    # nim_duplicate shares router_second's model group ("shared-model") --\n    # admitting it would not add a new independently-failing path, only a\n    # pricier duplicate of a model already covered. openai_model is both a\n    # new provider and a new model group, so it is preferred instead.\n''',
        '''    # router_second is deferred in the first pass because OpenRouter already\n    # contributed router_cheapest, so its shared-model group is not selected yet.\n    # nim_duplicate therefore contributes both a new provider and a new model\n    # group; openai_model then supplies the third independent provider path.\n''',
    )


def update_traceability() -> None:
    """Record the execution-identity and bounded-worker contracts."""
    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    bullet = (
        "- Provider embedding batch execution now treats persisted provider-routing metadata as "
        "part of the immutable execution identity, and OpenRouter free-model endpoint enrichment "
        "uses at most eight daemon workers regardless of catalog cardinality (PR #971).\n"
    )
    if bullet not in text:
        marker = "### Fixed\n\n"
        if marker not in text:
            raise SystemExit("CHANGELOG.md: missing Fixed section")
        changelog.write_text(text.replace(marker, marker + bullet, 1))

    baseline = Path("docs/product-technical-gap-baseline.md")
    text = baseline.read_text()
    title = "## PR #971 execution-identity and discovery-worker repair (2026-09-02)"
    if title not in text:
        baseline.write_text(
            text.rstrip()
            + "\n\n"
            + title
            + "\n\n"
            + "**Status: Proposed until one unchanged successor head is exact-head GREEN.** "
            "Current external review evidence showed that equal model/agent/ZDR fields could still "
            "coalesce records with different persisted `provider_routing`, and that OpenRouter free-"
            "model endpoint enrichment allocated one daemon thread per catalog row despite an eight-"
            "request semaphore. The owner repair makes `provider_routing` part of the batch execution "
            "identity and replaces thread-per-row construction with a fixed pool of at most eight "
            "daemon workers. `tests/test_pr971_review_quality_regressions.py` preserves both false-"
            "negative cases as executable regressions.\n"
        )


def apply_green() -> None:
    """Apply only the smallest causal source/docs fixes for the installed REDs."""
    repair_provider_routing_identity()
    repair_openrouter_endpoint_worker_bound()
    repair_comment_contract()
    update_traceability()


def main() -> None:
    """Run the requested transaction phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("red", "green"))
    args = parser.parse_args()
    if args.phase == "red":
        install_red_tests()
    else:
        apply_green()


if __name__ == "__main__":
    main()
