"""Apply and verify request-scoped sampling isolation for PR 805."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command and surface captured output."""

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace one known fragment or fail closed if the branch moved."""

    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"refusing unknown {label} shape")
    return text.replace(old, new, 1)


def _add_regressions() -> None:
    """Add concurrent request and Responses precedence regressions first."""

    chat_path = ROOT / "tests/test_chat_temperature_top_p_http_honesty.py"
    chat = chat_path.read_text(encoding="utf-8")
    chat_anchor = '\n\nif __name__ == "__main__":\n'
    chat_test = r'''

def test_concurrent_structured_chat_sampling_is_request_local() -> None:
    orchestrator = build()
    rendezvous = threading.Barrier(2)
    observed: dict[str, tuple[dict, dict]] = {}
    responses: dict[str, tuple[int, dict]] = {}

    def snapshot() -> dict:
        accessor = getattr(orchestrator.client, "current_sampling_defaults", None)
        if callable(accessor):
            return accessor()
        return {
            "max_output_tokens": orchestrator.client.max_output_tokens,
            "temperature": orchestrator.client.default_temperature,
            "top_p": orchestrator.client.default_top_p,
            "presence_penalty": orchestrator.client.default_presence_penalty,
            "frequency_penalty": orchestrator.client.default_frequency_penalty,
        }

    def proxy_completion(body: dict, *, endpoint: str = "chat/completions") -> dict:
        assert endpoint == "chat/completions"
        label = body["messages"][0]["content"]
        before = snapshot()
        rendezvous.wait(timeout=5)
        after = snapshot()
        observed[label] = (before, after)
        return {
            "id": f"chatcmpl-{label}",
            "object": "chat.completion",
            "model": "mock-planner",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": label},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]

    def request(label: str, temperature: float, max_tokens: int) -> None:
        responses[label] = _post(
            port,
            "/v1/chat/completions",
            {
                "model": "mock-planner",
                "messages": [{"role": "user", "content": label}],
                "response_format": {"type": "json_object"},
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )

    low = threading.Thread(target=request, args=("low", 0.3, 11))
    high = threading.Thread(target=request, args=("high", 1.7, 29))
    try:
        low.start()
        high.start()
        low.join(timeout=10)
        high.join(timeout=10)
        assert not low.is_alive()
        assert not high.is_alive()
        assert responses["low"][0] == 200, responses["low"]
        assert responses["high"][0] == 200, responses["high"]
        for snapshot_value in observed["low"]:
            assert snapshot_value["temperature"] == 0.3
            assert snapshot_value["max_output_tokens"] == 11
        for snapshot_value in observed["high"]:
            assert snapshot_value["temperature"] == 1.7
            assert snapshot_value["max_output_tokens"] == 29
        assert orchestrator.client.default_temperature == 0.2
        assert orchestrator.client.max_output_tokens == 2048
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
'''
    if chat_test not in chat:
        if chat_anchor not in chat:
            raise SystemExit("refusing unknown chat sampling test insertion point")
        chat = chat.replace(chat_anchor, chat_test + chat_anchor, 1)
    chat_path.write_text(chat, encoding="utf-8")

    responses_path = ROOT / "tests/test_responses_temperature_top_p_http_honesty.py"
    responses_text = responses_path.read_text(encoding="utf-8")
    responses_anchor = '\n\nif __name__ == "__main__":\n'
    responses_test = r'''

def test_http_responses_prefers_native_max_output_tokens() -> None:
    orchestrator = build()
    observed: list[int] = []

    def proxy_completion(body: dict, *, endpoint: str = "chat/completions") -> dict:
        assert endpoint == "responses"
        accessor = getattr(orchestrator.client, "current_sampling_defaults", None)
        if callable(accessor):
            observed.append(int(accessor()["max_output_tokens"]))
        else:
            observed.append(orchestrator.client.max_output_tokens)
        return {
            "id": "resp-native-budget",
            "object": "response",
            "model": "mock-planner",
            "output": [],
            "status": "completed",
        }

    orchestrator.proxy_completion = proxy_completion  # type: ignore[method-assign]
    server = build_server(
        orchestrator,
        port=0,
        security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            server.server_address[1],
            {
                "model": "mock-planner",
                "input": "native budget wins",
                "max_tokens": 11,
                "max_completion_tokens": 17,
                "max_output_tokens": 23,
            },
        )
        assert status == 200, body
        assert observed == [23]
        assert orchestrator.client.max_output_tokens == 2048
    finally:
        server.shutdown()
        thread.join(timeout=5)
'''
    if responses_test not in responses_text:
        if responses_anchor not in responses_text:
            raise SystemExit("refusing unknown Responses sampling test insertion point")
        responses_text = responses_text.replace(
            responses_anchor, responses_test + responses_anchor, 1
        )
    responses_path.write_text(responses_text, encoding="utf-8")


def _apply_orchestrator_repair() -> None:
    """Move request sampling from shared attributes into thread-local scope."""

    path = ROOT / "contextual_orchestrator/orchestrator.py"
    text = path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "from collections.abc import Iterable, Mapping\n",
        "from collections.abc import Iterable, Iterator, Mapping\n",
        label="collections.abc import",
    )

    method_anchor = '''    def take_usage(self) -> dict[str, Any] | None:
        """Return and clear provider-reported usage from the most recent chat() on this thread."""
        usage = getattr(self._local, "usage", None)
        self._local.usage = None
        return usage

'''
    methods = '''    def take_usage(self) -> dict[str, Any] | None:
        """Return and clear provider-reported usage from the most recent chat() on this thread."""
        usage = getattr(self._local, "usage", None)
        self._local.usage = None
        return usage

    def _request_sampling_value(self, key: str, fallback: Any) -> Any:
        """Return one request-local sampling override or its immutable fallback."""

        overrides = getattr(self._local, "sampling_defaults", None)
        if isinstance(overrides, dict) and key in overrides:
            return overrides[key]
        return fallback

    def current_sampling_defaults(self) -> dict[str, int | float | None]:
        """Return sampling defaults effective for the current request thread."""

        return {
            "max_output_tokens": self._request_sampling_value(
                "max_output_tokens", self.max_output_tokens
            ),
            "temperature": self._request_sampling_value(
                "temperature", self.default_temperature
            ),
            "top_p": self._request_sampling_value("top_p", self.default_top_p),
            "presence_penalty": self._request_sampling_value(
                "presence_penalty", self.default_presence_penalty
            ),
            "frequency_penalty": self._request_sampling_value(
                "frequency_penalty", self.default_frequency_penalty
            ),
        }

    @contextmanager
    def scoped_sampling_defaults(
        self,
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
    ) -> Iterator[None]:
        """Apply nested request-local sampling values without shared-state mutation."""

        had_previous = hasattr(self._local, "sampling_defaults")
        previous = getattr(self._local, "sampling_defaults", None)
        current = dict(previous) if isinstance(previous, dict) else {}
        for key, value in (
            ("max_output_tokens", max_output_tokens),
            ("temperature", temperature),
            ("top_p", top_p),
            ("presence_penalty", presence_penalty),
            ("frequency_penalty", frequency_penalty),
        ):
            if value is not None:
                current[key] = value
        self._local.sampling_defaults = current
        try:
            yield
        finally:
            if had_previous:
                self._local.sampling_defaults = previous
            else:
                del self._local.sampling_defaults

'''
    text = _replace_once(text, method_anchor, methods, label="ModelClient sampling methods")

    old_chat = '''        # Expose the effective sampling knobs for request-path tests / diagnostics.
        effective_temperature = self.default_temperature if temperature is None else temperature
        effective_top_p = self.default_top_p if top_p is None else top_p
        effective_presence = self.default_presence_penalty
        effective_frequency = self.default_frequency_penalty
'''
    new_chat = '''        # Expose request-local sampling knobs for tests and diagnostics without
        # mutating defaults shared by the threaded HTTP server.
        defaults = self.current_sampling_defaults()
        effective_temperature = defaults["temperature"] if temperature is None else temperature
        effective_top_p = defaults["top_p"] if top_p is None else top_p
        effective_presence = defaults["presence_penalty"]
        effective_frequency = defaults["frequency_penalty"]
        effective_max_tokens = defaults["max_output_tokens"]
'''
    text = _replace_once(text, old_chat, new_chat, label="chat effective sampling")
    text = _replace_once(
        text,
        '            "max_tokens": self.max_output_tokens,\n',
        '            "max_tokens": effective_max_tokens,\n',
        label="chat max tokens",
    )

    old_stream = '''        payload = {  # pragma: no cover
            "model": agent.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": True,
            "max_tokens": self.max_output_tokens,
        }
'''
    new_stream = '''        effective_temperature = (
            self._request_sampling_value("temperature", self.temperature)
            if temperature is None
            else temperature
        )
        payload = {  # pragma: no cover
            "model": agent.model,
            "messages": messages,
            "temperature": effective_temperature,
            "stream": True,
            "max_tokens": self._request_sampling_value(
                "max_output_tokens", self.max_output_tokens
            ),
        }
'''
    text = _replace_once(text, old_stream, new_stream, label="stream sampling")

    text = text.replace(
        'chat_payload.setdefault("max_tokens", self.max_output_tokens)',
        'chat_payload.setdefault(\n                "max_tokens", self._request_sampling_value("max_output_tokens", self.max_output_tokens)\n            )',
        1,
    )
    text = text.replace(
        'local_payload.setdefault("max_tokens", self.max_output_tokens)',
        'local_payload.setdefault(\n                "max_tokens", self._request_sampling_value("max_output_tokens", self.max_output_tokens)\n            )',
        1,
    )

    old_judge = '''                "temperature": self.orchestrator.client.temperature,
                "max_tokens": self.orchestrator.client.max_output_tokens,
'''
    new_judge = '''                "temperature": self.orchestrator.client._request_sampling_value(
                    "temperature", self.orchestrator.client.temperature
                ),
                "max_tokens": self.orchestrator.client._request_sampling_value(
                    "max_output_tokens", self.orchestrator.client.max_output_tokens
                ),
'''
    text = _replace_once(text, old_judge, new_judge, label="judge request sampling")

    text = _replace_once(
        text,
        '            raise RuntimeError(f"requested model {requested_model!r} is disabled")\n',
        '            model_label = requested_model if requested_model is not None else final_agent.model\n            raise RuntimeError(f"requested model {model_label!r} is disabled")\n',
        label="disabled model error",
    )
    path.write_text(text, encoding="utf-8")


def _apply_server_repair() -> None:
    """Use the request-local ModelClient context on every HTTP sampling path."""

    path = ROOT / "contextual_orchestrator/server.py"
    text = path.read_text(encoding="utf-8")

    old_structured = '''                        model_client = orchestrator.client
                        previous_max_tokens = model_client.max_output_tokens
                        previous_temperature = model_client.default_temperature
                        previous_top_p = model_client.default_top_p
                        previous_presence = model_client.default_presence_penalty
                        previous_frequency = model_client.default_frequency_penalty
                        if max_tokens is not None:
                            model_client.max_output_tokens = max_tokens
                        if temperature is not None:
                            model_client.default_temperature = temperature
                        if top_p is not None:
                            model_client.default_top_p = top_p
                        if presence_penalty is not None:
                            model_client.default_presence_penalty = presence_penalty
                        if frequency_penalty is not None:
                            model_client.default_frequency_penalty = frequency_penalty
                        try:
                            proxied = self._run(
                                lambda: orchestrator.proxy_completion(body, endpoint="chat/completions")
                            )
                        finally:
                            model_client.max_output_tokens = previous_max_tokens
                            model_client.default_temperature = previous_temperature
                            model_client.default_top_p = previous_top_p
                            model_client.default_presence_penalty = previous_presence
                            model_client.default_frequency_penalty = previous_frequency
'''
    new_structured = '''                        with orchestrator.client.scoped_sampling_defaults(
                            max_output_tokens=max_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            presence_penalty=presence_penalty,
                            frequency_penalty=frequency_penalty,
                        ):
                            proxied = self._run(
                                lambda: orchestrator.proxy_completion(body, endpoint="chat/completions")
                            )
'''
    text = _replace_once(text, old_structured, new_structured, label="structured chat scope")

    old_plain = '''                    model_client = orchestrator.client
                    previous_max_tokens = model_client.max_output_tokens
                    previous_temperature = model_client.default_temperature
                    previous_top_p = model_client.default_top_p
                    previous_presence = model_client.default_presence_penalty
                    previous_frequency = model_client.default_frequency_penalty
                    if max_tokens is not None:
                        model_client.max_output_tokens = max_tokens
                    if temperature is not None:
                        model_client.default_temperature = temperature
                    if top_p is not None:
                        model_client.default_top_p = top_p
                    if presence_penalty is not None:
                        model_client.default_presence_penalty = presence_penalty
                    if frequency_penalty is not None:
                        model_client.default_frequency_penalty = frequency_penalty
                    try:
                        if stream and orchestrator.would_route(messages, mode):
                            self._stream_route_completion(orchestrator, security, messages, model_name)
                            orchestrator.record_analytics_event(
                                "chat_completion_requested",
                                {
                                    "endpoint_path": "/v1/chat/completions",
                                    "actor_scope": "inference",
                                    "status_code": 200,
                                    "run_mode": "route",
                                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                                    "response_streamed": True,
                                },
                            )
                            return
                        result = self._run(lambda: coordinator.complete(
                            messages,
                            mode=mode,
                            attribution=attribution,
                            hints=routing,
                            model_name=model_name,
                            workflow_run_id=f"run_{uuid.uuid4().hex}",
                        ))
                    finally:
                        model_client.max_output_tokens = previous_max_tokens
                        model_client.default_temperature = previous_temperature
                        model_client.default_top_p = previous_top_p
                        model_client.default_presence_penalty = previous_presence
                        model_client.default_frequency_penalty = previous_frequency
'''
    new_plain = '''                    with orchestrator.client.scoped_sampling_defaults(
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty,
                    ):
                        if stream and orchestrator.would_route(messages, mode):
                            self._stream_route_completion(orchestrator, security, messages, model_name)
                            orchestrator.record_analytics_event(
                                "chat_completion_requested",
                                {
                                    "endpoint_path": "/v1/chat/completions",
                                    "actor_scope": "inference",
                                    "status_code": 200,
                                    "run_mode": "route",
                                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                                    "response_streamed": True,
                                },
                            )
                            return
                        result = self._run(lambda: coordinator.complete(
                            messages,
                            mode=mode,
                            attribution=attribution,
                            hints=routing,
                            model_name=model_name,
                            workflow_run_id=f"run_{uuid.uuid4().hex}",
                        ))
'''
    text = _replace_once(text, old_plain, new_plain, label="plain chat scope")

    old_precedence = '''                    response_max_tokens = (
                        responses_max_tokens
                        if responses_max_tokens is not None
                        else responses_max_completion_tokens
                        if responses_max_completion_tokens is not None
                        else responses_max_output_tokens
                    )
'''
    new_precedence = '''                    response_max_tokens = (
                        responses_max_output_tokens
                        if responses_max_output_tokens is not None
                        else responses_max_completion_tokens
                        if responses_max_completion_tokens is not None
                        else responses_max_tokens
                    )
'''
    text = _replace_once(text, old_precedence, new_precedence, label="Responses token precedence")

    old_responses = '''                    model_client = orchestrator.client
                    previous_max_tokens = model_client.max_output_tokens
                    previous_temperature = model_client.default_temperature
                    previous_top_p = model_client.default_top_p
                    previous_presence = model_client.default_presence_penalty
                    previous_frequency = model_client.default_frequency_penalty
                    response_max_tokens = (
                        responses_max_output_tokens
                        if responses_max_output_tokens is not None
                        else responses_max_completion_tokens
                        if responses_max_completion_tokens is not None
                        else responses_max_tokens
                    )
                    if response_max_tokens is not None:
                        model_client.max_output_tokens = response_max_tokens
                    if responses_temperature is not None:
                        model_client.default_temperature = responses_temperature
                    if responses_top_p is not None:
                        model_client.default_top_p = responses_top_p
                    if responses_presence_penalty is not None:
                        model_client.default_presence_penalty = responses_presence_penalty
                    if responses_frequency_penalty is not None:
                        model_client.default_frequency_penalty = responses_frequency_penalty
                    try:
                        proxied = self._run(
                            lambda: orchestrator.proxy_completion(body, endpoint="responses")
                        )
                    finally:
                        model_client.max_output_tokens = previous_max_tokens
                        model_client.default_temperature = previous_temperature
                        model_client.default_top_p = previous_top_p
                        model_client.default_presence_penalty = previous_presence
                        model_client.default_frequency_penalty = previous_frequency
'''
    new_responses = '''                    response_max_tokens = (
                        responses_max_output_tokens
                        if responses_max_output_tokens is not None
                        else responses_max_completion_tokens
                        if responses_max_completion_tokens is not None
                        else responses_max_tokens
                    )
                    with orchestrator.client.scoped_sampling_defaults(
                        max_output_tokens=response_max_tokens,
                        temperature=responses_temperature,
                        top_p=responses_top_p,
                        presence_penalty=responses_presence_penalty,
                        frequency_penalty=responses_frequency_penalty,
                    ):
                        proxied = self._run(
                            lambda: orchestrator.proxy_completion(body, endpoint="responses")
                        )
'''
    text = _replace_once(text, old_responses, new_responses, label="Responses sampling scope")
    path.write_text(text, encoding="utf-8")


def _update_changelog() -> None:
    """Record the customer-visible concurrency and request-honesty repair."""

    path = ROOT / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n"
    entry = (
        "\n- Sampling limits for Chat, structured output, and Responses requests are now "
        "request-local under the threaded server; concurrent callers cannot overwrite shared "
        "defaults, and the native Responses `max_output_tokens` field has precedence.\n"
    )
    if entry.strip() not in text:
        if marker not in text:
            raise SystemExit("refusing unknown changelog structure")
        text = text.replace(marker, marker + entry, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    """Prove RED, repair production code, then prove focused and full GREEN."""

    _add_regressions()
    red = _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_chat_temperature_top_p_http_honesty.py::test_concurrent_structured_chat_sampling_is_request_local",
        "tests/test_responses_temperature_top_p_http_honesty.py::test_http_responses_prefers_native_max_output_tokens",
        check=False,
    )
    if red.returncode == 0:
        raise SystemExit("sampling regressions unexpectedly passed before the repair")
    _apply_orchestrator_repair()
    _apply_server_repair()
    _update_changelog()
    _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_chat_temperature_top_p_http_honesty.py::test_concurrent_structured_chat_sampling_is_request_local",
        "tests/test_responses_temperature_top_p_http_honesty.py::test_http_responses_prefers_native_max_output_tokens",
    )
    _run(sys.executable, "-m", "pytest", "-q")


if __name__ == "__main__":
    main()
