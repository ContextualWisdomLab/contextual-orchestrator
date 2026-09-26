"""Per-call cost evidence decides whether a route is servable free right now."""

from __future__ import annotations

import io
import json
import urllib.error
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


# --- Round-2 decisions: promotions nomination, 429 demotion, UTC reset, idempotency ---

_UTC_2026_09_26_1000 = 1790416800.0  # 2026-09-26T10:00:00Z (19:00 KST)
_UTC_2026_09_27_0000 = 1790467200.0  # 2026-09-27T00:00:00Z (09:00 KST), next reset


def _quota_body(code: str) -> dict[str, object]:
    return {"error": {"code": code, "type": "rate_limit", "message": "free allowance used"}}


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_utc_reset_boundary_is_midnight_utc() -> None:
    assert evidence.last_allowance_reset(_UTC_2026_09_26_1000) == _UTC_2026_09_27_0000 - 86400
    assert evidence.last_allowance_reset(_UTC_2026_09_27_0000) == _UTC_2026_09_27_0000
    assert evidence.last_allowance_reset(_UTC_2026_09_27_0000 - 1) == _UTC_2026_09_27_0000 - 86400


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


def test_quota_exhaustion_demotes_until_the_next_utc_reset_and_needs_a_free_probe() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is True
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    assert (
        evidence.record_provider_error(
            EXPERIENTIAL, "m", 429, _quota_body("free_limit_reached"), ledger=ledger
        )
        is CostVerdict.EXHAUSTED
    )
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    # A zero-cost reply before the reset cannot undo the demotion.
    clock.now = _UTC_2026_09_27_0000 - 1
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.EXHAUSTED
    assert ledger.probe_due(EXPERIENTIAL, "m") is False

    # After 00:00 UTC the route is probe-due but still not free until evidence.
    clock.now = _UTC_2026_09_27_0000 + 1
    assert ledger.probe_due(EXPERIENTIAL, "m") is True
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is False
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted(EXPERIENTIAL, "m", catalog_free=True, ledger=ledger) is True


def test_paid_demotion_also_holds_until_the_reset_for_catalog_free_providers() -> None:
    clock = _Clock(_UTC_2026_09_26_1000)
    ledger = FreeServingLedger(clock=clock)
    record_reported_cost("openrouter", "m:free", {"cost": 0.2, "is_byok": False}, ledger=ledger)
    record_reported_cost("openrouter", "m:free", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is False
    clock.now = _UTC_2026_09_27_0000 + 60
    record_reported_cost("openrouter", "m:free", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert free_serving_admitted("openrouter", "m:free", catalog_free=True, ledger=ledger) is True


def test_non_quota_errors_do_not_touch_the_ledger() -> None:
    ledger = FreeServingLedger()
    record_reported_cost(EXPERIENTIAL, "m", {"cost": 0, "is_byok": False}, ledger=ledger)
    assert (
        evidence.record_provider_error(
            EXPERIENTIAL, "m", 429, {"error": {"code": "rate_limit_exceeded"}}, ledger=ledger
        )
        is None
    )
    assert evidence.record_provider_error(EXPERIENTIAL, "m", 503, None, ledger=ledger) is None
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.FREE


@pytest.mark.parametrize(
    "request_headers",
    [
        {"Idempotency-Key": "k-1"},
        {"idempotency-key": "k-1"},
        [("Idempotency-key", "k-1")],  # urllib.request.Request.header_items() spelling
    ],
)
def test_idempotency_key_requests_neither_promote_nor_demote(request_headers) -> None:
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
            429,
            _quota_body("free_limit_reached"),
            request_headers=request_headers,
            ledger=ledger,
        )
        is None
    )
    assert ledger.verdict(EXPERIENTIAL, "m") is CostVerdict.FREE


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
    record_reported_cost(EXPERIENTIAL, agent.model, {"cost": 0, "is_byok": False})
    assert TaskOrchestrator([agent])._is_free_agent(agent) is True

    error = _http_error(429, _quota_body("insufficient_quota"))

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(client, "_open_provider", _raise)
    payload = {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(urllib.error.HTTPError):
        client._send(agent, payload)
    assert FREE_SERVING_LEDGER.verdict(EXPERIENTIAL, agent.model) is CostVerdict.EXHAUSTED
    assert TaskOrchestrator([agent])._is_free_agent(agent) is False
    # The cached error body stays readable for downstream classifiers.
    assert orchestrator_module._http_error_payload(error) == _quota_body("insufficient_quota")


def test_model_client_ignores_non_quota_http_errors(monkeypatch) -> None:
    agent = _agent()
    client = ModelClient()
    record_reported_cost(EXPERIENTIAL, agent.model, {"cost": 0, "is_byok": False})

    def _raise(*_args, **_kwargs):
        raise _http_error(503, {"error": {"code": "overloaded"}})

    monkeypatch.setattr(client, "_open_provider", _raise)
    payload = {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(urllib.error.HTTPError):
        client._send(agent, payload)
    assert FREE_SERVING_LEDGER.verdict(EXPERIENTIAL, agent.model) is CostVerdict.FREE


def test_serving_hooks_skip_idempotency_key_requests() -> None:
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
    assert FREE_SERVING_LEDGER.verdict(EXPERIENTIAL, agent.model) is None


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


def test_promotion_nominates_a_priced_row_but_only_evidence_admits_it() -> None:
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
    record_reported_cost(EXPERIENTIAL, "promo-model", {"cost": 0, "is_byok": False})
    assert [
        (row.provider_name, row.model_id) for row in general_free_serving_candidates(marked)
    ] == [(EXPERIENTIAL, "promo-model")]
    record_reported_cost(EXPERIENTIAL, "other-model", {"cost": 0, "is_byok": False})
    assert [row.model_id for row in general_free_serving_candidates(marked)] == ["promo-model"]


def test_probe_free_candidates_probes_only_nominated_due_evidence_routes() -> None:
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
        if model.model_id == "free-now":
            record_reported_cost(
                EXPERIENTIAL, model.model_id, {"cost": 0, "is_byok": False}, ledger=ledger
            )
        elif model.model_id == "exhausted":
            evidence.record_provider_error(
                EXPERIENTIAL, model.model_id, 429, _quota_body("free_limit_reached"), ledger=ledger
            )
        elif model.model_id == "raises":
            raise RuntimeError("transport failed")

    result = evidence.probe_free_candidates(rows, probe=_probe, max_probes=4, ledger=ledger)
    assert seen == ["free-now", "exhausted", "raises", "silent"]
    assert result == {
        "probes": 4,
        "probed": [f"{EXPERIENTIAL}/{name}" for name in seen],
    }
    assert ledger.snapshot() == {
        f"{EXPERIENTIAL}/exhausted": "exhausted",
        f"{EXPERIENTIAL}/free-now": "free",
        f"{EXPERIENTIAL}/raises": "unknown",
        f"{EXPERIENTIAL}/silent": "unknown",
    }

    # Same UTC day: nothing is due again except the never-probed row.
    seen.clear()
    evidence.probe_free_candidates(rows, probe=_probe, max_probes=4, ledger=ledger)
    assert seen == ["over-budget"]

    # After 00:00 UTC every non-FREE route is due again; FREE is not re-probed.
    seen.clear()
    clock.now = _UTC_2026_09_27_0000 + 5
    evidence.probe_free_candidates(rows, probe=_probe, max_probes=10, ledger=ledger)
    assert seen == ["exhausted", "raises", "silent", "over-budget"]
