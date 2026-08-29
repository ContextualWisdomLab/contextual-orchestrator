"""Regression coverage for isolating non-chat models from chat agent discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.chat_capability import (  # noqa: E402
    is_chat_compatible_model_id,
)
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.cost_ledger import PriceBook, PriceEntry  # noqa: E402
from contextual_orchestrator.kv_config import InMemoryConfigStore  # noqa: E402
from contextual_orchestrator import provider_bootstrap, review_gateway  # noqa: E402
from contextual_orchestrator.model_discovery import (  # noqa: E402
    DiscoveredModel,
    ProviderModelSource,
    agent_from_discovered,
    discover_provider_models,
    refresh_price_book,
    select_cheapest_discovered_agent,
    select_top_n_cheapest_discovered_agents,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


class _Response:
    """Small context-managed HTTP response used by the offline regression."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _fresh_credential_backend():
    """Keep the provider credential registry isolated between tests."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _model(model_id: str, *, priced: bool = False) -> DiscoveredModel:
    """Build one synthetic discovered model for capability-boundary tests."""
    return DiscoveredModel(
        provider_name="enterprise_gateway",
        model_id=model_id,
        credential_name="GATEWAY_API_KEY",
        chat_base_url="https://gateway.example.test/v1",
        auth_scheme="Bearer",
        prompt_price_per_1k=1.0 if priced else None,
        completion_price_per_1k=1.0 if priced else None,
    )


def _agent(
    agent_id: str,
    model_id: str,
    *,
    priority: int = 0,
    tags: tuple[str, ...] = ("writing",),
) -> ModelAgent:
    """Build one mock-backed runtime agent for selection-path regressions."""
    return ModelAgent(
        id=agent_id,
        model=model_id,
        base_url="mock://local",
        priority=priority,
        tags=tags,
    )


def test_embedding_deployments_never_enter_chat_agent_discovery() -> None:
    """Exclude the exact Azure embedding deployment seen in synthesis alerts."""
    register_credential("GATEWAY_API_KEY", "gateway-secret")
    source = ProviderModelSource(
        provider_name="enterprise_gateway",
        credential_name="GATEWAY_API_KEY",
        list_url="https://gateway.example.test/v1/models",
        chat_base_url="https://gateway.example.test/v1",
    )
    payload = {
        "data": [
            {"id": "azure/text-embedding-3-large"},
            {"id": "text_embedding_3_large"},
            {"id": "BAAI/bge-m3"},
            {"id": "openai/whisper-1"},
            {"id": "gpt-4o-mini-transcribe"},
            {"id": "text-moderation-latest"},
            {"id": "company/reranker-v2"},
            {"id": "nvidia/llama-3.1-nemotron-safety-guard-8b-v3"},
            {"id": "gpt-audio"},
            {"id": "gpt-5.2"},
            {"id": "qwen/qwen3-235b-a22b-instruct"},
        ]
    }

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == [
        "gpt-audio",
        "gpt-5.2",
        "qwen/qwen3-235b-a22b-instruct",
    ]


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        (None, False),
        ("", False),
        ("---", False),
        ("vendor/embeddingv2", False),
        ("vendor/reranking-v2", False),
        ("vendor/transcriber-v2", False),
        ("gpt-5.2", True),
        ("qwen/qwen3-instruct", True),
    ],
)
def test_chat_compatibility_normalizes_identifiers(
    model_id: object, expected: bool
) -> None:
    """Normalize provider prefixes and separators without guessing chat features."""
    assert is_chat_compatible_model_id(model_id) is expected  # type: ignore[arg-type]


def test_bytez_chat_catalog_still_rejects_non_chat_identifiers() -> None:
    """Apply the same boundary even when a provider accepts a chat task filter."""
    register_credential("BYTEZ_API_KEY", "bytez-secret")
    source = ProviderModelSource(
        provider_name="bytez",
        credential_name="BYTEZ_API_KEY",
        list_url="https://api.bytez.com/models/v2/list/models",
        chat_base_url="https://api.bytez.com/models/v2/openai/v1",
        auth_scheme="Key",
        style="bytez",
        task_filter="chat",
    )
    payload = {
        "output": [
            {"modelId": "vendor/embeddingv2"},
            {"modelId": "vendor/chat-instruct"},
        ]
    }

    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == ["vendor/chat-instruct"]


def test_non_chat_discovery_cannot_be_converted_to_agent() -> None:
    """Keep manually constructed discovery rows from bypassing the parser filter."""
    with pytest.raises(ValueError, match="general chat agent"):
        agent_from_discovered(_model("azure/text-embedding-3-large"))


def test_non_chat_discovery_is_not_priced_or_selected_for_chat() -> None:
    """Keep price routing from reintroducing an incompatible endpoint model."""
    price_book = PriceBook(InMemoryConfigStore())
    embedding_model = _model("azure/text-embedding-3-large", priced=True)
    chat_model = _model("gpt-5.2", priced=True)
    price_book.set_price(PriceEntry("enterprise_gateway", "gpt-5.2", 1.0, 1.0))

    assert refresh_price_book([embedding_model, chat_model], price_book) == 1
    assert price_book.get_price(
        "enterprise_gateway", "azure/text-embedding-3-large"
    ) is None
    assert select_cheapest_discovered_agent([embedding_model], price_book) is None
    assert select_top_n_cheapest_discovered_agents(
        [embedding_model], price_book, 1
    ) == []


def test_generic_media_catalog_rows_stay_out_of_bootstrap_and_review_chat_pool(
    monkeypatch,
) -> None:
    """Explicit media metadata beats a generic model-id heuristic everywhere."""
    register_credential("NVIDIA_NIM_API_KEY", "nim-secret")
    source = ProviderModelSource(
        provider_name="nvidia_nim",
        credential_name="NVIDIA_NIM_API_KEY",
        list_url="https://integrate.api.nvidia.com/v1/models",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        capabilities=("chat",),
    )
    payload = {
        "data": [
            {
                "id": "text-free-model",
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {"output_modalities": ["text"]},
            },
            {
                "id": "wan-3.0",
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {"output_modalities": ["video"]},
            },
            {
                "id": "avatar-iv",
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {"output_modalities": ["image"]},
            },
        ]
    }
    with patch(
        "contextual_orchestrator.model_discovery.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        discovered = discover_provider_models(source)

    assert [model.model_id for model in discovered] == [
        "text-free-model",
        "wan-3.0",
        "avatar-iv",
    ]
    assert [
        model.model_id
        for model in discovered
        if provider_bootstrap.is_chat_serving_candidate(model)
    ] == ["text-free-model"]
    assert [
        model.model_id
        for model in provider_bootstrap.select_provider_diverse_models(
            discovered, limit=10
        )
    ] == ["text-free-model"]

    monkeypatch.setattr(
        review_gateway,
        "discover_all_models",
        lambda: (discovered, []),
    )
    review_orchestrator = review_gateway.build_review_orchestrator(
        {"OPENAI_API_KEY": "review-secret"}, max_agents=10
    )
    assert [agent.model for agent in review_orchestrator.agents] == [
        "text-free-model"
    ]


def test_stale_embedding_agent_cannot_win_synthesizer_selection() -> None:
    """Exclude an already-persisted embedding row even when it has high priority."""
    embedding_agent = _agent(
        "embedding_agent",
        "azure/text-embedding-3-large",
        priority=10_000,
    )
    chat_agent = _agent("chat_agent", "gpt-5.2")
    orchestrator = TaskOrchestrator([embedding_agent, chat_agent])

    assert orchestrator._select_agent("Produce the final answer.", "synthesizer") is chat_agent


def test_all_non_chat_agents_fail_before_synthesis() -> None:
    """Fail closed when a stale pool contains no chat-compatible worker."""
    orchestrator = TaskOrchestrator(
        [_agent("embedding_agent", "azure/text-embedding-3-large")]
    )

    with pytest.raises(RuntimeError, match="chat-compatible"):
        orchestrator._select_agent("Produce the final answer.", "synthesizer")


def test_generated_plan_reselects_non_chat_agent_assignment() -> None:
    """Do not trust a generated plan that names a stale embedding agent directly."""
    embedding_agent = _agent(
        "embedding_agent",
        "azure/text-embedding-3-large",
        priority=10_000,
    )
    chat_agent = _agent("chat_agent", "gpt-5.2")
    orchestrator = TaskOrchestrator([embedding_agent, chat_agent])
    raw_plan = json.dumps(
        {
            "steps": [
                {
                    "id": 0,
                    "role": "worker",
                    "agent_id": "chat_agent",
                    "subtask": "Execute the task.",
                    "access": [],
                },
                {
                    "id": 1,
                    "role": "synthesizer",
                    "agent_id": "embedding_agent",
                    "subtask": "Produce the final answer.",
                    "access": [0],
                },
            ]
        }
    )

    steps = orchestrator._parse_workflow_plan(raw_plan)

    assert steps[-1].agent_id == "chat_agent"


def test_failover_candidates_exclude_stale_embedding_agents() -> None:
    """Keep cross-agent retry from falling through to an incompatible endpoint."""
    chat_agent = _agent("chat_agent", "gpt-5.2")
    embedding_agent = _agent(
        "embedding_agent",
        "azure/text-embedding-3-large",
        priority=10_000,
    )
    orchestrator = TaskOrchestrator([chat_agent, embedding_agent])

    candidates = orchestrator._failover_candidates(
        chat_agent,
        "Produce the final answer.",
        "synthesizer",
    )

    assert candidates == [chat_agent]


def test_invoke_fails_clearly_when_no_general_chat_agent_remains() -> None:
    """Report the role boundary instead of claiming that zero candidates failed."""
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")
    orchestrator = TaskOrchestrator([embedding_agent])

    with pytest.raises(RuntimeError, match="no chat-compatible agent available"):
        orchestrator._invoke(
            embedding_agent,
            [{"role": "user", "content": "Produce the final answer."}],
            text="Produce the final answer.",
            role="worker",
        )


def test_model_client_rejects_non_chat_model_before_mock_or_network_call() -> None:
    """Keep the provider boundary fail-closed even when selection is bypassed."""
    client = ModelClient()
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")

    with pytest.raises(ValueError, match="chat-compatible"):
        client.chat(
            embedding_agent,
            [{"role": "user", "content": "Produce the final answer."}],
        )


def test_non_chat_primary_fails_over_only_to_chat_agents() -> None:
    """Drop an incompatible primary while retaining a compatible fallback."""
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")
    chat_agent = _agent("chat_agent", "gpt-5.2")
    orchestrator = TaskOrchestrator([embedding_agent, chat_agent])

    candidates = orchestrator._failover_candidates(
        embedding_agent,
        "Produce the final answer.",
        "synthesizer",
    )

    assert candidates == [chat_agent]


def test_streaming_client_rejects_non_chat_model_before_transport() -> None:
    """Apply the same endpoint boundary to streaming chat requests."""
    client = ModelClient()
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")

    with pytest.raises(ValueError, match="chat-compatible"):
        next(
            client.stream_chat(
                embedding_agent,
                [{"role": "user", "content": "Produce the final answer."}],
            )
        )


def test_probe_reports_non_chat_model_without_provider_transport(monkeypatch) -> None:
    """Readiness must fail closed with a stable code before network access."""
    client = ModelClient()
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")
    monkeypatch.setattr(
        client,
        "_validate_provider",
        lambda _agent: (_ for _ in ()).throw(AssertionError("transport reached")),
    )

    assert client.probe(embedding_agent)["failure_code"] == "non_chat_model"


def test_generated_planner_inventory_excludes_non_chat_agents() -> None:
    """Do not advertise stale endpoint-incompatible agents to the planner."""
    embedding_agent = _agent("embedding_agent", "azure/text-embedding-3-large")
    chat_agent = _agent("chat_agent", "gpt-5.2", tags=("reasoning", "writing"))

    class PlannerClient:
        def __init__(self) -> None:
            self.system_prompt = ""

        def chat(self, _agent, messages, **_kwargs):
            self.system_prompt = messages[0]["content"]
            return json.dumps(
                {
                    "steps": [
                        {
                            "id": 0,
                            "role": "worker",
                            "agent_id": "chat_agent",
                            "subtask": "Execute the task.",
                            "access": [],
                        },
                        {
                            "id": 1,
                            "role": "synthesizer",
                            "agent_id": "chat_agent",
                            "subtask": "Produce the answer.",
                            "access": [0],
                        },
                    ]
                }
            )

    client = PlannerClient()
    orchestrator = TaskOrchestrator([embedding_agent, chat_agent], client=client)

    steps = orchestrator._plan_generated("Produce the final answer.")

    assert steps[-1].agent_id == "chat_agent"
    assert "embedding_agent" not in client.system_prompt
    assert "azure/text-embedding-3-large" not in client.system_prompt
    assert "chat_agent" in client.system_prompt


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
