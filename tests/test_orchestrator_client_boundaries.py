"""Boundary coverage for ModelClient transport, probes, slots, and streams."""

from __future__ import annotations

import json
import sys
import threading
import types
import urllib.error
from unittest.mock import patch

import pytest

from contextual_orchestrator.orchestrator import (
    MAX_PROVIDER_PROBE_TIMEOUT,
    ModelAgent,
    ModelClient,
    OrchestrationPolicy,
    TaskOrchestrator,
    _FastMLSIJudgeAdapter,
    _coerce_input_text,
    _coerce_message_content_text,
    _local_provider_slot,
    _local_provider_state,
    _resolve_fast_mlsirm_components,
    _validate_batch_results,
    _validate_provider_probe_timeout,
)


def _orch(*agents: ModelAgent, **kwargs) -> TaskOrchestrator:
    return TaskOrchestrator(list(agents), **kwargs)


def _agent(agent_id: str = "planner_agent", **overrides) -> ModelAgent:
    fields = {
        "id": agent_id,
        "model": "mock-model",
        "tags": ("planning", "reasoning"),
    }
    fields.update(overrides)
    return ModelAgent(**fields)


# -- probe timeout validation -------------------------------------------------


@pytest.mark.parametrize("bad", [True, "5", None])
def test_probe_timeout_rejects_non_numeric_types(bad) -> None:
    with pytest.raises(ValueError, match="finite number"):
        _validate_provider_probe_timeout(bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.05, 31.0])
def test_probe_timeout_rejects_out_of_range_values(bad) -> None:
    with pytest.raises(ValueError, match="between 0.1 and"):
        _validate_provider_probe_timeout(bad)
    assert MAX_PROVIDER_PROBE_TIMEOUT == 30.0


# -- optional fast-mlsirm adapter seam ----------------------------------------


def test_missing_fast_mlsirm_resolves_to_none(monkeypatch) -> None:
    """Without the optional judge package the adapter seam is disabled."""

    class _Blocker:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "fast_mlsirm":
                raise ModuleNotFoundError("package not installed", name=fullname)
            return None

    monkeypatch.delitem(sys.modules, "fast_mlsirm", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocker(), *sys.meta_path])
    assert _resolve_fast_mlsirm_components() is None


def test_unrelated_import_failure_from_fast_mlsirm_propagates(monkeypatch) -> None:
    """Only the package-missing case counts as 'adapter unavailable'."""

    class _BrokenNativePackage(types.ModuleType):
        def __getattr__(self, name):
            raise ModuleNotFoundError(
                "native extension missing", name=f"fast_mlsirm.{name}"
            )

    monkeypatch.setitem(sys.modules, "fast_mlsirm", _BrokenNativePackage("fast_mlsirm"))

    with pytest.raises(ModuleNotFoundError, match="native extension missing"):
        _resolve_fast_mlsirm_components()


def test_judge_adapter_validates_mode_and_response_format() -> None:
    orch = _orch(_agent())
    adapter = _FastMLSIJudgeAdapter(orchestrator=orch, text="task", judge="planner_agent")

    with pytest.raises(ValueError, match="mode must be auto, route, or conduct"):
        adapter.complete([{"role": "user", "content": "hi"}], mode="bogus")
    with pytest.raises(ValueError, match="mode must be auto, route, or conduct"):
        adapter.complete_structured(
            [{"role": "user", "content": "hi"}], mode="bogus", response_format={}
        )
    with pytest.raises(TypeError, match="response_format must be a mapping"):
        adapter.complete_structured(
            [{"role": "user", "content": "hi"}],
            mode="route",
            response_format=["not", "a", "mapping"],
        )

    payload = adapter.complete([{"role": "user", "content": "hello world"}])
    assert payload["answer"] == "[planner_agent:worker] hello world"
    structured = adapter.complete_structured(
        [{"role": "user", "content": "hello again"}],
        mode="route",
        response_format={"type": "json_object"},
    )
    assert structured["mode"] == "route"
    assert structured["trace"][0]["agent_id"] == "planner_agent"


# -- agent and policy validation -----------------------------------------------


def test_model_agent_rejects_bad_local_credential_key_and_effort_flag() -> None:
    with pytest.raises(TypeError, match="local_credential_key must be a string"):
        ModelAgent(id="agent_two", model="m", local_credential_key=123)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reasoning_effort_supported must be"):
        ModelAgent(id="agent_two", model="m", reasoning_effort_supported="yes")  # type: ignore[arg-type]


def test_policy_rejects_non_positive_route_text_threshold() -> None:
    with pytest.raises(ValueError, match="route_text_length_threshold"):
        OrchestrationPolicy(route_text_length_threshold=0)
    with pytest.raises(ValueError, match="route_text_length_threshold"):
        OrchestrationPolicy(route_text_length_threshold="5")  # type: ignore[arg-type]


def test_batch_results_must_be_a_mapping() -> None:
    requests = {"task_0": [{"role": "user", "content": "x"}]}
    with pytest.raises(TypeError, match="invalid result map"):
        _validate_batch_results(requests, ["nope"])  # type: ignore[arg-type]


# -- local provider slot concurrency ------------------------------------------


def test_slot_shrinks_capacity_for_same_model_and_resets_when_empty() -> None:
    """Concurrent same-model holders shrink capacity; last release resets."""
    url = "local://127.0.0.1:59341/v1"
    state = _local_provider_state(url)
    agent = ModelAgent(id="slot_agent", model="slot-model", base_url=url)
    first_acquired = threading.Event()
    second_done = threading.Event()

    def holder_first():
        with _local_provider_slot(agent, 4, 5.0):
            first_acquired.set()
            assert second_done.wait(timeout=5)

    def holder_second():
        assert first_acquired.wait(timeout=5)
        with _local_provider_slot(agent, 2, 5.0):
            # While both hold the same model, capacity shrank to the minimum.
            assert state.capacity == 2
        second_done.set()

    threads = [
        threading.Thread(target=holder_first),
        threading.Thread(target=holder_second),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert state.active == 0
    assert state.active_model is None


def test_slot_release_while_peer_still_active_skips_state_reset() -> None:
    url = "local://127.0.0.1:59342/v1"
    state = _local_provider_state(url)
    agent = ModelAgent(id="peer_agent", model="peer-model", base_url=url)
    entered = threading.Event()
    release = threading.Event()

    def peer():
        with _local_provider_slot(agent, 4, 5.0):
            entered.set()
            assert release.wait(timeout=5)

    thread = threading.Thread(target=peer)
    thread.start()
    assert entered.wait(timeout=5)
    with _local_provider_slot(agent, 4, 5.0):
        pass  # second concurrent holder acquires immediately
    # The first holder is still active; this release must not clear its slot.
    assert state.active == 1
    assert state.active_model == "peer-model"
    release.set()
    thread.join(timeout=10)
    assert state.active == 0


# -- client construction guards -------------------------------------------------


def test_ssl_context_requires_loadable_ca_bundle(tmp_path) -> None:
    unreadable = tmp_path / "ca.pem"
    unreadable.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    unreadable.chmod(0o000)
    try:
        with pytest.raises(ValueError, match="could not be loaded"):
            ModelClient(ca_bundle=str(unreadable))
    finally:
        unreadable.chmod(0o644)


@pytest.mark.parametrize(
    ("hosts", "fragment"),
    [
        ("host.example", "iterable of host strings"),
        (b"host.example", "iterable of host strings"),
        (17, "iterable of host strings"),
        ([17], "contain only strings"),
        (["path/slash.example"], "bare host names"),
        ([""], "bare host names"),
    ],
)
def test_allowed_provider_hosts_normalization_rejects_bad_input(hosts, fragment) -> None:
    with pytest.raises(ValueError, match=fragment):
        ModelClient(allowed_provider_hosts=hosts)


def test_request_settings_nesting_restores_previous_scope() -> None:
    client = ModelClient()
    with client.request_settings(temperature=0.9):
        assert client.request_settings_snapshot()["temperature"] == 0.9
        with client.request_settings(max_output_tokens=7):
            inner = client.request_settings_snapshot()
            assert inner["temperature"] == 0.9
            assert inner["max_output_tokens"] == 7
        restored = client.request_settings_snapshot()
        assert restored["temperature"] == 0.9
        assert restored["max_output_tokens"] != 7
    assert client.request_settings_snapshot()["temperature"] == client.temperature


# -- readiness probe paths -------------------------------------------------------


def test_probe_reports_not_ready_for_empty_mock_content() -> None:
    orch = _orch(_agent())
    agent = orch.candidates[0]
    with patch.object(ModelClient, "_mock", return_value="   "):
        report = orch.client.probe(agent, timeout=1.0)
    assert report["status"] == "not_ready"
    assert report["failure_code"] == "provider_empty_probe_response"
    assert report["error_type"] == "RuntimeError"


def test_probe_against_https_provider_skips_registry_and_reports_ready() -> None:
    agent = ModelAgent(
        id="remote_agent",
        model="remote-chat-model",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    client = ModelClient()
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_send", return_value="OK"
    ):
        report = client.probe(agent, timeout=1.0)
    assert report["status"] == "ready"
    assert report["latency_ms"] >= 0


class _RegistryResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


@pytest.mark.parametrize(
    ("base_url", "chat_template_args"),
    [
        ("mlx://127.0.0.1:59351/v1", {"enable_thinking": True}),
        ("local://127.0.0.1:59352/v1", None),
    ],
    ids=["mlx_with_kwargs", "local_without_kwargs"],
)
def test_probe_registry_check_passes_for_registered_local_model(
    base_url, chat_template_args
) -> None:
    """Local probes verify /models registration; mlx adds template kwargs."""
    client = ModelClient(chat_template_args=chat_template_args)
    agent = ModelAgent(
        id="local_agent",
        model="registered-local-model",
        base_url=base_url,
    )
    registry_payload = {"data": [{"id": "registered-local-model"}, {"id": "other"}]}
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_open_provider", return_value=_RegistryResponse(registry_payload)
    ), patch.object(client, "_send", return_value="OK"):
        report = client.probe(agent, timeout=1.0)
    assert report["status"] == "ready"

    missing_client = ModelClient()
    with patch.object(missing_client, "_validate_provider", return_value=None), patch.object(
        missing_client,
        "_open_provider",
        return_value=_RegistryResponse({"data": [{"id": "other"}]}),
    ):
        missing = missing_client.probe(agent, timeout=1.0)
    assert missing["status"] == "not_ready"
    assert missing["failure_code"] == "provider_model_not_registered"


# -- streaming boundary ------------------------------------------------------------


class _StreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self._lines)


def _streaming_agent() -> ModelAgent:
    return ModelAgent(
        id="stream_remote_agent",
        model="remote-chat-model",
        base_url="https://stream.example/v1",
        credential_key="STREAM_API_KEY",
    )


def test_stream_survives_noise_and_stream_without_done_marker() -> None:
    """Non-JSON junk and a stream that ends without [DONE] still yield deltas."""
    agent = _streaming_agent()
    client = ModelClient()
    lines = [
        b": keep-alive comment",
        b"data: not-json-at-all",
        b'data: {"choices":[{"delta":{"content":"hel"}}]}',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}',
    ]
    with patch.object(
        client, "_open_provider", return_value=_StreamResponse(lines)
    ):
        deltas = list(client._stream_send(agent, {}))
    assert deltas == ["hel", "lo"]


def test_stream_wraps_mid_stream_transport_failure_without_provider_text() -> None:
    agent = _streaming_agent()
    client = ModelClient()

    class _ExplodingStream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"par"}}]}'
            raise urllib.error.URLError("connection reset by provider")

    with patch.object(
        client, "_open_provider", return_value=_ExplodingStream()
    ):
        iterator = client._stream_send(agent, {})
        assert next(iterator) == "par"
        with pytest.raises(RuntimeError, match="streaming request failed"):
            next(iterator)


# -- batch success paths ------------------------------------------------------------


def test_batch_chat_success_on_https_provider_returns_validated_results() -> None:
    agent = ModelAgent(
        id="batch_remote_agent",
        model="remote-chat-model",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    client = ModelClient()
    requests = {"task_0": [{"role": "user", "content": "hi"}]}
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client,
        "_batch_run",
        return_value={"task_0": {"content": "done", "usage": None}},
    ) as run:
        results = client.batch_chat(agent, requests)
    assert results == {"task_0": {"content": "done", "usage": None}}
    run.assert_called_once()


def test_batch_chat_wraps_provider_failures_without_provider_text() -> None:
    agent = ModelAgent(
        id="batch_failing_agent",
        model="remote-chat-model",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    client = ModelClient()
    requests = {"task_0": [{"role": "user", "content": "hi"}]}
    with patch.object(client, "_validate_provider", return_value=None), patch.object(
        client, "_batch_run", side_effect=ValueError("provider secret detail")
    ):
        with pytest.raises(RuntimeError, match="batch request failed") as excinfo:
            client.batch_chat(agent, requests)
    assert "secret detail" not in str(excinfo.value)


def test_local_batch_chat_runs_serially_and_concurrently() -> None:
    agent_base = "local://127.0.0.1:59361/v1"

    serial_agent = ModelAgent(
        id="serial_local_agent", model="local-chat-model", base_url=agent_base
    )
    client = ModelClient(local_concurrency=1)
    requests = {f"task_{i}": [{"role": "user", "content": f"p{i}"}] for i in range(2)}
    with patch.object(client, "_send", return_value="ok"):
        serial = client.batch_chat(serial_agent, requests)
    assert sorted(serial) == ["task_0", "task_1"]
    assert all(result["content"] == "ok" for result in serial.values())

    parallel_agent = ModelAgent(
        id="parallel_local_agent",
        model="local-chat-model",
        base_url=agent_base,
        reasoning_effort_supported=True,
    )
    parallel_client = ModelClient(local_concurrency=2)
    with patch.object(parallel_client, "_send", return_value="ok"):
        parallel = parallel_client.batch_chat(parallel_agent, requests)
    assert sorted(parallel) == ["task_0", "task_1"]

    profiled_agent = ModelAgent(
        id="profiled_local_agent",
        model="local-chat-model",
        base_url=agent_base,
        reasoning_effort_supported=True,
    )
    profiled_client = ModelClient(local_concurrency=1)
    from contextual_orchestrator.reasoning_effort_profile import ReasoningEffortProfile

    profile = ReasoningEffortProfile(reasoning_effort="high")
    with patch.object(profiled_client, "_send", return_value="ok"):
        profiled = profiled_client.batch_chat(
            profiled_agent, requests, effort_profile=profile
        )
    assert all(result["content"] == "ok" for result in profiled.values())


def test_batch_run_skips_blank_lines_in_output_content() -> None:
    client = ModelClient()
    agent = ModelAgent(
        id="raw_batch_agent",
        model="remote-chat-model",
        base_url="https://remote.example/v1",
        credential_key="REMOTE_API_KEY",
    )
    raw = (
        b'\n{"custom_id": "task_0", "response": {"body": '
        b'{"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3}}}}\n\n'
    )

    def batch_json(_agent, method, _path, payload=None, destination=None):
        del destination
        if method == "POST":
            assert payload["endpoint"] == "/v1/chat/completions"
            return {"id": "batch_1"}
        return {"status": "completed", "output_file_id": "file_9"}

    with patch.object(
        client, "_batch_upload", return_value="file_1"
    ), patch.object(client, "_batch_json", side_effect=batch_json), patch.object(
        client, "_batch_raw", return_value=raw
    ):
        results = client._batch_run(
            agent,
            {"task_0": [{"role": "user", "content": "hi"}]},
            None,
            0.01,
            5.0,
        )
    assert results["task_0"]["content"] == "ok"
    assert results["task_0"]["usage"] == {"prompt_tokens": 3}


# -- Responses input coercion shapes -------------------------------------------------


def test_coerce_input_text_handles_nested_content_shapes() -> None:
    value = [
        "plain-part",
        {"type": "text", "text": "dict-text"},
        {"content": "string-content"},
        {"content": ["nested", {"text": "chunk-text"}, {"ignored": True}]},
        {"unrelated": True},
        42,
    ]
    coerced = _coerce_input_text(value)
    assert "plain-part" in coerced
    assert "dict-text" in coerced
    assert "string-content" in coerced
    assert "chunk-text" in coerced
    assert isinstance(_coerce_input_text(42), str)

    assert _coerce_message_content_text("direct") == "direct"
    assert _coerce_message_content_text([{"text": "parts"}]) == "parts"
    assert _coerce_message_content_text(None) == ""
    assert _coerce_message_content_text({"dict": True}) == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
