"""Mixed-pool regression coverage for the PR #958 round-2 Devin finding.

``_require_eligible_role_effort_agents`` (``contextual_orchestrator/__main__.py``)
only proves that *some* agent in the configured pool has
``reasoning_effort_supported: true``. Before this fix, ordinary role-based
selection (``route_once``, ``conduct``, ``stream_route``, ``batch_route``)
could still rank or select an *unsupported* agent ahead of a supported one
from a mixed pool:

- ``route_once``/``conduct`` recovered by accident, via ``_invoke``'s generic
  tool-failure classifier treating the resulting ``EffortProfileError`` as an
  unknown failure and failing over to the next candidate (see
  ``tool_fallback.classify_tool_failure``'s "Unknown exceptions retain the
  existing sequential agent-failover behavior" docstring) -- correct, but
  wasteful: an extra doomed provider call per request.
- ``stream_route`` and ``batch_route`` call the provider directly with no
  such recovery and would raise ``EffortProfileError`` straight through to
  the caller, crashing the request outright.

``TaskOrchestrator._ranked_agents`` now narrows role-based candidates to
agents that prove ``reasoning_effort`` support (via
``_eligible_role_effort_candidates``) whenever the role's
``role_effort_catalog`` entry fails closed. These tests pin that an
unsupported agent -- even one ranked ahead of a supported one by priority --
is never dispatched to across all four paths, and that a supported agent
still serves the request instead of the request crashing or wastefully
failing over.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import (  # noqa: E402
    ModelAgent,
    TaskOrchestrator,
    default_role_effort_catalog,
)

_UNSUPPORTED_BASE_URL = "mlx://127.0.0.1:59481/v1"
_SUPPORTED_BASE_URL = "mlx://127.0.0.1:59482/v1"


def _mixed_pool() -> tuple[ModelAgent, ModelAgent]:
    """Return (unsupported, supported) agents; unsupported ranks first by priority.

    Both are real (non-mock) ``mlx://`` loopback agents -- ``agent_proves_
    reasoning_effort_support`` only auto-passes ``mock://`` agents, and
    ``mlx://`` is keyless (no KV credential needed), so these exercise the
    real ``apply_effort_profile`` gate without any network access.
    """
    unsupported = ModelAgent(
        "unsupported_agent",
        "unsupported-model",
        base_url=_UNSUPPORTED_BASE_URL,
        priority=10,
        reasoning_effort_supported=False,
    )
    supported = ModelAgent(
        "supported_agent",
        "supported-model",
        base_url=_SUPPORTED_BASE_URL,
        priority=1,
        reasoning_effort_supported=True,
    )
    return unsupported, supported


def _recording_send_with_retry(calls: list[str]):
    """Return a ``ModelClient._send_with_retry`` stand-in that records the agent id."""

    def _send(agent: ModelAgent, payload: dict, destination) -> str:
        del payload, destination
        calls.append(agent.id)
        return f"answer from {agent.id}"

    return _send


def _recording_stream_send(calls: list[str]):
    """Return a ``ModelClient._stream_send`` stand-in that records the agent id."""

    def _send(agent: ModelAgent, payload: dict, destination=None):
        del payload, destination
        calls.append(agent.id)
        yield f"answer from {agent.id}"

    return _send


def test_mixed_pool_route_never_dispatches_to_the_unsupported_agent() -> None:
    """route_once must select the supported agent directly, with no failover."""
    unsupported, supported = _mixed_pool()
    orchestrator = TaskOrchestrator(
        [unsupported, supported], role_effort_catalog=default_role_effort_catalog()
    )
    calls: list[str] = []
    # The real-time/model judge is a concern this fix does not touch; force
    # its "fast-mlsirm unavailable" fail-closed branch so this test is
    # deterministic regardless of whether the optional judge package happens
    # to be installed in the environment it runs in (it is a real, if
    # Python-version-gated, dependency -- see requirements.lock).
    with (
        patch(
            "contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components",
            return_value=None,
        ),
        patch.object(
            orchestrator.client, "_send_with_retry", side_effect=_recording_send_with_retry(calls)
        ),
    ):
        result = orchestrator.route_once([{"role": "user", "content": "hello"}])

    assert calls == ["supported_agent"]
    assert result["trace"][0]["agent_id"] == "supported_agent"
    assert "failover_from" not in result["trace"][0]
    assert result["answer"] == "answer from supported_agent"


def test_mixed_pool_conduct_never_dispatches_to_the_unsupported_agent() -> None:
    """Every conduct() workflow step (thinker/worker/verifier/synthesizer) must
    land on the supported agent; the unsupported one is never even offered."""
    unsupported, supported = _mixed_pool()
    orchestrator = TaskOrchestrator(
        [unsupported, supported], role_effort_catalog=default_role_effort_catalog()
    )
    calls: list[str] = []
    # See the route test above for why the model judge is forced unavailable.
    with (
        patch(
            "contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components",
            return_value=None,
        ),
        patch.object(
            orchestrator.client, "_send_with_retry", side_effect=_recording_send_with_retry(calls)
        ),
    ):
        result = orchestrator.complete(
            [{"role": "user", "content": "Analyze this and verify the risks."}],
            mode="conduct",
        )

    assert calls, "conduct() must have invoked at least one workflow step"
    assert set(calls) == {"supported_agent"}
    assert {step["agent_id"] for step in result["trace"]} == {"supported_agent"}
    assert all("failover_from" not in step for step in result["trace"])


def test_mixed_pool_stream_route_never_dispatches_to_the_unsupported_agent() -> None:
    """stream_route has no cross-agent failover, so a wrong pick would crash
    the request outright; the fix must keep it from ever being picked."""
    unsupported, supported = _mixed_pool()
    orchestrator = TaskOrchestrator(
        [unsupported, supported], role_effort_catalog=default_role_effort_catalog()
    )
    calls: list[str] = []
    # See the route test above for why the model judge is forced unavailable
    # (stream_route also runs the real-time judge, after the stream ends).
    with (
        patch(
            "contextual_orchestrator.orchestrator._resolve_fast_mlsirm_components",
            return_value=None,
        ),
        patch.object(
            orchestrator.client, "_stream_send", side_effect=_recording_stream_send(calls)
        ),
    ):
        chunks = list(
            orchestrator.stream_route([{"role": "user", "content": "hello"}])
        )

    assert calls == ["supported_agent"]
    assert "".join(chunks) == "answer from supported_agent"


def test_mixed_pool_batch_route_never_dispatches_to_the_unsupported_agent() -> None:
    """batch_route has no cross-agent failover either; same guarantee as stream."""
    unsupported, supported = _mixed_pool()
    orchestrator = TaskOrchestrator(
        [unsupported, supported], role_effort_catalog=default_role_effort_catalog()
    )
    calls: list[str] = []
    with patch.object(
        orchestrator.client, "_send_with_retry", side_effect=_recording_send_with_retry(calls)
    ):
        records = orchestrator.batch_route(["hello", "world"])

    assert calls == ["supported_agent", "supported_agent"]
    assert {record["trace"][0]["agent_id"] for record in records} == {"supported_agent"}
    assert [record["answer"] for record in records] == [
        "answer from supported_agent",
        "answer from supported_agent",
    ]


def test_mixed_pool_omit_fallback_role_does_not_filter() -> None:
    """A role whose profile safely omits reasoning_effort must not be narrowed.

    ``unsupported_provider_fallback="omit"`` never raises EffortProfileError
    for an unproven agent (it just skips the reasoning_effort field), so the
    filter must leave ranking alone and the naturally top-ranked (by
    priority) agent -- unsupported or not -- must still be selected.
    """
    from dataclasses import replace

    unsupported, supported = _mixed_pool()
    catalog = {
        **default_role_effort_catalog(),
        "worker": replace(
            default_role_effort_catalog()["worker"],
            unsupported_provider_fallback="omit",
        ),
    }
    orchestrator = TaskOrchestrator([unsupported, supported], role_effort_catalog=catalog)
    # Disable the (unrelated) real-time answer judge so this test isolates
    # candidate *selection* -- with it on, the fast-mlsirm judge being absent
    # in this test environment fails every verdict closed and route_once
    # keeps trying candidates regardless of this filter.
    orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)
    calls: list[str] = []
    with patch.object(
        orchestrator.client, "_send_with_retry", side_effect=_recording_send_with_retry(calls)
    ):
        result = orchestrator.route_once([{"role": "user", "content": "hello"}])

    # unsupported_agent has the higher priority (10 vs 1) and is not filtered
    # out for an "omit" role, so it is the one actually dispatched to.
    assert calls == ["unsupported_agent"]
    assert result["trace"][0]["agent_id"] == "unsupported_agent"


if __name__ == "__main__":
    test_mixed_pool_route_never_dispatches_to_the_unsupported_agent()
    test_mixed_pool_conduct_never_dispatches_to_the_unsupported_agent()
    test_mixed_pool_stream_route_never_dispatches_to_the_unsupported_agent()
    test_mixed_pool_batch_route_never_dispatches_to_the_unsupported_agent()
    test_mixed_pool_omit_fallback_role_does_not_filter()
    print("ok")
