"""Model discovery: KV-driven provider model listing, offline via mocked HTTP."""

from __future__ import annotations

import io
import json
import logging
import sys
import urllib.error
import urllib.parse
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import AUTH_SCHEME_RAW_TOKEN  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.cost_ledger import PriceBook  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    PROVIDER_MODEL_SOURCES,
    DiscoveredModel,
    ModelUnitPrice,
    ProviderDiscoveryError,
    ProviderModelSource,
    _MODELS_DEV_FETCH_ATTEMPTS,
    _deduplicate_discovered_models,
    _fetch_json,
    _merge_configured_gateway_metadata,
    _merge_openrouter_provider_privacy,
    _merge_openrouter_zdr_metadata,
    _price_per_1k,
    _parse_openai_compatible,
    agent_from_discovered,
    agent_id_for,
    discover_all_models,
    discover_provider_models,
    free_discovered_models,
    general_free_serving_candidates,
    openrouter_paid_inference_available,
    refresh_price_book,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)


def test_openrouter_zdr_metadata_covers_paid_and_free_models() -> None:
    payload = {"data": [{"id": "paid/private"}, {"id": "free/training"}]}

    merged = _merge_openrouter_zdr_metadata(
        payload, {"data": [{"model_id": "paid/private"}]}
    )

    assert [row["supports_zero_data_retention"] for row in merged["data"]] == [True, False]


def test_openrouter_empty_zdr_inventory_keeps_support_unknown() -> None:
    payload = {"data": [{"id": "paid/private"}]}

    merged = _merge_openrouter_zdr_metadata(payload, {"data": []})

    assert "supports_zero_data_retention" not in merged["data"][0]


def test_openrouter_provider_privacy_preserves_terms_and_withholds_mixed_claims() -> None:
    payload = {"data": [{"id": "free/model"}]}
    providers = {
        "data": [
            {
                "slug": "private",
                "dataPolicy": {
                    "training": False,
                    "retainsPrompts": False,
                    "privacyPolicyURL": "https://private.example/privacy",
                },
            },
            {
                "slug": "training",
                "dataPolicy": {
                    "training": True,
                    "retainsPrompts": True,
                    "termsOfServiceURL": "https://training.example/terms",
                },
            },
        ]
    }

    merged = _merge_openrouter_provider_privacy(
        payload,
        providers,
        {"free/model": {"endpoints": [{"tag": "private"}, {"tag": "training"}]}},
    )

    assert merged["data"][0] == {
        "id": "free/model",
        "privacy_policy_urls": [
            "https://private.example/privacy",
            "https://training.example/terms",
        ],
    }


def test_openrouter_provider_privacy_requires_complete_safe_consensus() -> None:
    payload = {"data": [{"id": "free/model"}]}
    providers = {
        "data": [
            {
                "slug": "private",
                "dataPolicy": {"training": False, "retainsPrompts": False},
            }
        ]
    }

    merged = _merge_openrouter_provider_privacy(
        payload,
        providers,
        {"free/model": {"endpoints": [{"tag": "private"}]}},
    )

    assert merged["data"][0]["supports_no_training"] is True
    assert merged["data"][0]["supports_no_prompt_retention"] is True


def test_configured_gateway_withholds_conflicting_or_incomplete_prices() -> None:
    """Logical-model pricing requires complete consensus across deployments."""
    payload = {
        "data": [
            {
                "id": "shared-model",
                "pricing": {"prompt": 0, "completion": 0},
                "architecture": {"output_modalities": ["text", "embedding"]},
            }
        ]
    }
    metadata = {
        "data": [
            {
                "model_name": "shared-model",
                "model_info": {
                    "mode": "chat",
                    "input_cost_per_token": 0.000001,
                    "output_cost_per_token": 0.000002,
                    "supports_no_training": True,
                },
            },
            {
                "model_name": "shared-model",
                "model_info": {
                    "mode": "chat",
                    "input_cost_per_token": {"invalid": True},
                    "output_cost_per_token": 0.000002,
                    "supports_no_training": False,
                },
            },
        ]
    }

    merged = _merge_configured_gateway_metadata(payload, metadata)

    assert "pricing" not in merged["data"][0]
    assert "supports_no_training" not in merged["data"][0]
    assert merged["data"][0]["architecture"]["output_modalities"] == ["text"]


def test_configured_gateway_preserves_consensus_privacy_evidence() -> None:
    payload = {"data": [{"id": "free-model"}]}
    detail = {
        "model_name": "free-model",
        "model_info": {
            "mode": "chat",
            "input_cost_per_token": 0,
            "output_cost_per_token": 0,
            "supports_zero_data_retention": True,
            "supports_no_training": True,
            "supports_no_prompt_retention": True,
            "privacy_policy_url": "https://provider.example/privacy",
        },
    }

    merged = _merge_configured_gateway_metadata(payload, {"data": [detail, detail]})

    assert merged["data"][0]["supports_zero_data_retention"] is True
    assert merged["data"][0]["supports_no_training"] is True
    assert merged["data"][0]["supports_no_prompt_retention"] is True
    assert merged["data"][0]["privacy_policy_urls"] == [
        "https://provider.example/privacy"
    ]


def test_configured_gateway_keeps_ambiguous_privacy_strings_unknown() -> None:
    """Only explicit boolean strings can become provider privacy evidence."""
    payload = {"data": [{"id": "chat-model"}]}
    metadata = {
        "data": [
            {
                "model_name": "chat-model",
                "model_info": {"supports_zero_data_retention": "unknown"},
            }
        ]
    }

    merged = _merge_configured_gateway_metadata(payload, metadata)

    assert "supports_zero_data_retention" not in merged["data"][0]


def test_configured_gateway_preserves_only_consensus_unit_prices() -> None:
    """Official non-token units survive only whole-deployment consensus."""
    payload = {"data": [{"id": "image-model"}, {"id": "mixed-model"}]}
    agreed = {"model_name": "image-model", "model_info": {
        "mode": "image_generation", "output_cost_per_image": 0.04,
        "output_cost_per_second": 0.01,
    }}
    metadata = {"data": [agreed, agreed,
        {"model_name": "mixed-model", "model_info": {"mode": "video_generation", "output_cost_per_video_per_second": 0.2}},
        {"model_name": "mixed-model", "model_info": {"mode": "video_generation", "output_cost_per_video_per_second": 0.3}},
    ]}

    merged = _merge_configured_gateway_metadata(payload, metadata)

    assert merged["data"][0]["unit_pricing"] == {
        "output_cost_per_image": 0.04, "output_cost_per_second": 0.01,
    }
    assert "unit_pricing" not in merged["data"][1]

    source = ProviderModelSource(
        provider_name="gateway", credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example/v1/models",
        chat_base_url="https://gateway.example/v1",
        capabilities=("image",),
    )
    discovered = _parse_openai_compatible(merged, source)
    assert discovered[0].unit_prices == (
        ModelUnitPrice("output_cost_per_image", 0.04),
        ModelUnitPrice("output_cost_per_second", 0.01),
    )


def test_duplicate_discovery_withholds_conflicting_price_and_privacy_evidence() -> None:
    """Ambiguous duplicate rows must not preserve unverified price/privacy fields."""
    discovered = _deduplicate_discovered_models(
        [
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_A",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                prompt_price_per_1k=1.0,
                completion_price_per_1k=2.0,
                unit_prices=(ModelUnitPrice("output_cost_per_image", 0.0),),
                is_free=True,
                supports_zero_data_retention=True,
                supports_no_training=True,
                supports_no_prompt_retention=True,
            ),
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_A",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                prompt_price_per_1k=1.0,
                completion_price_per_1k=2.0,
                unit_prices=(ModelUnitPrice("output_cost_per_image", 0.1),),
                is_free=False,
                supports_zero_data_retention=False,
                supports_no_training=False,
                supports_no_prompt_retention=False,
            ),
        ]
    )

    assert len(discovered) == 1
    assert discovered[0].prompt_price_per_1k is None
    assert discovered[0].completion_price_per_1k is None
    assert discovered[0].unit_prices == ()
    assert discovered[0].is_free is False
    assert discovered[0].supports_zero_data_retention is None
    assert discovered[0].supports_no_training is None
    assert discovered[0].supports_no_prompt_retention is None
    assert discovered[0].zdr_capable is False


def test_duplicate_discovery_withholds_conflicting_zdr_capability() -> None:
    """Conflicting duplicate rows must not preserve a positive ZDR route tag."""
    discovered = _deduplicate_discovered_models(
        [
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_A",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                zdr_capable=True,
            ),
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_A",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                zdr_capable=False,
            ),
        ]
    )

    assert len(discovered) == 1
    assert discovered[0].zdr_capable is False


def test_same_provider_model_under_different_credentials_remains_independent() -> None:
    """Credential accounts may expose different evidence for the same model id."""
    discovered = _deduplicate_discovered_models(
        [
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_A",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                is_free=True,
            ),
            DiscoveredModel(
                provider_name="gateway",
                model_id="shared-model",
                credential_name="KEY_B",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                is_free=False,
            ),
        ]
    )

    assert [(model.credential_name, model.is_free) for model in discovered] == [
        ("KEY_A", True),
        ("KEY_B", False),
    ]


def test_discovery_debug_log_identifies_account_without_secret(caplog) -> None:
    """Verbose diagnostics expose account progress but never credential values."""
    register_credential("OPENAI_API_KEY", "secret-value-must-not-appear")
    with (
        caplog.at_level("DEBUG", logger="contextual_orchestrator.model_discovery"),
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            return_value=_Response({"data": [{"id": "gpt-test"}]}),
        ),
    ):
        discover_provider_models(OPENAI_SOURCE, models_dev_metadata=None)

    assert "account=openai" in caplog.text
    assert "OPENAI_API_KEY" not in caplog.text
    assert "model_count=1" in caplog.text
    assert "secret-value-must-not-appear" not in caplog.text


def test_configured_gateway_withholds_heterogeneous_capabilities() -> None:
    payload = {
        "data": [
            {
                "id": "shared-model",
                "architecture": {"output_modalities": ["text", "embedding"]},
            }
        ]
    }
    metadata = {
        "data": [
            {"model_name": "shared-model", "model_info": {"mode": "chat"}},
            {"model_name": "shared-model", "model_info": {"mode": "embedding"}},
        ]
    }
    merged = _merge_configured_gateway_metadata(payload, metadata)
    assert "architecture" not in merged["data"][0]


def test_openai_bare_list_promotes_transport_compatible_ids_to_chat() -> None:
    """A metadata-free listing still discovers chat, never embedding siblings.

    A generic OpenAI-compatible gateway (e.g. LiteLLM) often returns only an
    ``id`` per row. The identifier that passes the ordinary chat transport gate
    must receive the same ``chat`` capability the rest of the pool advertises;
    otherwise runtime auto-discovery silently drops chat deployments while
    embedding deployments that happen to carry richer metadata survive.
    """
    discovered = _parse_openai_compatible(
        {"data": [
            {"id": "gpt-4o"},
            {"id": "claude-3-5-sonnet"},
            {"id": "text-embedding-3-large"},
        ]},
        OPENAI_SOURCE,
    )
    by_id = {model.model_id: model for model in discovered}
    assert by_id["gpt-4o"].capabilities == ("chat",)
    assert by_id["claude-3-5-sonnet"].capabilities == ("chat",)
    assert "text-embedding-3-large" not in by_id


def test_openai_parse_preserves_explicit_capability_evidence() -> None:
    """A metadata-bearing listing keeps its provider-declared capabilities."""
    discovered = _parse_openai_compatible(
        {
            "data": [
                {
                    "id": "chat-model-xl",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                },
                {
                    "id": "rerank-model",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["rerank"],
                    },
                },
            ]
        },
        OPENAI_SOURCE,
    )
    by_id = {model.model_id: model for model in discovered}
    assert "chat" in by_id["chat-model-xl"].capabilities
    assert by_id["rerank-model"].capabilities == ("rerank",)


def test_configured_gateway_preserves_litellm_endpoint_modalities() -> None:
    payload = {
        "data": [
            {"id": "responses-model"},
            {"id": "completion-model"},
            {"id": "embedding-model"},
            {"id": "image-model"},
            {"id": "speech-model"},
            {"id": "transcription-model"},
            {"id": "video-model"},
            {"id": "rerank-model"},
            {"id": "moderation-model"},
        ]
    }
    metadata = {
        "data": [
            {"model_name": "responses-model", "model_info": {"mode": "responses"}},
            {
                "model_name": "completion-model",
                "model_info": {"mode": "completion"},
            },
            {
                "model_name": "embedding-model",
                "model_info": {"mode": "embedding"},
            },
            {
                "model_name": "image-model",
                "model_info": {"mode": "image_generation"},
            },
            {"model_name": "speech-model", "model_info": {"mode": "audio_speech"}},
            {
                "model_name": "transcription-model",
                "model_info": {"mode": "audio_transcription"},
            },
            {
                "model_name": "video-model",
                "model_info": {
                    "mode": "video_generation",
                    "supported_modalities": ["text", "image"],
                    "supported_output_modalities": ["video"],
                },
            },
            {"model_name": "rerank-model", "model_info": {"mode": "rerank"}},
            {
                "model_name": "moderation-model",
                "model_info": {"mode": "moderation"},
            },
        ]
    }

    merged = _merge_configured_gateway_metadata(payload, metadata)

    assert [row["architecture"] for row in merged["data"]] == [
        {"input_modalities": ["text"], "output_modalities": ["text", "responses"]},
        {"input_modalities": ["text"], "output_modalities": ["text", "completion"]},
        {"input_modalities": ["text"], "output_modalities": ["embedding"]},
        {"input_modalities": ["text"], "output_modalities": ["image"]},
        {"input_modalities": ["text"], "output_modalities": ["speech"]},
        {"input_modalities": ["audio"], "output_modalities": ["transcription"]},
        {"input_modalities": ["text", "image"], "output_modalities": ["video"]},
        {"input_modalities": ["text"], "output_modalities": ["rerank"]},
        {"input_modalities": [], "output_modalities": ["moderation"]},
    ]


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amt: int | None = None) -> bytes:
        # amt mirrors http.client.HTTPResponse.read(amt): _fetch_json reads the
        # full body (amt=None) while _fetch_json_same_host_https caps it to
        # enforce MAX_DISCOVERY_RESPONSE_BYTES -- both are exercised through
        # this same fixture now that both share _open_trusted_discovery_request.
        return self._body if amt is None else self._body[:amt]


OPENAI_SOURCE = ProviderModelSource(
    provider_name="openai",
    credential_name="OPENAI_API_KEY",
    list_url="https://api.openai.com/v1/models",
    chat_base_url="https://api.openai.com/v1",
)

EMBEDDING_SOURCE = ProviderModelSource(
    provider_name="embedding_provider",
    credential_name="EMBEDDING_API_KEY",
    list_url="https://embedding.example/v1/models",
    chat_base_url="https://embedding.example/v1",
    capabilities=("embedding",),
)

OPENROUTER_SOURCE = ProviderModelSource(
    provider_name="openrouter",
    credential_name="OPENROUTER_API_KEY",
    list_url="https://openrouter.ai/api/v1/models?output_modalities=all",
    chat_base_url="https://openrouter.ai/api/v1",
    capabilities=("chat",),
    evidence_only=True,
)

BYTEZ_SOURCE = ProviderModelSource(
    provider_name="bytez",
    credential_name="BYTEZ_API_KEY",
    list_url="https://api.bytez.com/models/v2/list/models",
    chat_base_url="https://api.bytez.com/models/v2/openai/v1",
    auth_scheme=AUTH_SCHEME_RAW_TOKEN,
    style="bytez",
    task_filter="chat",
    capabilities=("chat",),
)


def test_discover_provider_models_skips_when_credential_missing() -> None:
    assert discover_provider_models(OPENAI_SOURCE) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": {"total_credits": 10, "total_usage": 9}}, True),
        ({"data": {"total_credits": 10, "total_usage": 10}}, False),
        ({"data": {"total_credits": 10, "total_usage": 11}}, False),
        ({"data": {"total_credits": "invalid", "total_usage": 0}}, None),
    ],
)
def test_openrouter_paid_inference_uses_attested_remaining_credit(
    payload: dict, expected: bool | None
) -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response(payload),
    ):
        assert openrouter_paid_inference_available() is expected


def test_discover_openai_compatible_parses_models_and_pricing() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    payload = {
        "data": [
            {
                "id": "meta/llama-3.3",
                "pricing": {"prompt": "0.0000006", "completion": "0.0000012"},
                "supported_parameters": ["response_format"],
            },
            {"id": "no-pricing-model"},
            {"missing": "id-field"},
        ]
    }
    seen_requests = []

    def urlopen(request, timeout=None, **_kwargs):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert seen_requests[0].get_header("Authorization") == "Bearer sk-router"
    assert seen_requests[0].full_url == "https://openrouter.ai/api/v1/models?output_modalities=all"
    assert [m.model_id for m in discovered] == ["meta/llama-3.3", "no-pricing-model"]
    priced = discovered[0]
    assert priced.prompt_price_per_1k == pytest.approx(0.0006)
    assert priced.completion_price_per_1k == pytest.approx(0.0012)
    assert discovered[1].prompt_price_per_1k is None
    assert discovered[0].capabilities == ("chat", "response_format")
    assert discovered[1].capabilities == ("chat",)
    assert all(model.evidence_only for model in discovered)
    assert "response_format" in agent_from_discovered(
        replace(discovered[0], evidence_only=False)
    ).tags


def test_openrouter_discovery_preserves_every_declared_modality() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    rows = [
        {"id": f"provider/{output}", "architecture": {"input_modalities": [input_], "output_modalities": [output]}}
        for input_, output in [
            ("text", "text"),
            ("text", "image"),
            ("text", "video"),
            ("text", "speech"),
            ("audio", "transcription"),
            ("text", "embeddings"),
            ("text", "rerank"),
            ("text", "audio"),
        ]
    ]
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response({"data": rows}),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert {capability for model in discovered for capability in model.capabilities} >= {
        "text", "image", "video", "speech", "transcription", "embedding", "rerank", "audio"
    }
    transcription = next(model for model in discovered if "transcription" in model.capabilities)
    generated_audio = next(
        model for model in discovered if model.output_modalities == ("audio",)
    )
    assert transcription.input_modalities == ("audio",)
    assert "audio" not in transcription.capabilities
    assert "audio" in generated_audio.capabilities
    embedding = next(model for model in discovered if "embedding" in model.capabilities)
    assert embedding.output_modalities == ("embeddings",)
    assert {"input:text", "output:embeddings"} <= set(
        agent_from_discovered(replace(embedding, evidence_only=False)).tags
    )


def test_openrouter_skips_model_endpoint_fetches_when_provider_policies_fail() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    with patch(
        "contextual_orchestrator.model_discovery._fetch_json",
        side_effect=[
            {"data": [{"id": "free/model", "pricing": {"prompt": "0", "completion": "0"}}]},
            {"data": []},
            urllib.error.URLError("provider policy unavailable"),
        ],
    ), patch(
        "contextual_orchestrator.model_discovery._openrouter_free_model_endpoints"
    ) as endpoint_fetch:
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert [model.model_id for model in discovered] == ["free/model"]
    endpoint_fetch.assert_not_called()
def test_non_text_model_does_not_gain_structured_response_capability() -> None:
    """A provider parameter alone cannot make an image-only model a synthesizer."""
    register_credential("OPENROUTER_API_KEY", "sk-router")
    payload = {
        "data": [
            {
                "id": "provider/image-only",
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["image"],
                },
                "supported_parameters": ["response_format"],
            }
        ]
    }
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert discovered[0].capabilities == ("image",)


def test_non_text_model_does_not_gain_chat_from_chat_like_identifier() -> None:
    """Explicit non-text outputs win over heuristic chat-name recovery."""
    discovered = _parse_openai_compatible(
        {
            "data": [
                {
                    "id": "provider/chat-image-only",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["image"],
                    },
                }
            ]
        },
        OPENAI_SOURCE,
    )

    assert discovered[0].capabilities == ("image",)


def test_discovery_treats_null_modality_arrays_as_unspecified() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response(
            {
                "data": [
                    {
                        "id": "provider/unspecified",
                        "architecture": {"input_modalities": None, "output_modalities": None},
                    }
                ]
            }
        ),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert discovered[0].capabilities == ("chat",)


def test_discovery_preserves_operator_declared_source_capabilities() -> None:
    register_credential("EMBEDDING_API_KEY", "registered-secret")
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response({"data": [{"id": "embedding-deployment"}]}),
    ):
        discovered = discover_provider_models(EMBEDDING_SOURCE)

    assert discovered[0].capabilities == ("embedding",)


def test_discovery_retains_full_catalog_and_marks_free_models() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-router")
    payload = {
        "data": [
            {"id": "vendor/free-model", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "paid/model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            {"id": "request-fee/model", "pricing": {"prompt": "0", "completion": "0", "request": "0.01"}},
        ]
    }
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert [model.model_id for model in discovered] == ["vendor/free-model", "paid/model", "request-fee/model"]
    assert [model.model_id for model in free_discovered_models(discovered)] == ["vendor/free-model"]
    assert agent_from_discovered(replace(discovered[0], evidence_only=False)).group_name == ""


def _nim_vision_model() -> DiscoveredModel:
    """NVIDIA NIM's incident model: free, chat-capable, declares text + image."""
    return DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="meta/llama-3.2-90b-vision-instruct",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text", "image"),
        output_modalities=("text",),
        is_free=True,
    )


def test_general_free_serving_candidates_excludes_a_free_vision_only_input_model() -> None:
    """The general-purpose free pool must exclude a zero-priced vision-input model.

    Relocated from ``free_discovered_models`` (ContextualWisdomLab/.github PR
    #1198's original fix) onto the dedicated serving-eligibility selector once
    Devin's review on PR #933 found that ``free_discovered_models`` itself must
    stay a pure price-based inventory (see
    ``test_free_discovered_models_still_counts_a_free_vision_only_input_model``
    below) -- the intent of the original regression test is unchanged.

    Reproduces ``ContextualWisdomLab/.github`` PR #1198's required Strix Security
    Scan failure (run 33325907333, job 99295892400): NVIDIA NIM's free
    ``meta/llama-3.2-90b-vision-instruct`` passes every existing chat-capability
    check (Models.dev reports its cost as 0/0, its output modality is "text",
    and its model id carries no disqualifying token), yet NIM's live deployment
    rejected Strix's tool-calling request against it with a definitive HTTP 400
    (``invalid_request_error``) three independent times in a row -- because the
    orchestrator/free pool has no other candidate to fail over to, this one
    vision-input model alone exhausts the whole "free" tool-calling pool.
    Models.dev's own ``tool_call`` field claims ``true`` for this exact model
    (verified live), so that field cannot be the fix; its declared *input*
    modality (``image``, alongside ``text``) is the only honest catalog
    evidence distinguishing it from an ordinary text-only free worker. A
    model requiring non-text input is a specialized multimodal deployment, not
    a general-purpose worker a caller can route arbitrary (including
    tool-calling) requests to without knowing in advance that it needs an
    image -- so it must not enter the general free pool, while a text-only
    free model of identical price remains fully eligible.
    """
    vision_model = _nim_vision_model()
    text_only_model = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="meta/llama-3.1-8b-instruct",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        is_free=True,
    )
    no_modality_evidence_model = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="mistralai/mistral-small",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        is_free=True,
    )

    serving_candidates = general_free_serving_candidates(
        [vision_model, text_only_model, no_modality_evidence_model]
    )

    assert [model.model_id for model in serving_candidates] == [
        "meta/llama-3.1-8b-instruct",
        "mistralai/mistral-small",
    ]


def test_free_discovered_models_still_counts_a_free_vision_only_input_model() -> None:
    """Price-based free inventory must not lose a model excluded from serving.

    Finding 3 of Devin's review on PR #933: by filtering inside
    ``free_discovered_models()`` itself, the original PR #1198 fix silently
    undercounted a genuinely free model in every consumer of that function
    that wants raw price inventory rather than serving-pool eligibility --
    ``--free-only`` CLI output, ``free_tier_count``, and the free-tier
    data-privacy totals. This model is priced at zero and must be counted
    here even though :func:`general_free_serving_candidates` correctly
    excludes it from blind serving.
    """
    vision_model = _nim_vision_model()

    assert free_discovered_models([vision_model]) == [vision_model]
    assert general_free_serving_candidates([vision_model]) == []


def test_general_free_serving_candidates_excludes_unroutable_free_models() -> None:
    """Non-text price/modality evidence alone does not certify servability.

    Devin's review pass on PR #933 after ``efd44f6`` found that
    ``general_free_serving_candidates`` admits any zero-priced, text-input
    row regardless of whether it could ever actually become a serving agent:
    an ``evidence_only`` catalog row (``agent_from_discovered`` refuses to
    build an agent from one at all) and a free non-chat-capable model (e.g.
    an embedding-only deployment) both pass the price and modality checks
    while being fundamentally unroutable. ``general_free_serving_count``
    therefore overcounted models the general chat pool could never actually
    serve. ``is_routable_discovered_model`` -- the same predicate
    ``_auto_discover_runtime_agents`` and ``provider_bootstrap`` already use
    to decide whether a discovered row may become an ordinary chat agent at
    all -- is the missing check.
    """
    evidence_only_free_text_model = replace(
        DiscoveredModel(
            provider_name="nvidia_nim",
            model_id="evidence-only-free-model",
            credential_name="NVIDIA_NIM_API_KEY",
            chat_base_url="https://integrate.api.nvidia.com/v1",
            auth_scheme="Bearer",
            capabilities=("chat",),
            input_modalities=("text",),
            output_modalities=("text",),
            is_free=True,
        ),
        evidence_only=True,
    )
    embedding_only_free_model = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="embedding-only-free-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
        input_modalities=("text",),
        output_modalities=("text",),
        is_free=True,
    )
    routable_free_text_model = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="routable-free-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        is_free=True,
    )

    serving_candidates = general_free_serving_candidates([
        evidence_only_free_text_model,
        embedding_only_free_model,
        routable_free_text_model,
    ])

    assert [model.model_id for model in serving_candidates] == ["routable-free-model"]
    # Both unroutable rows remain fully counted in the price-based inventory.
    assert {model.model_id for model in free_discovered_models([
        evidence_only_free_text_model,
        embedding_only_free_model,
        routable_free_text_model,
    ])} == {
        "evidence-only-free-model",
        "embedding-only-free-model",
        "routable-free-model",
    }


def test_general_free_serving_candidates_modality_shapes() -> None:
    """Explicit three-way modality contract: text-only, image-only, text+image.

    Finding 2 of Devin's review on PR #933 argued the exclusion should spare a
    model that "also supports text as a standalone input", so that only a
    strictly vision-*only* model (no declared text input at all) is excluded.
    Verified against this repository's own incident evidence and rejected:
    NVIDIA NIM's real incident model (see ``_nim_vision_model``) declares
    *both* ``text`` and ``image`` as supported inputs per Models.dev -- i.e.
    it already satisfies "text is a supported standalone input" by Devin's own
    proposed test -- yet NIM's live deployment rejected a plain tool-calling
    request against it three times in a row. Models.dev's ``input_modalities``
    documents supported inputs, not which ones a given request must supply, so
    it cannot certify that this exact model would have served a tool-calling
    request that carried text alone. Narrowing the exclusion to spare
    "text is also listed" models would therefore silently re-admit the very
    model this incident is about, so this repository instead keeps excluding
    any declared non-text input modality from blind serving (see
    ``general_free_serving_candidates``'s and ``_requires_non_text_input``'s
    docstrings for the full reasoning) -- while a model with *no* modality
    evidence at all is not penalized for an absent catalog field.
    """
    text_only = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="text-only-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        is_free=True,
    )
    vision_only = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="vision-only-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("image",),
        output_modalities=("text",),
        is_free=True,
    )
    text_and_image = _nim_vision_model()

    serving_candidates = general_free_serving_candidates(
        [text_only, vision_only, text_and_image]
    )

    assert [model.model_id for model in serving_candidates] == ["text-only-model"]
    # All three remain fully counted in the price-based inventory regardless.
    assert {model.model_id for model in free_discovered_models(
        [text_only, vision_only, text_and_image]
    )} == {"text-only-model", "vision-only-model", "meta/llama-3.2-90b-vision-instruct"}


def test_discovery_and_orchestrator_modality_eligibility_cannot_drift() -> None:
    """``general_free_serving_candidates`` and ``_is_general_free_agent`` agree.

    Devin's review on PR #933 (design-consistency note): the discovery-time
    selector (over ``DiscoveredModel.input_modalities``) and the
    selection-time predicate (over an agent's persisted ``input:<modality>``
    tags) must never independently reimplement "what counts as non-text
    input" -- both now delegate to ``chat_capability.requires_non_text_input``
    for that classification. This locks the three fixture shapes already
    established by ``test_general_free_serving_candidates_modality_shapes``
    (text-only, vision-only-input, text+image) so the two call sites cannot
    silently diverge again.
    """
    text_only = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="text-only-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text",),
        output_modalities=("text",),
        is_free=True,
    )
    vision_only = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="vision-only-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("image",),
        output_modalities=("text",),
        is_free=True,
    )
    text_and_image = _nim_vision_model()
    discovered = [text_only, vision_only, text_and_image]
    serving_model_ids = {model.model_id for model in general_free_serving_candidates(discovered)}

    # ModelAgent.id must be two-or-more-word snake_case; provider model ids
    # (e.g. "meta/llama-3.2-90b-vision-instruct") are not, so derive a
    # compliant id distinct from the ``model`` field under test.
    agent_id_translation = str.maketrans("/.-", "___")
    agents = {
        model.model_id: ModelAgent(
            model.model_id.casefold().translate(agent_id_translation),
            model.model_id,
            tags=("cost:free", *(f"input:{value}" for value in model.input_modalities)),
        )
        for model in discovered
    }
    orchestrator = TaskOrchestrator(list(agents.values()))

    for model in discovered:
        agent = agents[model.model_id]
        assert orchestrator._is_general_free_agent(agent) == (
            model.model_id in serving_model_ids
        ), model.model_id
        # Every one of these stays reachable through its own capability route.
        assert orchestrator._is_free_agent(agent) is True


def test_discovery_does_not_mark_multimodal_input_rows_free_without_unit_prices() -> None:
    """Non-text inputs require explicit zero non-token price evidence."""
    source = ProviderModelSource(
        provider_name="gateway",
        credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example/v1/models",
        chat_base_url="https://gateway.example/v1",
        capabilities=("chat",),
    )

    discovered = _parse_openai_compatible(
        {
            "data": [
                {
                    "id": "vision-chat",
                    "pricing": {"prompt": 0, "completion": 0},
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                }
            ]
        },
        source,
    )

    assert len(discovered) == 1
    assert discovered[0].is_free is False


def test_discovery_does_not_mark_rows_free_with_unknown_unit_price_dimensions() -> None:
    """Unknown unit dimensions keep free status unknown rather than zero-cost."""
    source = ProviderModelSource(
        provider_name="gateway",
        credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example/v1/models",
        chat_base_url="https://gateway.example/v1",
        capabilities=("chat",),
    )

    discovered = _parse_openai_compatible(
        {
            "data": [
                {
                    "id": "text-chat",
                    "pricing": {"prompt": 0, "completion": 0},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "unit_pricing": {"per_call": 0},
                }
            ]
        },
        source,
    )

    assert len(discovered) == 1
    assert discovered[0].is_free is False


def test_opencode_zen_joins_models_dev_cost_and_modalities_without_name_inference() -> None:
    source = next(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "opencode_zen")
    register_credential("OPENCODE_ZEN_API_KEY", "zen-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            assert request.get_header("Authorization") is None
            return _Response(
                {
                    "opencode": {
                        "models": {
                            "provider/example-free": {
                                "cost": {"input": 0, "output": 0, "cache_read": 0},
                                "modalities": {"input": ["text", "image"], "output": ["text"]},
                            },
                            "paid-model": {
                                "cost": {"input": 2, "output": 12},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            },
                            "cache-fee-free": {
                                "cost": {"input": 0, "output": 0, "cache_write": 0.1},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            },
                        }
                    }
                }
            )
        return _Response(
            {
                "data": [
                    {"id": "provider/example-free"},
                    {"id": "paid-model"},
                    {"id": "cache-fee-free"},
                    {"id": "unknown-free"},
                ]
            }
        )

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].is_free is True
    assert discovered[1].is_free is False
    assert discovered[2].is_free is False
    assert discovered[3].is_free is False
    assert discovered[0].input_modalities == ("text", "image")
    assert discovered[1].prompt_price_per_1k == pytest.approx(0.002)
    assert discovered[1].completion_price_per_1k == pytest.approx(0.012)
    assert agent_from_discovered(discovered[0]).group_name == ""


def test_opencode_zen_metadata_failure_keeps_availability_but_not_free_suffix() -> None:
    register_credential("OPENCODE_ZEN_API_KEY", "zen-key")
    source = next(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "opencode_zen")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "vendor/paid-free"}]})

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].is_free is False


def test_non_text_models_without_unit_price_evidence_are_not_classified_free() -> None:
    """A zero token price alone cannot prove a non-text model is free."""
    source = ProviderModelSource(
        provider_name="gateway",
        credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example/v1/models",
        chat_base_url="https://gateway.example/v1",
        capabilities=("image",),
    )

    discovered = _parse_openai_compatible(
        {
            "data": [
                {
                    "id": "image-free-ish",
                    "pricing": {"prompt": 0, "completion": 0},
                    "architecture": {"output_modalities": ["image"]},
                }
            ]
        },
        source,
    )

    assert discovered[0].is_free is False


def test_nvidia_nim_joins_models_dev_cost_and_modalities_without_name_inference() -> None:
    """The generalized join (ADR 0032's opencode_zen contract, now data-driven)."""
    source = next(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "nvidia_nim")
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            assert request.get_header("Authorization") is None
            return _Response(
                {
                    "nvidia": {
                        "models": {
                            "meta/llama-3.1-8b-instruct": {
                                "cost": {"input": 0, "output": 0, "cache_read": 0},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            },
                            "deepseek-ai/deepseek-v4-flash": {
                                "cost": {"input": 0.1, "output": 0.4},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            },
                            "nvidia/cache-fee-model": {
                                "cost": {"input": 0, "output": 0, "cache_write": 0.05},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            },
                        }
                    }
                }
            )
        return _Response(
            {
                "data": [
                    {"id": "meta/llama-3.1-8b-instruct"},
                    {"id": "deepseek-ai/deepseek-v4-flash"},
                    {"id": "nvidia/cache-fee-model"},
                    {"id": "nvidia/unlisted-model"},
                ]
            }
        )

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered = discover_provider_models(source)

    # Free: every declared monetary component is exactly zero.
    assert discovered[0].is_free is True
    assert discovered[0].input_modalities == ("text",)
    # Paid: nonzero input/output cost, consistent with the deliberately-priced
    # models Models.dev documents for the nvidia provider.
    assert discovered[1].is_free is False
    assert discovered[1].prompt_price_per_1k == pytest.approx(0.0001)
    assert discovered[1].completion_price_per_1k == pytest.approx(0.0004)
    # Only cache_write is nonzero: must NOT be classified free (off-by-omission
    # guard -- a free-looking token price is not the whole cost vector).
    assert discovered[2].is_free is False
    # In NIM's own listing but absent from Models.dev: stays unknown, not free.
    assert discovered[3].is_free is False


def test_nvidia_nim_metadata_failure_keeps_availability_but_not_free() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    source = next(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "nvidia_nim")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].is_free is False


def test_fetch_json_sends_a_stable_user_agent_on_every_request() -> None:
    """Models.dev rejects urllib's default UA with HTTP 403 (Cloudflare error 1010);

    every request -- authenticated or not -- must carry an identifying UA so the
    Models.dev join (and any other unauthenticated discovery call) does not
    silently degrade to metadata-unavailable.
    """
    captured: list[object] = []

    def urlopen(request, timeout=None, **_kwargs):
        captured.append(request)
        return _Response({"data": []})

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        _fetch_json("https://models.dev/api.json", timeout=5.0)
        _fetch_json("https://api.openai.com/v1/models", api_key="sk-test", timeout=5.0)

    assert len(captured) == 2
    for request in captured:
        user_agent = request.get_header("User-agent")
        assert user_agent, "every discovery request must carry a User-Agent header"
        assert "urllib" not in user_agent.lower()
    # The authorization header must still be scoped to the authenticated call only.
    assert captured[0].get_header("Authorization") is None
    assert captured[1].get_header("Authorization") == "Bearer sk-test"


def test_nvidia_nim_join_requires_the_user_agent_header_to_avoid_a_403() -> None:
    """Regression for the exact live failure: a fetch mock that 403s without a UA."""
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    source = next(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "nvidia_nim")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            if not request.get_header("User-agent"):
                raise urllib.error.HTTPError(
                    request.full_url, 403, "Forbidden", {}, None
                )
            return _Response(
                {"nvidia": {"models": {"meta/llama-3.1-8b-instruct": {"cost": {"input": 0, "output": 0}}}}}
            )
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].is_free is True


def test_discover_all_models_fetches_models_dev_exactly_once_across_sources() -> None:
    """opencode_zen + nvidia_nim + nvidia_nim_sub share one Models.dev fetch."""
    register_credential("OPENCODE_ZEN_API_KEY", "zen-key")
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    register_credential("NVIDIA_NIM_API_KEY_SUB", "nim-sub-key")
    models_dev_calls = []

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            models_dev_calls.append(request.full_url)
            return _Response(
                {
                    "opencode": {"models": {}},
                    "nvidia": {
                        "models": {
                            "meta/llama-3.1-8b-instruct": {
                                "cost": {"input": 0, "output": 0},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            }
                        }
                    },
                }
            )
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    sources = tuple(
        item
        for item in PROVIDER_MODEL_SOURCES
        if item.provider_name in {"opencode_zen", "nvidia_nim", "nvidia_nim_sub"}
    )
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered, errors = discover_all_models(sources)

    assert errors == []
    assert len(models_dev_calls) == 1
    # Both NVIDIA NIM credentials joined against the identical shared catalog.
    assert [
        (model.provider_name, model.is_free)
        for model in discovered
        if model.provider_name in {"nvidia_nim", "nvidia_nim_sub"}
    ] == [("nvidia_nim", True), ("nvidia_nim_sub", True)]


def test_discover_all_models_shared_models_dev_fetch_failure_keeps_is_free_false() -> None:
    """A failure of the ONE shared prefetch degrades every source to unknown cost."""
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    register_credential("NVIDIA_NIM_API_KEY_SUB", "nim-sub-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    sources = tuple(
        item
        for item in PROVIDER_MODEL_SOURCES
        if item.provider_name in {"nvidia_nim", "nvidia_nim_sub"}
    )
    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered, errors = discover_all_models(sources)

    assert errors == []
    assert [model.is_free for model in discovered] == [False, False]


def test_discover_all_models_shared_models_dev_fetch_retries_a_transient_failure() -> None:
    """A single transient Models.dev failure recovers on retry instead of erasing coverage.

    Regression for the ContextualWisdomLab/.github#1433 ``orchestrator/free``
    reliability gap: NVIDIA NIM's free-tier coverage depends entirely on this
    one unauthenticated, third-party fetch (ADR 0041) succeeding, so a lone
    blip must not degrade every dependent provider's evidence for the run.
    """
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    attempts = {"models_dev": 0}

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            attempts["models_dev"] += 1
            if attempts["models_dev"] < 2:
                raise urllib.error.URLError("transient blip")
            return _Response(
                {
                    "nvidia": {
                        "models": {
                            "meta/llama-3.1-8b-instruct": {
                                "cost": {"input": 0, "output": 0},
                                "modalities": {"input": ["text"], "output": ["text"]},
                            }
                        }
                    }
                }
            )
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    sources = tuple(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "nvidia_nim")
    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
    ):
        discovered, errors = discover_all_models(sources)

    assert errors == []
    assert attempts["models_dev"] == 2
    assert [model.is_free for model in discovered] == [True]


def test_discover_all_models_shared_models_dev_fetch_gives_up_after_retry_budget() -> None:
    """Exhausting the bounded retry budget still degrades to unknown cost, not a crash."""
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")
    attempts = {"models_dev": 0}

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            attempts["models_dev"] += 1
            raise urllib.error.URLError("still offline")
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    sources = tuple(item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "nvidia_nim")
    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
    ):
        discovered, errors = discover_all_models(sources)

    assert errors == []
    assert attempts["models_dev"] == _MODELS_DEV_FETCH_ATTEMPTS
    assert [model.is_free for model in discovered] == [False]


def test_discover_all_models_leaves_bytez_unaffected_and_skips_models_dev() -> None:
    """Bytez has no Models.dev coverage; it must never trigger the shared fetch."""
    register_credential("BYTEZ_API_KEY", "bytez-key")
    models_dev_calls = []

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == "https://models.dev/api.json":
            models_dev_calls.append(request.full_url)
            return _Response({})
        return _Response(
            {"output": [{"modelId": "0-hero/Matter-0.1-Slim-7B-C", "task": "chat"}]}
        )

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        side_effect=urlopen,
    ):
        discovered, errors = discover_all_models()

    assert errors == []
    assert models_dev_calls == []
    assert [model.model_id for model in discovered] == ["0-hero/Matter-0.1-Slim-7B-C"]
    assert discovered[0].is_free is False


def test_default_sources_request_openrouter_full_modality_catalog() -> None:
    sources = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}

    assert sources["openai"].capabilities == ()
    assert sources["openrouter"].capabilities == ("chat",)
    assert sources["openrouter"].list_url.endswith("?output_modalities=all")
    assert sources["openrouter"].evidence_only is True
    assert sources["opencode_zen"].list_url == "https://opencode.ai/zen/v1/models"
    assert sources["nvidia_nim"].capabilities == ("chat",)
    assert sources["nvidia_nim_sub"].capabilities == ("chat",)


def test_price_per_1k_rejects_underflowing_positive_value() -> None:
    """A nonzero per-token price that underflows to 0.0 in float stays unknown."""
    assert _price_per_1k("1e-10000") is None
    assert _price_per_1k(0) == 0.0
    assert _price_per_1k(0.000001) == pytest.approx(0.001)


def test_discover_bytez_parses_models_with_key_auth_scheme() -> None:
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    payload = {
        "error": None,
        "output": [
            {"modelId": "0-hero/Matter-0.1-Slim-7B-C", "task": "chat", "meterPrice": "0.0006 / sec"},
            {"modelId": "provider/llama-guard", "task": "chat"},
        ],
    }
    seen_requests = []

    def urlopen(request, timeout=None, **_kwargs):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen):
        discovered = discover_provider_models(BYTEZ_SOURCE)

    assert seen_requests[0].get_header("Authorization") == "bytez-secret"
    assert seen_requests[0].full_url == "https://api.bytez.com/models/v2/list/models?task=chat"
    assert len(discovered) == 1
    assert discovered[0].model_id == "0-hero/Matter-0.1-Slim-7B-C"
    assert discovered[0].auth_scheme == AUTH_SCHEME_RAW_TOKEN
    assert discovered[0].capabilities == ("chat",)
    # Bytez prices by GPU-second, not per-token: no fabricated per-1k estimate.
    assert discovered[0].prompt_price_per_1k is None


def test_discover_bytez_preserves_operator_declared_capabilities() -> None:
    """A declared endpoint capability admits Bytez identifiers without name inference."""
    register_credential("BYTEZ_EMBEDDING_KEY", "bytez-secret")
    source = ProviderModelSource(
        provider_name="bytez",
        credential_name="BYTEZ_EMBEDDING_KEY",
        list_url="https://api.bytez.com/models/v2/list/models?task=embedding",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme=AUTH_SCHEME_RAW_TOKEN,
        style="bytez",
        capabilities=("embedding",),
    )

    with patch(
        "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
        return_value=_Response({"output": [{"modelId": "embedding-deployment"}]}),
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].capabilities == ("embedding",)


def test_discover_all_models_continues_after_one_provider_error() -> None:
    register_credential("OPENAI_API_KEY", "sk-openai")
    register_credential("OPENROUTER_API_KEY", "sk-router")

    def urlopen(request, timeout=None, **_kwargs):
        if urllib.parse.urlsplit(request.full_url).hostname == "api.openai.com":
            raise urllib.error.URLError("connection refused")
        return _Response({"data": [{"id": "meta/llama-3.3"}]})

    with patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen):
        discovered, errors = discover_all_models((OPENAI_SOURCE, OPENROUTER_SOURCE))

    assert [m.model_id for m in discovered] == ["meta/llama-3.3"]
    assert len(errors) == 1
    assert errors[0].provider_name == "openai"
    assert errors[0].error_code == "transport_error"
    assert "connection refused" not in str(errors[0])
    assert errors[0].__cause__ is None


def test_discover_all_models_applies_model_zdr_evidence_to_other_sources() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-openrouter")
    other_source = ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
    )
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "openai/shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
        patch(
            "contextual_orchestrator.model_discovery._fetch_json_same_host_https",
            return_value={"data": [{"model_id": "openai/shared-model"}]},
        ),
    ):
        discovered, errors = discover_all_models((OPENROUTER_SOURCE, other_source))

    assert errors == []
    assert [(model.provider_name, model.zdr_capable) for model in discovered] == [
        ("openrouter", False),
        ("nvidia_nim", True),
    ]


def test_openrouter_zdr_evidence_uses_the_registered_kv_credential() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-openrouter")
    seen_calls = []

    def fetch(url, *, api_key="", auth_scheme="Bearer", timeout):
        seen_calls.append((url, api_key, auth_scheme, timeout))
        return {"data": [{"model_id": "openai/shared-model"}]}

    with patch(
        "contextual_orchestrator.model_discovery._fetch_json_same_host_https",
        side_effect=fetch,
    ):
        from contextual_orchestrator.model_discovery import _openrouter_zdr_model_ids

        assert _openrouter_zdr_model_ids(timeout=1.0) == {"openai/shared-model"}

    assert seen_calls == [
        ("https://openrouter.ai/api/v1/endpoints/zdr", "sk-openrouter", "Bearer", 1.0)
    ]


def test_openrouter_zdr_evidence_rejects_cross_host_redirects() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-openrouter")
    seen_requests = []

    class _RedirectingOpener:
        def __init__(self, handler):
            self._handler = handler

        def open(self, request, timeout=None):
            seen_requests.append(request)
            return self._handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://evil.example/zdr"},
                "https://evil.example/zdr",
            )

    def build_opener(handler):
        return _RedirectingOpener(handler)

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.build_opener",
        side_effect=build_opener,
    ):
        from contextual_orchestrator.model_discovery import _openrouter_zdr_model_ids

        assert _openrouter_zdr_model_ids(timeout=1.0) == set()

    assert seen_requests[0].get_header("Authorization") == "Bearer sk-openrouter"


def test_fetch_json_rejects_a_cross_host_redirect_and_does_not_leak_the_credential() -> None:
    """CVE-shaped regression for CodeRabbit's PR #946 finding.

    ``_fetch_json`` is the function every standard provider's authenticated
    "list models" call goes through (openai, openrouter, nvidia_nim,
    nvidia_nim_sub, bytez), including under the one bounded retry added for
    a transient failure -- so a credential leak here would fire up to twice.
    Before the fix it called bare ``urllib.request.urlopen``, whose default
    ``HTTPRedirectHandler`` copies the ``Authorization`` header onto a
    redirected request even when the redirect leaves the original host.
    This proves the leak is closed: the trusted-host opener must raise
    before a second, cross-host request is ever issued -- red against the
    unfixed ``_fetch_json`` (it followed the redirect and returned the
    attacker's payload instead of raising), green after.
    """
    seen_requests = []

    class _RedirectingOpener:
        def __init__(self, handler):
            self._handler = handler

        def open(self, request, timeout=None):
            seen_requests.append(request)
            return self._handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://evil.example/steal"},
                "https://evil.example/steal",
            )

    def build_opener(*handlers):
        assert len(handlers) == 1, "no SSL-context handler expected on the first attempt"
        return _RedirectingOpener(handlers[0])

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.build_opener",
        side_effect=build_opener,
    ):
        with pytest.raises(urllib.error.HTTPError):
            _fetch_json(
                "https://api.example.com/v1/models",
                api_key="sk-super-secret-provider-key",
                timeout=1.0,
            )

    # Exactly one request was ever issued -- to the original, trusted host.
    # redirect_request raises instead of returning a request to evil.example,
    # so the credential is never even constructed for, let alone sent to, it.
    assert len(seen_requests) == 1
    assert seen_requests[0].full_url == "https://api.example.com/v1/models"
    assert seen_requests[0].get_header("Authorization") == "Bearer sk-super-secret-provider-key"


def test_fetch_json_still_follows_a_same_host_redirect() -> None:
    """Negative control: a same-host redirect (different path) must still work.

    The fix must not collaterally break the legitimate case a real
    provider API can use -- e.g. ``api.example.com/v1/models`` redirecting to
    ``api.example.com/v2/models``.
    """
    seen_requests = []

    class _RedirectingOpener:
        def __init__(self, handler):
            self._handler = handler

        def open(self, request, timeout=None):
            seen_requests.append(request)
            redirected = self._handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {"Location": "https://api.example.com/v2/models"},
                "https://api.example.com/v2/models",
            )
            seen_requests.append(redirected)
            return _Response({"data": [{"id": "same-host-model"}]})

    def build_opener(*handlers):
        return _RedirectingOpener(handlers[0])

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.build_opener",
        side_effect=build_opener,
    ):
        payload = _fetch_json(
            "https://api.example.com/v1/models",
            api_key="sk-super-secret-provider-key",
            timeout=1.0,
        )

    assert payload == {"data": [{"id": "same-host-model"}]}
    assert len(seen_requests) == 2
    assert seen_requests[0].full_url == "https://api.example.com/v1/models"
    assert seen_requests[1].full_url == "https://api.example.com/v2/models"
    # The redirected same-host request still legitimately carries the credential.
    for request in seen_requests:
        assert request.get_header("Authorization") == "Bearer sk-super-secret-provider-key"


def test_discover_all_models_does_not_match_a_shared_zdr_model_suffix() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-openrouter")
    other_source = ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
    )
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
        patch(
            "contextual_orchestrator.model_discovery._fetch_json_same_host_https",
            return_value={"data": [{"model_id": "openai/shared-model"}]},
        ),
    ):
        discovered, errors = discover_all_models((OPENROUTER_SOURCE, other_source))

    assert errors == []
    assert [(model.provider_name, model.zdr_capable) for model in discovered] == [
        ("openrouter", False),
        ("nvidia_nim", False),
    ]


def test_discover_all_models_rejects_an_ambiguous_zdr_model_suffix() -> None:
    register_credential("OPENROUTER_API_KEY", "sk-openrouter")
    other_source = ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
    )
    register_credential("NVIDIA_NIM_API_KEY", "nim-key")

    def urlopen(request, timeout=None, **_kwargs):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            side_effect=urlopen,
        ),
        patch(
            "contextual_orchestrator.model_discovery._fetch_json_same_host_https",
            return_value={
                "data": [
                    {"model_id": "openai/shared-model"},
                    {"model_id": "other/shared-model"},
                ]
            },
        ),
    ):
        discovered, errors = discover_all_models((OPENROUTER_SOURCE, other_source))

    assert errors == []
    assert [(model.provider_name, model.zdr_capable) for model in discovered] == [
        ("openrouter", False),
        ("nvidia_nim", False),
    ]


def test_malformed_openrouter_zdr_data_is_ignored(monkeypatch) -> None:
    monkeypatch.setattr(
        "contextual_orchestrator.model_discovery._fetch_json_same_host_https",
        lambda *args, **kwargs: {"data": {"model_id": "not-a-list"}},
    )

    from contextual_orchestrator.model_discovery import _openrouter_zdr_model_ids

    assert _openrouter_zdr_model_ids(timeout=1.0) == set()


def test_discovery_boundary_contains_raw_connection_reset() -> None:
    """A raw ConnectionResetError (not a URLError) still fails inside the boundary.

    Regression: ``ConnectionError``/``OSError`` subclasses that are not
    ``URLError`` used to escape ``discover_provider_models`` uncaught, leaking
    provider transport diagnostics to discovery callers. A connection reset is
    also transient, so this now retries once before giving up; both attempts
    fail identically here, exercising the exhausted-retry path.
    """
    register_credential("OPENAI_API_KEY", "sk-openai")
    attempts = []

    def urlopen(request, timeout=None, **_kwargs):
        attempts.append(timeout)
        raise ConnectionResetError(104, "Connection reset by peer")

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep") as mock_sleep,
    ):
        try:
            discover_provider_models(OPENAI_SOURCE)
        except ProviderDiscoveryError as error:
            assert error.provider_name == "openai"
            assert error.error_code == "transport_error"
            assert "reset" not in str(error)
            assert error.__cause__ is None
        else:  # pragma: no cover
            raise AssertionError("a raw connection reset must become a ProviderDiscoveryError")

    assert len(attempts) == 2  # initial attempt + one bounded retry, both transient
    mock_sleep.assert_called_once()


def test_discover_provider_models_retries_transient_failure_then_succeeds() -> None:
    """A single transient 5xx on the primary fetch is retried, not fatal.

    This is the exact shape of the incident that motivated the retry: one
    provider's momentary HTTP 500 must not zero out that provider's entire
    contribution for this discovery pass.
    """
    register_credential("OPENAI_API_KEY", "sk-openai")
    payload = {"data": [{"id": "gpt-test", "object": "model"}]}
    attempt_timeouts = []

    def urlopen(request, timeout=None, **_kwargs):
        attempt_timeouts.append(timeout)
        if len(attempt_timeouts) == 1:
            raise urllib.error.HTTPError(request.full_url, 500, "Internal Server Error", {}, None)
        return _Response(payload)

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep") as mock_sleep,
    ):
        discovered = discover_provider_models(OPENAI_SOURCE)

    assert len(attempt_timeouts) == 2
    assert attempt_timeouts[1] < attempt_timeouts[0]  # retry uses the shortened timeout
    mock_sleep.assert_called_once()
    assert [model.model_id for model in discovered] == ["gpt-test"]


def test_discover_provider_models_does_not_retry_non_transient_failure() -> None:
    """A 401 (bad credential) is never retried -- a retry cannot fix it."""
    register_credential("OPENAI_API_KEY", "sk-openai")
    attempts = []

    def urlopen(request, timeout=None, **_kwargs):
        attempts.append(timeout)
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep") as mock_sleep,
    ):
        try:
            discover_provider_models(OPENAI_SOURCE)
        except ProviderDiscoveryError as error:
            assert error.provider_name == "openai"
            assert error.error_code == "http_status_401"
        else:  # pragma: no cover
            raise AssertionError("a 401 must become a ProviderDiscoveryError")

    assert len(attempts) == 1
    mock_sleep.assert_not_called()


def test_discover_provider_models_isolates_a_dns_resolution_failure() -> None:
    """A configured-gateway DNS failure must not abort the whole discovery pass.

    ``ModelClient._resolve_addresses`` wraps ``socket.gaierror`` as a plain
    ``RuntimeError`` (see ``_fetch_configured_gateway_json``'s pinned-address
    validation path), which was not in ``discover_provider_models``'s catch
    tuple (``URLError``, ``TimeoutError``, ``ValueError``, ``OSError``). One
    provider's DNS hiccup must become an isolated ``ProviderDiscoveryError``,
    not a bare ``RuntimeError`` that crashes ``discover_all_models`` entirely.
    """
    register_credential("LLM_GATEWAY_API_KEY", "sk-gateway")
    gateway_source = ProviderModelSource(
        provider_name="configured_gateway",
        credential_name="LLM_GATEWAY_API_KEY",
        list_url="https://gateway.example/v1/models",
        chat_base_url="https://gateway.example/v1",
        capabilities=("chat",),
    )

    with patch(
        "contextual_orchestrator.model_discovery._fetch_configured_gateway_json",
        side_effect=RuntimeError("provider host 'gateway.example' could not be resolved"),
    ):
        try:
            discover_provider_models(gateway_source)
        except ProviderDiscoveryError as error:
            assert error.provider_name == "configured_gateway"
        else:  # pragma: no cover
            raise AssertionError("a DNS RuntimeError must become a ProviderDiscoveryError")


def test_discover_provider_models_retry_timeout_never_exceeds_callers_budget() -> None:
    """A caller-supplied timeout shorter than the retry default must not expand on retry.

    Regression (Devin review on #923): the retry attempt hardcoded
    _DISCOVERY_RETRY_TIMEOUT_SECONDS (5.0s) regardless of what timeout the
    caller actually requested, so a caller budgeting e.g. 2s per attempt
    could see the retry alone blow well past that budget.
    """
    register_credential("OPENAI_API_KEY", "sk-openai")
    payload = {"data": [{"id": "gpt-test", "object": "model"}]}
    attempt_timeouts = []

    def urlopen(request, timeout=None, **_kwargs):
        attempt_timeouts.append(timeout)
        if len(attempt_timeouts) == 1:
            raise urllib.error.HTTPError(request.full_url, 500, "Internal Server Error", {}, None)
        return _Response(payload)

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        patch("contextual_orchestrator.model_discovery.time.sleep"),
    ):
        discovered = discover_provider_models(OPENAI_SOURCE, timeout=2.0)

    assert attempt_timeouts == [2.0, 2.0]
    assert [model.model_id for model in discovered] == ["gpt-test"]


def test_agent_id_for_is_two_word_snake_case() -> None:
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="Meta/Llama-3.3-70B",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    assert agent_id_for(discovered) == "openrouter_meta_llama_3_3_70b"


def test_agent_from_discovered_builds_disabled_agent_with_correct_auth() -> None:
    discovered = DiscoveredModel(
        provider_name="bytez",
        model_id="0-hero/Matter-0.1-Slim-7B-C",
        credential_name="BYTEZ_API_KEY",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme=AUTH_SCHEME_RAW_TOKEN,
    )
    agent = agent_from_discovered(discovered, priority=3)
    assert agent.id == "bytez_0_hero_matter_0_1_slim_7b_c"
    assert agent.disabled is True
    assert agent.auth_scheme == AUTH_SCHEME_RAW_TOKEN
    assert agent.credential_key == "BYTEZ_API_KEY"
    assert agent.priority == 3
    assert "discovered" in agent.tags


def test_agent_from_discovered_rejects_evidence_only_rows() -> None:
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/evidence-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        evidence_only=True,
    )

    with pytest.raises(ValueError, match="evidence-only"):
        agent_from_discovered(discovered)


def test_agent_from_discovered_preserves_explicit_capabilities() -> None:
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )

    assert agent_from_discovered(discovered).tags == (
        "discovered",
        "embedding",
        "capability:embedding",
    )


def test_agent_from_discovered_preserves_explicit_privacy_evidence() -> None:
    """Every persistence path receives the same provider-declared privacy tags."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        supports_zero_data_retention=True,
        supports_no_training=True,
        supports_no_prompt_retention=False,
    )

    assert {
        "privacy:zdr",
        "privacy:no_training",
        "privacy:retention_only",
    } <= set(agent_from_discovered(discovered).tags)
def test_response_format_metadata_does_not_make_non_chat_model_eligible() -> None:
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
    )

    with pytest.raises(ValueError, match="not eligible"):
        agent_from_discovered(discovered)


def test_refresh_price_book_writes_known_pricing_and_skips_unpriced() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    priced = DiscoveredModel(
        provider_name="openrouter",
        model_id="meta/llama-3.3",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=0.0006,
        completion_price_per_1k=0.0012,
    )
    unpriced = DiscoveredModel(
        provider_name="bytez",
        model_id="some/model",
        credential_name="BYTEZ_API_KEY",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme=AUTH_SCHEME_RAW_TOKEN,
    )
    written = refresh_price_book([priced, unpriced], price_book)
    assert written == 1
    entry = price_book.get_price("openrouter", "meta/llama-3.3")
    assert entry is not None
    assert entry.prompt_price_per_1k == pytest.approx(0.0006)
    assert price_book.get_price("bytez", "some/model") is None


def test_select_cheapest_discovered_agent_picks_the_lower_priced_candidate() -> None:
    from contextual_orchestrator.cost_ledger import PriceEntry

    price_book = PriceBook(InMemoryConfigStore())
    cheap = DiscoveredModel(
        provider_name="openrouter",
        model_id="small-cheap-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    pricey = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="large-pricey-model",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
    )
    price_book.set_price(PriceEntry("openrouter", "small-cheap-model", 0.1, 0.1))
    price_book.set_price(PriceEntry("nvidia_nim", "large-pricey-model", 5.0, 10.0))

    winner = select_cheapest_discovered_agent([pricey, cheap], price_book)
    assert winner is cheap


def test_select_cheapest_discovered_agent_returns_none_for_empty_list() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    assert select_cheapest_discovered_agent([], price_book) is None


def test_select_top_n_cheapest_discovered_agents_orders_by_cost() -> None:
    from contextual_orchestrator.cost_ledger import PriceEntry

    price_book = PriceBook(InMemoryConfigStore())
    cheapest = DiscoveredModel("openrouter", "a", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "Bearer")
    middle = DiscoveredModel("nvidia_nim", "b", "NVIDIA_NIM_API_KEY", "https://integrate.api.nvidia.com/v1", "Bearer")
    priciest = DiscoveredModel("openai", "c", "OPENAI_API_KEY", "https://api.openai.com/v1", "Bearer")
    price_book.set_price(PriceEntry("openrouter", "a", 0.01, 0.01))
    price_book.set_price(PriceEntry("nvidia_nim", "b", 1.0, 1.0))
    price_book.set_price(PriceEntry("openai", "c", 5.0, 5.0))

    top_two = select_top_n_cheapest_discovered_agents([priciest, middle, cheapest], price_book, 2)
    assert top_two == [cheapest, middle]


def test_unknown_price_is_not_silently_ranked_as_free() -> None:
    from contextual_orchestrator.cost_ledger import PriceEntry

    price_book = PriceBook(InMemoryConfigStore())
    known = DiscoveredModel("openrouter", "known", "KEY_NAME", "https://openrouter.ai/api/v1", "Bearer")
    unknown = DiscoveredModel("bytez", "unknown", "KEY_NAME", "https://api.bytez.com/v1", AUTH_SCHEME_RAW_TOKEN)
    price_book.set_price(PriceEntry("openrouter", "known", 0.1, 0.1))

    assert select_cheapest_discovered_agent([unknown, known], price_book) is known
    assert select_top_n_cheapest_discovered_agents([unknown, known], price_book, 2) == [known, unknown]


def test_top_n_uses_discovery_price_before_price_book_refresh() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    expensive = DiscoveredModel(
        "openrouter",
        "priced-by-discovery",
        "KEY_NAME",
        "https://openrouter.ai/api/v1",
        "Bearer",
        prompt_price_per_1k=0.2,
        completion_price_per_1k=0.4,
    )
    cheap = replace(
        expensive,
        model_id="cheaper-by-discovery",
        prompt_price_per_1k=0.01,
        completion_price_per_1k=0.02,
    )

    assert select_top_n_cheapest_discovered_agents([expensive, cheap], price_book, 2) == [
        cheap,
        expensive,
    ]


def test_select_top_n_cheapest_discovered_agents_zero_limit_returns_empty() -> None:
    price_book = PriceBook(InMemoryConfigStore())
    model = DiscoveredModel("openai", "a", "OPENAI_API_KEY", "https://api.openai.com/v1", "Bearer")
    assert select_top_n_cheapest_discovered_agents([model], price_book, 0) == []


def test_sync_discovered_agents_adds_and_updates_idempotently() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")])
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="meta/llama-3.3",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
    )
    agent_v1 = agent_from_discovered(discovered, priority=0)

    result = orchestrator.sync_discovered_agents([agent_v1])
    assert result == {"added": ["openrouter_meta_llama_3_3"], "updated": []}
    assert {a.id for a in orchestrator.candidates} == {"seed_agent", "openrouter_meta_llama_3_3"}

    agent_v2 = agent_from_discovered(discovered, priority=7)
    result = orchestrator.sync_discovered_agents([agent_v2])
    assert result == {"added": [], "updated": ["openrouter_meta_llama_3_3"]}
    stored = next(a for a in orchestrator.candidates if a.id == "openrouter_meta_llama_3_3")
    assert stored.priority == 7
    # No duplicate rows were appended on the update pass.
    assert len(orchestrator.candidates) == 2

    orchestrator.set_model_group(
        "shared_reasoning_model", ["openrouter_meta_llama_3_3"]
    )
    orchestrator.sync_discovered_agents([agent_v1])
    stored = next(a for a in orchestrator.candidates if a.id == "openrouter_meta_llama_3_3")
    assert stored.group_name == "shared_reasoning_model"


def test_sync_discovered_agents_persists_when_agents_db_is_set(tmp_path) -> None:
    db_path = str(tmp_path / "pool.db")
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="gpt-5.5",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
    )
    agent = agent_from_discovered(discovered)

    first = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    first.sync_discovered_agents([agent])

    second = TaskOrchestrator([ModelAgent("seed_agent", "seed-model")], agents_db=db_path)
    assert any(a.id == "openai_gpt_5_5" for a in second.candidates)


_MODEL_DISCOVERY_LOGGER_NAME = "contextual_orchestrator.model_discovery"


@contextmanager
def _captured_discovery_logs(level: int) -> Iterator[io.StringIO]:
    """Attach an isolated StringIO handler to the model_discovery logger only."""
    logger = logging.getLogger(_MODEL_DISCOVERY_LOGGER_NAME)
    previous_level = logger.level
    previous_propagate = logger.propagate
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def test_discover_provider_models_debug_logs_credential_name_not_value() -> None:
    """Reconciled with main's stricter privacy contract (merge of #946 and the
    independently-landed test_discovery_debug_log_identifies_account_without_secret):
    the discovery debug logs identify the account by provider name only and
    never include the KV credential *name* (label) either, not just never its
    value.
    """
    fake_value = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture
    register_credential("OPENAI_API_KEY", fake_value)
    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            return_value=_Response({"data": [{"id": "gpt-5.5"}]}),
        ),
        _captured_discovery_logs(logging.DEBUG) as buffer,
    ):
        discover_provider_models(OPENAI_SOURCE)
    output = buffer.getvalue()
    assert "account=openai" in output
    assert "OPENAI_API_KEY" not in output
    assert fake_value not in output


def test_discover_provider_models_debug_logs_attempt_and_result() -> None:
    register_credential("OPENAI_API_KEY", "sk-router")
    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            return_value=_Response({"data": [{"id": "gpt-5.5"}, {"id": "gpt-5.5-mini"}]}),
        ),
        _captured_discovery_logs(logging.DEBUG) as buffer,
    ):
        discover_provider_models(OPENAI_SOURCE)
    output = buffer.getvalue()
    assert "discovery_attempt account=openai" in output
    assert "discovery_result account=openai model_count=2" in output


def test_discover_provider_models_debug_logs_are_silent_without_debug() -> None:
    register_credential("OPENAI_API_KEY", "sk-router")
    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            return_value=_Response({"data": [{"id": "gpt-5.5"}]}),
        ),
        _captured_discovery_logs(logging.WARNING) as buffer,
    ):
        discover_provider_models(OPENAI_SOURCE)
    assert buffer.getvalue() == ""


def test_discover_provider_models_debug_logs_failure_error_type_and_redacts_message() -> None:
    register_credential("OPENAI_API_KEY", "sk-router")
    fake_secret = "sk-FAKEFAKEFAKEFAKEFAKE1234567890"  # noqa: S105 - obviously non-functional fixture

    def urlopen(request, timeout=None, **_kwargs):
        raise urllib.error.URLError(f"connection refused api_key={fake_secret}")

    with (
        patch("contextual_orchestrator.model_discovery._open_trusted_discovery_request", side_effect=urlopen),
        _captured_discovery_logs(logging.DEBUG) as buffer,
    ):
        try:
            discover_provider_models(OPENAI_SOURCE)
        except ProviderDiscoveryError:
            pass
        else:  # pragma: no cover
            raise AssertionError("a transport failure must raise ProviderDiscoveryError")
    output = buffer.getvalue()
    assert "discovery_provider_failed account=openai" in output
    assert "error_type=URLError" in output
    assert "[REDACTED]" in output
    assert fake_secret not in output


def test_discover_all_models_logs_aggregate_summary_at_info() -> None:
    register_credential("OPENAI_API_KEY", "sk-router")
    with (
        patch(
            "contextual_orchestrator.model_discovery._open_trusted_discovery_request",
            return_value=_Response({"data": [{"id": "gpt-5.5"}]}),
        ),
        _captured_discovery_logs(logging.INFO) as buffer,
    ):
        discover_all_models((OPENAI_SOURCE,))
    output = buffer.getvalue()
    assert "discovery_complete providers=1" in output
    assert "models=" in output
    assert "errors=" in output
