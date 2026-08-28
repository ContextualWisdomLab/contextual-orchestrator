"""Boundary coverage for model discovery transport and selection guards.

Exercises provider-failure classification (HTTP errors, timeouts, invalid
payloads, insecure URLs), degenerate catalog rows, hostile price-book
backends, and empty/zero-limit bootstrap selections that the ordinary
happy-path tests cannot reach.
"""

from __future__ import annotations

import ssl
import urllib.error
from dataclasses import replace
from unittest.mock import patch

import pytest

from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderDiscoveryError,
    ProviderModelSource,
    _fetch_json,
    _fetch_configured_gateway_json,
    MAX_DISCOVERY_RESPONSE_BYTES,
    _provider_discovery_error_code,
    _valid_price_component,
    agent_from_discovered,
    discover_provider_models,
    refresh_price_book,
    select_bootstrap_discovered_agents,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)
from tests.test_model_discovery import (
    BYTEZ_SOURCE,
    OPENAI_SOURCE,
    OPENROUTER_SOURCE,
    _Response,
)


@pytest.fixture(autouse=True)
def _fresh_credentials():
    """Isolate the KV credential registry exactly like the canonical module."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def test_http_error_maps_to_stable_status_code_without_provider_text() -> None:
    """An HTTP 429 from a provider becomes ``http_status_429`` evidence."""
    register_credential("OPENAI_API_KEY", "sk-openai")

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 429, "rate limited", hdrs=None, fp=None
        )

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        side_effect=urlopen,
    ):
        with pytest.raises(ProviderDiscoveryError) as excinfo:
            discover_provider_models(OPENAI_SOURCE)
    assert excinfo.value.error_code == "http_status_429"
    assert "rate limited" not in str(excinfo.value)


def test_timeout_maps_to_stable_timeout_code() -> None:
    """A socket-level timeout never leaks as an unclassified failure."""
    register_credential("OPENAI_API_KEY", "sk-openai")

    def urlopen(request, timeout=None):
        raise TimeoutError("timed out")

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        side_effect=urlopen,
    ):
        with pytest.raises(ProviderDiscoveryError) as excinfo:
            discover_provider_models(OPENAI_SOURCE)
    assert excinfo.value.error_code == "timeout"


def test_configured_gateway_uses_pinned_bounded_provider_transport() -> None:
    response = _Response({"data": []})
    reads = []
    original_read = response.read

    def bounded_read(size=-1):
        reads.append(size)
        return original_read()

    response.read = bounded_read
    with (
        patch(
            "contextual_orchestrator.model_discovery.ModelClient._validate_provider",
            return_value=(2, ("203.0.113.10", 443)),
        ) as validate,
        patch(
            "contextual_orchestrator.model_discovery.ModelClient._open_provider",
            return_value=response,
        ) as opened,
    ):
        assert _fetch_configured_gateway_json(
            "https://gateway.example/v1/models",
            api_key="secret",
            auth_scheme="Bearer",
            timeout=1,
        ) == {"data": []}
    validate.assert_called_once()
    assert validate.call_args.args[0].credential_key == "LLM_GATEWAY_API_KEY"
    request = opened.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer secret"
    assert reads == [MAX_DISCOVERY_RESPONSE_BYTES + 1]


def test_configured_gateway_discovery_keeps_combined_system_trust() -> None:
    """Configured discovery uses the client's system-plus-certifi trust default."""
    with patch(
        "contextual_orchestrator.model_discovery.ModelClient",
        side_effect=RuntimeError("stop after construction"),
    ) as client:
        with pytest.raises(RuntimeError, match="stop after construction"):
            _fetch_configured_gateway_json(
                "https://gateway.example/v1/models",
                api_key="secret",
                auth_scheme="Bearer",
                timeout=1,
            )
    assert client.call_args.kwargs.get("ca_bundle") is None


def test_fixed_provider_ca_failure_retries_with_certifi_verification() -> None:
    calls = []

    def urlopen(request, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError(1, "unable to get local issuer")
            )
        return _Response({"data": []})

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        side_effect=urlopen,
    ):
        assert _fetch_json("https://provider.example/v1/models", timeout=1) == {
            "data": []
        }
    assert "context" not in calls[0]
    assert calls[1]["context"].verify_mode == ssl.CERT_REQUIRED
    assert calls[1]["context"].check_hostname is True


def test_malformed_json_maps_to_invalid_response_code() -> None:
    """A non-JSON provider body is invalid_response, not a crash."""
    register_credential("OPENAI_API_KEY", "sk-openai")

    class GarbageResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b"<html>not json</html>"

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=GarbageResponse(),
    ):
        with pytest.raises(ProviderDiscoveryError) as excinfo:
            discover_provider_models(OPENAI_SOURCE)
    assert excinfo.value.error_code == "invalid_response"


def test_insecure_discovery_url_is_refused_before_any_network_call() -> None:
    """An http:// list URL is refused before any request leaves the process."""
    source = ProviderModelSource(
        provider_name="insecure_provider",
        credential_name="INSECURE_API_KEY",
        list_url="http://insecure.example/v1/models",
        chat_base_url="https://insecure.example/v1",
    )
    register_credential("INSECURE_API_KEY", "secret-value")
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen"
    ) as urlopen:
        with pytest.raises(ProviderDiscoveryError) as excinfo:
            discover_provider_models(source)
    urlopen.assert_not_called()
    assert excinfo.value.error_code == "invalid_response"

    with pytest.raises(ValueError, match="refusing non-https"):
        _fetch_json(
            "ftp://insecure.example/models",
            api_key="k",
            auth_scheme="Bearer",
            timeout=1.0,
        )


def test_unclassified_provider_failure_fails_loudly() -> None:
    """If the caller's catch tuple drifts, the mapper refuses to guess a code."""
    with pytest.raises(AssertionError, match="unclassified provider discovery"):
        _provider_discovery_error_code(RuntimeError("not transport related"))


def test_openai_rows_that_are_not_objects_are_skipped() -> None:
    """Non-dict rows in an OpenAI-style payload cannot crash parsing."""
    register_credential("OPENROUTER_API_KEY", "sk-router")
    payload = {"data": ["junk-string", 42, None, {"id": "meta/llama-3.3"}]}
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)
    assert [model.model_id for model in discovered] == ["meta/llama-3.3"]


def test_bytez_rows_that_are_not_objects_are_skipped() -> None:
    """Non-dict rows in a Bytez payload cannot crash parsing."""
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    payload = {"output": [7, "bad", {"modelId": "0-hero/Matter-0.1-Slim-7B-C"}]}
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(BYTEZ_SOURCE)
    assert [model.model_id for model in discovered] == [
        "0-hero/Matter-0.1-Slim-7B-C"
    ]


def test_valid_price_component_rejects_overflowing_integers() -> None:
    """An int too large for float is rejected, not treated as infinite price."""
    assert _valid_price_component(10**500) is False
    assert _valid_price_component(True) is False
    assert _valid_price_component("0.5") is False


class _HostileGetPriceBook:
    """Price book whose backend raises on every lookup."""

    default_currency = "USD"

    def get_price(self, provider: str, model: str):
        raise TypeError("price book storage misconfigured")


class _HostileComputeBook:
    """Price book returning a valid entry whose cost computation explodes."""

    default_currency = "USD"

    def get_price(self, provider: str, model: str):
        return PriceEntry(provider, model, 0.01, 0.02, "usd")

    def compute_cost(self, provider: str, model: str, prompt: int, completion: int):
        raise OverflowError("cost arithmetic exploded")


class _LyingComputeBook:
    """Price book computing a cost its own entry cannot justify."""

    default_currency = "USD"

    def get_price(self, provider: str, model: str):
        return PriceEntry(provider, model, 0.01, 0.02, "usd")

    def compute_cost(self, provider: str, model: str, prompt: int, completion: int):
        return float("inf"), "EUR"


def _chat_model(provider_name: str, model_id: str) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=provider_name,
        model_id=model_id,
        credential_name=f"{provider_name.upper()}_API_KEY",
        chat_base_url=f"https://{provider_name}.example/v1",
        auth_scheme="Bearer",
    )


@pytest.mark.parametrize(
    "book",
    [_HostileGetPriceBook(), _HostileComputeBook(), _LyingComputeBook()],
    ids=["get_price_raises", "compute_cost_raises", "lying_compute_cost"],
)
def test_hostile_price_books_degrade_to_unknown_ranking(book) -> None:
    """A broken ranking backend must not crash bootstrap or fabricate prices."""
    priced = _chat_model("openrouter", "priced-model")
    other = _chat_model("bytez", "other-model")

    cheapest = select_cheapest_discovered_agent([priced, other], book)
    assert cheapest is not None

    top = select_top_n_cheapest_discovered_agents([priced, other], book, 2)
    assert [m.model_id for m in top] == sorted(["priced-model", "other-model"])

    bootstrapped = select_bootstrap_discovered_agents([priced, other], book, 2)
    assert len(bootstrapped) == 2


def test_refresh_price_book_writes_complete_evidence_and_skips_overflow() -> None:
    """Complete comparable rows are written; overflowing ints stay unknown."""
    book = PriceBook(InMemoryConfigStore())
    good = DiscoveredModel(
        provider_name="openrouter",
        model_id="good-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.5,
        completion_price_per_1k=1.5,
        currency_code="usd",
    )
    overflow = DiscoveredModel(
        provider_name="openrouter",
        model_id="overflow-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=10**500,
        completion_price_per_1k=10**500,
        currency_code="USD",
    )
    partial = DiscoveredModel(
        provider_name="openrouter",
        model_id="partial-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.5,
        completion_price_per_1k=None,
        currency_code="USD",
    )
    guard_model = DiscoveredModel(
        provider_name="openrouter",
        model_id="safety-guard-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.example/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.1,
        completion_price_per_1k=0.1,
        currency_code="USD",
    )
    written = refresh_price_book([good, overflow, partial, guard_model], book)
    assert written == 1
    assert book.get_price("openrouter", "good-model") is not None
    assert book.get_price("openrouter", "overflow-model") is None
    assert book.get_price("openrouter", "safety-guard-model") is None
    assert book.get_price("openrouter", "partial-model") is None


def test_bootstrap_rejects_non_positive_limits_and_empty_catalogs() -> None:
    """Zero/negative limits and chat-ineligible catalogs select nothing."""
    book = PriceBook(InMemoryConfigStore())
    assert select_bootstrap_discovered_agents([], book, 3) == []
    assert select_bootstrap_discovered_agents([_chat_model("a", "m")], book, 0) == []
    assert select_bootstrap_discovered_agents([_chat_model("a", "m")], book, -2) == []
    ineligible = [
        DiscoveredModel(
            provider_name="openrouter",
            model_id="text-embedding-ada-002",
            credential_name="OPENROUTER_API_KEY",
            chat_base_url="https://openrouter.example/v1",
            auth_scheme="Bearer",
        ),
        DiscoveredModel(
            provider_name="openrouter",
            model_id="shieldgemma-9b",
            credential_name="OPENROUTER_API_KEY",
            chat_base_url="https://openrouter.example/v1",
            auth_scheme="Bearer",
        ),
    ]
    assert select_bootstrap_discovered_agents(ineligible, book, 5) == []
    assert select_top_n_cheapest_discovered_agents(ineligible, book, 5) == []
    assert select_cheapest_discovered_agent([], book) is None


def test_bootstrap_rejects_explicit_non_chat_capabilities() -> None:
    """A video-looking catalog row cannot enter the chat pool by identifier fallback."""
    book = PriceBook(InMemoryConfigStore())
    video = replace(
        _chat_model("openrouter", "vendor-video-model"),
        capabilities=("video",),
        output_modalities=("video",),
    )

    assert select_bootstrap_discovered_agents([video], book, 1) == []
    assert "video" in agent_from_discovered(video).tags


def test_bootstrap_fills_remainder_from_deferred_same_family_models() -> None:
    """When one family dominates, deferred models fill remaining capacity."""
    book = PriceBook(InMemoryConfigStore())
    solo = _chat_model("bytez", "solo-model")
    family = [_chat_model("nvidia_nim", f"family-model-{i}") for i in range(3)]
    selected = select_bootstrap_discovered_agents([*family, solo], book, 4)
    # First pass admits one nvidia_nim and bytez; remainder comes from deferred.
    assert len(selected) == 4
    assert {m.provider_name for m in selected} == {"nvidia_nim", "bytez"}
    assert {selected[0].provider_name, selected[1].provider_name} == {
        "bytez",
        "nvidia_nim",
    }
    assert all(m.provider_name == "nvidia_nim" for m in selected[2:])


def test_bootstrap_early_return_stops_at_limit_within_loop() -> None:
    """A limit below the distinct-family count returns without a second pass."""
    book = PriceBook(InMemoryConfigStore())
    models = [
        _chat_model("openai", "openai-model"),
        _chat_model("openrouter", "openrouter-model"),
        _chat_model("bytez", "bytez-model"),
    ]
    selected = select_bootstrap_discovered_agents(models, book, 2)
    # Unpriced ties rank by provider name: bytez < openai < openrouter.
    assert len(selected) == 2
    assert [m.provider_name for m in selected] == ["bytez", "openai"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
