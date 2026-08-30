"""Model discovery: KV-driven provider model listing, offline via mocked HTTP."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
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
                credential_name="KEY_B",
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
                credential_name="KEY_B",
                chat_base_url="https://gateway.example/v1",
                auth_scheme="Bearer",
                zdr_capable=False,
            ),
        ]
    )

    assert len(discovered) == 1
    assert discovered[0].zdr_capable is False


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

    def read(self) -> bytes:
        return self._body


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
    auth_scheme="Key",
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(OPENROUTER_SOURCE)

    assert [model.model_id for model in discovered] == ["vendor/free-model", "paid/model", "request-fee/model"]
    assert [model.model_id for model in free_discovered_models(discovered)] == ["vendor/free-model"]
    assert agent_from_discovered(replace(discovered[0], evidence_only=False)).group_name == ""


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

    def urlopen(request, timeout=None):
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "vendor/paid-free"}]})

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        captured.append(request)
        return _Response({"data": []})

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
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
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        if request.full_url == "https://models.dev/api.json":
            raise urllib.error.URLError("offline")
        return _Response({"data": [{"id": "meta/llama-3.1-8b-instruct"}]})

    sources = tuple(
        item
        for item in PROVIDER_MODEL_SOURCES
        if item.provider_name in {"nvidia_nim", "nvidia_nim_sub"}
    )
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        side_effect=urlopen,
    ):
        discovered, errors = discover_all_models(sources)

    assert errors == []
    assert [model.is_free for model in discovered] == [False, False]


def test_discover_all_models_leaves_bytez_unaffected_and_skips_models_dev() -> None:
    """Bytez has no Models.dev coverage; it must never trigger the shared fetch."""
    register_credential("BYTEZ_API_KEY", "bytez-key")
    models_dev_calls = []

    def urlopen(request, timeout=None):
        if request.full_url == "https://models.dev/api.json":
            models_dev_calls.append(request.full_url)
            return _Response({})
        return _Response(
            {"output": [{"modelId": "0-hero/Matter-0.1-Slim-7B-C", "task": "chat"}]}
        )

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        seen_requests.append(request)
        return _Response(payload)

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        discovered = discover_provider_models(BYTEZ_SOURCE)

    assert seen_requests[0].get_header("Authorization") == "Key bytez-secret"
    assert seen_requests[0].full_url == "https://api.bytez.com/models/v2/list/models?task=chat"
    assert len(discovered) == 1
    assert discovered[0].model_id == "0-hero/Matter-0.1-Slim-7B-C"
    assert discovered[0].auth_scheme == "Key"
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
        auth_scheme="Key",
        style="bytez",
        capabilities=("embedding",),
    )

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response({"output": [{"modelId": "embedding-deployment"}]}),
    ):
        discovered = discover_provider_models(source)

    assert discovered[0].capabilities == ("embedding",)


def test_discover_all_models_continues_after_one_provider_error() -> None:
    register_credential("OPENAI_API_KEY", "sk-openai")
    register_credential("OPENROUTER_API_KEY", "sk-router")

    def urlopen(request, timeout=None):
        if urllib.parse.urlsplit(request.full_url).hostname == "api.openai.com":
            raise urllib.error.URLError("connection refused")
        return _Response({"data": [{"id": "meta/llama-3.3"}]})

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
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

    def urlopen(request, timeout=None):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "openai/shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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

    def urlopen(request, timeout=None):
        if request.full_url == other_source.list_url:
            return _Response({"data": [{"id": "shared-model"}]})
        return _Response({"data": [{"id": "openai/shared-model"}]})

    with (
        patch(
            "contextual_orchestrator.model_discovery.urllib.request.urlopen",
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
    provider transport diagnostics to discovery callers.
    """
    register_credential("OPENAI_API_KEY", "sk-openai")

    def urlopen(request, timeout=None):
        raise ConnectionResetError(104, "Connection reset by peer")

    with patch("contextual_orchestrator.model_discovery.urllib.request.urlopen", side_effect=urlopen):
        try:
            discover_provider_models(OPENAI_SOURCE)
        except ProviderDiscoveryError as error:
            assert error.provider_name == "openai"
            assert error.error_code == "transport_error"
            assert "reset" not in str(error)
            assert error.__cause__ is None
        else:  # pragma: no cover
            raise AssertionError("a raw connection reset must become a ProviderDiscoveryError")


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
        auth_scheme="Key",
    )
    agent = agent_from_discovered(discovered, priority=3)
    assert agent.id == "bytez_0_hero_matter_0_1_slim_7b_c"
    assert agent.disabled is True
    assert agent.auth_scheme == "Key"
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
        auth_scheme="Key",
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
    unknown = DiscoveredModel("bytez", "unknown", "KEY_NAME", "https://api.bytez.com/v1", "Key")
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
