"""Tests for issue #1106: owner-versioned review-pool admission contract.

The free review pool exposes typed catalog provenance so a leaf
caller can send only the gateway token plus ``model: orchestrator/free`` and
delete its own provider/model/credential preflight. Request-shaped admission
and live readiness require separate evidence.
"""

from __future__ import annotations

import json
from dataclasses import replace
import threading
from typing import get_type_hints
import urllib.error
import urllib.request

from jsonschema import validate

from contextual_orchestrator.api_contract import OPENAPI_SPEC
from contextual_orchestrator import CostRoutingCoordinator, InMemoryConfigStore
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend
from contextual_orchestrator.model_discovery import DiscoveredModel
from contextual_orchestrator import review_gateway
from contextual_orchestrator.orchestrator import TaskOrchestrator
from contextual_orchestrator.provider_errors import ProviderUpstreamError
from contextual_orchestrator.server import SecurityConfig, build_server

import pytest


@pytest.fixture(autouse=True)
def _fresh_backend():
    """Give each contract test an isolated in-memory credential registry."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _discovered(
    provider: str,
    model: str,
    credential: str,
    *,
    max_output_tokens: int | None = None,
    context_window: int | None = None,
) -> DiscoveredModel:
    """Build one explicitly evidenced, free, text-only chat candidate."""
    return DiscoveredModel(
        provider_name=provider,
        model_id=model,
        credential_name=credential,
        chat_base_url=f"https://{provider}.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0,
        completion_price_per_1k=0.0,
        is_free=True,
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        max_output_tokens=max_output_tokens,
        context_window=context_window,
    )


def test_versioned_contract_exposes_real_admission_provenance(monkeypatch):
    """The contract yields typed per-model eligibility evidence, not just a name."""
    discovered = [
        _discovered(
            "openrouter",
            "router-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=8192,
            context_window=131072,
        ),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret", "NVIDIA_NIM_API_KEY": "nim-secret"}
    )

    admissions = review_gateway.review_pool_admissions(orchestrator.agents)

    assert {admission.model_id for admission in admissions} == {
        "router-review",
        "nim-review",
    }
    assert {admission.provider_name for admission in admissions} == {
        "openrouter",
        "nvidia_nim",
    }
    assert {admission.credential_key for admission in admissions} == {
        "OPENROUTER_API_KEY",
        "NVIDIA_NIM_API_KEY",
    }
    assert all(
        admission.contract_version == review_gateway.REVIEW_READINESS_CONTRACT_VERSION
        for admission in admissions
    )
    router = next(a for a in admissions if a.model_id == "router-review")
    assert router.max_output_tokens == 8192
    assert router.context_window == 131072
    assert "cost:free" in router.tags
    assert "review" in router.tags


def test_admission_excludes_openai_source_even_when_discovered(monkeypatch):
    """Typed provenance never carries an OpenAI-sourced model into the pool."""
    discovered = [
        _discovered("openai", "gpt-review", "OPENAI_API_KEY"),
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "openai-secret", "OPENROUTER_API_KEY": "router-secret"}
    )

    admissions = review_gateway.review_pool_admissions(orchestrator.agents)

    assert [admission.model_id for admission in admissions] == ["router-review"]
    assert all(admission.provider_name != "openai" for admission in admissions)


def test_single_model_provenance_helper_matches_pool_projection():
    """The per-model helper agrees with the pool projection for one candidate."""
    model = _discovered(
        "openrouter",
        "router-review",
        "OPENROUTER_API_KEY",
        max_output_tokens=4096,
    )
    admission = review_gateway.review_model_admission(
        model, tags=("discovered", "review", "cost:free")
    )
    assert admission.model_id == "router-review"
    assert admission.provider_name == "openrouter"
    assert admission.credential_key == "OPENROUTER_API_KEY"
    assert admission.max_output_tokens == 4096
    assert admission.contract_version == review_gateway.REVIEW_READINESS_CONTRACT_VERSION


def test_client_imposes_no_fixed_global_output_cap(monkeypatch):
    """The gateway never injects a hidden fixed cap; each request resolves its
    own serving model's published ceiling (issue #1134 superseded the old
    single transport envelope)."""
    discovered = [
        _discovered(
            "openrouter",
            "small-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=4096,
        ),
        _discovered(
            "openrouter",
            "large-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=200000,
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    assert orchestrator.client.max_output_tokens is None
    assert (
        orchestrator.client.effective_max_output_tokens(
            next(a for a in orchestrator.agents if a.model == "large-review")
        )
        == 200000
    )


def test_pool_admission_preserves_each_published_ceiling(monkeypatch):
    """Per-model published ceilings survive as typed provenance, so a consumer
    never has to re-derive or impose its own token budget."""
    discovered = [
        _discovered(
            "openrouter",
            "small-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=4096,
        ),
        _discovered(
            "openrouter",
            "large-review",
            "OPENROUTER_API_KEY",
            max_output_tokens=200000,
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator(
        {"OPENROUTER_API_KEY": "router-secret"}
    )
    ceilings = {
        admission.model_id: admission.max_output_tokens
        for admission in review_gateway.review_pool_admissions(orchestrator.agents)
    }
    assert ceilings == {"small-review": 4096, "large-review": 200000}


def test_public_review_pool_admissions_type_hints_resolve():
    """The public admission contract exposes runtime-resolvable annotations."""
    hints = get_type_hints(review_gateway.review_pool_admissions)
    assert hints["agents"]
    assert hints["return"]


def test_review_pool_refuses_uncalibrated_allocation_before_provider_send(monkeypatch):
    """Catalog eligibility alone never authorizes a review allocation."""
    discovered = [
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        _discovered("nvidia_nim", "nim-review", "NVIDIA_NIM_API_KEY"),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret", "NVIDIA_NIM_API_KEY": "nim-secret",
    })
    sends: list[str] = []

    def forbid_send(*args, **kwargs):
        del args, kwargs
        sends.append("sent")
        raise AssertionError("provider transport must not be reached")

    monkeypatch.setattr(orchestrator.client, "chat", forbid_send)
    monkeypatch.setattr(orchestrator.client, "proxy_send", forbid_send)
    monkeypatch.setattr(orchestrator.client, "stream_chat", forbid_send)
    messages = [{"role": "user", "content": "Review this change"}]
    calls = (
        lambda: orchestrator.complete(messages, mode="route", model_name=TaskOrchestrator.FREE_MODEL),
        lambda: orchestrator.complete(messages, mode="conduct", model_name=TaskOrchestrator.FREE_MODEL),
        lambda: orchestrator.route_once(messages, model_name=TaskOrchestrator.FREE_MODEL),
        lambda: orchestrator.proxy_completion({
            "model": TaskOrchestrator.FREE_MODEL, "messages": messages,
        }),
        lambda: list(orchestrator.stream_route(
            messages, model_name=TaskOrchestrator.FREE_MODEL,
        )),
    )
    for call in calls:
        with pytest.raises(ProviderUpstreamError) as caught:
            call()
        assert caught.value.error_code == "allocation_evidence_unavailable"
        assert caught.value.client_status == 503
        assert caught.value.retryable is False
    assert sends == []


def test_review_allocation_failure_is_typed_at_http_boundary(monkeypatch):
    discovered = [_discovered("openrouter", "router-review", "OPENROUTER_API_KEY")]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret",
    })
    sends: list[str] = []

    def forbid_send(*args, **kwargs):
        del args, kwargs
        sends.append("sent")
        raise AssertionError("provider transport must not be reached")

    monkeypatch.setattr(orchestrator.client, "chat", forbid_send)
    monkeypatch.setattr(orchestrator.client, "proxy_send", forbid_send)
    monkeypatch.setattr(orchestrator.client, "stream_chat", forbid_send)
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token="review-test-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, body in (
            ("/v1/chat/completions", {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "review"}],
            }),
            ("/v1/responses", {
                "model": TaskOrchestrator.FREE_MODEL, "input": "review",
            }),
            ("/v1/chat/completions", {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": "review"}],
                "stream": True,
            }),
            ("/v1/responses", {
                "model": TaskOrchestrator.FREE_MODEL, "input": "review",
                "stream": True,
            }),
        ):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}{path}",
                data=json.dumps(body).encode(),
                headers={"content-type": "application/json", "authorization": "Bearer review-test-token"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
            with caught.value as response:
                assert response.code == 503
                payload = json.load(response)
            assert payload["error"]["code"] == "allocation_evidence_unavailable"
            assert payload["error"]["detail"]["retryable"] is False
            response_schema = OPENAPI_SPEC["paths"][path]["post"]["responses"]["503"]["content"]["application/json"]["schema"]
            validate(payload, {**response_schema, "components": OPENAPI_SPEC["components"]})
        for path, body in (
            ("/v1/chat/completions", {
                "model": "router-review",
                "messages": [{"role": "user", "content": "review"}],
            }),
            ("/v1/responses", {"model": "router-review", "input": "review"}),
            ("/v1/chat/completions", {
                "model": "router-review",
                "messages": [{"role": "user", "content": "review"}],
                "stream": True,
            }),
        ):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}{path}",
                data=json.dumps(body).encode(),
                headers={"content-type": "application/json", "authorization": "Bearer review-test-token"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
            with caught.value as response:
                assert response.code == 400
                payload = json.load(response)
            assert payload["error"]["code"] == "review_model_not_allowed"
            assert payload["error"]["detail"]["retryable"] is False
            response_schema = OPENAPI_SPEC["paths"][path]["post"]["responses"]["400"]["content"]["application/json"]["schema"]
            validate(payload, {**response_schema, "components": OPENAPI_SPEC["components"]})
        assert sends == []
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_review_gateway_rejects_explicit_model_before_provider_send(monkeypatch):
    """A caller cannot bypass the free-pool allocation gate by naming a member."""
    discovered = [_discovered("openrouter", "router-review", "OPENROUTER_API_KEY")]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret",
    })
    sends: list[str] = []

    def forbid_send(*args, **kwargs):
        del args, kwargs
        sends.append("sent")
        raise AssertionError("provider transport must not be reached")

    monkeypatch.setattr(orchestrator.client, "chat", forbid_send)
    monkeypatch.setattr(orchestrator.client, "proxy_send", forbid_send)
    monkeypatch.setattr(orchestrator.client, "proxy_send_once", forbid_send)
    for call in (
        lambda: orchestrator.complete(
            [{"role": "user", "content": "review"}],
            mode="route",
            model_name="router-review",
        ),
        lambda: orchestrator.proxy_completion({
            "model": "router-review",
            "messages": [{"role": "user", "content": "review"}],
        }),
        lambda: orchestrator.route_once(
            [{"role": "user", "content": "review"}], model_name="router-review",
        ),
        lambda: orchestrator.conduct(
            [{"role": "user", "content": "review"}], model_name="router-review",
        ),
        lambda: list(orchestrator.stream_route(
            [{"role": "user", "content": "review"}], model_name="router-review",
        )),
    ):
        with pytest.raises(ProviderUpstreamError) as caught:
            call()
        assert caught.value.error_code == "review_model_not_allowed"
        assert caught.value.client_status == 400
        assert caught.value.retryable is False
    assert sends == []


def test_review_gateway_rejects_capability_model_before_provider_send(monkeypatch):
    """A chat-capable member cannot bypass review allocation via another API."""
    discovered = [replace(
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        capabilities=("chat", "image"),
        output_modalities=("text", "image"),
    )]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret",
    })
    sends: list[str] = []

    def fake_send(*args, **kwargs):
        del args, kwargs
        sends.append("sent")
        return {"data": [{"url": "https://example.com/synthetic.png"}]}

    monkeypatch.setattr(orchestrator.client, "proxy_send", fake_send)
    with pytest.raises(ProviderUpstreamError) as caught:
        orchestrator.proxy_capability(
            {"model": "router-review", "prompt": "synthetic image"},
            capability="image",
            endpoint="images/generations",
        )
    assert caught.value.error_code == "review_model_not_allowed"
    assert caught.value.client_status == 400
    assert caught.value.retryable is False
    assert sends == []


def test_review_gateway_rerank_allocation_is_typed_and_never_sends(monkeypatch):
    """Direct and HTTP capability routes share the review allocation gate."""
    discovered = [replace(
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        capabilities=("chat", "rerank"),
    )]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret",
    })
    sends: list[str] = []
    monkeypatch.setattr(
        orchestrator.client, "proxy_send", lambda *args, **kwargs: sends.append("sent"),
    )
    server = build_server(
        orchestrator, port=0, security=SecurityConfig(auth_token="review-test-token"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for model, status, code in (
            ("router-review", 400, "review_model_not_allowed"),
            (TaskOrchestrator.FREE_MODEL, 503, "allocation_evidence_unavailable"),
            (None, 400, "review_model_not_allowed"),
        ):
            body = {"query": "synthetic", "documents": ["synthetic"]}
            if model is not None:
                body["model"] = model
            with pytest.raises(ProviderUpstreamError) as caught:
                orchestrator.proxy_capability(body, capability="rerank", endpoint="rerank")
            assert (caught.value.client_status, caught.value.error_code, caught.value.retryable) == (
                status, code, False,
            )
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/v1/rerank",
                data=json.dumps(body).encode(),
                headers={"content-type": "application/json", "authorization": "Bearer review-test-token"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request, timeout=5)
            with rejected.value as response:
                assert response.code == status
                payload = json.load(response)
            assert payload["error"]["code"] == code
            assert payload["error"]["detail"]["retryable"] is False
        assert sends == []
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_review_gateway_embedding_batch_rejects_before_backend_submission(monkeypatch):
    """The direct batch coordinator cannot bypass review allocation."""
    discovered = [replace(
        _discovered("openrouter", "router-review", "OPENROUTER_API_KEY"),
        capabilities=("chat", "embedding"),
    )]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "synthetic",
    })
    submissions: list[str] = []

    class Backend:
        name = "synthetic"

        def submit(self, requests, metadata=None):
            del requests, metadata
            submissions.append("sent")
            raise AssertionError("embedding backend must not be reached")

    class Counter:
        def count_text(self, text, model=""):
            del model
            return len(text.split())

    coordinator = CostRoutingCoordinator(
        orchestrator,
        InMemoryConfigStore(),
        embedding_batch_backend=Backend(),
        embedding_token_counter=Counter(),
    )
    for model, status, code in (
        ("router-review", 400, "review_model_not_allowed"),
        (TaskOrchestrator.FREE_MODEL, 503, "allocation_evidence_unavailable"),
    ):
        with pytest.raises(ProviderUpstreamError) as caught:
            coordinator.submit_embeddings_batch(["synthetic"], model=model)
        assert (caught.value.client_status, caught.value.error_code, caught.value.retryable) == (
            status, code, False,
        )
    assert submissions == []


def test_image_review_request_without_vision_evidence_stops_before_send(monkeypatch):
    """Text chat readiness cannot authorize an image-bearing review request."""
    discovered = [_discovered("openrouter", "text-review", "OPENROUTER_API_KEY")]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret",
    })
    # Isolate request capability admission from the separate allocation gate.
    orchestrator._review_allocation_evidence_required = False
    sends: list[str] = []

    def forbid_send(*args, **kwargs):
        del args, kwargs
        sends.append("sent")
        raise AssertionError("provider send must not occur")

    monkeypatch.setattr(orchestrator.client, "chat", forbid_send)
    monkeypatch.setattr(orchestrator.client, "stream_chat", forbid_send)
    monkeypatch.setattr(orchestrator.client, "proxy_send_once", forbid_send)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Review this image"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
    ]}]
    calls = (
        lambda: orchestrator.complete(messages, mode="route", model_name=TaskOrchestrator.FREE_MODEL),
        lambda: orchestrator.proxy_completion({
            "model": TaskOrchestrator.FREE_MODEL, "messages": messages,
        }),
        lambda: list(orchestrator.stream_route(
            messages, model_name=TaskOrchestrator.FREE_MODEL,
        )),
    )
    for call in calls:
        with pytest.raises(ProviderUpstreamError) as caught:
            call()
        assert caught.value.error_code == "request_capability_unavailable"
        assert caught.value.client_status == 503
        assert caught.value.detail["capability"] == "input:image"
    assert sends == []


def test_image_review_stream_selects_only_proven_vision_candidate(monkeypatch):
    """A higher-priority text model cannot receive a review image."""
    discovered = [
        _discovered("openrouter", "text-review", "OPENROUTER_API_KEY"),
        replace(
            _discovered("nvidia_nim", "vision-review", "NVIDIA_NIM_API_KEY"),
            capabilities=("chat", "vision"),
            input_modalities=(),
        ),
    ]
    monkeypatch.setattr(review_gateway, "discover_all_models", lambda: (discovered, []))
    orchestrator = review_gateway.build_review_orchestrator({
        "OPENROUTER_API_KEY": "router-secret", "NVIDIA_NIM_API_KEY": "nim-secret",
    })
    # Isolate request capability admission from the separate allocation gate.
    orchestrator._review_allocation_evidence_required = False
    orchestrator.agents = [
        replace(agent, priority=10) if agent.model == "text-review" else agent
        for agent in orchestrator.agents
    ]
    calls: list[str] = []

    def stream_chat(agent, messages, **kwargs):
        del messages, kwargs
        calls.append(agent.model)
        yield "served"

    monkeypatch.setattr(orchestrator.client, "stream_chat", stream_chat)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Review this image"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
    ]}]

    assert "".join(orchestrator.stream_route(
        messages, model_name=TaskOrchestrator.FREE_MODEL,
    )) == "served"
    assert calls == ["vision-review"]

    def proxy_send_once(agent, endpoint, payload):
        del endpoint, payload
        calls.append(agent.model)
        return {
            "id": "image-review", "object": "chat.completion", "model": agent.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "served"},
                         "finish_reason": "stop"}],
        }

    monkeypatch.setattr(orchestrator.client, "proxy_send_once", proxy_send_once)
    result = orchestrator.proxy_completion({
        "model": TaskOrchestrator.FREE_MODEL, "messages": messages,
    })
    assert result["model"] == "vision-review"
    assert calls == ["vision-review", "vision-review"]
