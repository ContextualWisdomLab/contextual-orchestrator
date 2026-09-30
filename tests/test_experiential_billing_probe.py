"""Bounded Experiential measurement contracts, independent of pool admission."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from contextual_orchestrator.credentials import InMemoryCredentialBackend, register_credential, set_backend
from contextual_orchestrator import experiential_billing_probe as probe


@pytest.fixture(autouse=True)
def credential_backend():
    """Use fixture credentials only; these tests never contact a provider."""
    set_backend(InMemoryCredentialBackend())
    register_credential("EXPERIENTAL_LABS_API_KEY", "fixture-secret")
    try:
        yield
    finally:
        set_backend(None)


def _catalog(model="jev-latest"):
    return {"models": [{"model": {"slug": model, "status": "active",
        "input_modalities": ["text"], "output_modalities": ["text"]},
        "providers": [{"input_nano_usd_per_million": 42000000}]}],
        "promotions": [{"id": "promo-1", "free": True, "display_only": False,
            "slugs": [model]}], "total": 1, "limit": 100, "offset": 0}


class FixtureTransport:
    """Return independent receipt identities and record the one possible POST."""

    def __init__(self, path):
        self.path = path
        self.calls = []
        self.label = None
        self.inline = 0.0
        self.generation = 0.25
        self.charge = 0.5
        self.pricing_known = True
        self.duplicate = False
        self.wrong_label = False
        self.cursor = None
        self.post_error = None
        self.request_id = "req-1"

    def __call__(self, method, route, payload=None):
        self.calls.append((method, route, payload))
        if route == "/v1/models":
            return 200, {}, {"data": [{"id": "jev-latest"}]}
        if route.startswith("/api/models"):
            return 200, {}, _catalog()
        if method == "POST":
            marker = json.loads(self.path.read_text())
            assert marker["outcome"] == "attempt_pending"
            assert marker["request_count"] == 1
            assert payload["max_tokens"] == 16 and payload["stream"] is False
            assert payload["messages"] == [{"role": "user", "content": "Reply OK."}]
            self.label = payload["safety_identifier"]
            assert marker["attribution_label"] == self.label
            if self.post_error:
                raise self.post_error
            return 200, {"x-request-id": self.request_id}, {
                "model": "jev-latest", "usage": {"cost": self.inline, "prompt_tokens": 4},
                "choices": [{"message": {"content": "private completion not retained"}}]}
        if route.startswith("/api/v1/generation"):
            return 200, {}, {"data": {"id": "gen-req-1", "total_cost": self.generation}}
        row = {"id": "settled-row-91", "attribution_label": "other" if self.wrong_label else self.label,
               "cost_usd": self.charge, "estimated_cost_usd": 0.75,
               "pricing_known": self.pricing_known}
        return 200, {}, {"data": [row, dict(row)] if self.duplicate else [row], "next_cursor": self.cursor}

    @property
    def posts(self):
        return sum(method == "POST" for method, _, _ in self.calls)


def _run(path, request, **kwargs):
    return probe.run_probe(path, source_sha="a" * 40, run_id="123", run_attempt="1",
                           request=request, pause=lambda _: None, **kwargs)


def test_one_call_is_marked_before_send_and_costs_are_separate(tmp_path):
    """Do not join row IDs to request IDs, retain secrets, or replay a request."""
    path = tmp_path / "evidence.json"
    transport = FixtureTransport(path)
    result = _run(path, transport)
    assert result["response_cost_usd"] == 0.0
    assert result["generation_total_cost_usd"] == 0.25
    assert result["ledger_charge_usd"] == 0.5
    assert result["cost_comparison"] == "mismatch"
    assert result["outcome"] == "charge_observed"
    assert transport.posts == 1
    assert "fixture-secret" not in path.read_text() and "private completion" not in path.read_text()
    assert "estimated_cost_usd" not in path.read_text()
    with pytest.raises(ValueError, match="already exists"):
        _run(path, transport)
    assert transport.posts == 1


@pytest.mark.parametrize("receipt_id", [None, "gen-other", "req-1", "gen-req-1"])
def test_generation_cost_requires_returned_request_identity(tmp_path, receipt_id):
    """An omitted identity must not be manufactured from the lookup parameter."""
    transport = FixtureTransport(tmp_path / "evidence.json")
    def request(method, route, payload=None):
        status, headers, body = transport(method, route, payload)
        if route.startswith("/api/v1/generation"):
            if receipt_id is None:
                body["data"].pop("id")
            else:
                body["data"]["id"] = receipt_id
        return status, headers, body
    result = _run(transport.path, request)
    matched = receipt_id in {"req-1", "gen-req-1"}
    assert result["generation_total_cost_usd"] == (0.25 if matched else None)
    assert result["cost_comparison"] == ("mismatch" if matched else "unknown")
    assert result["ledger_charge_usd"] == 0.5
    assert transport.posts == 1


def test_free_promotion_with_nonzero_base_tariff_preserves_callable_id():
    """Only exact shared identity is verified; canonical_slug is not a documented join."""
    model = "typesafe/jev-latest"
    assert probe.select_promotion({"data": [{"id": model}]}, _catalog(model)) == (model, "promo-1")
    with pytest.raises(ValueError):
        probe.select_promotion({"data": [{"id": model, "canonical_slug": "jev-latest"}]}, _catalog())


def test_multiple_eligible_promotions_fail_closed_without_a_tie_break():
    """Do not choose a billed request target by lexical model or promotion identity."""
    catalog = _catalog("model-a")
    catalog["models"].append({"model": {"slug": "model-b", "status": "active",
        "input_modalities": ["text"], "output_modalities": ["text"]}})
    catalog["promotions"].append({"id": "promo-2", "free": True,
        "display_only": False, "slugs": ["model-b"]})
    callable_models = {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    with pytest.raises(ValueError, match="ambiguous"):
        probe.select_promotion(callable_models, catalog)


@pytest.mark.parametrize("change", ["free", "display_only", "status", "modalities"])
def test_ineligible_or_malformed_catalog_never_selects(change):
    catalog = _catalog()
    if change == "free":
        catalog["promotions"][0]["free"] = "true"
    elif change == "display_only":
        catalog["promotions"][0]["display_only"] = True
    elif change == "status":
        catalog["models"][0]["model"]["status"] = "inactive"
    else:
        catalog["models"][0]["model"]["input_modalities"] = "text"
    with pytest.raises(ValueError):
        probe.select_promotion({"data": [{"id": "jev-latest"}]}, catalog)


@pytest.mark.parametrize("value", [None, True, -1, "bad", float("nan"), float("inf")])
def test_missing_or_malformed_cost_is_unknown(tmp_path, value):
    transport = FixtureTransport(tmp_path / "evidence.json")
    transport.inline = transport.generation = transport.charge = value
    result = _run(transport.path, transport)
    assert result["response_cost_usd"] is None
    assert result["generation_total_cost_usd"] is None
    assert result["ledger_charge_usd"] is None
    assert result["outcome"] == "charge_unknown"
    assert result["cost_comparison"] == "unknown"
    assert transport.posts == 1


def test_explicit_zero_requires_correlated_priced_settled_row(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    transport.inline = transport.generation = transport.charge = 0
    result = _run(transport.path, transport)
    assert result["outcome"] == "zero_charge_observed"
    assert result["cost_comparison"] == "match"
    assert transport.posts == 1


@pytest.mark.parametrize("problem", ["wrong_label", "duplicate", "pricing_unknown", "unfinished_pages"])
def test_uncorrelated_or_incomplete_usage_is_unknown(tmp_path, problem):
    transport = FixtureTransport(tmp_path / "evidence.json")
    if problem == "wrong_label":
        transport.wrong_label = True
    elif problem == "duplicate":
        transport.duplicate = True
    elif problem == "pricing_unknown":
        transport.pricing_known = False
    else:
        transport.cursor = {"cursor_ts": "2026-09-30", "cursor_id": "row-1", "cursor_after": "opaque"}
    result = _run(transport.path, transport)
    assert result["ledger_charge_usd"] is None
    assert result["outcome"] == "charge_unknown"
    assert transport.posts == 1


def test_usage_cursor_is_followed_before_accepting_charge(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    def request(method, route, payload=None):
        status, headers, body = transport(method, route, payload)
        if route.startswith("/api/v1/usage"):
            if "cursor_after=" not in route:
                body["next_cursor"] = {"cursor_ts": "timestamp", "cursor_id": "row-1", "cursor_after": "opaque"}
            else:
                body = {"data": [], "next_cursor": None}
        return status, headers, body
    result = _run(transport.path, request)
    assert result["ledger_charge_usd"] == 0.5
    assert transport.posts == 1
    assert any("cursor_ts=timestamp" in route and "cursor_id=row-1" in route
               for _, route, _ in transport.calls)


def test_catalog_pagination_does_not_treat_first_page_as_complete(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    def request(method, route, payload=None):
        if route.startswith("/api/models"):
            catalog = _catalog()
            catalog.update(total=101, offset=100 if "offset=100" in route else 0)
            if catalog["offset"] == 0:
                catalog["models"] = [{"model": {"slug": f"other-{i}"}} for i in range(100)]
            return 200, {}, catalog
        return transport(method, route, payload)
    assert _run(transport.path, request)["ledger_charge_usd"] == 0.5
    assert transport.posts == 1


def test_ambiguous_send_is_durable_and_never_replayed(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    transport.post_error = TimeoutError("fixture-secret private error body")
    transport.wrong_label = True
    result = _run(transport.path, transport)
    assert result["outcome"] == "ambiguous"
    assert result["send_outcome"] == "ambiguous"
    assert transport.posts == 1
    assert "fixture-secret" not in transport.path.read_text()
    with pytest.raises(ValueError, match="already exists"):
        _run(transport.path, transport)
    assert transport.posts == 1


def test_ambiguous_send_can_read_correlated_charge_without_replay(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    transport.post_error = TimeoutError("fixture-secret")
    result = _run(transport.path, transport)
    assert result["send_outcome"] == "ambiguous"
    assert result["outcome"] == "charge_observed"
    assert result["ledger_charge_usd"] == 0.5
    assert result["response_cost_usd"] is None
    assert result["generation_total_cost_usd"] is None
    assert transport.posts == 1


def test_provider_identifier_echoes_cannot_leak_secret(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    transport.request_id = "fixture-secret"
    def request(method, route, payload=None):
        status, headers, body = transport(method, route, payload)
        if method == "POST":
            body["model"] = "fixture-secret"
        return status, headers, body
    result = _run(transport.path, request)
    assert result["request_id"] is None and result["returned_model"] is None
    assert "fixture-secret" not in transport.path.read_text()
    assert transport.posts == 1


def test_incomplete_catalog_fails_before_inference(tmp_path):
    transport = FixtureTransport(tmp_path / "evidence.json")
    def request(method, route, payload=None):
        status, headers, body = transport(method, route, payload)
        if route.startswith("/api/models"):
            body["total"] = 101
        return status, headers, body
    with pytest.raises(ValueError, match="discovery"):
        _run(transport.path, request)
    assert transport.posts == 0
    assert json.loads(transport.path.read_text())["outcome"] == "preflight_failed"


def test_fsync_failure_prevents_send(tmp_path, monkeypatch):
    transport = FixtureTransport(tmp_path / "evidence.json")
    def fail(_):
        raise OSError("disk unavailable")
    monkeypatch.setattr(probe.os, "fsync", fail)
    with pytest.raises(OSError):
        _run(transport.path, transport)
    assert transport.posts == 0
    assert transport.path.exists()


def test_missing_key_and_rerun_fail_before_network(tmp_path):
    def request(*_):
        pytest.fail("must not contact provider")
    with pytest.raises(ValueError, match="first attempt"):
        probe.run_probe(tmp_path / "rerun.json", source_sha="a" * 40, run_id="123", run_attempt="2", request=request)
    set_backend(InMemoryCredentialBackend())
    with pytest.raises(ValueError, match="credential"):
        _run(tmp_path / "missing.json", request)


def test_transport_bounds_and_closes_response(monkeypatch):
    class Response:
        status = 200
        closed = False
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self.closed = True
        def getheader(self, name):
            assert name == "x-request-id"
            return "req-1"
        def read(self, size):
            assert size == probe.MAX_RESPONSE_BYTES + 1
            return b'{"data":[]}'
    response = Response()
    monkeypatch.setattr(probe.ModelClient, "_validate_provider", lambda *_: "pinned")
    def open_response(self, request, destination, *, timeout):
        assert destination == "pinned" and timeout == 30
        assert request.get_header("Authorization") == "Bearer fixture-secret"
        assert request.full_url == "https://api.experientiallabs.ai/v1/models"
        return response
    monkeypatch.setattr(probe.ModelClient, "_open_provider", open_response)
    assert probe._request("GET", "/v1/models")[0] == 200
    assert response.closed


@pytest.mark.parametrize("cleanup_error", [OSError, RuntimeError, KeyboardInterrupt])
def test_transport_closes_http_error_without_swallowing_baseexception(monkeypatch, cleanup_error):
    body = io.BytesIO(b"fixture-secret")
    error = urllib.error.HTTPError("https://api.experientiallabs.ai/v1/models", 503, "unavailable", {}, body)
    close = error.close
    def failing_close():
        close()
        raise cleanup_error()
    monkeypatch.setattr(error, "close", failing_close)
    monkeypatch.setattr(probe.ModelClient, "_validate_provider", lambda *_: "pinned")
    def fail(*_, **__):
        raise error
    monkeypatch.setattr(probe.ModelClient, "_open_provider", fail)
    try:
        if cleanup_error is KeyboardInterrupt:
            with pytest.raises(KeyboardInterrupt):
                probe._request("GET", "/v1/models")
        else:
            assert probe._request("GET", "/v1/models") == (503, {"x-request-id": None}, {})
        assert body.closed
    finally:
        close()


def test_workflow_is_opt_in_protected_and_never_replays():
    """Do not expose credentials to PR code, schedules, or rerun attempts."""
    workflow = Path(".github/workflows/provider-catalog-sync.yml").read_text()
    billing = workflow.split("\n  sync:", 1)[0]
    assert "measure_experiential_billing:" in billing and "default: false" in billing
    assert "github.event_name == 'workflow_dispatch'" in billing
    assert "github.ref == 'refs/heads/main'" in billing
    assert "inputs.measure_experiential_billing && github.run_attempt == 1" in billing
    assert "environment: production" in billing and "needs:" not in billing
    assert "pull_request_target" not in workflow and "continue-on-error" not in workflow
    assert "cancel-in-progress: false" in workflow and "contents: read" in workflow
    assert "EXPERIENTAL_LABS_API_KEY: ${{ secrets.EXPERIENTAL_LABS_API_KEY }}" in billing
    assert "--require-hashes -r requirements.lock" in billing
    assert "always() && hashFiles('experiential-billing-evidence.json') != ''" in billing
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in billing
    assert "path: experiential-billing-evidence.json" in billing and "retention-days: 7" in billing
    assert "if-no-files-found: error" in billing


def test_workflow_bootstrap_normalizes_secret_and_runtime_uses_kv(tmp_path, monkeypatch):
    """Execute the actual bootstrap with a fixture-only, offline probe."""
    import textwrap
    from contextual_orchestrator.credentials import get_credential
    billing = Path(".github/workflows/provider-catalog-sync.yml").read_text().split("\n  sync:", 1)[0]
    script = textwrap.dedent(billing.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXPERIENTAL_LABS_API_KEY", "fixture-secret\r\n")
    for name, value in {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(name, value)
    transport = FixtureTransport(tmp_path / "experiential-billing-evidence.json")
    run_probe = probe.run_probe
    def offline(path, **kwargs):
        assert "EXPERIENTAL_LABS_API_KEY" not in probe.os.environ
        assert get_credential("EXPERIENTAL_LABS_API_KEY") == "fixture-secret"
        return run_probe(path, **kwargs, request=transport, pause=lambda _: None)
    monkeypatch.setattr(probe, "run_probe", offline)
    exec(compile(script, "billing-bootstrap", "exec"), {})
    assert transport.posts == 1
    assert "fixture-secret" not in transport.path.read_text()
