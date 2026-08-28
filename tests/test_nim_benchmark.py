"""NIM benchmark harness contracts — discovery, all-modality probes, fair eval.

Everything here runs fully offline: provider behavior is injected through the
transport seam, evaluation workers ride the mock:// path, and the credential
registry is a fresh in-memory KV per test. Adversarial coverage follows the
issue contract: malformed catalogs, duplicate ids, unsupported capabilities,
partial results, non-finite token/cost values, rate limits, timeouts,
response-order drift, and secret redaction.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import tempfile
import urllib.error
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import nim_benchmark as nb  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelAgent, ModelClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = str(REPO_ROOT / "examples" / "nim_task_manifest.json")
PRICING_SCENARIO_PATH = str(REPO_ROOT / "examples" / "nim_pricing_scenario.json")
FAKE_ENDPOINT = "https://nim.example.test/v1"


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Isolated in-memory KV and a clean benchmark env var for every test."""
    set_backend(InMemoryCredentialBackend())
    saved_env = os.environ.pop(nb.NIM_CREDENTIAL_NAME, None)
    try:
        yield
    finally:
        set_backend(None)
        if saved_env is not None:
            os.environ[nb.NIM_CREDENTIAL_NAME] = saved_env


def _ok_json(payload: object) -> tuple[int, bytes]:
    return 200, json.dumps(payload).encode("utf-8")


def _fixed_transport(status: int, body: bytes):
    def transport(method, url, headers, body_bytes):
        return status, body

    return transport


def _mini_manifest(task_count: int = 2) -> dict:
    tasks = [
        {
            "task_id": f"locked_task_{index}",
            "split": "locked",
            "prompt": f"Question number {index}?",
            "scorer": {"name": "substring_match", "version": "1"},
            "expected": {"substring": "zebra"},
        }
        for index in range(task_count)
    ]
    return {"manifest_version": "test.1", "tasks": tasks}


def _mock_agents(*model_ids: str) -> list[ModelAgent]:
    taken: set[str] = set()
    return [
        ModelAgent(
            id=nb.sanitize_worker_agent_id(model_id, taken),
            model=model_id,
            base_url="mock://nim-test",
            credential_key=nb.NIM_CREDENTIAL_NAME,
            tags=("reasoning", "writing"),
        )
        for model_id in model_ids
    ]


# --------------------------------------------------------------------------
# Egress guard + default transport
# --------------------------------------------------------------------------


def test_endpoint_guard_rejects_http() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.require_public_https_endpoint("http://nim.example.test/v1")


def test_endpoint_guard_rejects_missing_host() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.require_public_https_endpoint("https:///v1")


def _patched_getaddrinfo(ip_address: str):
    return lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip_address, 443))]


def test_endpoint_guard_rejects_private_address() -> None:
    original = socket.getaddrinfo
    socket.getaddrinfo = _patched_getaddrinfo("10.0.0.8")
    try:
        with pytest.raises(nb.BenchmarkContractError):
            nb.require_public_https_endpoint(FAKE_ENDPOINT)
    finally:
        socket.getaddrinfo = original


def test_endpoint_guard_accepts_public_address() -> None:
    original = socket.getaddrinfo
    socket.getaddrinfo = _patched_getaddrinfo("93.184.216.34")
    try:
        nb.require_public_https_endpoint(FAKE_ENDPOINT)
    finally:
        socket.getaddrinfo = original


class _FakeDirectResponse:
    """Minimal response returned by the pinned HTTPS connection test seam."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.closed = False

    def read(self, maximum_bytes: int = -1) -> bytes:
        if maximum_bytes < 0:
            return self._body
        return self._body[:maximum_bytes]

    def close(self) -> None:
        self.closed = True


class _FakeDirectConnection:
    """Scripted pinned connection that records address and authority evidence."""

    plans: list[object] = []
    instances: list["_FakeDirectConnection"] = []

    def __init__(self, server_hostname, pinned_ip, port, timeout, context) -> None:
        self.server_hostname = server_hostname
        self.pinned_ip = pinned_ip
        self.port = port
        self.timeout = timeout
        self.context = context
        self.method = ""
        self.target = ""
        self.body = None
        self.headers = {}
        self.closed = False
        self._plan = type(self).plans.pop(0)
        type(self).instances.append(self)

    def request(self, method, target, body, headers) -> None:
        self.method = method
        self.target = target
        self.body = body
        self.headers = headers
        if isinstance(self._plan, BaseException):
            raise self._plan

    def getresponse(self):
        return self._plan

    def close(self) -> None:
        self.closed = True


def _install_direct_transport_fakes(monkeypatch, plans, addresses=("93.184.216.34",)):
    """Install deterministic DNS and connection seams for one transport test."""
    resolution_calls = []

    def resolve(host, port, label):
        resolution_calls.append((host, port, label))
        return addresses

    _FakeDirectConnection.plans = list(plans)
    _FakeDirectConnection.instances = []
    monkeypatch.setattr(nb, "_validated_public_addresses", resolve)
    monkeypatch.setattr(nb, "_PinnedHTTPSConnection", _FakeDirectConnection)
    return resolution_calls


def test_default_transport_returns_status_and_revalidates_each_request(monkeypatch) -> None:
    first_response = _FakeDirectResponse(200, b"body-one")
    second_response = _FakeDirectResponse(200, b"body-two")
    resolution_calls = _install_direct_transport_fakes(
        monkeypatch,
        [first_response, second_response],
    )

    transport = nb.build_default_transport(timeout_seconds=5.0)
    first = transport("GET", f"{FAKE_ENDPOINT}/models", {}, None)
    second = transport("GET", f"{FAKE_ENDPOINT}/models;format=json?second=1", {}, None)

    assert first == (200, b"body-one")
    assert second == (200, b"body-two")
    assert resolution_calls == [
        ("nim.example.test", 443, "NIM benchmark"),
        ("nim.example.test", 443, "NIM benchmark"),
    ]
    assert all(response.closed for response in (first_response, second_response))
    assert all(connection.closed for connection in _FakeDirectConnection.instances)
    assert _FakeDirectConnection.instances[0].server_hostname == "nim.example.test"
    assert _FakeDirectConnection.instances[0].pinned_ip == "93.184.216.34"
    assert _FakeDirectConnection.instances[1].target == "/v1/models;format=json?second=1"


def test_default_transport_returns_http_error_status_with_body(monkeypatch) -> None:
    response = _FakeDirectResponse(429, b"slow down")
    _install_direct_transport_fakes(monkeypatch, [response])
    assert nb.build_default_transport(5.0)(
        "POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b"{}"
    ) == (429, b"slow down")
    assert response.closed is True


def test_default_transport_rejects_oversized_response_and_closes_resources(
    monkeypatch,
) -> None:
    """A provider cannot exhaust memory with an unbounded response body."""
    response = _FakeDirectResponse(200, b"x" * (nb.MAX_PROVIDER_RESPONSE_BYTES + 1))
    _install_direct_transport_fakes(monkeypatch, [response])

    with pytest.raises(nb.BenchmarkContractError, match="response exceeds"):
        nb.build_default_transport(5.0)(
            "GET", f"{FAKE_ENDPOINT}/models", {}, None
        )

    assert response.closed is True
    assert _FakeDirectConnection.instances[0].closed is True


def test_default_transport_rejects_redirect_without_following(monkeypatch) -> None:
    response = _FakeDirectResponse(302, b"redirect")
    _install_direct_transport_fakes(monkeypatch, [response])
    with pytest.raises(nb.BenchmarkContractError, match="redirects are not permitted"):
        nb.build_default_transport(5.0)(
            "POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b"{}"
        )
    assert response.closed is True


def test_default_transport_falls_back_only_to_another_validated_address(monkeypatch) -> None:
    response = _FakeDirectResponse(200, b"catalog")
    _install_direct_transport_fakes(
        monkeypatch,
        [OSError("first pin failed"), response],
        addresses=("93.184.216.34", "93.184.216.35"),
    )
    result = nb.build_default_transport(5.0)(
        "GET", f"{FAKE_ENDPOINT}/models", {}, None
    )
    assert result == (200, b"catalog")
    assert [item.pinned_ip for item in _FakeDirectConnection.instances] == [
        "93.184.216.34",
        "93.184.216.35",
    ]


def test_default_transport_reports_failure_after_every_pin_fails(monkeypatch) -> None:
    _install_direct_transport_fakes(
        monkeypatch,
        [OSError("first pin failed"), OSError("second pin failed")],
        addresses=("93.184.216.34", "93.184.216.35"),
    )
    with pytest.raises(urllib.error.URLError, match="second pin failed"):
        nb.build_default_transport(5.0)(
            "GET", f"{FAKE_ENDPOINT}/models", {}, None
        )


# --------------------------------------------------------------------------
# Request budget
# --------------------------------------------------------------------------


def test_request_budget_rejects_non_positive_cap() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.RequestBudget(0)


def test_request_budget_spends_then_exhausts() -> None:
    budget = nb.RequestBudget(2)
    assert budget.try_spend() and budget.try_spend()
    assert not budget.try_spend()
    assert budget.requests_spent == 2
    with pytest.raises(nb.BenchmarkBudgetError):
        budget.spend_or_fail()


def test_budgeted_client_charges_each_chat_call() -> None:
    budget = nb.RequestBudget(1)
    client = nb._BudgetedModelClient(budget)
    agent = _mock_agents("dryrun/chat-basic")[0]
    assert client.max_retries == 0
    assert client.chat(agent, [{"role": "user", "content": "hello there"}])
    with pytest.raises(nb.BenchmarkBudgetError):
        client.chat(agent, [{"role": "user", "content": "over budget"}])


def test_equal_budget_client_forwards_delegate_controls() -> None:
    delegate = ModelClient(max_output_tokens=32)
    client = nb.EqualBudgetModelClient(delegate, total_token_budget=128, maximum_calls=2)
    assert client.temperature == delegate.temperature
    assert client.timeout == delegate.timeout
    assert client.request_settings_snapshot() == delegate.request_settings_snapshot()
    with client.request_settings(max_output_tokens=16):
        assert client.request_settings_snapshot()["max_output_tokens"] == 16


# --------------------------------------------------------------------------
# Catalog parsing (adversarial)
# --------------------------------------------------------------------------


def test_catalog_parse_rejects_invalid_utf8() -> None:
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.parse_model_catalog_body(b"\xff\xfe\xfa")


def test_catalog_parse_rejects_invalid_json() -> None:
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.parse_model_catalog_body(b"{not json")


def test_catalog_parse_rejects_non_object_and_missing_data() -> None:
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.parse_model_catalog_body(b"[1, 2, 3]")
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.parse_model_catalog_body(json.dumps({"data": "nope"}).encode("utf-8"))


def test_catalog_parse_records_invalid_and_duplicate_entries() -> None:
    body = json.dumps(
        {
            "data": [
                {"id": "vendor/model-b", "owned_by": "vendor"},
                "not-an-object",
                {"owned_by": "vendor"},
                {"id": "   ", "owned_by": "vendor"},
                {"id": 42},
                {"id": "vendor/model-a", "owned_by": 99},
                {"id": "vendor/model-b", "owned_by": "vendor"},
            ]
        }
    ).encode("utf-8")
    catalog = nb.parse_model_catalog_body(body)
    # Sorted output guards against provider response-order drift.
    assert [row["model_id"] for row in catalog["models"]] == ["vendor/model-a", "vendor/model-b"]
    assert catalog["models"][0]["owned_by"] == ""  # non-string owner coerced
    assert catalog["duplicate_model_ids"] == ["vendor/model-b"]
    reasons = {entry["invalid_reason"] for entry in catalog["invalid_entries"]}
    assert reasons == {"entry_not_an_object", "missing_model_id"}
    assert len(catalog["invalid_entries"]) == 4


def test_catalog_order_drift_never_reorders_models() -> None:
    forward = json.dumps({"data": [{"id": "a/model-one"}, {"id": "b/model-two"}]}).encode("utf-8")
    reverse = json.dumps({"data": [{"id": "b/model-two"}, {"id": "a/model-one"}]}).encode("utf-8")
    assert nb.parse_model_catalog_body(forward)["models"] == nb.parse_model_catalog_body(reverse)["models"]


def test_discover_catalog_success_and_budget_charge() -> None:
    budget = nb.RequestBudget(3)
    catalog = nb.discover_model_catalog(
        _fixed_transport(*_ok_json({"data": [{"id": "vendor/model-a"}]})), FAKE_ENDPOINT, "key", budget
    )
    assert catalog["models"][0]["model_id"] == "vendor/model-a"
    assert budget.requests_spent == 1


def test_discover_catalog_fails_closed_on_auth_rejection() -> None:
    for status in (401, 403):
        with pytest.raises(nb.BenchmarkAuthError):
            nb.discover_model_catalog(_fixed_transport(status, b"{}"), FAKE_ENDPOINT, "key", nb.RequestBudget(3))


def test_discover_catalog_fails_closed_on_http_error() -> None:
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.discover_model_catalog(_fixed_transport(500, b"{}"), FAKE_ENDPOINT, "key", nb.RequestBudget(3))


def test_discover_catalog_fails_closed_on_network_error() -> None:
    def transport(method, url, headers, body):
        raise urllib.error.URLError("dns failure")

    with pytest.raises(nb.CatalogDiscoveryError):
        nb.discover_model_catalog(transport, FAKE_ENDPOINT, "key", nb.RequestBudget(3))


def test_discover_catalog_fails_closed_on_empty_inventory() -> None:
    with pytest.raises(nb.CatalogDiscoveryError):
        nb.discover_model_catalog(_fixed_transport(*_ok_json({"data": []})), FAKE_ENDPOINT, "key", nb.RequestBudget(3))


# --------------------------------------------------------------------------
# Capability probes — every NIM contract
# --------------------------------------------------------------------------


def test_probe_registry_covers_every_nim_contract() -> None:
    assert set(nb.CAPABILITY_PROBE_ORDER) == {
        "chat_completion",
        "text_completion",
        "response_generation",
        "text_embedding",
        "image_understanding",
        "video_understanding",
        "audio_understanding",
        "audio_transcription",
        "audio_speech",
    }


def test_probe_assets_are_deterministic_and_well_formed() -> None:
    assert nb._tiny_wav_bytes() == nb._tiny_wav_bytes()
    assert nb._tiny_wav_bytes().startswith(b"RIFF")
    assert nb._image_data_uri().startswith("data:image/png;base64,")
    assert nb._video_data_uri().startswith("data:video/mp4;base64,")
    multipart = nb._multipart_transcription_body("vendor/asr-model")
    assert b'name="model"' in multipart and b"vendor/asr-model" in multipart
    assert b'filename="probe.wav"' in multipart and b"RIFF" in multipart


def test_response_validators_accept_and_reject_shapes() -> None:
    assert nb._has_choice({"choices": [{"message": {"content": "x"}}]})
    assert not nb._has_choice({"choices": []}) and not nb._has_choice({})
    assert nb._has_embedding({"data": [{"embedding": [0.1]}]})
    assert not nb._has_embedding({"data": []})
    assert not nb._has_embedding({"data": ["oops"]})
    assert not nb._has_embedding({"data": [{"embedding": "oops"}]})
    assert not nb._has_embedding({})
    assert nb._has_response_output({"output_text": "x"})
    assert not nb._has_response_output({"unrelated": 1})
    assert nb._has_transcription_text({"text": "ok"})
    assert not nb._has_transcription_text({"text": 5})


def test_probe_status_classification_table() -> None:
    assert nb.classify_probe_status(200) == "supported"
    for status in (400, 404, 405, 415, 422, 501):
        assert nb.classify_probe_status(status) == "unsupported"
    assert nb.classify_probe_status(401) == "auth_rejected"
    assert nb.classify_probe_status(403) == "unavailable"
    assert nb.classify_probe_status(408) == "timeout"
    assert nb.classify_probe_status(429) == "rate_limited"
    assert nb.classify_probe_status(500) == "unavailable"
    assert nb.classify_probe_status(302) == "failed"


def _probe(transport, capability_name="chat_completion"):
    return nb.execute_capability_probe(transport, FAKE_ENDPOINT, "key", "vendor/model-a", capability_name)


def test_probe_supported_chat() -> None:
    row = _probe(_fixed_transport(*_ok_json({"choices": [{"message": {"content": "OK"}}]})))
    assert row["probe_outcome"] == "supported"
    assert row["http_status"] == 200


def test_probe_timeout_and_network_failures() -> None:
    def timeout_transport(method, url, headers, body):
        raise socket.timeout("slow")

    def broken_transport(method, url, headers, body):
        raise ConnectionResetError("reset")

    assert _probe(timeout_transport)["probe_outcome"] == "timeout"
    row = _probe(broken_transport)
    assert row["probe_outcome"] == "failed"
    assert row["outcome_reason"].startswith("network_error:")


def test_probe_auth_rejection_fails_closed() -> None:
    with pytest.raises(nb.BenchmarkAuthError):
        _probe(_fixed_transport(401, b"{}"))


def test_probe_unsupported_and_rate_limited() -> None:
    assert _probe(_fixed_transport(404, b"{}"))["probe_outcome"] == "unsupported"
    assert _probe(_fixed_transport(429, b"{}"))["probe_outcome"] == "rate_limited"


def test_probe_malformed_success_bodies() -> None:
    assert _probe(_fixed_transport(200, b"not json"))["probe_outcome"] == "malformed_response"
    assert _probe(_fixed_transport(200, b"[]"))["probe_outcome"] == "malformed_response"
    assert _probe(_fixed_transport(*_ok_json({"choices": []})))["probe_outcome"] == "malformed_response"


def test_probe_binary_speech_contract() -> None:
    supported = _probe(_fixed_transport(200, b"RIFFaudio"), "audio_speech")
    assert supported["probe_outcome"] == "supported"
    empty = _probe(_fixed_transport(200, b""), "audio_speech")
    assert empty["probe_outcome"] == "malformed_response"
    assert empty["outcome_reason"] == "http_200_with_empty_media_body"


def _rows(**outcome_by_capability: str) -> list[dict]:
    return [
        {"capability_name": name, "probe_outcome": outcome}
        for name, outcome in outcome_by_capability.items()
    ]


def test_classification_covers_every_modality_class() -> None:
    assert nb.classify_model_capabilities(
        _rows(chat_completion="supported", image_understanding="supported", audio_understanding="supported")
    )["model_classification"] == "omni_capable"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="supported", image_understanding="supported")
    )["model_classification"] == "vision_chat_capable"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="supported", video_understanding="supported")
    )["model_classification"] == "vision_chat_capable"
    assert nb.classify_model_capabilities(_rows(chat_completion="supported"))["model_classification"] == "chat_capable"
    assert nb.classify_model_capabilities(_rows(text_embedding="supported"))["model_classification"] == "embedding_only"
    assert nb.classify_model_capabilities(_rows(text_completion="supported"))["model_classification"] == "completion_only"
    assert nb.classify_model_capabilities(
        _rows(response_generation="supported")
    )["model_classification"] == "responses_only"
    assert nb.classify_model_capabilities(_rows(audio_transcription="supported"))["model_classification"] == "audio_only"
    assert nb.classify_model_capabilities(_rows(audio_speech="supported"))["model_classification"] == "audio_only"
    assert nb.classify_model_capabilities(_rows(chat_completion="skipped"))["model_classification"] == "skipped"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="rate_limited", text_embedding="unsupported")
    )["model_classification"] == "rate_limited"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="unavailable", text_embedding="unsupported")
    )["model_classification"] == "unavailable"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="timeout", text_embedding="unsupported")
    )["model_classification"] == "failed"
    assert nb.classify_model_capabilities(
        _rows(chat_completion="unsupported", text_embedding="unsupported")
    )["model_classification"] == "unsupported_for_contract"


def test_classification_reports_chat_eligibility() -> None:
    assert nb.classify_model_capabilities(_rows(chat_completion="supported"))["chat_eligible"]
    assert not nb.classify_model_capabilities(_rows(text_embedding="supported"))["chat_eligible"]


def test_probe_models_rejects_bad_concurrency() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.probe_discovered_models([], _fixed_transport(200, b"{}"), FAKE_ENDPOINT, "key", nb.RequestBudget(1), 0, lambda: 0.0)


def test_probe_models_sorted_despite_input_order_drift() -> None:
    # Models arrive in reverse order; the snapshot must still come out sorted.
    models = [{"model_id": "b/model-two", "owned_by": ""}, {"model_id": "a/model-one", "owned_by": ""}]
    results = nb.probe_discovered_models(
        models,
        _fixed_transport(*_ok_json({"choices": [{"message": {"content": "OK"}}]})),
        FAKE_ENDPOINT,
        "key",
        nb.RequestBudget(100),
        2,
        lambda: 1234.0,
        lambda: 0.0,
    )
    assert [row["model_id"] for row in results] == ["a/model-one", "b/model-two"]
    # The fixed transport answers every probe, so the model reads as omni.
    assert results[0]["model_classification"] == "omni_capable"
    assert results[0]["discovered_at_unix"] == 1234.0
    assert results[0]["endpoint"] == FAKE_ENDPOINT


def test_probe_models_rejects_incomplete_probe_budget_before_egress() -> None:
    """A capability phase never emits biased partial-inventory evidence."""
    models = [
        {"model_id": "a/model-one", "owned_by": ""},
        {"model_id": "b/model-two", "owned_by": ""},
    ]
    budget = nb.RequestBudget(5)
    calls: list[str] = []

    def transport(
        _method: str,
        _url: str,
        _headers: dict[str, str],
        _body: bytes | None,
    ) -> tuple[int, bytes]:
        calls.append("called")
        return _ok_json({"choices": [{"message": {"content": "OK"}}]})

    with pytest.raises(nb.BenchmarkBudgetError, match="capability probe plan needs 18"):
        nb.probe_discovered_models(
            models,
            transport,
            FAKE_ENDPOINT,
            "key",
            budget,
            1,
            lambda: 1234.0,
            lambda: 0.0,
        )

    assert calls == []
    assert budget.requests_spent == 0


# --------------------------------------------------------------------------
# Scorers, manifest, pricing
# --------------------------------------------------------------------------


def test_scorers_match_and_miss() -> None:
    assert nb.score_exact_number_match({"number": "21"}, "the answer is 21.") == 1.0
    assert nb.score_exact_number_match({"number": "21"}, "the answer is 210") == 0.0
    assert nb.score_exact_number_match({"number": "21"}, "the answer is 21.5") == 0.0
    assert nb.score_exact_number_match({"number": "21"}, "the answer is 121") == 0.0
    assert nb.score_exact_number_match({"number": "0.05"}, "It costs $0.05 total") == 1.0
    assert nb.score_substring_match({"substring": "Paris"}, "It is PARIS indeed") == 1.0
    assert nb.score_substring_match({"substring": "Paris"}, "It is Lyon") == 0.0


def _write_json(tmp_path: str, name: str, payload: object) -> str:
    path = os.path.join(tmp_path, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_example_task_manifest_is_valid_and_split() -> None:
    manifest = nb.load_task_manifest(TASK_MANIFEST_PATH)
    locked = nb.locked_evaluation_tasks(manifest)
    assert len(locked) == 30
    assert len(manifest["tasks"]) - len(locked) == 2  # exploratory tuning split stays out


def test_manifest_rejects_each_contract_violation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad_json = os.path.join(tmp, "bad.json")
        with open(bad_json, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        cases = [
            (bad_json, None),
            (_write_json(tmp, "list.json", [1]), None),
            (_write_json(tmp, "nover.json", {"tasks": []}), None),
            (_write_json(tmp, "notasks.json", {"manifest_version": "1", "tasks": []}), None),
            (_write_json(tmp, "taskstr.json", {"manifest_version": "1", "tasks": ["x"]}), None),
        ]
        for path, _ in cases:
            with pytest.raises(nb.BenchmarkContractError):
                nb.load_task_manifest(path)

        def manifest_with(**overrides: object) -> dict:
            task = {
                "task_id": "valid_task_one",
                "split": "locked",
                "prompt": "What color is the clear daytime sky?",
                "scorer": {"name": "substring_match", "version": "1"},
                "expected": {"substring": "blue"},
            }
            task.update(overrides)
            return {"manifest_version": "1", "tasks": [task]}

        violations = [
            manifest_with(task_id="Bad-Id"),
            manifest_with(task_id="single"),
            manifest_with(split="training"),
            manifest_with(prompt="   "),
            manifest_with(prompt=42),
            manifest_with(scorer="substring_match"),
            manifest_with(scorer={"name": "unknown_scorer", "version": "9"}),
            manifest_with(expected={}),
            manifest_with(expected="blue"),
            # Leakage: the scorer would award the prompt itself a point.
            manifest_with(prompt="Answer blue if the sky is blue."),
        ]
        for index, payload in enumerate(violations):
            path = _write_json(tmp, f"violation_{index}.json", payload)
            with pytest.raises(nb.BenchmarkContractError):
                nb.load_task_manifest(path)

        duplicate = manifest_with()
        duplicate["tasks"] = [duplicate["tasks"][0], dict(duplicate["tasks"][0])]
        path = _write_json(tmp, "duplicate.json", duplicate)
        with pytest.raises(nb.BenchmarkContractError):
            nb.load_task_manifest(path)


def test_example_pricing_scenario_is_valid_and_none_passthrough() -> None:
    scenario = nb.load_pricing_scenario(PRICING_SCENARIO_PATH)
    assert scenario["scenario_status"] == "example_unreviewed"
    assert nb.load_pricing_scenario(None) is None


def test_pricing_scenario_rejects_each_contract_violation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad_json = os.path.join(tmp, "bad.json")
        with open(bad_json, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        base = {
            "scenario_version": "1",
            "scenario_status": "reviewed",
            "usd_per_million_tokens": {"vendor/model-a": {"input": 1.0, "output": 2.0}},
        }
        violations = [
            dict(base, scenario_version=3),
            dict(base, scenario_status="draft"),
            dict(base, usd_per_million_tokens=[1]),
            dict(base, usd_per_million_tokens={"vendor/model-a": "cheap"}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"input": True, "output": 2.0}}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"input": 1.0, "output": "two"}}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"input": float("nan"), "output": 2.0}}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"input": float("inf"), "output": 2.0}}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"input": -0.1, "output": 2.0}}),
            dict(base, usd_per_million_tokens={"vendor/model-a": {"output": 2.0}}),
        ]
        with pytest.raises(nb.BenchmarkContractError):
            nb.load_pricing_scenario(bad_json)
        for index, payload in enumerate(violations):
            path = _write_json(tmp, f"pricing_{index}.json", payload)
            with pytest.raises(nb.BenchmarkContractError):
                nb.load_pricing_scenario(path)


def test_hypothetical_cost_paths() -> None:
    scenario = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {"vendor/model-a": {"input": 1.0, "output": 2.0}},
    }
    usage = {"vendor/model-a": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}}
    assert nb.hypothetical_cost_usd(scenario, usage) == 2.0
    assert nb.hypothetical_cost_usd(None, usage) == "unknown"
    unpriced = {"vendor/other-model": {"prompt_tokens": 10, "completion_tokens": 10}}
    assert nb.hypothetical_cost_usd(scenario, unpriced) == "unknown"


# --------------------------------------------------------------------------
# Worker pool + usage accounting
# --------------------------------------------------------------------------


def test_sanitize_worker_agent_id_paths() -> None:
    taken: set[str] = set()
    assert nb.sanitize_worker_agent_id("meta/llama-3.1-8b", taken) == "meta_llama_3_1_8b"
    assert nb.sanitize_worker_agent_id("meta/llama-3.1-8b", taken) == "meta_llama_3_1_8b_2"
    assert nb.sanitize_worker_agent_id("meta/llama-3.1-8b", taken) == "meta_llama_3_1_8b_3"
    assert nb.sanitize_worker_agent_id("gpt", taken) == "nim_gpt"
    assert nb.sanitize_worker_agent_id("///", taken) == "unnamed_model"


def _probed(model_id: str, chat_eligible: bool = True) -> dict:
    return {
        "model_id": model_id,
        "owned_by": "vendor",
        "chat_eligible": chat_eligible,
        "model_classification": "chat_capable" if chat_eligible else "embedding_only",
    }


def test_build_worker_agents_filters_caps_and_validates() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.build_worker_agents([], "mock://x", 0)
    probed = [_probed("a/chat-one"), _probed("b/embed-only", chat_eligible=False), _probed("c/chat-two"), _probed("d/chat-three")]
    agents = nb.build_worker_agents(probed, "mock://x", 2)
    assert [agent.model for agent in agents] == ["a/chat-one", "c/chat-two"]
    assert all(agent.credential_key == nb.NIM_CREDENTIAL_NAME for agent in agents)


def test_token_count_coercion_guards_non_finite_values() -> None:
    assert nb._coerce_token_count(7) == 7
    assert nb._coerce_token_count(7.9) == 7
    assert nb._coerce_token_count(True) is None
    assert nb._coerce_token_count("7") is None
    assert nb._coerce_token_count(float("nan")) is None
    assert nb._coerce_token_count(float("inf")) is None
    assert nb._coerce_token_count(-1) is None
    assert nb._coerce_token_count(None) is None


def test_cell_usage_reported_vs_estimated_and_failover() -> None:
    agents_by_id = {"worker_one": "vendor/model-a", "worker_two": "vendor/model-b"}
    reported_trace = [
        {"id": 0, "role": "worker", "agent_id": "worker_one", "output": "x",
         "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        {"id": 1, "role": "verifier", "agent_id": "worker_one", "served_agent_id": "worker_two", "output": "y",
         "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
    ]
    usage_by_model, summary = nb._cell_usage(reported_trace, agents_by_id, "prompt text")
    assert summary["token_usage_source"] == "reported"
    assert usage_by_model["vendor/model-a"] == {"prompt_tokens": 10, "completion_tokens": 5}
    assert usage_by_model["vendor/model-b"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert summary["total_tokens"] == 20
    assert summary["models_used"][1]["agent_id"] == "worker_two"

    adversarial_trace = [
        {"id": 0, "role": "worker", "agent_id": "worker_one", "output": "answer text",
         "usage": {"prompt_tokens": float("nan"), "completion_tokens": float("inf")}},
        {"id": 1, "role": "worker", "agent_id": "worker_one", "output": None, "usage": "corrupted"},
    ]
    _usage, summary = nb._cell_usage(adversarial_trace, agents_by_id, "prompt text")
    assert summary["token_usage_source"] == "estimated"
    assert summary["total_tokens"] > 0


def test_run_error_classification() -> None:
    assert nb._classify_run_error(TimeoutError("slow")) == "timeout"
    wrapped = RuntimeError("provider failed")
    wrapped.__cause__ = socket.timeout("slow")
    assert nb._classify_run_error(wrapped) == "timeout"
    assert nb._classify_run_error(ValueError("bad")) == "failure"


def _task(task_id: str = "sample_task", expected: str = "zebra") -> dict:
    return {
        "task_id": task_id,
        "split": "locked",
        "prompt": "Where do stripes live?",
        "scorer": {"name": "substring_match", "version": "1"},
        "expected": {"substring": expected},
    }


def test_run_policy_cell_success_failure_timeout_and_fail_closed() -> None:
    agents_by_id = {"worker_one": "vendor/model-a"}
    ok = nb.run_policy_cell(
        "route_once",
        _task(),
        lambda: {"answer": "a zebra appears", "trace": [{"id": 0, "role": "worker", "agent_id": "worker_one", "output": "a zebra appears"}]},
        agents_by_id,
        None,
        nb._deterministic_timer(),
    )
    assert ok["run_outcome"] == "success" and ok["task_score"] == 1.0
    assert ok["hypothetical_cost_usd"] == "unknown" and ok["actual_cost_usd"] == 0.0
    assert ok["response_sha256"] and ok["call_count"] == 1

    def fail() -> dict:
        raise RuntimeError("boom")

    failed = nb.run_policy_cell("route_once", _task(), fail, agents_by_id, None, nb._deterministic_timer())
    assert failed["run_outcome"] == "failure" and failed["task_score"] is None

    def slow() -> dict:
        raise TimeoutError("deadline")

    timed_out = nb.run_policy_cell("route_once", _task(), slow, agents_by_id, None, nb._deterministic_timer())
    assert timed_out["run_outcome"] == "timeout"

    def out_of_budget() -> dict:
        raise nb.BenchmarkBudgetError("exhausted")

    with pytest.raises(nb.BenchmarkBudgetError):
        nb.run_policy_cell("route_once", _task(), out_of_budget, agents_by_id, None, nb._deterministic_timer())


def test_cheapest_priced_agent_selection() -> None:
    agents = _mock_agents("vendor/model-a", "vendor/model-b", "vendor/model-c")
    scenario = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {
            "vendor/model-b": {"input": 0.1, "output": 0.2},
            "vendor/model-c": {"input": 0.1, "output": 0.2},
        },
    }
    assert nb.cheapest_priced_agent(agents, None) is None
    assert nb.cheapest_priced_agent(agents, {"scenario_version": "1", "scenario_status": "reviewed", "usd_per_million_tokens": {}}) is None
    # Deterministic tiebreak: equal combined rate resolves by model id.
    assert nb.cheapest_priced_agent(agents, scenario).model == "vendor/model-b"


def test_planned_evaluation_requests_formula() -> None:
    assert nb.planned_evaluation_requests(3, 10) == 10 * (
        3 * 2 + nb.MAX_WORKFLOW_DEPTH + nb.MAX_WORKFLOW_DEPTH + 2
    )


def test_evaluate_policies_contract_failures() -> None:
    client = ModelClient()
    with pytest.raises(nb.BenchmarkContractError):
        nb.evaluate_policies([], _mini_manifest(), None, client, nb.RequestBudget(100))
    agents = _mock_agents("vendor/model-a")
    exploratory_only = {"manifest_version": "1", "tasks": [dict(_task(), split="exploratory")]}
    with pytest.raises(nb.BenchmarkContractError):
        nb.evaluate_policies(agents, exploratory_only, None, client, nb.RequestBudget(100))
    with pytest.raises(nb.BenchmarkBudgetError):
        nb.evaluate_policies(agents, _mini_manifest(), None, client, nb.RequestBudget(2))


def test_evaluate_policies_all_arms_with_pricing() -> None:
    agents = _mock_agents("dryrun/chat-basic", "dryrun/chat-vision")
    scenario = nb.load_pricing_scenario(PRICING_SCENARIO_PATH)
    budget = nb.RequestBudget(200)
    evaluation = nb.evaluate_policies(
        agents, _mini_manifest(3), scenario, nb._BudgetedModelClient(budget), budget, nb._deterministic_timer()
    )
    cells = evaluation["evaluation_cells"]
    policies = {cell["policy_name"] for cell in cells}
    assert policies == {
        "direct_single_worker:dryrun/chat-basic",
        "direct_single_worker:dryrun/chat-vision",
        "route_once",
        "conduct_bounded",
        "cheapest_eligible_worker",
    }
    assert evaluation["cheapest_worker_skip_reason"] is None
    conduct_cells = [cell for cell in cells if cell["policy_name"] == "conduct_bounded"]
    assert all(cell["workflow_depth"] <= nb.MAX_WORKFLOW_DEPTH for cell in conduct_cells)
    assert all(cell["configured_total_token_budget"] == 256 for cell in conduct_cells)
    assert all(cell["configured_maximum_calls"] == nb.MAX_WORKFLOW_DEPTH for cell in conduct_cells)
    assert all(cell["observed_budget_calls"] <= nb.MAX_WORKFLOW_DEPTH for cell in conduct_cells)
    assert cells == sorted(cells, key=lambda cell: (cell["policy_name"], cell["task_id"]))
    assert budget.requests_spent > 0


def test_evaluate_policies_skip_reasons_without_pricing() -> None:
    agents = _mock_agents("vendor/model-a")
    budget = nb.RequestBudget(200)
    evaluation = nb.evaluate_policies(agents, _mini_manifest(), None, ModelClient(), budget)
    assert evaluation["cheapest_worker_skip_reason"] == "no_pricing_scenario_supplied"
    unpriced_scenario = {
        "scenario_version": "1",
        "scenario_status": "reviewed",
        "usd_per_million_tokens": {"vendor/other": {"input": 1.0, "output": 1.0}},
    }
    evaluation = nb.evaluate_policies(agents, _mini_manifest(), unpriced_scenario, ModelClient(), nb.RequestBudget(200))
    assert evaluation["cheapest_worker_skip_reason"] == "no_worker_priced_by_scenario"


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def test_paired_bootstrap_requires_pairs_and_is_deterministic() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.paired_bootstrap_mean_difference([])
    first = nb.paired_bootstrap_mean_difference([(1.0, 0.0), (0.5, 0.5), (1.0, 0.5)], seed=11)
    second = nb.paired_bootstrap_mean_difference([(1.0, 0.0), (0.5, 0.5), (1.0, 0.5)], seed=11)
    assert first == second
    assert first["ci_low"] <= first["mean_difference"] <= first["ci_high"]
    assert first["pair_count"] == 3


def test_pareto_frontier_excludes_dominated_rows() -> None:
    rows = [
        {"name": "good_cheap", "quality": 0.9, "cost": 1.0},
        {"name": "good_pricey", "quality": 0.9, "cost": 2.0},
        {"name": "bad_cheap", "quality": 0.1, "cost": 0.5},
        {"name": "bad_pricey", "quality": 0.1, "cost": 5.0},
    ]
    frontier = nb.pareto_frontier(rows, "quality", "cost")
    assert [row["name"] for row in frontier] == ["good_cheap", "bad_cheap"]


def _synthetic_cell(policy: str, task_id: str, score, outcome: str = "success", cost=0.5) -> dict:
    return {
        "policy_name": policy,
        "task_id": task_id,
        "task_split": "locked",
        "scorer_name": "substring_match",
        "scorer_version": "1",
        "task_score": score,
        "run_outcome": outcome,
        "outcome_reason": "completed",
        "end_to_end_latency_ms": 10.0,
        "provider_latency_ms": None,
        "call_count": 1,
        "workflow_depth": 1,
        "prompt_tokens": 4,
        "completion_tokens": 4,
        "total_tokens": 8,
        "token_usage_source": "estimated",
        "actual_cost_usd": 0.0,
        "hypothetical_cost_usd": cost,
        "models_used": [],
        "response_sha256": "hash",
    }


def test_summaries_label_unknown_costs_and_all_failure_policies() -> None:
    cells = [
        _synthetic_cell("route_once", "task_one", 1.0, cost=0.5),
        _synthetic_cell("route_once", "task_two", 0.0, cost="unknown"),
        _synthetic_cell("broken_policy", "task_one", None, outcome="failure", cost="unknown"),
    ]
    summaries = {row["policy_name"]: row for row in nb.summarize_policies(cells)}
    assert summaries["route_once"]["mean_task_score"] == 0.5
    assert summaries["route_once"]["mean_hypothetical_cost_usd"] == 0.5
    assert summaries["route_once"]["unknown_hypothetical_cost_cells"] == 1
    assert summaries["broken_policy"]["mean_task_score"] == 0.0
    assert summaries["broken_policy"]["mean_hypothetical_cost_usd"] == "unknown"
    assert summaries["broken_policy"]["success_count"] == 0


def test_best_single_worker_hindsight_selection() -> None:
    assert nb.best_single_worker_hindsight([{"policy_name": "route_once", "mean_task_score": 1.0}]) is None
    summaries = nb.summarize_policies(
        [
            _synthetic_cell("direct_single_worker:vendor/model-a", "task_one", 0.0),
            _synthetic_cell("direct_single_worker:vendor/model-b", "task_one", 1.0),
        ]
    )
    best = nb.best_single_worker_hindsight(summaries)
    assert best["model_id"] == "vendor/model-b"
    assert best["selection_basis"] == "hindsight_argmax_mean_locked_score"


def test_paired_policy_comparisons_skip_missing_and_disjoint() -> None:
    disjoint = [
        _synthetic_cell("conduct_bounded", "task_one", 1.0),
        _synthetic_cell("route_once", "task_two", 0.0),
    ]
    assert nb.paired_policy_comparisons(disjoint, seed=3) == []
    cells = [
        _synthetic_cell("conduct_bounded", "task_one", 1.0),
        _synthetic_cell("route_once", "task_one", 0.0),
        _synthetic_cell("direct_single_worker:vendor/model-a", "task_one", 1.0),
        # Failed cells carry no score and must stay out of the pairing.
        _synthetic_cell("route_once", "task_three", None, outcome="failure"),
    ]
    comparisons = nb.paired_policy_comparisons(cells, seed=3)
    pairs = {(row["policy_a"], row["policy_b"]) for row in comparisons}
    assert ("conduct_bounded", "route_once") in pairs
    assert ("route_once", "direct_single_worker:vendor/model-a") in pairs


def test_pareto_frontiers_exclude_unknown_cost_policies() -> None:
    summaries = nb.summarize_policies(
        [
            _synthetic_cell("route_once", "task_one", 1.0, cost=0.5),
            _synthetic_cell("conduct_bounded", "task_one", 1.0, cost="unknown"),
        ]
    )
    frontiers = nb.build_pareto_frontiers(summaries)
    assert [row["policy_name"] for row in frontiers["quality_vs_hypothetical_cost"]] == ["route_once"]
    assert frontiers["excluded_unknown_cost_policies"] == ["conduct_bounded"]
    assert len(frontiers["quality_vs_latency"]) >= 1


# --------------------------------------------------------------------------
# Provenance, schema, artifacts, secrets
# --------------------------------------------------------------------------


def test_hash_helpers_are_stable() -> None:
    assert nb.sha256_of_json({"b": 1, "a": 2}) == nb.sha256_of_json({"a": 2, "b": 1})
    assert len(nb.sha256_of_file(TASK_MANIFEST_PATH)) == 64


def test_provenance_fails_closed_for_live_without_identity() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.build_provenance("live", "", "", {}, TASK_MANIFEST_PATH, None, {})
    live = nb.build_provenance("live", "abc123", "run-9", {}, TASK_MANIFEST_PATH, PRICING_SCENARIO_PATH, {"seed": 7})
    assert live["pricing_scenario_sha256"] is not None
    dry = nb.build_provenance("dry_run", "", "", {}, TASK_MANIFEST_PATH, None, {})
    assert dry["git_sha"] == nb.DRY_RUN_PROVENANCE_PLACEHOLDER
    assert dry["pricing_scenario_sha256"] is None


def test_report_schema_validation_reports_missing_paths() -> None:
    with pytest.raises(nb.BenchmarkContractError) as excinfo:
        nb.validate_report_schema({"provenance": "not-a-dict"})
    assert "provenance.run_mode" in str(excinfo.value)


def _dry_report(output_dir: str) -> dict:
    return nb.run_benchmark(
        "dry_run",
        TASK_MANIFEST_PATH,
        PRICING_SCENARIO_PATH,
        output_dir,
        max_total_requests=900,
    )


def test_artifact_writer_refuses_secret_leak() -> None:
    register_credential(nb.NIM_CREDENTIAL_NAME, "nvapi-super-secret-value")
    with tempfile.TemporaryDirectory() as tmp:
        report = _dry_report(os.path.join(tmp, "clean"))
        # The honest artifacts never contain the credential...
        serialized = json.dumps(report)
        assert "nvapi-super-secret-value" not in serialized
        # ...and a poisoned report is refused outright.
        report["catalog_snapshot"]["probed_models"][0]["owned_by"] = "nvapi-super-secret-value"
        with pytest.raises(nb.SecretLeakError):
            nb.write_benchmark_artifacts(report, os.path.join(tmp, "leaky"))


def test_secret_guard_passes_when_no_secret_registered() -> None:
    nb._ensure_secret_absent("no secret registered anywhere")


# --------------------------------------------------------------------------
# Dry-run provider + full pipeline
# --------------------------------------------------------------------------


def test_dry_run_transport_serves_all_paths() -> None:
    transport = nb.build_dry_run_transport()
    status, body = transport("GET", f"{FAKE_ENDPOINT}/models", {}, None)
    assert status == 200 and b"dryrun/chat-omni" in body
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b'{"model": "dryrun/unknown-model"}')
    assert status == 404
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b"no model marker at all")
    assert status == 404
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b'{"model": "dryrun/throttled-model"}')
    assert status == 429
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b'{"model": "dryrun/outage-model"}')
    assert status == 503
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/chat/completions", {}, b'{"model": "dryrun/legacy-unsupported"}')
    assert status == 404
    status, _ = transport("POST", f"{FAKE_ENDPOINT}/embeddings", {}, b'{"model": "dryrun/chat-basic"}')
    assert status == 400
    status, body = transport("POST", f"{FAKE_ENDPOINT}/embeddings", {}, b'{"model": "dryrun/embed-basic"}')
    assert status == 200 and b"embedding" in body
    status, body = transport("POST", f"{FAKE_ENDPOINT}/responses", {}, b'{"model": "dryrun/responses-native"}')
    assert status == 200 and b"output_text" in body
    multipart = nb._multipart_transcription_body("dryrun/audio-transcribe")
    status, body = transport("POST", f"{FAKE_ENDPOINT}/audio/transcriptions", {}, multipart)
    assert status == 200 and b"text" in body
    status, body = transport("POST", f"{FAKE_ENDPOINT}/audio/speech", {}, b'{"model": "dryrun/audio-speech"}')
    assert status == 200 and body.startswith(b"RIFF")
    with pytest.raises(nb.CatalogDiscoveryError):
        transport("POST", f"{FAKE_ENDPOINT}/never/heard-of-it", {}, b'{"model": "dryrun/chat-basic"}')


def test_dry_run_success_bodies_per_endpoint() -> None:
    assert b"embedding" in nb._dry_run_success_body("/v1/embeddings")
    assert b"output_text" in nb._dry_run_success_body("/v1/responses")
    assert b"text" in nb._dry_run_success_body("/v1/audio/transcriptions")
    assert nb._dry_run_success_body("/v1/audio/speech").startswith(b"RIFF")
    assert b"choices" in nb._dry_run_success_body("/v1/chat/completions")


def test_deterministic_timer_advances_monotonically() -> None:
    timer = nb._deterministic_timer()
    assert timer() < timer() < timer()


def test_run_benchmark_rejects_unknown_mode() -> None:
    with pytest.raises(nb.BenchmarkContractError):
        nb.run_benchmark("test", TASK_MANIFEST_PATH, None, "unused")


def test_dry_run_pipeline_covers_every_modality_and_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        first = _dry_report(os.path.join(tmp, "one"))
        second = _dry_report(os.path.join(tmp, "two"))
        assert first["capability_summary"] == {
            "audio_only": 2,
            "chat_capable": 1,
            "completion_only": 1,
            "embedding_only": 1,
            "omni_capable": 1,
            "rate_limited": 1,
            "responses_only": 1,
            "unavailable": 1,
            "unsupported_for_contract": 1,
            "vision_chat_capable": 2,
        }
        by_model = {row["model_id"]: row for row in first["catalog_snapshot"]["probed_models"]}
        assert by_model["dryrun/chat-omni"]["model_classification"] == "omni_capable"
        assert set(by_model["dryrun/chat-omni"]["supported_capabilities"]) >= {
            "chat_completion",
            "image_understanding",
            "video_understanding",
            "audio_understanding",
        }
        assert by_model["dryrun/audio-transcribe"]["supported_capabilities"] == ["audio_transcription"]
        assert by_model["dryrun/audio-speech"]["supported_capabilities"] == ["audio_speech"]
        assert by_model["dryrun/embed-basic"]["model_classification"] == "embedding_only"
        assert by_model["dryrun/chat-video"]["model_classification"] == "vision_chat_capable"
        # Catalog hygiene lists survive into the snapshot.
        assert first["catalog_snapshot"]["duplicate_model_ids"] == ["dryrun/chat-basic"]
        assert first["catalog_snapshot"]["invalid_entries"][0]["invalid_reason"] == "missing_model_id"
        # The evaluation compares every required system.
        assert first["evaluation"]["best_single_worker_hindsight"] is not None
        assert first["evaluation"]["pareto_frontiers"]["quality_vs_latency"]
        assert first["evaluation"]["paired_comparisons"]
        # Deterministic artifacts: identical reports across runs.
        with open(os.path.join(tmp, "one", "benchmark_report.json"), "rb") as handle:
            first_bytes = handle.read()
        with open(os.path.join(tmp, "two", "benchmark_report.json"), "rb") as handle:
            second_bytes = handle.read()
        assert first_bytes == second_bytes
        assert first["provenance"]["catalog_snapshot_sha256"] == second["provenance"]["catalog_snapshot_sha256"]
        for artifact in ("benchmark_report.json", "benchmark_cells.csv", "benchmark_summary.md"):
            assert os.path.exists(os.path.join(tmp, "one", artifact))


def test_dry_run_accepts_explicit_transport() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = nb.run_benchmark(
            "dry_run",
            TASK_MANIFEST_PATH,
            None,
            tmp,
            max_total_requests=900,
            transport=nb.build_dry_run_transport(),
        )
        assert report["provenance"]["pricing_scenario_sha256"] is None
        assert report["evaluation"]["cheapest_worker_skip_reason"] == "no_pricing_scenario_supplied"


def test_live_run_fails_closed_without_credential() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(NotConfigured):
            nb.run_benchmark("live", TASK_MANIFEST_PATH, None, tmp, git_sha="abc", workflow_run_id="run-1")


def test_live_run_end_to_end_offline() -> None:
    register_credential(nb.NIM_CREDENTIAL_NAME, "nvapi-test-credential")
    original_validate = ModelClient._validate_provider
    original_send = ModelClient._send
    ModelClient._validate_provider = lambda self, agent: None
    ModelClient._send = lambda self, agent, payload: "stub live answer"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report = nb.run_benchmark(
                "live",
                TASK_MANIFEST_PATH,
                None,
                tmp,
                max_total_requests=900,
                git_sha="abc123",
                workflow_run_id="run-42",
                transport=nb.build_dry_run_transport(),
            )
    finally:
        ModelClient._validate_provider = original_validate
        ModelClient._send = original_send
    assert report["provenance"]["run_mode"] == "live"
    assert report["provenance"]["git_sha"] == "abc123"
    assert report["honesty_labels"]["actual_cost_basis"] == (
        "reviewed_nvidia_developer_program_hosted_endpoint_access"
    )
    assert report["request_budget"]["requests_spent"] <= 900
    assert "nvapi-test-credential" not in json.dumps(report)


def test_live_run_uses_default_transport_builder_when_none_given() -> None:
    register_credential(nb.NIM_CREDENTIAL_NAME, "nvapi-test-credential")
    original_builder = nb.build_default_transport
    nb.build_default_transport = lambda timeout_seconds: nb.build_dry_run_transport()
    original_validate = ModelClient._validate_provider
    original_send = ModelClient._send
    ModelClient._validate_provider = lambda self, agent: None
    ModelClient._send = lambda self, agent, payload: "stub live answer"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report = nb.run_benchmark(
                "live", TASK_MANIFEST_PATH, None, tmp,
                max_total_requests=900, git_sha="abc123", workflow_run_id="run-43",
            )
    finally:
        nb.build_default_transport = original_builder
        ModelClient._validate_provider = original_validate
        ModelClient._send = original_send
    assert report["provenance"]["workflow_run_id"] == "run-43"


# --------------------------------------------------------------------------
# CLI + bootstrap
# --------------------------------------------------------------------------


def test_bootstrap_live_credential_paths() -> None:
    from contextual_orchestrator.credentials import get_credential

    nb._bootstrap_live_credential()  # neither KV nor env: stays unset
    assert get_credential(nb.NIM_CREDENTIAL_NAME) is None
    os.environ[nb.NIM_CREDENTIAL_NAME] = "nvapi-from-env"
    try:
        nb._bootstrap_live_credential()  # env seeds the KV (bootstrap transport)
        assert get_credential(nb.NIM_CREDENTIAL_NAME) == "nvapi-from-env"
        os.environ[nb.NIM_CREDENTIAL_NAME] = "nvapi-different"
        nb._bootstrap_live_credential()  # existing KV value wins; no re-seed
        assert get_credential(nb.NIM_CREDENTIAL_NAME) == "nvapi-from-env"
    finally:
        os.environ.pop(nb.NIM_CREDENTIAL_NAME, None)


def test_cli_dry_run_succeeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = nb.run_benchmark_cli(
                [
                    "--dry-run",
                    "--task-manifest", TASK_MANIFEST_PATH,
                    "--pricing-scenario", PRICING_SCENARIO_PATH,
                    "--output-dir", tmp,
                    "--max-total-requests", "900",
                ]
            )
        assert exit_code == 0
        printed = json.loads(stdout.getvalue())
        assert printed["run_mode"] == "dry_run"
        assert printed["capability_summary"]["omni_capable"] == 1


def test_cli_fails_closed_on_missing_manifest() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = nb.run_benchmark_cli(["--dry-run", "--task-manifest", "does/not/exist.json"])
    assert exit_code == 1
    assert json.loads(stdout.getvalue())["benchmark_failed_closed"] is True


def test_cli_live_fails_closed_without_secret() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = nb.run_benchmark_cli(
            ["--task-manifest", TASK_MANIFEST_PATH, "--git-sha", "abc", "--workflow-run-id", "run-1"]
        )
    assert exit_code == 1
    assert json.loads(stdout.getvalue())["error_class"] == "NotConfigured"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
