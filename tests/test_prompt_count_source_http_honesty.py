"""HTTP honesty for the served-response ``prompt_count_source`` field (#1157).

``prompt_count_source`` sits next to the existing ``usage``/
``usage_measurement_status`` pair on ``/v1/chat/completions`` responses. It is
present only when ``token_counting.COUNTING_PROVENANCE_REGISTRY`` has a
verified, in-scope entry for the exact served model and every request
message uses only that entry's supported fields; otherwise it is omitted,
never fabricated.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    SecurityConfig,
    _take_shared_context_budget,
    build_server,
)
from contextual_orchestrator.token_counting import NativeExactTokenCounter  # noqa: E402

_TEST_AUTH_TOKEN = "prompt_count_source_http_honesty_token"  # noqa: S105
_VERIFIED_MODEL = "gpt-4o-2024-08-06"


def _stub_native_token_counter() -> NativeExactTokenCounter:
    """A deterministic stand-in for the optional native tokenizer extension.

    Production dispatches through the packaged Rust tokenizer
    (``contextual_orchestrator._token_packer``); this repo's local dev/test
    environment does not have that optional extension installed, so
    ``TaskOrchestrator``'s default ``token_counter`` is an
    ``UnavailableTokenCounter`` and would never demonstrate the "present"
    case below. Injecting a stub ``NativeExactTokenCounter`` exercises the
    exact same ``describe_messages`` provenance/validation path the real
    extension would.
    """
    module = type(
        "_StubNativeModule",
        (),
        {
            "count_cl100k": staticmethod(lambda text: len(text.split())),
            "count_o200k": staticmethod(lambda text: len(text.split())),
            "pack_cl100k": staticmethod(lambda *_args: ([], [])),
        },
    )()
    return NativeExactTokenCounter(module)


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
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _server(agents: list[ModelAgent], *, token_counter=None):
    orchestrator = TaskOrchestrator(agents, token_counter=token_counter)
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_prompt_count_source_present_for_a_verified_in_scope_model() -> None:
    server, thread, port = _server(
        [ModelAgent("general_agent", _VERIFIED_MODEL, tags=("reasoning", "writing"))],
        token_counter=_stub_native_token_counter(),
    )
    try:
        status, body = _post(
            port,
            {
                "model": _VERIFIED_MODEL,
                "messages": [{"role": "user", "content": "hello there"}],
            },
        )
        assert status == 200, body
        assert body["prompt_count_source"] == "provenance_exact"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_prompt_count_source_absent_for_an_unscoped_model() -> None:
    server, thread, port = _server(
        [ModelAgent("general_agent", "mock-planner", tags=("reasoning", "writing"))]
    )
    try:
        status, body = _post(
            port,
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": "hello there"}],
            },
        )
        assert status == 200, body
        assert "prompt_count_source" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_prompt_count_source_absent_when_a_message_carries_a_non_text_content_part() -> None:
    # ``_validate_messages`` normalizes an OpenAI content-parts array into a
    # list (not a plain string). That list survives into the message dict
    # the multi-agent route path counts from, so it exercises the same
    # "field is not plain text" rejection ``describe_messages`` raises for
    # any non-text field -- without needing the tool-call passthrough branch,
    # which never reaches ``chat_completion_response``/``_prompt_count_source``
    # at all (tool-bearing requests take the structured/passthrough branch).
    server, thread, port = _server(
        [
            ModelAgent(
                "general_agent",
                _VERIFIED_MODEL,
                tags=("reasoning", "writing", "input:text", "input:image"),
            )
        ],
        token_counter=_stub_native_token_counter(),
    )
    try:
        status, body = _post(
            port,
            {
                "model": _VERIFIED_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe this"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.invalid/synthetic.png"},
                            },
                        ],
                    },
                ],
            },
        )
        assert status == 200, body
        assert "prompt_count_source" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_shared_context_budget_reads_and_clears_client_evidence() -> None:
    """``_take_shared_context_budget`` is a thin, honest read/clear seam.

    The real evidence is produced by ``ModelClient.chat()`` (see
    ``test_output_budget_model_max.py`` for the full decision matrix); this
    only proves the server-response wiring reads whatever the client last
    recorded and clears it, and degrades to ``None`` for a client without the
    method at all (e.g. a caller-supplied client that predates this feature).
    """

    class _ClientWithEvidence:
        def __init__(self, evidence):
            self._evidence = evidence

        def take_shared_context_budget(self):
            evidence, self._evidence = self._evidence, None
            return evidence

    evidence = {
        "context_window": 20,
        "prompt_tokens": 9,
        "output_ceiling": 11,
        "source": "exact",
    }
    client = _ClientWithEvidence(evidence)
    orchestrator = type("_Orchestrator", (), {"client": client})()
    assert _take_shared_context_budget(orchestrator) == evidence
    # Consumed exactly once, like take_usage().
    assert _take_shared_context_budget(orchestrator) is None


def test_shared_context_budget_is_none_for_a_client_without_the_method() -> None:
    orchestrator = type("_Orchestrator", (), {"client": object()})()
    assert _take_shared_context_budget(orchestrator) is None
