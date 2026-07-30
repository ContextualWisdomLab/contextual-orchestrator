"""Targeted coverage for ModelClient transport and module-helper branches.

These exercise the previously-uncovered non-mock transport edges of
``orchestrator.py`` — TLS bundle load failure, the real ``chat`` send return,
streaming JSON-decode skips, blank batch-result lines, the ``_coerce_input_text``
Responses-input walker, batch-route budget/persistence, and the mixed
usage-source spend bucket — without touching production logic.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    ModelClient,
    _coerce_input_text,
    _dedupe_blockers,
    _freeze_report_cache_value,
    optimize_orchestration,
)


def test_ca_bundle_that_cannot_be_loaded_raises_value_error() -> None:
    """A present-but-invalid CA bundle file must surface as a clear ValueError."""
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write("this is not a PEM certificate\n")
        bundle_path = handle.name
    try:
        raised = False
        try:
            ModelClient(ca_bundle=bundle_path)
        except ValueError as exc:
            raised = True
            assert "could not be loaded" in str(exc)
            assert bundle_path in str(exc)
        assert raised
    finally:
        Path(bundle_path).unlink()


def test_chat_non_mock_agent_reaches_send_with_retry() -> None:
    """The non-mock ``chat`` path validates, resolves a credential, then sends."""

    class _StubClient(ModelClient):
        def _validate_provider(self, agent: ModelAgent) -> None:  # type: ignore[override]
            # Skip real egress validation; we only need the send path to run.
            self.validated = getattr(self, "validated", 0) + 1

        def _send(self, agent: ModelAgent, payload: dict) -> str:  # type: ignore[override]
            self.sent_payload = payload
            return "provider-answer"

    set_backend(InMemoryCredentialBackend())
    try:
        register_credential("OPENAI_API_KEY", "sk-live-abc123456789")
        client = _StubClient()
        agent = ModelAgent("remote_worker", "gpt-x", base_url="https://provider.example/v1")
        answer = client.chat(agent, [{"role": "user", "content": "hi there"}], temperature=0.3)
        assert answer == "provider-answer"
        assert client.validated == 1
        assert client.sent_payload["model"] == "gpt-x"
        assert client.sent_payload["temperature"] == 0.3
        assert client.sent_payload["stream"] is False
    finally:
        set_backend(None)


class _FakeStreamResponse:
    """Minimal context-manager response yielding raw SSE byte lines."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_stream_send_skips_non_data_and_malformed_json_lines() -> None:
    """SSE parsing ignores comments and undecodable data lines, yielding real deltas."""

    class _StreamClient(ModelClient):
        def _open_provider(self, request: object) -> _FakeStreamResponse:  # type: ignore[override]
            return _FakeStreamResponse(
                [
                    b": keep-alive comment\n",
                    b"data: {not valid json}\n",
                    b'data: {"choices": [{"delta": {"content": "hello"}}]}\n',
                    b'data: {"choices": [{"delta": {"content": " world"}}]}\n',
                    b"data: [DONE]\n",
                    b'data: {"choices": [{"delta": {"content": "after-done"}}]}\n',
                ]
            )

    set_backend(InMemoryCredentialBackend())
    try:
        register_credential("OPENAI_API_KEY", "sk-live-streaming-000")
        client = _StreamClient()
        agent = ModelAgent("stream_worker", "gpt-x", base_url="https://provider.example/v1")
        payload = {"model": "gpt-x", "messages": [], "stream": True}
        deltas = list(client._stream_send(agent, payload))
        # Comment + bad-JSON lines are skipped; content stops at [DONE].
        assert deltas == ["hello", " world"]
    finally:
        set_backend(None)


def test_batch_run_skips_blank_result_lines() -> None:
    """Blank lines in the batch output JSONL are ignored during parse."""

    class _BatchClient(ModelClient):
        def _batch_upload(self, agent: ModelAgent, payload: bytes) -> str:  # type: ignore[override]
            return "file_input_1"

        def _batch_json(self, agent, method, path, payload=None):  # type: ignore[override]
            if method == "POST":
                return {"id": "batch_1"}
            return {"status": "completed", "output_file_id": "file_out_1"}

        def _batch_raw(self, agent: ModelAgent, path: str) -> bytes:  # type: ignore[override]
            # Deliberately include blank lines around a real result row.
            return (
                b"\n"
                b'{"custom_id": "task_a", "response": {"body": '
                b'{"choices": [{"message": {"content": "answer A"}}], "usage": {"completion_tokens": 4}}}}\n'
                b"   \n"
            )

    client = _BatchClient()
    client._sleep = lambda _s: None
    agent = ModelAgent("batch_worker", "gpt-x", base_url="https://provider.example/v1")
    results = client._batch_run(
        agent,
        {"task_a": [{"role": "user", "content": "q"}]},
        temperature=0.2,
        poll_interval=0.0,
        poll_timeout=5.0,
    )
    assert set(results) == {"task_a"}
    assert results["task_a"]["content"] == "answer A"
    assert results["task_a"]["usage"]["completion_tokens"] == 4


def test_coerce_input_text_walks_responses_input_shapes() -> None:
    """The Responses ``input`` walker joins strings, dict content, and text chunks."""
    value = [
        "first",
        {"content": "second"},
        {"content": [{"text": "third"}, {"text": "fourth"}, {"nope": "skip"}]},
        {"other": "ignored"},
        123,
    ]
    assert _coerce_input_text(value) == "first second third fourth"
    # The plain-string fast path stays intact.
    assert _coerce_input_text("already text") == "already text"


def _mock_pool() -> list[ModelAgent]:
    return [
        ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
        ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation")),
        ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review")),
    ]


def test_batch_route_rejects_when_budget_already_exceeded() -> None:
    """batch_route fails closed on an exhausted spend budget before any provider call."""
    orchestrator = TaskOrchestrator(_mock_pool(), budget_max_output_tokens=0)
    raised = False
    try:
        orchestrator.batch_route(["a batch prompt"])
    except BudgetExceededError as exc:
        raised = True
        assert exc.detail["exceeded"] is True
    assert raised


def test_batch_route_persists_runs_to_state_db() -> None:
    """batch_route saves each run to the durable store when one is configured."""
    with tempfile.TemporaryDirectory() as directory:
        state_db = str(Path(directory) / "state.sqlite3")
        orchestrator = TaskOrchestrator(_mock_pool(), state_db=state_db)
        records = orchestrator.batch_route(["route this prompt through batch"])
        assert len(records) == 1
        stored = orchestrator._store.load("workflow_run")
        assert any(row["workflow_run_id"] == records[0]["workflow_run_id"] for row in stored)
        orchestrator.close()


def test_close_releases_agent_pool_store() -> None:
    """close() releases a configured durable agent-pool store without error."""
    with tempfile.TemporaryDirectory() as directory:
        agents_db = str(Path(directory) / "agents.sqlite3")
        orchestrator = TaskOrchestrator(_mock_pool(), agents_db=agents_db)
        assert orchestrator._pool_store is not None
        orchestrator.close()


def test_spend_analytics_reports_mixed_usage_source() -> None:
    """A model with some provider-reported and some estimated steps is labeled 'mixed'."""
    orchestrator = TaskOrchestrator(_mock_pool(), price_per_million={"mock-planner": 1.0})
    orchestrator._workflow_runs["run_mixed"] = {
        "workflow_run_id": "run_mixed",
        "created_at": 0,
        "mode": "conduct",
        "policy_mode": "conduct",
        "prompt_text": "prompt",
        "answer": "final",
        "trace": [
            {"id": 0, "role": "thinker", "agent_id": "planner_agent", "subtask": "s0",
             "access": [], "output": "reported step", "usage": {"completion_tokens": 11}},
            {"id": 1, "role": "worker", "agent_id": "planner_agent", "subtask": "s1",
             "access": [0], "output": "estimated step"},
        ],
        "policy_snapshot": {"verifier_required": True},
        "verification": {"accepted": True, "reason": "ok", "verifier_output": ""},
    }
    spend = orchestrator.spend_analytics()
    rows = {row["model"]: row for row in spend["by_model"]}
    assert rows["mock-planner"]["usage_source"] == "mixed"
    assert rows["mock-planner"]["step_count"] == 2


def test_dedupe_blockers_matches_fromkeys_for_hashables_and_tolerates_dicts() -> None:
    """The blocker de-duplicator preserves first-seen order and tolerates dict items."""
    # All-hashable / empty case is byte-for-byte identical to the old dict.fromkeys path.
    assert _dedupe_blockers([]) == []
    hashable = ["a", "b", "a", "c", "b"]
    assert _dedupe_blockers(hashable) == list(dict.fromkeys(hashable))
    # Dict artifact items are unhashable but still de-duplicated in order (the old crash).
    first = {"item_name": "runtime_reports", "completion_state": "blocked"}
    duplicate = {"completion_state": "blocked", "item_name": "runtime_reports"}  # same content, other order
    other = {"item_name": "packaging", "completion_state": "blocked"}
    result = _dedupe_blockers([first, duplicate, other, "marker", "marker"])
    assert result == [first, other, "marker"]


def test_freeze_report_cache_value_handles_set_and_unhashable() -> None:
    """The cache-key freezer sorts sets and falls back to repr for unhashable values."""
    assert _freeze_report_cache_value({3, 1, 2}) == (1, 2, 3)
    # bytearray is unhashable and not a container branch -> repr fallback.
    frozen = _freeze_report_cache_value(bytearray(b"ab"))
    assert frozen == repr(bytearray(b"ab"))


def _priced_candidate(name: str, agent_id: str, price: float) -> dict:
    orchestrator = TaskOrchestrator(
        [ModelAgent(agent_id, "model-x", tags=("reasoning", "writing"))],
        price_per_million={"model-x": price},
    )
    return {"name": name, "orchestrator": orchestrator, "mode": "route"}


def test_optimizer_recommends_nothing_without_candidates() -> None:
    """An empty candidate set yields no recommendation."""
    report = optimize_orchestration([], [{"prompt": "task one"}], lambda task, answer: 1.0, cost_budget_usd=1.0)
    assert report["results"] == []
    assert report["recommended"] is None


def test_optimizer_recommends_cheapest_when_none_fit_budget() -> None:
    """When no config fits the budget, the cheapest is recommended with the honest reason."""
    candidates = [
        _priced_candidate("pricey", "pricey_worker", price=90.0),
        _priced_candidate("cheaper", "cheaper_worker", price=30.0),
    ]
    report = optimize_orchestration(
        candidates, [{"prompt": "task one"}, {"prompt": "task two"}], lambda task, answer: 0.7, cost_budget_usd=0.0
    )
    assert report["recommended"]["reason"] == "no config within budget; cheapest instead"
    assert report["recommended"]["name"] == "cheaper"


if __name__ == "__main__":  # pragma: no cover
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"ok {name}")
    print("ok")
