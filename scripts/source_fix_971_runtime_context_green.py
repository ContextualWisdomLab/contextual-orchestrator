#!/usr/bin/env python3
"""One-shot PR #971 RED/GREEN materializer; deleted by its owning workflow on success."""

from __future__ import annotations

import argparse
from pathlib import Path


TEST_PATH = Path("tests/test_batch_job_registry.py")


def _replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one exact replacement, found {count}: {old!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def materialize_red() -> None:
    """Append durable restart/privacy/timeout regressions once."""
    text = TEST_PATH.read_text(encoding="utf-8")
    marker = "def test_recovered_provider_embedding_restores_persisted_request_context() -> None:"
    if marker in text:
        return
    snippet = r'''


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
    """One provider batch cannot inherit one request's privacy identity for another."""
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


def test_default_provider_embedding_execution_has_no_wall_clock_deadline() -> None:
    """Crash-recovery leases renew without inventing a model inference deadline."""
    client = FakeValkeyClient()
    client.lose_execution_extension = False
    backend = ProviderEmbeddingBatchBackend(
        lambda requests: ([[1.0] for _request in requests], len(requests)),
        job_registry=JobRegistryFactory(client),
        claim_lease_seconds=0.1,
    )
    job = backend.submit([EmbeddingBatchRequest(input_text="slow-is-valid")])
    try:
        assert backend.wait(job, timeout=1)["status"] == "completed"
        assert job.job_id not in backend._deadlines
    finally:
        backend.close()
'''
    TEST_PATH.write_text(text.rstrip() + snippet + "\n", encoding="utf-8")


def apply_green() -> None:
    """Apply the smallest causal production repair after RED verification."""
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
        "        self._execution_timeout_seconds = (\n"
        "            execution_timeout_seconds\n"
        "            if execution_timeout_seconds is not None\n"
        "            else self._registry.retention_seconds\n"
        "        )\n",
        "        self._execution_timeout_seconds = execution_timeout_seconds\n",
    )
    _replace_once(
        "contextual_orchestrator/batch_routing.py",
        "        existing = self._deadlines.get(job_id)\n"
        "        if existing is not None:\n"
        "            return float(existing)\n"
        "        with self._registry.lock(\n",
        "        existing = self._deadlines.get(job_id)\n"
        "        if existing is not None:\n"
        "            return float(existing)\n"
        "        if self._execution_timeout_seconds is None:\n"
        "            return float(\"inf\")\n"
        "        with self._registry.lock(\n",
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
        "_BATCH_LEDGER_SETTLEMENT_TIMEOUT_SECONDS = 1.0\n",
        "_BATCH_LEDGER_SETTLEMENT_TIMEOUT_SECONDS = 1.0\n"
        "_DEFAULT_PROVIDER_EMBEDDING_CLAIM_LEASE_SECONDS = 30.0\n",
    )
    _replace_once(
        "contextual_orchestrator/cost_router.py",
        "        client_timeout = float(getattr(client, \"timeout\", None) or 0)\n"
        "        return ProviderEmbeddingBatchBackend(\n",
        "        client_timeout = float(getattr(client, \"timeout\", None) or 0)\n"
        "        claim_lease_seconds = float(\n"
        "            self.config.get(\n"
        "                _EMBEDDING_CONFIG_CATEGORY,\n"
        "                \"provider_embedding_claim_lease_seconds\",\n"
        "                _DEFAULT_PROVIDER_EMBEDDING_CLAIM_LEASE_SECONDS,\n"
        "            )\n"
        "        )\n"
        "        if self.job_registry.durable and claim_lease_seconds <= 0:\n"
        "            raise ValueError(\"durable provider embedding claim lease must be positive\")\n"
        "        return ProviderEmbeddingBatchBackend(\n",
    )
    _replace_once(
        "contextual_orchestrator/cost_router.py",
        "            claim_lease_seconds=(\n"
        "                client_timeout\n"
        "                if self.job_registry.durable and client_timeout > 0\n"
        "                else None\n"
        "            ),\n"
        "            execution_timeout_seconds=client_timeout if client_timeout > 0 else None,\n"
        "        )\n",
        "            claim_lease_seconds=(\n"
        "                claim_lease_seconds if self.job_registry.durable else None\n"
        "            ),\n"
        "            execution_timeout_seconds=client_timeout if client_timeout > 0 else None,\n"
        "            request_context=lambda request: self.orchestrator.request_policy(\n"
        "                request.zdr_only\n"
        "            ),\n"
        "        )\n",
    )

    baseline = Path("docs/product-technical-gap-baseline.md")
    text = baseline.read_text(encoding="utf-8")
    marker = "## 2026-09-02 — persisted embedding execution authority"
    if marker not in text:
        section = (
            "\n\n"
            + marker
            + "\n\n"
            + "PR #971 treats persisted `zdr_only` as request authority that must be "
            "re-entered at the provider execution boundary after restart, not merely as "
            "stored metadata. `ProviderEmbeddingBatchBackend` rejects mixed-policy batches "
            "and executes the runner inside the recovered request scope. Durable claim lease "
            "duration is separately configured from model inference duration; the default "
            "provider execution deadline remains unbounded and the lease is renewed while an "
            "in-flight model call owns the claim. Exact-head restart/privacy/timeout "
            "regressions and the broader batch/cost-router suites are the source-level "
            "completion evidence; temporary source-fix workflows are never production "
            "artifacts.\n"
        )
        baseline.write_text(text.rstrip() + section, encoding="utf-8")

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text(encoding="utf-8")
    entry = (
        "- Restore persisted embedding request privacy scope after worker restart, reject "
        "mixed-ZDR provider batches, and decouple durable claim leases from unbounded model "
        "inference duration.\n"
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
