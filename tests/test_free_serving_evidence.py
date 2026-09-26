"""Per-call cost evidence decides whether a route is servable free right now."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager

import pytest

from contextual_orchestrator import free_serving_evidence as evidence
from contextual_orchestrator.free_serving_evidence import (
    FREE_SERVING_LEDGER,
    CostVerdict,
    FreeServingLedger,
    classify_reported_cost,
    free_serving_admitted,
    record_reported_cost,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    general_free_serving_candidates,
)
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    ModelClient,
    TaskOrchestrator,
)

EXPERIENTIAL = "experiential_labs"


def _discovered(provider: str, model_id: str, *, free: bool = True) -> DiscoveredModel:
    price = 0.0 if free else 1.0
    return DiscoveredModel(
        provider_name=provider,
        model_id=model_id,
        credential_name=f"{provider.upper()}_API_KEY",
        chat_base_url="https://example.invalid/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=price,
        completion_price_per_1k=price,
        is_free=free,
        input_modalities=("text",),
        output_modalities=("text",),
    )


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"cost": 0, "is_byok": False}, CostVerdict.FREE),
        ({"cost": 0.0, "is_byok": False}, CostVerdict.FREE),
        ({"cost": "0", "is_byok": False}, CostVerdict.FREE),
        ({"cost": 0.0016, "is_byok": False}, CostVerdict.PAID),
        ({"cost": 1}, CostVerdict.PAID),
        # BYOK settles cost 0 while the upstream provider bills the account.
        ({"cost": 0, "is_byok": True}, CostVerdict.UNKNOWN),
        # An absent BYOK flag is not evidence of a platform-side free charge.
        ({"cost": 0}, CostVerdict.UNKNOWN),
        # Idempotency-Key replies and non-reporting providers omit the field.
        ({"prompt_tokens": 3, "completion_tokens": 1}, CostVerdict.UNKNOWN),
        (None, CostVerdict.UNKNOWN),
        ({"cost": None, "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": -0.01, "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": float("nan"), "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": float("inf"), "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": "free", "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": True, "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": [0], "is_byok": False}, CostVerdict.UNKNOWN),
    ],
)
def test_reported_cost_classification_is_fail_closed(usage, expected) -> None:
    assert classify_reported_cost(usage) is expected


def test_cost_header_is_unset_until_a_provider_documents_one() -> None:
    """No public doc names a per-call cost header; headers are ignored by default."""
    assert evidence.REPORTED_COST_HEADER is None
    assert (
        classify_reported_cost({"cost": 0, "is_byok": False}, {"x-anything-cost": "5"})
        is CostVerdict.FREE
    )


def test_configured_cost_header_must_parse_and_agree_with_the_body(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "REPORTED_COST_HEADER", "x-test-call-cost")
    free_body = {"cost": 0, "is_byok": False}
    assert classify_reported_cost(free_body, {"x-test-call-cost": "0"}) is CostVerdict.FREE
    assert classify_reported_cost(free_body, {"x-test-call-cost": "0.01"}) is CostVerdict.UNKNOWN
    assert classify_reported_cost(free_body, {"x-test-call-cost": "n/a"}) is CostVerdict.UNKNOWN
    assert classify_reported_cost({"is_byok": False}, {"x-test-call-cost": "0.5"}) is CostVerdict.PAID
    assert classify_reported_cost({"is_byok": False}, {"x-test-call-cost": "0"}) is CostVerdict.FREE
    assert classify_reported_cost({}, {"x-test-call-cost": "0"}) is CostVerdict.UNKNOWN
    assert classify_reported_cost(free_body, {}) is CostVerdict.FREE


def test_ledger_ignores_unknown_for_providers_that_do_not_report_cost() -> None:
    ledger = FreeServingLedger()
    ledger.record("nvidia_nim", "m", CostVerdict.PAID)
    ledger.record("nvidia_nim", "m", CostVerdict.UNKNOWN)
    assert ledger.verdict("nvidia_nim", "m") is CostVerdict.PAID
    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)
    ledger.record(EXPERIENTIAL, "m", CostVerdict.UNKNOWN)
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.UNKNOWN
    assert ledger.snapshot() == {
        "experiential_labs/m": "unknown",
        "nvidia_nim/m": "paid",
    }


def test_admission_requires_free_evidence_for_experiential_only() -> None:
    ledger = FreeServingLedger()
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is True
    assert free_serving_admitted("openrouter", "m", catalog_free=False, ledger=ledger) is False

    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=False, ledger=ledger) is True
    ledger.record(EXPERIENTIAL, "m", CostVerdict.PAID)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False

    ledger.record("openrouter", "m:free", CostVerdict.PAID)
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is False


def test_discovery_and_serving_selectors_share_the_signal() -> None:
    """Changing one selector alone would leave dead routes in free slots."""
    discovered = [
        _discovered(EXPERIENTIAL, "promo-model"),
        _discovered("openrouter", "vendor/model:free"),
    ]
    agents = [
        ModelAgent(
            id=f"{model.provider_name}_route",
            model=model.model_id,
            provider_name=model.provider_name,
            tags=("chat", "cost:free"),
        )
        for model in discovered
    ]
    orchestrator = TaskOrchestrator(agents)

    def _free_now() -> tuple[list[str], list[str]]:
        return (
            [model.provider_name for model in general_free_serving_candidates(discovered)],
            [agent.provider_name for agent in agents if orchestrator._is_free_agent(agent)],
        )

    # No evidence: Experiential is paid (fail-closed); catalog-free OpenRouter serves.
    assert _free_now() == (["openrouter"], ["openrouter"])

    record_reported_cost(EXPERIENTIAL, "promo-model", {"cost": 0, "is_byok": False})
    assert _free_now() == ([EXPERIENTIAL, "openrouter"], [EXPERIENTIAL, "openrouter"])

    # Free allowance exhausted and credits overflow billed the call: demote at once.
    record_reported_cost(EXPERIENTIAL, "promo-model", {"cost": 0.0021, "is_byok": False})
    record_reported_cost("openrouter", "vendor/model:free", {"cost": 0.5, "is_byok": False})
    assert _free_now() == ([], [])


class _FakeResponse:
    def __init__(self, body: dict[str, object], headers: dict[str, str] | None = None) -> None:
        self._stream = io.BytesIO(json.dumps(body).encode("utf-8"))
        self.headers = headers or {}
        self.status = 200

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_model_client_records_evidence_from_every_completed_call(monkeypatch) -> None:
    agent = ModelAgent(
        id="experiential_promo",
        model="promo-model",
        base_url="https://api.experientiallabs.ai/v1",
        provider_name=EXPERIENTIAL,
        tags=("chat", "cost:free"),
    )
    client = ModelClient()
    bodies = iter(
        [
            {"choices": [{"message": {"content": "OK"}}], "usage": {"cost": 0, "is_byok": False}},
            {"choices": [{"message": {"content": "OK"}}], "usage": {"cost": 0.003, "is_byok": False}},
        ]
    )

    @contextmanager
    def _noop_slot(*_args, **_kwargs):
        yield

    monkeypatch.setattr(
        client,
        "_open_model_provider",
        lambda *_args, **_kwargs: _FakeResponse(next(bodies)),
    )
    payload = {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]}

    assert client._send(agent, payload) == "OK"
    assert FREE_SERVING_LEDGER.verdict(EXPERIENTIAL, "promo-model") is CostVerdict.FREE
    assert TaskOrchestrator([agent])._is_free_agent(agent) is True

    assert client._send(agent, payload) == "OK"
    assert FREE_SERVING_LEDGER.verdict(EXPERIENTIAL, "promo-model") is CostVerdict.PAID
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False
