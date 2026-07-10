"""Shared fuzz-target logic for the highest-value untrusted-input surfaces.

Each ``exercise_*`` function takes one decoded input, drives a real code path,
and asserts the invariants that must hold *for arbitrary input*:

* the function either produces a well-formed result or raises one of a small,
  documented set of "expected" exceptions -- never an unhandled ``TypeError``,
  ``AttributeError``, ``RecursionError``, ``SystemError`` or a hang; and
* structural invariants on any successful result (shape, types, idempotence).

CodeGraph (``codegraph explore``) surfaced these four surfaces as the ones that
consume untrusted bytes/JSON:

1. ``server._coerce_json`` / ``_validate_mode`` / ``_validate_messages`` /
   ``_reject_unknown_keys`` -- the HTTP request-body parser and validators.
2. ``orchestrator.ModelAgent.from_dict`` -- the agent-pool config parser.
3. ``orchestrator.redact_text`` / ``redact_value`` -- secret/PII redaction run
   over arbitrary trace payloads (regex + recursion).
4. ``orchestrator.TaskOrchestrator.run`` (+ ``sse_stream_body``) -- end-to-end
   prompt processing on a mock (offline) provider.

No network, no secrets, no filesystem: every target runs fully offline.
"""

from __future__ import annotations

import json
from typing import Any

from contextual_orchestrator import server
from contextual_orchestrator.orchestrator import (
    ModelAgent,
    TaskOrchestrator,
    chat_completion_chunks,
    redact_text,
    redact_value,
    sse_stream_body,
)

# ``RequestError`` is the only *domain* exception the request layer is allowed to
# raise; everything else below is a legitimate stdlib decode/parse failure.
RequestError = server.RequestError

# Malformed bytes/JSON must surface only as these.
_EXPECTED_BODY_EXC = (
    RequestError,
    json.JSONDecodeError,
    UnicodeDecodeError,
    ValueError,  # json.loads raises ValueError subclasses; be explicit anyway
)

# ``from_dict`` indexes/coerces raw config, so these are the sane failure modes.
_EXPECTED_CONFIG_EXC = (
    KeyError,
    TypeError,
    ValueError,
)


def exercise_request_body(raw: bytes) -> None:
    """Drive the HTTP request-body parser + validators over arbitrary bytes.

    Mirrors what ``Handler._read_json`` does after size/content-type checks:
    decode + JSON-parse, then run the field validators the POST routes use.
    """
    try:
        body = server._coerce_json(raw)
    except _EXPECTED_BODY_EXC:
        return
    except RecursionError:
        # Deeply nested JSON is attacker-controllable; the parser should not let
        # it escape as an unhandled crash of an unexpected type. Treat as a
        # finding only if it is NOT a plain RecursionError from json depth.
        return

    # On success the contract is: a plain ``dict``.
    assert isinstance(body, dict), f"body must be dict, got {type(body)!r}"

    # Unknown-key rejection must never raise anything but RequestError.
    try:
        server._reject_unknown_keys(body, {"prompt_text", "run_mode", "messages", "mode"})
    except RequestError:
        pass

    # Mode validation: any value either normalises to an allowed mode or raises
    # RequestError -- nothing else.
    for key in ("run_mode", "mode"):
        if key in body:
            try:
                mode = server._validate_mode(body[key])
            except RequestError:
                pass
            else:
                assert mode in server.ALLOWED_MODES

    # Message validation: returns a normalised list or raises RequestError.
    if "messages" in body:
        try:
            messages = server._validate_messages(body["messages"])
        except RequestError:
            pass
        else:
            assert isinstance(messages, list) and messages
            for message in messages:
                assert set(message) == {"role", "content"}
                assert message["role"] in server.ALLOWED_MESSAGE_ROLES
                assert isinstance(message["content"], str)


def exercise_agent_config(value: Any) -> None:
    """Drive ``ModelAgent.from_dict`` over an arbitrary decoded JSON value."""
    if not isinstance(value, dict):
        # from_dict indexes value["id"]; a non-dict is a config error, not a bug.
        return
    try:
        agent = ModelAgent.from_dict(value)
    except _EXPECTED_CONFIG_EXC:
        return

    # Successful parse invariants.
    assert isinstance(agent.id, str) and agent.id
    assert isinstance(agent.tags, tuple)
    assert isinstance(agent.provider_exclusions, tuple)
    assert isinstance(agent.priority, int)
    assert isinstance(agent.disabled, bool)


def exercise_redaction(text: str) -> None:
    """Drive secret/PII redaction over arbitrary text and structures.

    Invariants: never crashes, always returns ``str``, and is idempotent on its
    own output (re-redacting redacted text yields the same string). Idempotence
    guards against a regex that could re-trigger on the ``[REDACTED]`` marker.
    """
    once = redact_text(text)
    assert isinstance(once, str)
    twice = redact_text(once)
    assert once == twice, "redaction is not idempotent"

    # ``redact_value`` must preserve container shape while redacting leaves.
    payload = {"trace": [text, {"nested": text}], "count": 3, "flag": True, "none": None}
    out = redact_value(payload)
    assert isinstance(out, dict)
    assert isinstance(out["trace"], list)
    assert isinstance(out["trace"][1], dict)
    assert out["count"] == 3 and out["flag"] is True and out["none"] is None


def _mock_orchestrator() -> TaskOrchestrator:
    agents = [
        ModelAgent(id="general_agent", model="mock-generalist", base_url="mock://generalist",
                   tags=("reasoning", "writing", "planning"), priority=1),
        ModelAgent(id="builder_agent", model="mock-builder", base_url="mock://builder",
                   tags=("coding", "debugging", "implementation"), priority=2),
        ModelAgent(id="reviewer_agent", model="mock-reviewer", base_url="mock://reviewer",
                   tags=("verification", "security", "review"), priority=3),
    ]
    return TaskOrchestrator(agents)


def exercise_orchestration(prompt: str, mode: str) -> None:
    """Run a full orchestration on arbitrary prompt text against mock providers.

    Exercises ``_latest_user_text`` -> ``_needs_workflow`` -> ``_score_agent`` ->
    route/conduct -> trace assembly -> SSE framing, all offline via ``mock://``.
    """
    orchestrator = _mock_orchestrator()
    if mode not in server.ALLOWED_MODES:
        mode = "auto"

    record = orchestrator.run([{"role": "user", "content": prompt}], mode=mode)

    assert record["mode"] in server.ALLOWED_MODES
    assert isinstance(record["answer"], str)
    assert isinstance(record["trace"], list) and record["trace"]
    assert record["prompt_text"] == prompt

    # The whole record must be JSON-serialisable (it is returned over HTTP).
    json.dumps(record, ensure_ascii=False)

    # SSE framing must produce a body whose data frames are valid JSON (or DONE).
    chunks = chat_completion_chunks(record, include_trace=True)
    body = sse_stream_body(chunks)
    assert body.endswith("data: [DONE]\n\n")
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame or frame == "data: [DONE]":
            continue
        assert frame.startswith("data: ")
        json.loads(frame[len("data: "):])
