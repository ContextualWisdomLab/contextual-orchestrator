"""orchestrator/free image parts must use image-capable free agents or fail closed.

Synthetic DOCX/HWPX figure review sends text + image_url parts on
``orchestrator/free``. A text-only free agent must not absorb that traffic and
return a 200 that silently ignores figures. Coverage is local/mock only — no
research document upload.

Also composes issue #940 tool-call admission: image entitlement is an additional
predicate, never a replacement for ``tool_call:single`` exclusion on multi-tool
/ ``parallel_tool_calls: true`` requests.
"""

from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any

import pytest

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server

_TEST_AUTH_TOKEN = "review_free_multimodal_image_failclosed_token"  # noqa: S105

# 1x1 PNG — synthetic figure bytes, not a research artifact.
_TINY_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_IMAGE_FREE_TAGS = (
    "cost:free",
    "reasoning",
    "writing",
    "input:text",
    "input:image",
    "output:text",
)


def _post(port: int, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_raw(port: int, payload: dict) -> tuple[int, str, bytes]:
    """Return the HTTP status and media type without assuming a JSON response."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
            "connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return (
                response.status,
                response.headers.get_content_type(),
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.headers.get_content_type(), exc.read()


def _serve(orchestrator: TaskOrchestrator):
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN, rate_limit_requests=10_000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _figure_payload(*, model: str = TaskOrchestrator.FREE_MODEL) -> dict:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Review table 1 and figure 1 in this synthetic paper excerpt.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": _TINY_PNG_DATA_URI},
                    },
                ],
            }
        ],
    }


def _figure_messages() -> list[dict[str, Any]]:
    return _figure_payload()["messages"]


class _SequencedProxyClient:
    """Record proxy attempts without network I/O."""

    def __init__(self, outcomes: dict[str, dict[str, Any] | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def proxy_send_once(
        self, agent: ModelAgent, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del endpoint
        self.calls.append((agent.id, deepcopy(payload)))
        outcome = self.outcomes[agent.id]
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(outcome)

    proxy_send = proxy_send_once


def _image_free_pool_with_tool_evidence(
    client: _SequencedProxyClient,
    *,
    primary_tool_tags: tuple[str, ...],
    fallback_tool_tags: tuple[str, ...] = ("tool_call:multi",),
) -> TaskOrchestrator:
    """Two free image-capable agents; primary carries the given tool-call evidence."""
    primary = ModelAgent(
        "primary_vision",
        "primary-vision-model",
        priority=10,
        provider_name="primary",
        tags=(*_IMAGE_FREE_TAGS, *primary_tool_tags),
        base_url="mock://primary",
    )
    fallback = ModelAgent(
        "fallback_vision",
        "fallback-vision-model",
        priority=1,
        provider_name="fallback",
        tags=(*_IMAGE_FREE_TAGS, *fallback_tool_tags),
        base_url="mock://fallback",
    )
    return TaskOrchestrator([primary, fallback], client=client)


def _two_tool_figure_request(**extra: Any) -> dict[str, Any]:
    return {
        "model": TaskOrchestrator.FREE_MODEL,
        "messages": _figure_messages(),
        "tools": [
            {"type": "function", "function": {"name": "inspect", "description": "x"}},
            {"type": "function", "function": {"name": "scan", "description": "y"}},
        ],
        **extra,
    }


def _one_tool_figure_request(**extra: Any) -> dict[str, Any]:
    return {
        "model": TaskOrchestrator.FREE_MODEL,
        "messages": _figure_messages(),
        "tools": [
            {"type": "function", "function": {"name": "inspect", "description": "x"}},
        ],
        **extra,
    }


def test_free_image_request_fails_closed_when_only_text_free_agents_exist() -> None:
    """Text-only free pool must not succeed on figure-bearing free traffic."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "mock-text-free",
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
                base_url="mock://text",
            )
        ]
    )
    server, thread, port = _serve(orchestrator)
    try:
        status, body = _post(port, _figure_payload())
        assert status == 400, body
        blob = json.dumps(body).casefold()
        assert "input:image" in blob or "required tags" in blob
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_free_image_stream_fails_before_sse_when_only_text_free_agents_exist() -> None:
    """Image admission must fail before a streaming HTTP 200 is committed."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "mock-text-free",
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
                base_url="mock://text",
            )
        ]
    )
    server, thread, port = _serve(orchestrator)
    try:
        payload = _figure_payload()
        payload["stream"] = True
        status, media_type, body = _post_raw(port, payload)
        assert status == 400, body
        assert media_type != "text/event-stream"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_free_image_request_serves_image_capable_free_agent() -> None:
    """When a free text+image agent exists, figure-bearing free traffic reaches it."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "mock-text-free",
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
                base_url="mock://text",
            ),
            ModelAgent(
                "vision_free",
                "mock-vision-free",
                tags=_IMAGE_FREE_TAGS,
                base_url="mock://vision",
            ),
        ]
    )
    server, thread, port = _serve(orchestrator)
    try:
        status, body = _post(port, _figure_payload())
        assert status == 200, body
        served = body.get("model") or ""
        assert "vision" in served or body.get("choices"), body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_text_only_free_request_still_excludes_vision_free_agent() -> None:
    """Blind free text traffic must not select a non-text-input free deployment."""
    vision = ModelAgent(
        "vision_free",
        "mock-vision-free",
        tags=_IMAGE_FREE_TAGS,
        base_url="mock://vision",
    )
    text = ModelAgent(
        "text_free",
        "mock-text-free",
        tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
        base_url="mock://text",
    )
    orchestrator = TaskOrchestrator([vision, text])
    assert not orchestrator._is_general_free_agent(vision)
    assert orchestrator._is_general_free_agent(text)
    free_text_ids = orchestrator._free_pool_agent_ids(
        messages=[{"role": "user", "content": "text only review"}]
    )
    assert free_text_ids == {"text_free"}
    free_image_ids = orchestrator._free_pool_agent_ids(
        messages=_figure_messages()
    )
    assert free_image_ids == {"vision_free"}


@pytest.mark.parametrize("part_type", ["input_image", " Image_Url "])
def test_free_image_aliases_enter_image_pool_before_validation(part_type: str) -> None:
    """Accepted chat aliases must carry image entitlement during preflight."""
    vision = ModelAgent(
        "vision_free",
        "mock-vision-free",
        tags=_IMAGE_FREE_TAGS,
        base_url="mock://vision",
    )
    text = ModelAgent(
        "text_free",
        "mock-text-free",
        tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
        base_url="mock://text",
    )
    messages = _figure_messages()
    messages[0]["content"][1]["type"] = part_type

    assert TaskOrchestrator([vision, text])._free_pool_agent_ids(messages=messages) == {
        "vision_free"
    }


def test_free_image_pool_excludes_disabled_vision_agent() -> None:
    """A disabled image agent must not make preflight appear serviceable."""
    disabled = ModelAgent(
        "disabled_vision",
        "disabled-vision-model",
        tags=_IMAGE_FREE_TAGS,
        disabled=True,
    )

    assert TaskOrchestrator([disabled])._free_pool_agent_ids(
        messages=_figure_messages()
    ) == set()


def test_free_image_pool_skips_single_tool_agent_for_multi_tool_request() -> None:
    """Image entitlement must not reopen #940 for multi-tool figure traffic."""
    client = _SequencedProxyClient(
        {
            "primary_vision": {"model": "primary-vision-model"},
            "fallback_vision": {"model": "fallback-vision-model"},
        }
    )
    orchestrator = _image_free_pool_with_tool_evidence(
        client, primary_tool_tags=("tool_call:single",)
    )

    result = orchestrator.proxy_completion(_two_tool_figure_request())

    assert result["model"] == "fallback-vision-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_vision"]


def test_free_image_pool_skips_single_tool_agent_when_parallel_calls_requested() -> None:
    """Explicit parallel_tool_calls:true excludes tool_call:single image free agents."""
    client = _SequencedProxyClient(
        {
            "primary_vision": {"model": "primary-vision-model"},
            "fallback_vision": {"model": "fallback-vision-model"},
        }
    )
    orchestrator = _image_free_pool_with_tool_evidence(
        client, primary_tool_tags=("tool_call:single",)
    )

    result = orchestrator.proxy_completion(
        _one_tool_figure_request(parallel_tool_calls=True)
    )

    assert result["model"] == "fallback-vision-model"
    assert [agent_id for agent_id, _ in client.calls] == ["fallback_vision"]


@pytest.mark.parametrize(
    "body",
    [
        _one_tool_figure_request(),
        _two_tool_figure_request(parallel_tool_calls=False),
    ],
    ids=["single_tool_without_flag", "parallel_calls_disabled"],
)
def test_free_image_pool_keeps_single_tool_agent_for_single_call_shapes(
    body: dict[str, Any],
) -> None:
    """Shapes no provider evidence rejects keep the single-call image agent eligible."""
    client = _SequencedProxyClient(
        {
            "primary_vision": {"model": "primary-vision-model"},
            "fallback_vision": {"model": "fallback-vision-model"},
        }
    )
    orchestrator = _image_free_pool_with_tool_evidence(
        client, primary_tool_tags=("tool_call:single",)
    )

    result = orchestrator.proxy_completion(body)

    assert result["model"] == "primary-vision-model"
    assert [agent_id for agent_id, _ in client.calls] == ["primary_vision"]


def test_free_image_pool_fails_closed_when_only_single_tool_image_agent_exists() -> None:
    """Only a doomed tool_call:single image free agent must fail before provider I/O."""
    client = _SequencedProxyClient(
        {"solo_vision": {"model": "solo-vision-model"}}
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "solo_vision",
                "solo-vision-model",
                tags=(*_IMAGE_FREE_TAGS, "tool_call:single"),
                base_url="mock://solo",
            )
        ],
        client=client,
    )

    with pytest.raises(RuntimeError, match="no eligible provider candidate"):
        orchestrator.proxy_completion(_two_tool_figure_request())

    assert client.calls == []


def test_free_image_pool_ids_compose_tool_call_exclusion() -> None:
    """Direct pool query excludes tool_call:single under multi-tool image shape."""
    single = ModelAgent(
        "single_vision",
        "single-vision",
        tags=(*_IMAGE_FREE_TAGS, "tool_call:single"),
        base_url="mock://single",
    )
    multi = ModelAgent(
        "multi_vision",
        "multi-vision",
        tags=(*_IMAGE_FREE_TAGS, "tool_call:multi"),
        base_url="mock://multi",
    )
    orchestrator = TaskOrchestrator([single, multi])
    body = _two_tool_figure_request()
    ids = orchestrator._free_pool_agent_ids(
        messages=body["messages"], chat_body=body
    )
    assert ids == {"multi_vision"}
    eligible = orchestrator._free_pool_agent_ids(
        messages=body["messages"],
        chat_body=_one_tool_figure_request(),
    )
    assert eligible == {"single_vision", "multi_vision"}


def test_responses_free_image_request_routes_to_image_agent() -> None:
    """Responses image parts must survive conversion into free-pool admission."""
    client = _SequencedProxyClient(
        {
            "text_free": {"model": "text-only-model", "output": []},
            "vision_free": {"model": "vision-model", "output": []},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "text_free",
                "text-only-model",
                priority=10,
                tags=("cost:free", "reasoning", "writing", "input:text", "output:text"),
            ),
            ModelAgent(
                "vision_free",
                "vision-model",
                tags=_IMAGE_FREE_TAGS,
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        {
            "model": TaskOrchestrator.FREE_MODEL,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Review this figure."},
                        {"type": "input_image", "image_url": _TINY_PNG_DATA_URI},
                    ],
                }
            ],
        },
        endpoint="responses",
        single_agent=True,
    )

    assert result["model"] == "vision-model"
    assert [agent_id for agent_id, _ in client.calls] == ["vision_free"]


def test_free_image_template_plan_selects_image_agents() -> None:
    """Every template role must retain the request's image requirement."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "vision_free",
                "vision-model",
                tags=(*_IMAGE_FREE_TAGS, "planning", "research", "verification"),
            )
        ]
    )

    steps = orchestrator._plan(
        "Review this figure.",
        model_name=TaskOrchestrator.FREE_MODEL,
        required_tags=("input:image",),
    )

    assert {step.agent_id for step in steps} == {"vision_free"}


def test_realtime_route_judge_preserves_image_requirement() -> None:
    """Direct-route verification must judge an image answer with an image-capable model."""
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "vision_free",
                "vision-model",
                tags=(*_IMAGE_FREE_TAGS, "verification"),
            )
        ]
    )
    captured: dict[str, Any] = {}

    def judge(
        text: str,
        report: dict[str, Any],
        *,
        free_only: bool = False,
        allowed_agent_ids: set[str] | None = None,
        required_tags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        del text, report, free_only, allowed_agent_ids
        captured["required_tags"] = required_tags
        return {
            "accepted": True,
            "reason": "image-capable judge",
            "verifier_output": "accepted",
            "judge": "model",
        }

    orchestrator._model_judge_verification = judge  # type: ignore[method-assign]

    verdict = orchestrator._realtime_route_judge(
        text="Review this figure.",
        answer="The figure contains one point.",
        served_id="vision_free",
        latency_seconds=0.01,
        usage=None,
        free_only=True,
        required_tags=("input:image",),
    )

    assert verdict["accepted"] is True
    assert captured["required_tags"] == ("input:image",)


def test_proxy_image_failover_excludes_text_only_agent() -> None:
    """A failed image primary must fail over only within the image-capable pool."""
    request_too_large = urllib.error.HTTPError(
        "https://provider.invalid/v1/chat/completions",
        413,
        "request too large",
        {},
        io.BytesIO(b'{"error":{"message":"request too large"}}'),
    )
    client = _SequencedProxyClient(
        {
            "primary_vision": request_too_large,
            "text_free": {"model": "text-only-model"},
            "fallback_vision": {"model": "fallback-vision-model"},
        }
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "primary_vision",
                "primary-vision-model",
                priority=20,
                tags=_IMAGE_FREE_TAGS,
                provider_name="primary",
            ),
            ModelAgent(
                "text_free",
                "text-only-model",
                priority=10,
                tags=("cost:free", "input:text", "output:text"),
                provider_name="text",
            ),
            ModelAgent(
                "fallback_vision",
                "fallback-vision-model",
                priority=1,
                tags=_IMAGE_FREE_TAGS,
                provider_name="fallback",
            ),
        ],
        client=client,
    )

    result = orchestrator.proxy_completion(
        _figure_payload(model=TaskOrchestrator.AUTO_MODEL)
    )

    assert result["model"] == "fallback-vision-model"
    assert [agent_id for agent_id, _ in client.calls] == [
        "primary_vision",
        "fallback_vision",
    ]


def test_runtime_image_pool_requires_text_and_image_input() -> None:
    """Mixed figure review must reject durable agents that declare image-only input."""
    image_only = ModelAgent(
        "image_only",
        "image-only-model",
        priority=10,
        tags=("cost:free", "input:image", "output:text"),
    )
    text_and_image = ModelAgent(
        "text_and_image",
        "text-and-image-model",
        tags=_IMAGE_FREE_TAGS,
    )
    orchestrator = TaskOrchestrator([image_only, text_and_image])

    assert not orchestrator._is_image_capable_free_agent(image_only)
    assert orchestrator._free_pool_agent_ids(messages=_figure_messages()) == {
        "text_and_image"
    }


def test_runtime_image_pool_preserves_legacy_vision_admission() -> None:
    """Legacy vision evidence implies mixed text/image input when input tags are absent."""
    legacy_vision = ModelAgent(
        "legacy_vision",
        "legacy-vision-model",
        tags=("cost:free", "vision", "output:text"),
    )
    orchestrator = TaskOrchestrator([legacy_vision])

    assert orchestrator._free_pool_agent_ids(messages=_figure_messages()) == {
        "legacy_vision"
    }


if __name__ == "__main__":
    test_free_image_request_fails_closed_when_only_text_free_agents_exist()
    test_free_image_request_serves_image_capable_free_agent()
    test_text_only_free_request_still_excludes_vision_free_agent()
    test_free_image_pool_skips_single_tool_agent_for_multi_tool_request()
    test_free_image_pool_skips_single_tool_agent_when_parallel_calls_requested()
    test_free_image_pool_keeps_single_tool_agent_for_single_call_shapes(
        _one_tool_figure_request()
    )
    test_free_image_pool_keeps_single_tool_agent_for_single_call_shapes(
        _two_tool_figure_request(parallel_tool_calls=False)
    )
    test_free_image_pool_fails_closed_when_only_single_tool_image_agent_exists()
    test_free_image_pool_ids_compose_tool_call_exclusion()
    print("ok")
