"""OpenAI provider features remain inside multi-agent orchestration."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    _FastMLSIJudgeAdapter,
    _responses_to_chat_payload,
    _responses_text_format_to_chat_response_format,
    estimate_tokens,
)
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    build_server,
    responses_sse_body,
)


def _build(*, budget_max_output_tokens: int | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        agents=[
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning", "vision")),
            ModelAgent("disabled_builder_duplicate", "mock-builder", disabled=True),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "review")),
            ModelAgent("disabled_candidate", "disabled-model", disabled=True),
        ],
        budget_max_output_tokens=budget_max_output_tokens,
    )


# -- orchestrator-level ------------------------------------------------------

def test_responses_translation_preserves_input_image_content() -> None:
    translated = _responses_to_chat_payload(
        {
            "model": "mock-planner",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Inspect this image"},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,AA==",
                            "detail": "high",
                        },
                    ],
                }
            ],
        }
    )

    assert translated["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this image"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,AA==",
                        "detail": "high",
                    },
                },
            ],
        }
    ]


def test_final_synthesis_attaches_private_evidence_to_latest_user_turn() -> None:
    result = _build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
                {"role": "user", "content": "Current task"},
            ],
            "response_format": {"type": "json_object"},
        }
    )

    messages = result["echo"]["messages"]
    assert messages[0]["content"] == "Earlier question"
    assert messages[2]["content"].startswith("Current task")
    assert "Verified workflow evidence" in messages[2]["content"]


def test_proxy_completion_forwards_response_format_and_returns_full_shape() -> None:
    orch = _build()
    body = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "extract JSON"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        "temperature": 0.1,
        "mode": "auto",  # orchestration-only, must be stripped upstream
    }
    result = orch.proxy_completion(body)

    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["role"] == "assistant"
    # response_format + temperature forwarded; orchestration-only 'mode' stripped.
    assert result["echo"]["response_format"] == body["response_format"]
    assert result["echo"]["temperature"] == 0.1
    assert "mode" not in result["echo"]
    # model overridden to the selected agent's model.
    assert result["model"] in {"mock-planner", "mock-builder", "mock-reviewer"}
    assert result["orchestration"]["mode"] == "conduct"
    assert result["orchestration"]["agent_count"] == 4


def test_proxy_completion_forwards_tools() -> None:
    orch = _build()
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    result = orch.proxy_completion(
        {"model": "mock-planner", "messages": [{"role": "user", "content": "call a tool"}], "tools": tools}
    )
    assert result["echo"]["tools"] == tools
    assert result["orchestration"]["agent_count"] == 4


def test_proxy_completion_honors_an_enabled_requested_worker_model() -> None:
    result = _build().proxy_completion({
        "model": "mock-builder",
        "messages": [{"role": "user", "content": "call a tool"}],
        "tools": [],
    })

    assert result["model"] == "mock-builder"


def test_proxy_completion_rejects_an_unknown_requested_model() -> None:
    try:
        _build().proxy_completion({
            "model": "not-configured",
            "messages": [{"role": "user", "content": "call a tool"}],
            "tools": [],
        })
    except ValueError as exc:
        assert "not configured" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown explicit model must not silently fall back")


def test_proxy_completion_rejects_disabled_and_malformed_requested_models() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        _build().proxy_completion({
            "model": "disabled-model",
            "messages": [{"role": "user", "content": "call a tool"}],
        })

    for requested_model in (17, ""):
        with pytest.raises(ValueError, match="non-empty string"):
            _build().proxy_completion({
                "model": requested_model,
                "messages": [{"role": "user", "content": "call a tool"}],
            })


def test_proxy_completion_blocks_before_structured_workflow_when_budget_is_exceeded() -> None:
    with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
        _build(budget_max_output_tokens=0).proxy_completion(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "extract JSON"}],
                "response_format": {"type": "json_object"},
            }
        )


def test_model_client_request_settings_are_thread_local() -> None:
    client = _build().client
    previous_temperature = client.default_temperature
    barrier = threading.Barrier(2)

    def read_settings(temperature: float, max_tokens: int) -> tuple[float, int]:
        with client.request_settings(temperature=temperature, max_output_tokens=max_tokens):
            barrier.wait(timeout=5)
            values = (
                client._request_setting("temperature", client.default_temperature),
                client._request_setting("max_output_tokens", client.max_output_tokens),
            )
            barrier.wait(timeout=5)
            return values

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(read_settings, 0.1, 11),
            executor.submit(read_settings, 0.9, 29),
        ]
        assert {future.result() for future in futures} == {(0.1, 11), (0.9, 29)}

    assert client.default_temperature == previous_temperature
    assert client.max_output_tokens == 2048

    with client.request_settings(temperature=0.3):
        with client.request_settings(temperature=0.4):
            assert client._request_setting("temperature", None) == 0.4
        assert client._request_setting("temperature", None) == 0.3


def test_plain_proxy_completion_persists_reported_usage_before_next_budget_check() -> None:
    orch = _build(budget_max_output_tokens=3)
    raw = {
        "id": "chatcmpl-accounted",
        "object": "chat.completion",
        "model": "mock-planner",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "accounted"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "echo": {},
    }
    body = {
        "model": "mock-planner",
        "messages": [{"role": "user", "content": "plain passthrough"}],
    }

    with patch.object(orch.client, "proxy_send", return_value=raw) as send:
        assert orch.proxy_completion(body)["id"] == "chatcmpl-accounted"
        analytics = orch.spend_analytics()
        assert analytics["totals"]["run_count"] == 1
        assert analytics["budget"]["spent_output_tokens"] == 3
        assert analytics["by_model"] == [
            {
                "model": "mock-planner",
                "estimated_output_tokens": 3,
                "output_tokens": 3,
                "usage_source": "reported",
                "step_count": 1,
                "price_per_million_usd": None,
                "estimated_cost_usd": None,
            }
        ]
        with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
            orch.proxy_completion(body)

    assert send.call_count == 1


def test_responses_tool_loop_usage_counts_toward_the_next_budget_check() -> None:
    orch = _build(budget_max_output_tokens=3)
    raw = {
        "id": "resp_accounted",
        "object": "response",
        "model": "mock-planner",
        "output": [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "{}",
            }
        ],
        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    }
    body = {
        "model": "mock-planner",
        "input": "call the tool",
        "tools": [{"type": "function", "name": "lookup"}],
    }

    with patch.object(orch.client, "proxy_send", return_value=raw) as send:
        assert orch.proxy_completion(body, endpoint="responses", single_agent=True) is raw
        assert raw["usage"] == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
        analytics = orch.spend_analytics()
        assert analytics["totals"]["reported_prompt_tokens"] == 2
        assert analytics["budget"]["spent_output_tokens"] == 3
        assert analytics["by_model"][0]["usage_source"] == "reported"
        with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
            orch.proxy_completion(body, endpoint="responses", single_agent=True)

    assert send.call_count == 1


def test_plain_proxy_completion_accounts_a_tool_only_response() -> None:
    orch = _build()
    raw = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function"}],
                }
            }
        ]
    }

    with patch.object(orch.client, "proxy_send", return_value=raw):
        assert orch.proxy_completion(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "call the tool"}],
            },
            single_agent=True,
        ) is raw

    assert next(iter(orch._workflow_runs.values()))["answer"] == ""


def test_structured_provider_completion_rechecks_budget_before_final_provider_call() -> None:
    orch = _build()
    orch.budget_max_output_tokens = 1
    budget_states = iter(({"exceeded": False}, {"exceeded": True}))
    with patch.object(orch, "budget_status", side_effect=lambda: next(budget_states)), patch.object(
        orch,
        "conduct",
        return_value={"trace": [{"id": "worker", "role": "worker", "output": "verified"}]},
    ), patch.object(orch.client, "proxy_send") as send:
        with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
            orch.proxy_completion(
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "extract JSON"}],
                    "response_format": {"type": "json_object"},
                }
            )

    send.assert_not_called()


def test_structured_provider_completion_counts_in_flight_usage_before_synthesis() -> None:
    orch = _build(budget_max_output_tokens=1)
    workflow = {
        "trace": [{"id": 0, "agent_id": "builder_agent", "role": "worker", "output": "verified"}],
        "verification": {"accepted": True},
    }
    with patch.object(orch, "conduct", return_value=workflow), patch.object(
        orch.client, "proxy_send"
    ) as send:
        with pytest.raises(BudgetExceededError, match="spend budget exceeded"):
            orch.proxy_completion(
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "extract JSON"}],
                    "response_format": {"type": "json_object"},
                }
            )

    send.assert_not_called()


def test_structured_provider_completion_enables_model_judge_boundary() -> None:
    orch = _build()
    workflow = {
        "trace": [{"id": 0, "agent_id": "builder_agent", "role": "worker", "output": "verified"}],
        "verification": {"accepted": True},
    }
    raw = {"choices": [{"message": {"content": "{}"}}]}
    with patch.object(orch, "conduct", return_value=workflow) as conduct, patch.object(
        orch.client, "proxy_send", return_value=raw
    ):
        orch.proxy_completion(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "extract JSON"}],
                "response_format": {"type": "json_object"},
            }
        )

    assert conduct.call_args.kwargs["judge"] is True


def test_native_responses_drops_chat_only_output_budget_aliases() -> None:
    orch = _build()
    raw = {"object": "response", "output_text": "{}", "output": []}
    with patch.object(orch.client, "proxy_send", return_value=raw) as send:
        orch.proxy_completion(
            {
                "model": "mock-planner",
                "input": "extract JSON",
                "max_tokens": 11,
                "max_completion_tokens": 13,
                "max_output_tokens": 17,
                "text": {"format": {"type": "json_object"}},
            },
            endpoint="responses",
        )

    forwarded = send.call_args.args[2]
    assert "max_tokens" not in forwarded
    assert "max_completion_tokens" not in forwarded
    assert forwarded["max_output_tokens"] == 17


def test_structured_provider_completion_persists_final_synthesis_run() -> None:
    orch = _build()
    result = orch.proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "extract JSON"}],
            "response_format": {"type": "json_object"},
        }
    )

    run_id = result["orchestration"]["workflow_run_id"]
    run = orch.get_workflow_run(run_id)
    assert run["trace"][-1]["role"] == "synthesizer"
    assert run["trace"][-1]["subtask"] == "Provider-facing structured synthesis"
    assert len(run["trace"]) == 5
    assert orch.spend_analytics()["totals"]["run_count"] == 1


def test_orchestrated_responses_synthesis_normalizes_provider_usage() -> None:
    orch = _build()
    raw = {
        "object": "response",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    }
    with patch.object(
        orch,
        "conduct",
        return_value={
            "trace": [{
                "id": "worker",
                "agent_id": "worker_agent",
                "role": "worker",
                "output": "verified",
            }]
        },
    ), patch.object(orch.client, "proxy_send", return_value=raw):
        result = orch.proxy_completion(
            {
                "model": "mock-planner",
                "input": "extract JSON",
                "text": {"format": {"type": "json_object"}},
            },
            endpoint="responses",
        )

    run = orch.get_workflow_run(result["orchestration"]["workflow_run_id"])
    assert run["trace"][-1]["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "prompt_tokens": 11,
        "completion_tokens": 7,
    }


def test_orchestrated_responses_usage_counts_toward_spend_budget() -> None:
    orch = _build(budget_max_output_tokens=100)
    raw = {
        "object": "response",
        "output_text": "{}",
        "output": [],
        "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
    }

    with patch.object(orch.client, "proxy_send", return_value=raw):
        result = orch.proxy_completion(
            {
                "model": "mock-planner",
                "input": "extract JSON",
                "text": {"format": {"type": "json_object"}},
            },
            endpoint="responses",
        )

    run = orch.get_workflow_run(result["orchestration"]["workflow_run_id"])
    assert run["trace"][-1]["usage"]["prompt_tokens"] == 4
    assert run["trace"][-1]["usage"]["completion_tokens"] == 5
    expected_spend = sum(
        row.get("usage", {}).get("completion_tokens", estimate_tokens(row["output"]))
        for row in run["trace"]
    )
    assert orch.spend_analytics()["budget"]["spent_output_tokens"] == expected_spend


def test_fast_mlsirm_structured_judge_uses_one_direct_provider_call() -> None:
    orch = _build()
    orch.client.temperature = 0.4
    adapter = _FastMLSIJudgeAdapter(orch, text="judge", judge="reviewer_agent")
    provider_response = {
        "choices": [{"message": {"role": "assistant", "content": '{"decision":"pass"}'}}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }
    with patch.object(orch, "proxy_completion", side_effect=AssertionError("judge must not recurse")), patch.object(
        orch.client, "proxy_send", return_value=provider_response
    ) as send:
        result = adapter.complete_structured(
            [{"role": "user", "content": "judge this"}],
            response_format={"type": "json_object"},
        )

    send.assert_called_once()
    assert result["answer"] == '{"decision":"pass"}'
    assert send.call_args.args[1] == "chat/completions"
    assert send.call_args.args[2]["response_format"] == {"type": "json_object"}
    assert send.call_args.args[2]["temperature"] == 0.4


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ({}, None),
        ({"format": {"type": "text"}}, {"type": "text"}),
        ({"format": {"type": "xml"}}, None),
    ],
)
def test_responses_text_format_translation_handles_non_schema_shapes(
    text: object,
    expected: dict | None,
) -> None:
    assert _responses_text_format_to_chat_response_format(text) == expected


def test_structured_provider_completion_rejects_empty_messages_and_disabled_model() -> None:
    with pytest.raises(ValueError, match="non-empty messages"):
        _build().proxy_completion(
            {"messages": [], "response_format": {"type": "json_object"}}
        )
    with pytest.raises(RuntimeError, match="disabled"):
        _build().proxy_completion(
            {
                "model": "disabled-model",
                "messages": [{"role": "user", "content": "extract JSON"}],
                "response_format": {"type": "json_object"},
            }
        )


@pytest.mark.parametrize(
    ("messages", "first_role"),
    [
        ([{"role": "user", "content": None}], "user"),
        ([{"role": "assistant", "content": "prior"}], "system"),
    ],
)
def test_structured_synthesis_injects_guidance_into_non_string_histories(
    messages: list[dict],
    first_role: str,
) -> None:
    orch = _build()
    raw = {"choices": [{"message": {"content": "done"}}]}
    with patch.object(
        orch,
        "conduct",
        return_value={"trace": [], "verification": {"accepted": True}},
    ), patch.object(orch.client, "proxy_send", return_value=raw) as send:
        orch.proxy_completion(
            {
                "model": "mock-planner",
                "messages": messages,
                "response_format": {"type": "json_object"},
            }
        )

    sent_messages = send.call_args.args[2]["messages"]
    assert sent_messages[0]["role"] == first_role
    assert isinstance(sent_messages[0]["content"], str)


def test_structured_synthesis_accounts_a_tool_only_response() -> None:
    orch = _build()
    raw = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function"}],
                }
            }
        ]
    }
    with patch.object(
        orch,
        "conduct",
        return_value={"trace": [], "verification": {"accepted": True}},
    ), patch.object(orch.client, "proxy_send", return_value=raw):
        result = orch.proxy_completion(
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "call the tool"}],
                "response_format": {"type": "json_object"},
            }
        )

    assert result["orchestration"]["mode"] == "conduct"
    run = orch.get_workflow_run(result["orchestration"]["workflow_run_id"])
    assert run["answer"] == ""


def test_structured_synthesis_preserves_tool_call_adjacency() -> None:
    orch = _build()
    intermediate_messages: list[list[dict]] = []
    original_chat = orch.client.chat

    def observe_chat(agent, messages, temperature=None, top_p=None):
        del temperature, top_p
        intermediate_messages.append(messages)
        return original_chat(agent, messages)

    with patch.object(orch.client, "chat", side_effect=observe_chat):
        result = orch.proxy_completion(
            {
                "model": "mock-planner",
                "messages": [
                    {"role": "user", "content": "look up the value"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_1", "content": "42"},
                ],
                "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
            }
        )

    final_messages = result["echo"]["messages"]
    assert final_messages[0]["role"] == "user"
    assert final_messages[1]["role"] == "assistant"
    assert final_messages[2]["role"] == "tool"
    assert final_messages[1]["tool_calls"][0]["id"] == final_messages[2]["tool_call_id"]
    assert intermediate_messages and all(messages[-1]["role"] == "tool" for messages in intermediate_messages)


def test_proxy_completion_responses_endpoint_returns_response_object() -> None:
    orch = _build()
    result = orch.proxy_completion(
        {"input": "summarize the recording", "response_format": {"type": "text"}},
        endpoint="responses",
    )
    assert result["object"] == "response"
    assert result["output"][0]["role"] == "assistant"
    assert result["echo"]["response_format"] == {"type": "text"}


def test_proxy_completion_responses_json_schema_is_orchestrated_and_native() -> None:
    orch = _build()
    body = {
        "input": "extract the visible region",
        "instructions": "Keep the result concise.",
        "metadata": {"tenant": "anonymous", "omitted": None},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "region_result",
                "schema": {"type": "object"},
                "strict": True,
            }
        },
    }
    result = orch.proxy_completion(
        body,
        endpoint="responses",
    )

    assert result["object"] == "response"
    assert result["echo"]["text"] == body["text"]
    assert "response_format" not in result["echo"]
    assert result["echo"]["instructions"] == "Keep the result concise."
    assert result["echo"]["metadata"] == body["metadata"]
    assert result["orchestration"]["agent_count"] == 4
    run = orch.get_workflow_run(result["orchestration"]["workflow_run_id"])
    assert run["mode"] == "conduct"


def test_responses_structured_request_keeps_native_endpoint_and_input() -> None:
    orch = _build()
    calls: list[tuple[str, dict]] = []

    def native_response(_agent, endpoint: str, payload: dict) -> dict:
        calls.append((endpoint, payload))
        return {"object": "response", "output": [], "echo": dict(payload)}

    with patch.object(orch.client, "proxy_send", side_effect=native_response):
        result = orch.proxy_completion(
            {
                "model": "mock-planner",
                "input": [{"role": "user", "content": "extract the visible region"}],
                "instructions": "Keep the original input order.",
                "text": {"format": {"type": "json_object"}},
            },
            endpoint="responses",
        )

    assert calls[0][0] == "responses"
    assert calls[0][1]["input"] == [{"role": "user", "content": "extract the visible region"}]
    assert "Keep the original input order." in calls[0][1]["instructions"]
    assert result["orchestration"]["workflow_run_id"]


def test_structured_chat_guidance_stays_in_original_user_turn() -> None:
    result = _build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [{"role": "user", "content": "extract JSON"}],
            "response_format": {"type": "json_object"},
        }
    )
    assert result["echo"]["messages"][0]["role"] == "user"
    assert "You are the final synthesizer" in result["echo"]["messages"][0]["content"]


def test_structured_workflow_preserves_multimodal_input_for_final_synthesis() -> None:
    result = _build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}},
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
    )

    final_messages = result["echo"]["messages"]
    assert any(
        isinstance(message.get("content"), list)
        and any(part.get("type") == "image_url" for part in message["content"])
        for message in final_messages
    )
    assert final_messages[0]["role"] == "user"
    assert any(
        isinstance(part, dict) and part.get("type") == "text"
        and "You are the final synthesizer" in part.get("text", "")
        for part in final_messages[0]["content"]
    )


def test_structured_multimodal_rejects_an_explicit_text_only_model() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("text_agent", "text-model", tags=("reasoning",))]
    )

    with pytest.raises(RuntimeError, match="lacks required tags: vision"):
        orchestrator.proxy_completion(
            {
                "model": "text-model",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe this"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,fixture"},
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
            }
        )


# -- HTTP server -------------------------------------------------------------

def _post(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}", "connection": "close"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _serve() -> tuple[object, int, str]:
    token = "passthrough_token"  # noqa: S105 - synthetic HTTP fixture credential
    server = build_server(_build(), port=0, security=SecurityConfig(auth_token=token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], token


def test_http_chat_completions_orchestrates_json_object_instead_of_passthrough() -> None:
    orch = _build()
    provider_calls: list[tuple[str, dict]] = []
    original_proxy_send = orch.client.proxy_send

    def observe_provider_call(agent, endpoint: str, payload: dict) -> dict:
        provider_calls.append((endpoint, dict(payload)))
        return original_proxy_send(agent, endpoint, payload)

    with patch.object(orch.client, "proxy_send", side_effect=observe_provider_call):
        token = "structured_http_token"  # noqa: S105 - synthetic HTTP fixture credential
        server = build_server(orch, port=0, security=SecurityConfig(auth_token=token))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, body = _post(
                f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "give me JSON"}],
                    "response_format": {"type": "json_object"},
                },
                token,
            )
        finally:
            server.shutdown()
    assert status == 200
    assert body["object"] == "chat.completion"
    assert json.loads(body["choices"][0]["message"]["content"]) == {}
    assert provider_calls[-1][0] == "chat/completions"
    assert provider_calls[-1][1]["response_format"] == {"type": "json_object"}


def test_http_chat_completions_omits_model_for_orchestrator_selection() -> None:
    server, port, token = _serve()
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": "give me JSON"}],
                "response_format": {"type": "json_object"},
            },
            token,
        )
    finally:
        server.shutdown()
    assert status == 200, body
    assert body["model"] == "contextual-orchestrator"
    assert json.loads(body["choices"][0]["message"]["content"]) == {}


def test_http_structured_workflow_applies_sampling_and_records_orchestration() -> None:
    orch = _build()
    previous_temperature = orch.client.default_temperature
    seen_sampling: list[tuple[float, int]] = []
    original_chat = orch.client.chat

    def observe_chat(agent, messages, temperature=None, top_p=None):
        del top_p
        seen_sampling.append((
            orch.client._request_setting("temperature", orch.client.default_temperature),
            orch.client._request_setting("max_output_tokens", orch.client.max_output_tokens),
        ))
        return original_chat(agent, messages, temperature=temperature)

    with patch.object(orch.client, "chat", side_effect=observe_chat):
        token = "passthrough_sampling_token"  # noqa: S105 - synthetic HTTP fixture credential
        server = build_server(orch, port=0, security=SecurityConfig(auth_token=token))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, body = _post(
                f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                {
                    "model": "mock-planner",
                    "messages": [{"role": "user", "content": "give me JSON"}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                    "max_tokens": 17,
                },
                token,
            )
        finally:
            server.shutdown()

    assert status == 200, body
    assert seen_sampling and all(item == (0.7, 17) for item in seen_sampling)
    assert orch.client.default_temperature == previous_temperature
    event_names = {event["event_name"] for event in orch._analytics_events}
    assert "chat_completion_requested" in event_names
    assert "chat_completion_passthrough" not in event_names


def test_http_responses_endpoint_passes_through() -> None:
    orch = _build()
    provider_calls: list[tuple[str, dict]] = []
    original_proxy_send = orch.client.proxy_send

    def observe_provider_call(agent, endpoint: str, payload: dict) -> dict:
        provider_calls.append((endpoint, dict(payload)))
        return original_proxy_send(agent, endpoint, payload)

    request_body = {
        "model": "mock-planner",
        "input": "hello",
        "text": {"format": {"type": "json_object"}},
    }
    with patch.object(orch.client, "proxy_send", side_effect=observe_provider_call):
        token = "responses_http_token"  # noqa: S105 - synthetic HTTP fixture credential
        server = build_server(orch, port=0, security=SecurityConfig(auth_token=token))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, body = _post(
                f"http://127.0.0.1:{server.server_address[1]}/v1/responses",
                request_body,
                token,
            )
        finally:
            server.shutdown()
    assert status == 200
    assert body["object"] == "response"
    assert provider_calls[-1][0] == "responses"
    assert provider_calls[-1][1]["input"] == "hello"
    assert provider_calls[-1][1]["text"] == request_body["text"]


def test_http_models_endpoint_lists_configured_models() -> None:
    server, port, token = _serve()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/models",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "list"
    # Disabled models are omitted: an inference-scope caller should never see
    # a model it cannot actually call (matches real OpenAI API behavior).
    assert {item["id"] for item in body["data"]} == {
        "contextual-orchestrator", "mock-planner", "mock-builder", "mock-reviewer"
    }


def test_responses_stream_has_completion_event() -> None:
    body = {
        "id": "resp_test",
        "object": "response",
        "status": "completed",
        "output": [{
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "OK", "annotations": []}],
        }],
    }
    stream = responses_sse_body(body)
    assert "event: response.output_text.delta" in stream
    assert '"delta": "OK"' in stream
    assert "event: response.completed" in stream
    assert stream.endswith("data: [DONE]\n\n")


def test_http_plain_prompt_still_uses_orchestration_path() -> None:
    server, port, token = _serve()
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    try:
        status, body = _post(url, {"model": "mock-planner", "messages": [{"role": "user", "content": "hi"}]}, token)
    finally:
        server.shutdown()
    assert status == 200
    assert body["object"] == "chat.completion"
    assert "echo" not in body  # ordinary orchestration path
    assert "orchestration" in body
