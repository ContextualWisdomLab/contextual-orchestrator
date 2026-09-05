from unittest.mock import patch

from contextual_orchestrator.model_discovery import (
    PROVIDER_MODEL_SOURCES,
    _parse_openai_compatible,
    agent_from_discovered,
    discover_provider_models,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.provider_catalog_store import provider_account_id

# Go admits only models whose Models.dev entry declares the OpenAI-compatible
# adapter (``required_models_dev_npm``), and ``_parse_openai_compatible`` reads
# that decision off the ``_models_dev_npm`` field the Models.dev join writes
# onto each row. Tests that call the parser directly supply the field
# themselves, standing in for that join.
_GO_NPM = "@ai-sdk/openai-compatible"


def _go_catalog_fetch(url: str, **_kwargs: object) -> dict[str, object]:
    """Serve the Go model listing and the Models.dev catalog off one fetch stub.

    ``discover_provider_models`` fetches both through ``_fetch_json``, so a
    single ``return_value`` would hand the model listing back as the Models.dev
    catalog, leaving every row without an npm declaration and dropping the
    provider to zero admitted models.
    """
    if url == "https://models.dev/api.json":
        return {
            "opencode-go": {
                "npm": _GO_NPM,
                "models": {"glm-5.3": {}, "minimax-m3": {}},
            }
        }
    return {"data": [{"id": "glm-5.3"}, {"id": "minimax-m3"}]}


def test_go_discovery_reuses_key_without_overwriting_zen_identity() -> None:
    sources = {source.provider_name: source for source in PROVIDER_MODEL_SOURCES}
    zen, go = sources["opencode_zen"], sources["opencode_go"]
    assert go.credential_name == zen.credential_name == "OPENCODE_ZEN_API_KEY"
    assert go.list_url == "https://opencode.ai/zen/go/v1/models"
    assert provider_account_id(go) != provider_account_id(zen)

    chat, responses, messages = _parse_openai_compatible(
        {
            "data": [
                {"id": "glm-5.3", "_models_dev_npm": _GO_NPM},
                {"id": "grok-4.6", "_models_dev_npm": _GO_NPM},
                {"id": "minimax-m3", "_models_dev_npm": _GO_NPM},
            ]
        },
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
            side_effect=_go_catalog_fetch,
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
    model = _parse_openai_compatible(
        {"data": [{"id": "glm-5.3", "_models_dev_npm": _GO_NPM}]}, go
    )[0]
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
