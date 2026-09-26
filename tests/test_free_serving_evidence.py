"""Per-call cost evidence decides whether a route is servable free right now."""

from __future__ import annotations

import io
import json
import threading
import urllib.error
from contextlib import contextmanager

import pytest

from contextual_orchestrator import free_serving_evidence as evidence
from contextual_orchestrator.free_serving_evidence import (
    FREE_SERVING_LEDGER,
    CostVerdict,
    FreeServingLedger,
    classify_reported_cost,
    credential_route_identity,
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
    _free_serving_route_identity,
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


def _discovered_route_identity(model: DiscoveredModel) -> str:
    """Return the ledger identity used when a discovered route becomes an agent."""
    return credential_route_identity(
        model.provider_name, model.credential_name, model.chat_base_url
    )


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"cost": 0, "is_byok": False}, CostVerdict.FREE),
        ({"cost": 0.0, "is_byok": False}, CostVerdict.FREE),
        # Only real JSON numbers count: numeric strings are malformed evidence.
        ({"cost": "0", "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": "0E+5", "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": " 0 ", "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": "\u0660", "is_byok": False}, CostVerdict.UNKNOWN),  # ARABIC-INDIC ZERO
        ({"cost": "0.5", "is_byok": False}, CostVerdict.UNKNOWN),
        ({"cost": 0e5, "is_byok": False}, CostVerdict.FREE),  # a JSON number 0E+5
        ({"cost": False, "is_byok": False}, CostVerdict.UNKNOWN),
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
    for malformed in ("0E+5", "\u0660", "-0", "0x0", "", "0."):
        assert (
            classify_reported_cost(free_body, {"x-test-call-cost": malformed})
            is CostVerdict.UNKNOWN
        ), malformed
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


def test_admission_requires_pre_send_authority_for_experiential() -> None:
    ledger = FreeServingLedger()
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is True
    assert free_serving_admitted("openrouter", "m", catalog_free=False, ledger=ledger) is False

    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=False, ledger=ledger) is False
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
            base_url=model.chat_base_url,
            credential_key=model.credential_name,
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

    record_reported_cost(
        EXPERIENTIAL,
        "promo-model",
        {"cost": 0, "is_byok": False},
        route_identity=_discovered_route_identity(discovered[0]),
    )
    assert _free_now() == (["openrouter"], ["openrouter"])

    # Free allowance exhausted and credits overflow billed the call: demote at once.
    record_reported_cost(
        EXPERIENTIAL,
        "promo-model",
        {"cost": 0.0021, "is_byok": False},
        route_identity=_discovered_route_identity(discovered[0]),
    )
    record_reported_cost(
        "openrouter",
        "vendor/model:free",
        {"cost": 0.5, "is_byok": False},
        route_identity=_discovered_route_identity(discovered[1]),
    )
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
    assert (
        FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), "promo-model")
        is CostVerdict.FREE
    )
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False

    assert client._send(agent, payload) == "OK"
    assert (
        FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), "promo-model")
        is CostVerdict.PAID
    )
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def test_unnamed_configured_agent_keeps_paid_evidence_on_its_stable_identity(monkeypatch) -> None:
    """A paid response must demote a valid configured agent with no provider label."""
    agent = ModelAgent(
        id="unnamed_free_agent",
        model="catalog-free-model",
        base_url="https://example.invalid/v1",
        tags=("chat", "cost:free"),
    )
    FREE_SERVING_LEDGER.reset()
    assert TaskOrchestrator([agent])._is_free_agent(agent) is True

    client = ModelClient()
    monkeypatch.setattr(
        client,
        "_open_model_provider",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"cost": 0.003, "is_byok": False},
            }
        ),
    )
    payload = {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]}

    assert client._send(agent, payload) == "OK"
    assert (
        FREE_SERVING_LEDGER.verdict("configured_agent:unnamed_free_agent", agent.model)
        is CostVerdict.PAID
    )
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def test_credential_routes_keep_independent_free_serving_evidence() -> None:
    """A billed account must not demote a sibling credential route."""
    account_a = ModelAgent(
        id="gateway_account_a",
        model="shared-model",
        base_url="https://gateway.example/v1",
        credential_key="KEY_A",
        provider_name="gateway",
        tags=("chat", "cost:free"),
    )
    account_b = ModelAgent(
        id="gateway_account_b",
        model="shared-model",
        base_url="https://gateway.example/v1",
        credential_key="KEY_B",
        provider_name="gateway",
        tags=("chat", "cost:free"),
    )
    orchestrator = TaskOrchestrator([account_a, account_b])
    assert orchestrator._is_free_agent(account_a) is True
    assert orchestrator._is_free_agent(account_b) is True

    from contextual_orchestrator import orchestrator as orchestrator_module

    orchestrator_module._record_free_serving_evidence(
        account_a,
        {"usage": {"cost": 0.003, "is_byok": False}},
    )

    assert orchestrator._is_free_agent(account_a) is False
    assert orchestrator._is_free_agent(account_b) is True


# --- Promotions nomination, persistent demotion, idempotency ----------------

_UTC_2026_09_26_1000 = 1790416800.0  # 2026-09-26T10:00:00Z (19:00 KST)
_UTC_2026_09_27_0000 = 1790467200.0


def _quota_body(code: str) -> dict[str, object]:
    return {"error": {"code": code, "type": "rate_limit", "message": "free allowance used"}}


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_ledger_has_no_automatic_calendar_reset_authority() -> None:
    assert not hasattr(evidence, "ALLOWANCE_RESET_SKEW_SECONDS")
    assert not hasattr(evidence, "last_allowance_reset")


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (429, _quota_body("free_limit_reached"), True),
        (429, _quota_body("insufficient_quota"), True),
        (429, {"error": {"type": "insufficient_quota"}}, True),
        (429, {"error": {"message": "Error: FREE_LIMIT_REACHED for today"}}, True),
        (429, {"error": "insufficient_quota"}, True),
        (429, {"code": "free_limit_reached"}, True),
        # A plain rate limit is not an exhausted allowance.
        (429, {"error": {"code": "rate_limit_exceeded"}}, False),
        (402, _quota_body("insufficient_quota"), False),
        (500, _quota_body("free_limit_reached"), False),
        (429, None, False),
        (429, "insufficient_quota", False),
    ],
)
def test_free_quota_exhaustion_is_a_429_with_a_documented_marker(status, payload, expected) -> None:
    assert evidence.is_free_quota_exhausted_error(status, payload) is expected


def test_quota_exhaustion_persists_until_explicit_process_reset() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    assert (
        evidence.record_provider_error(
            EXPERIENTIAL, "m", 429, _quota_body("free_limit_reached"), ledger=ledger
        )
        is CostVerdict.EXHAUSTED
    )
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    clock.now = _UTC_2026_09_27_0000 + 86400
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.EXHAUSTED
    assert ledger.probe_due(EXPERIENTIAL, "m") is False
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    ledger.reset()
    assert ledger.demoted(EXPERIENTIAL, "m") is False
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False


def test_paid_demotion_persists_for_catalog_free_providers() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    record_reported_cost("openrouter", "m:free", {"cost": 0.2, "is_byok": False}, ledger=ledger)
    record_reported_cost("openrouter", "m:free", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is False
    clock.now = _UTC_2026_09_27_0000 + 86400
    record_reported_cost("openrouter", "m:free", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is False
    ledger.reset()
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is True


def test_provider_errors_never_leave_an_evidence_required_route_free() -> None:
    """Non-quota errors are UNKNOWN for Experiential and ignored for other providers."""
    ledger = FreeServingLedger()
    for status, payload in (
        (429, {"error": {"code": "rate_limit_exceeded"}}),
        (503, None),
        (500, {}),
    ):
        record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
        assert (
            evidence.record_provider_error(EXPERIENTIAL, "m", status, payload, ledger=ledger)
            is CostVerdict.UNKNOWN
        )
        assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False

    record_reported_cost("openrouter", "m:free", {"cost": 0, "is_byok": False}, ledger=ledger)
    for status in (402, 429, 500, 503):
        assert evidence.record_provider_error("openrouter", "m:free", status, {}, ledger=ledger) is None
    assert ledger.verdict("openrouter", "m:free") is CostVerdict.FREE
    assert evidence.record_failed_call("openrouter", "m:free", ledger=ledger) is None
    assert ledger.verdict("openrouter", "m:free") is CostVerdict.FREE


def test_http_402_persistently_demotes_an_evidence_required_route() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert (
        evidence.record_provider_error(
            EXPERIENTIAL, "m", 402, {"error": {"code": "insufficient_credits"}}, ledger=ledger
        )
        is CostVerdict.EXHAUSTED
    )
    assert ledger.demoted(EXPERIENTIAL, "m") is True
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    clock.now = _UTC_2026_09_27_0000 + 86400
    assert ledger.demoted(EXPERIENTIAL, "m") is True
    assert ledger.probe_due(EXPERIENTIAL, "m") is False


@pytest.mark.parametrize("demotion", [CostVerdict.PAID, CostVerdict.EXHAUSTED])
def test_a_demotion_holds_through_later_unknown_and_free_verdicts(demotion) -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)
    clock.now += 60
    assert ledger.record(EXPERIENTIAL, "m", demotion) is True
    clock.now += 60
    assert ledger.record(EXPERIENTIAL, "m", CostVerdict.UNKNOWN) is True
    clock.now += 60
    assert ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE) is False
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.UNKNOWN
    assert ledger.demoted(EXPERIENTIAL, "m") is True
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    clock.now = _UTC_2026_09_27_0000 + 86400
    assert ledger.probe_due(EXPERIENTIAL, "m") is False
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE) is False


def test_concurrent_probe_callers_never_invoke_the_network_callback() -> None:
    ledger = FreeServingLedger()
    model = _discovered(EXPERIENTIAL, "m")
    called = threading.Event()

    def probe(_model: object) -> None:
        called.set()

    receipts = [
        evidence.probe_free_candidates([model], probe=probe, max_probes=1, ledger=ledger)
        for _ in range(2)
    ]
    assert receipts == [
        {"probes": 0, "probed": []},
        {"probes": 0, "probed": []},
    ]
    assert called.is_set() is False


def test_catalog_free_providers_keep_demotion_until_explicit_reset() -> None:
    ledger = FreeServingLedger()
    ledger.record("openrouter", "m:free", CostVerdict.PAID)
    assert ledger.record("openrouter", "m:free", CostVerdict.FREE) is False
    assert (
        free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger)
        is False
    )
    ledger.reset()
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is True


def test_calendar_time_cannot_lift_a_demotion() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    ledger.record(EXPERIENTIAL, "m", CostVerdict.PAID)
    assert ledger.demoted(EXPERIENTIAL, "m") is True
    clock.now += 10 * 365 * 24 * 60 * 60
    assert ledger.demoted(EXPERIENTIAL, "m") is True
    assert ledger.probe_due(EXPERIENTIAL, "m") is False
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False


def test_passive_free_evidence_never_admits_an_evidence_required_route() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.FREE
    assert ledger.free_now(EXPERIENTIAL, "m") is True
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    clock.now += 10 * 365 * 24 * 60 * 60
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=False, ledger=ledger) is False


@pytest.mark.parametrize(
    "request_headers",
    [
        {"Idempotency-Key": "k-1"},
        {"idempotency-key": "k-1"},
        [("Idempotency-key", "k-1")],  # urllib.request.Request.header_items() spelling
    ],
)
def test_idempotency_key_requests_skip_cost_only_evidence(request_headers) -> None:
    ledger = FreeServingLedger()
    assert evidence.request_has_idempotency_key(request_headers) is True
    assert (
        record_reported_cost(
            EXPERIENTIAL,
            "m",
            {"cost": 0, "is_byok": False},
            request_headers=request_headers,
            ledger=ledger,
        )
        is None
    )
    assert ledger.verdict(EXPERIENTIAL, "m") is None

    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    for usage in ({"prompt_tokens": 1}, {"cost": 0.5, "is_byok": False}):
        record_reported_cost(
            EXPERIENTIAL, "m", usage, request_headers=request_headers, ledger=ledger
        )
    assert (
        evidence.record_provider_error(
            EXPERIENTIAL,
            "m",
            500,
            {"error": {"code": "provider_error"}},
            request_headers=request_headers,
            ledger=ledger,
        )
        is None
    )
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.FREE


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (429, _quota_body("free_limit_reached")),
        (402, {"error": {"code": "payment_required"}}),
    ],
)
def test_idempotency_key_cannot_hide_explicit_quota_or_payment_demotion(
    status, payload
) -> None:
    ledger = FreeServingLedger()
    ledger.record(EXPERIENTIAL, "m", CostVerdict.FREE)

    assert (
        evidence.record_provider_error(
            EXPERIENTIAL,
            "m",
            status,
            payload,
            request_headers={"Idempotency-Key": "k-1"},
            ledger=ledger,
        )
        is CostVerdict.EXHAUSTED
    )
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.EXHAUSTED
    assert free_serving_admitted(
        EXPERIENTIAL, "m", catalog_free=False, ledger=ledger
    ) is False


def test_blank_idempotency_key_is_not_a_skip() -> None:
    assert evidence.request_has_idempotency_key({"Idempotency-Key": "  "}) is False
    assert evidence.request_has_idempotency_key(None) is False
    assert evidence.request_has_idempotency_key([("content-type", "application/json")]) is False


def _agent(model: str = "promo-model") -> ModelAgent:
    return ModelAgent(
        id="experiential_promo",
        model=model,
        base_url="https://api.experientiallabs.ai/v1",
        provider_name=EXPERIENTIAL,
        tags=("chat", "cost:free"),
    )


def _http_error(code: int, body: dict[str, object]):
    return urllib.error.HTTPError(
        "https://api.experientiallabs.ai/v1/chat/completions",
        code,
        "error",
        {},  # type: ignore[arg-type]
        io.BytesIO(json.dumps(body).encode("utf-8")),
    )


def test_model_client_demotes_a_route_on_a_served_429_free_quota_error(monkeypatch) -> None:
    from contextual_orchestrator import orchestrator as orchestrator_module

    agent = _agent()
    client = ModelClient()
    record_reported_cost(
        EXPERIENTIAL,
        agent.model,
        {"cost": 0, "is_byok": False},
        route_identity=_free_serving_route_identity(agent),
    )
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False

    error = _http_error(429, _quota_body("insufficient_quota"))

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(client, "_open_provider", _raise)
    payload = {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(urllib.error.HTTPError):
        client._send(agent, payload)
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.EXHAUSTED
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False
    # The cached error body stays readable for downstream classifiers.
    assert orchestrator_module._http_error_payload(error) == _quota_body("insufficient_quota")


def test_model_client_non_quota_http_errors_are_unknown_only_for_evidence_routes(
    monkeypatch,
) -> None:
    agent = _agent()
    other = ModelAgent(
        id="openrouter_free",
        model="vendor/model:free",
        base_url="https://openrouter.ai/api/v1",
        provider_name="openrouter",
        tags=("chat", "cost:free"),
    )
    client = ModelClient()
    record_reported_cost(
        EXPERIENTIAL,
        agent.model,
        {"cost": 0, "is_byok": False},
        route_identity=_free_serving_route_identity(agent),
    )
    record_reported_cost(
        "openrouter",
        other.model,
        {"cost": 0, "is_byok": False},
        route_identity=_free_serving_route_identity(other),
    )

    def _raise(*_args, **_kwargs):
        raise _http_error(503, {"error": {"code": "overloaded"}})

    monkeypatch.setattr(client, "_open_provider", _raise)
    for route in (agent, other):
        payload = {"model": route.model, "messages": [{"role": "user", "content": "hi"}]}
        with pytest.raises(urllib.error.HTTPError):
            client._send(route, payload)
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.UNKNOWN
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(other), other.model) is CostVerdict.FREE


def test_serving_hooks_skip_idempotent_cost_but_keep_quota_authority() -> None:
    import urllib.request

    from contextual_orchestrator import orchestrator as orchestrator_module

    agent = _agent()
    request = urllib.request.Request(
        "https://api.experientiallabs.ai/v1/chat/completions",
        headers={"Idempotency-Key": "replay-1"},
        method="POST",
    )
    orchestrator_module._record_free_serving_evidence(
        agent, {"usage": {"cost": 0, "is_byok": False}}, None, request
    )
    orchestrator_module._record_free_serving_quota_error(
        agent, _http_error(429, _quota_body("free_limit_reached")), request
    )
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.EXHAUSTED


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "promotions": [
                    {"free": True, "slugs": ["jev-latest"], "listed_slugs": ["jev-listed"]},
                    {"free": False, "badge_style": "free", "slugs": ["badge-only"]},
                    {"free": True, "display_only": True, "slugs": ["display-only"]},
                    {"free": "true", "slugs": ["string-flag"]},
                    {"free": True, "slugs": [" spaced ", "", 7]},
                    "not-a-dict",
                ]
            },
            frozenset({"jev-latest", "jev-listed", "spaced"}),
        ),
        ({"promotions": []}, frozenset()),
        ({"promotions": "nope"}, frozenset()),
        ({}, frozenset()),
        (None, frozenset()),
        ([{"free": True, "slugs": ["x"]}], frozenset()),
    ],
)
def test_free_promotion_slugs_require_an_explicit_free_true(payload, expected) -> None:
    assert evidence.free_promotion_slugs(payload) == expected


def test_promotions_fetch_is_keyless_and_fails_closed(monkeypatch) -> None:
    from contextual_orchestrator import model_discovery

    calls: list[tuple[str, str]] = []

    def _fetch(url: str, *, api_key: str, timeout: float | None = None, **_kwargs):
        calls.append((url, api_key))
        return {"promotions": [{"free": True, "slugs": ["promo-model"]}]}

    monkeypatch.setattr(model_discovery, "_fetch_json_same_host_https", _fetch)
    assert model_discovery._experiential_free_promotion_slugs(timeout=1.0) == frozenset(
        {"promo-model"}
    )
    assert calls == [(evidence.EXPERIENTIAL_PROMOTIONS_URL, "")]

    for failure in (
        urllib.error.URLError("down"),
        TimeoutError("slow"),
        ValueError("bad json"),
        OSError("reset"),
    ):

        def _fail(*_args, _failure=failure, **_kwargs):
            raise _failure

        monkeypatch.setattr(model_discovery, "_fetch_json_same_host_https", _fail)
        assert model_discovery._experiential_free_promotion_slugs(timeout=1.0) == frozenset()


def test_promotion_nominates_but_never_admits_without_pre_send_authority() -> None:
    from contextual_orchestrator.model_discovery import apply_free_promotions

    rows = [
        _discovered(EXPERIENTIAL, "promo-model", free=False),
        _discovered(EXPERIENTIAL, "other-model", free=False),
        _discovered("openrouter", "promo-model", free=False),
    ]
    marked = apply_free_promotions(rows, EXPERIENTIAL, frozenset({"promo-model"}))
    assert [row.free_promotion for row in marked] == [True, False, False]
    # Providers outside the evidence-required set are never promotion-nominated.
    assert apply_free_promotions(rows, "openrouter", frozenset({"promo-model"})) is rows
    # A failed fetch (empty set) nominates nothing.
    assert apply_free_promotions(rows, EXPERIENTIAL, frozenset()) is rows

    assert general_free_serving_candidates(marked) == []
    record_reported_cost(
        EXPERIENTIAL,
        "promo-model",
        {"cost": 0, "is_byok": False},
        route_identity=_discovered_route_identity(marked[0]),
    )
    assert general_free_serving_candidates(marked) == []
    record_reported_cost(
        EXPERIENTIAL,
        "other-model",
        {"cost": 0, "is_byok": False},
        route_identity=_discovered_route_identity(marked[1]),
    )
    assert general_free_serving_candidates(marked) == []


def test_probe_free_candidates_never_sends_a_post_hoc_cost_request() -> None:
    from dataclasses import replace

    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    rows = [
        replace(_discovered(EXPERIENTIAL, "free-now", free=False), free_promotion=True),
        replace(_discovered(EXPERIENTIAL, "exhausted", free=False), free_promotion=True),
        replace(_discovered(EXPERIENTIAL, "raises", free=False), free_promotion=True),
        replace(_discovered(EXPERIENTIAL, "silent", free=False), free_promotion=True),
        _discovered(EXPERIENTIAL, "not-nominated", free=False),
        _discovered("openrouter", "catalog:free"),
        replace(_discovered(EXPERIENTIAL, "over-budget", free=False), free_promotion=True),
    ]
    seen: list[str] = []

    def _probe(model) -> None:
        seen.append(model.model_id)

    result = evidence.probe_free_candidates(rows, probe=_probe, max_probes=4, ledger=ledger)
    assert seen == []
    assert result == {"probes": 0, "probed": []}
    assert ledger.snapshot() == {}


# --- R2/R3: every chat transport records evidence, including failures ---------


class _RawResponse(_FakeResponse):
    """A provider response whose body bytes are given verbatim (e.g. truncated)."""

    def __init__(self, raw: bytes) -> None:
        self._stream = io.BytesIO(raw)
        self.headers = {}
        self.status = 200


class _SSEResponse:
    def __init__(self, lines: list[bytes], *, fail_after: int | None = None) -> None:
        self._lines = lines
        self._fail_after = fail_after
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        for index, line in enumerate(self._lines):
            if self._fail_after is not None and index >= self._fail_after:
                raise OSError("connection reset mid-stream")
            yield line


_FREE_BODY = {"choices": [{"message": {"content": "OK"}}], "usage": {"cost": 0, "is_byok": False}}
_PAID_BODY = {"choices": [{"message": {"content": "OK"}}], "usage": {"cost": 0.004, "is_byok": False}}


def _sse(usage: dict[str, object] | None) -> list[bytes]:
    lines = [b'data: {"choices":[{"delta":{"content":"O"}}]}',
             b'data: {"choices":[{"delta":{"content":"K"},"finish_reason":"stop"}]}']
    if usage is not None:
        lines.append(b"data: " + json.dumps({"choices": [], "usage": usage}).encode("utf-8"))
    lines.append(b"data: [DONE]")
    return lines


def _free_route(agent: ModelAgent) -> None:
    FREE_SERVING_LEDGER.reset()
    record_reported_cost(
        agent.provider_name,
        agent.model,
        {"cost": 0, "is_byok": False},
        route_identity=_free_serving_route_identity(agent),
    )
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def _open_returning(client, monkeypatch, factory) -> None:
    monkeypatch.setattr(client, "_open_model_provider", lambda *_a, **_k: factory())


def _open_raising(client, monkeypatch, error: BaseException) -> None:
    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(client, "_open_provider", _raise)


_FAILURES = {
    "truncated_json": (lambda: _RawResponse(b'{"choices":[{"message":{"content":"OK"}}],"usage":{"cost":0.4')),
    "non_json": (lambda: _RawResponse(b"<html>bad gateway</html>")),
}


@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_send_records_unknown_for_an_unreadable_body(monkeypatch, failure) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    _open_returning(client, monkeypatch, _FAILURES[failure])
    with pytest.raises(Exception):
        client._send(agent, {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]})
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.UNKNOWN
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(402, {"error": {"code": "insufficient_credits"}}), CostVerdict.EXHAUSTED),
        (_http_error(500, {}), CostVerdict.UNKNOWN),
        (urllib.error.URLError("connection refused"), CostVerdict.UNKNOWN),
        (TimeoutError("read timed out"), CostVerdict.UNKNOWN),
    ],
    ids=["http_402", "http_500", "transport", "timeout"],
)
def test_send_records_failed_calls(monkeypatch, error, expected) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    _open_raising(client, monkeypatch, error)
    with pytest.raises(type(error)):
        client._send(agent, {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]})
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is expected
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False
    assert FREE_SERVING_LEDGER.demoted(_free_serving_route_identity(agent), agent.model) is (
        expected is CostVerdict.EXHAUSTED
    )


def _stream(client: ModelClient, agent: ModelAgent):
    return client.stream_chat(agent, [{"role": "user", "content": "hi"}])


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"cost": 0, "is_byok": False}, CostVerdict.FREE),
        ({"cost": 0.0021, "is_byok": False}, CostVerdict.PAID),
        ({"cost": "0", "is_byok": False}, CostVerdict.UNKNOWN),
        (None, CostVerdict.UNKNOWN),  # stream ended without a usage frame
    ],
)
def test_stream_records_the_final_usage_frame(monkeypatch, usage, expected) -> None:
    agent = _agent()
    client = ModelClient()
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    _open_returning(client, monkeypatch, lambda: _SSEResponse(_sse(usage)))
    assert "".join(_stream(client, agent)) == "OK"
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is expected
    assert TaskOrchestrator([agent])._is_free_agent(agent) is (expected is CostVerdict.FREE)


def test_stream_records_unknown_when_it_fails_mid_stream(monkeypatch) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    _open_returning(
        client, monkeypatch, lambda: _SSEResponse(_sse({"cost": 0, "is_byok": False}), fail_after=1)
    )
    received: list[str] = []
    with pytest.raises(Exception):
        for delta in _stream(client, agent):
            received.append(delta)
    assert received == ["O"]
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.UNKNOWN
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def test_stream_records_unknown_when_the_consumer_abandons_it(monkeypatch) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    _open_returning(
        client, monkeypatch, lambda: _SSEResponse(_sse({"cost": 0, "is_byok": False}))
    )
    stream = _stream(client, agent)
    assert next(stream) == "O"
    stream.close()  # GeneratorExit before the final usage frame
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.UNKNOWN
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(402, {"error": {"code": "insufficient_credits"}}), CostVerdict.EXHAUSTED),
        (_http_error(429, _quota_body("free_limit_reached")), CostVerdict.EXHAUSTED),
        (_http_error(503, {}), CostVerdict.UNKNOWN),
        (urllib.error.URLError("connection refused"), CostVerdict.UNKNOWN),
    ],
    ids=["http_402", "quota_429", "http_503", "transport"],
)
def test_stream_records_open_failures(monkeypatch, error, expected) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    _open_raising(client, monkeypatch, error)
    with pytest.raises(Exception):
        list(_stream(client, agent))
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is expected
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def _passthrough(client: ModelClient, agent: ModelAgent) -> dict[str, object]:
    return client.proxy_send_once(
        agent,
        "chat/completions",
        {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]},
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [(_FREE_BODY, CostVerdict.FREE), (_PAID_BODY, CostVerdict.PAID)],
)
def test_proxy_send_once_records_evidence_through_send_raw(monkeypatch, body, expected) -> None:
    agent = _agent()
    client = ModelClient()
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    _open_returning(client, monkeypatch, lambda: _FakeResponse(body))
    assert _passthrough(client, agent)["usage"] == body["usage"]
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is expected
    assert TaskOrchestrator([agent])._is_free_agent(agent) is (expected is CostVerdict.FREE)


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("truncated_json", CostVerdict.UNKNOWN),
        ("http_402", CostVerdict.EXHAUSTED),
        ("http_500", CostVerdict.UNKNOWN),
        ("transport", CostVerdict.UNKNOWN),
    ],
)
def test_proxy_send_once_records_failed_calls(monkeypatch, setup, expected) -> None:
    agent = _agent()
    client = ModelClient()
    _free_route(agent)
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    if setup == "truncated_json":
        _open_returning(client, monkeypatch, _FAILURES["truncated_json"])
    else:
        error = {
            "http_402": _http_error(402, {"error": {"code": "insufficient_credits"}}),
            "http_500": _http_error(500, {}),
            "transport": urllib.error.URLError("connection refused"),
        }[setup]
        _open_raising(client, monkeypatch, error)
    with pytest.raises(Exception):
        _passthrough(client, agent)
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is expected
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False


def test_send_raw_records_evidence_directly(monkeypatch) -> None:
    agent = _agent()
    client = ModelClient()
    _open_returning(client, monkeypatch, lambda: _FakeResponse(_FREE_BODY))
    assert client._send_raw(agent, "chat/completions", {"model": agent.model})["usage"] == (
        _FREE_BODY["usage"]
    )
    assert FREE_SERVING_LEDGER.verdict(_free_serving_route_identity(agent), agent.model) is CostVerdict.FREE


def test_failure_recording_never_masks_the_provider_error(monkeypatch) -> None:
    from contextual_orchestrator import orchestrator as orchestrator_module

    agent = _agent()
    client = ModelClient()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(orchestrator_module, "record_failed_call", _boom)
    monkeypatch.setattr(orchestrator_module, "record_provider_error", _boom)
    for error in (urllib.error.URLError("refused"), _http_error(500, {})):
        _open_raising(client, monkeypatch, error)
        with pytest.raises(type(error)):
            client._send(agent, {"model": agent.model, "messages": []})

# --- Fail-closed pre-send authority -----------------------------------------


def test_reported_free_cost_does_not_authorize_the_next_request() -> None:
    """Post-response cost evidence cannot prove that the next call is free."""

    ledger = FreeServingLedger()
    ledger.record(EXPERIENTIAL, "promotion-model", CostVerdict.FREE)

    assert (
        free_serving_admitted(
            EXPERIENTIAL,
            "promotion-model",
            catalog_free=True,
            ledger=ledger,
        )
        is False
    )


def test_free_pool_never_sends_a_post_hoc_cost_probe() -> None:
    """A possibly billed request cannot be used to decide free admission."""

    from types import SimpleNamespace

    model = SimpleNamespace(
        provider_name=EXPERIENTIAL,
        model_id="promotion-model",
        is_free=False,
        free_promotion=True,
    )
    calls: list[str] = []

    def _probe(candidate) -> None:
        calls.append(candidate.model_id)

    result = evidence.probe_free_candidates(
        [model],
        probe=_probe,
        max_probes=1,
        ledger=FreeServingLedger(),
    )

    assert calls == []
    assert result == {"probes": 0, "probed": []}
