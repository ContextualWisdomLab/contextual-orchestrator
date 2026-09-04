from unittest.mock import patch

from contextual_orchestrator.model_discovery import (
    PROVIDER_MODEL_SOURCES,
    _parse_openai_compatible,
    agent_from_discovered,
    discover_provider_models,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_catalog_store import provider_account_id


def test_go_discovery_reuses_key_without_overwriting_zen_identity() -> None:
    sources = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}
    zen, go = sources["opencode_zen"], sources["opencode_go"]
    assert go.credential_name == zen.credential_name == "OPENCODE_ZEN_API_KEY"
    assert go.list_url == "https://opencode.ai/zen/go/v1/models"
    assert provider_account_id(go) != provider_account_id(zen)

    chat, responses, messages = _parse_openai_compatible(
        {"data": [{"id": "glm-5.3"}, {"id": "grok-4.6"}, {"id": "minimax-m3"}]},
        go,
    )
    assert chat.evidence_only is False
    assert responses.evidence_only is True
    assert messages.evidence_only is True

    with (
        patch(
            "contextual_orchestrator.model_discovery.get_credential", return_value="key"
        ),
        patch(
            "contextual_orchestrator.model_discovery._fetch_json",
            return_value={"data": [{"id": "glm-5.3"}, {"id": "minimax-m3"}]},
        ),
    ):
        discovered = discover_provider_models(go)
    assert [model.evidence_only for model in discovered] == [False, True]


def test_go_chat_model_reuses_existing_responses_conversion() -> None:
    go = next(
        source
        for source in PROVIDER_MODEL_SOURCES
        if source.provider_name == "opencode_go"
    )
    model = _parse_openai_compatible({"data": [{"id": "glm-5.3"}]}, go)[0]
    agent = agent_from_discovered(model)
    client = ModelClient()
    upstream = {
        "id": "chat_1",
        "model": "glm-5.3",
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with (
        patch.object(client, "_validate_provider", return_value=None),
        patch.object(client, "_send_raw_with_retry", return_value=upstream) as send,
    ):
        result = client.proxy_send(
            agent, "responses", {"model": "glm-5.3", "input": "hi"}
        )
    assert send.call_args.args[1] == "chat/completions"
    assert result["output_text"] == "ok"
