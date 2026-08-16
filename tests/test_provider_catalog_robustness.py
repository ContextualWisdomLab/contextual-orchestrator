"""Exception-robust routing: partial keys, 429 failover, circuit breaker, malformed JSON.

These are fail-closed contracts, not happy-path demos. FrugalGPT / Hybrid LLM
routing re-runs the cost-performance chooser on the remaining healthy pool
when an upstream 429s or returns junk — not a YAML list walk (Chen et al.,
2023; Ding et al., 2024). Missing credentials must never fall back to GitHub
Models.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


class _ScriptedClient(ModelClient):
    """Capability-preserving client that scripts per-agent outcomes."""

    def __init__(self, outcomes: dict[str, list[object]]) -> None:
        super().__init__(max_retries=1, retry_backoff=0.0)
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        queue = self.outcomes.setdefault(agent.id, [])
        if not queue:
            return f"[{agent.id}] ok"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


NIM_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
OPENAI_MODEL = "gpt-5.5"
WORKER_PRICES = {NIM_MODEL: 1.0, OPENAI_MODEL: 20.0}


def _https_workers() -> list[ModelAgent]:
    # File order is OpenAI then NIM. The chooser must still pick cheaper NIM first.
    return [
        ModelAgent(
            "backup_openai_agent",
            OPENAI_MODEL,
            "https://api.openai.com/v1",
            credential_key="OPENAI_API_KEY",
            tags=("reasoning", "coding", "writing"),
        ),
        ModelAgent(
            "primary_nim_agent",
            NIM_MODEL,
            "https://integrate.api.nvidia.com/v1",
            credential_key="NVIDIA_NIM_API_KEY",
            tags=("reasoning", "coding", "writing"),
        ),
    ]


def test_one_provider_429_failovers_to_next_capability_matched_agent() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    register_credential("OPENAI_API_KEY", "sk-test")
    client = _ScriptedClient(
        {
            "primary_nim_agent": [_http_error(429), _http_error(429)],
            "backup_openai_agent": ["backup answer"],
        }
    )
    orchestrator = TaskOrchestrator(_https_workers(), client=client, price_per_million=WORKER_PRICES)
    result = orchestrator.route_once([{"role": "user", "content": "route this coding task"}])
    assert result["answer"] == "backup answer"
    assert result["trace"][0]["served_agent_id"] == "backup_openai_agent"
    assert result["trace"][0]["failover_from"] == "primary_nim_agent"
    assert client.calls[0] == "primary_nim_agent"
    assert "backup_openai_agent" in client.calls


def test_one_missing_credential_disables_that_worker_and_others_still_route() -> None:
    register_credential("OPENAI_API_KEY", "sk-only")
    # NVIDIA_NIM_API_KEY is deliberately absent.
    client = _ScriptedClient({"backup_openai_agent": ["openai served"]})
    orchestrator = TaskOrchestrator(_https_workers(), client=client, price_per_million=WORKER_PRICES)
    result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert result["answer"] == "openai served"
    assert "primary_nim_agent" not in client.calls
    assert client.calls == ["backup_openai_agent"]


def test_all_credentials_missing_fail_closed_without_github_models_fallback() -> None:
    client = _ScriptedClient({})
    orchestrator = TaskOrchestrator(_https_workers(), client=client, price_per_million=WORKER_PRICES)
    with pytest.raises(NotConfigured) as exc:
        orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    message = str(exc.value).lower()
    assert "notconfigured" in type(exc.value).__name__.lower() or "credential" in message or "resolvable" in message
    assert "copilot" not in message
    assert client.calls == []
    assert all("github" not in agent.base_url for agent in orchestrator.agents)
    assert all(agent.credential_name != "COPILOT_GITHUB_TOKEN" for agent in orchestrator.agents)


def test_timeout_and_5xx_open_circuit_then_skip_dead_agent() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    register_credential("OPENAI_API_KEY", "sk-test")
    client = _ScriptedClient(
        {
            "primary_nim_agent": [
                TimeoutError("read timeout"),
                _http_error(503),
                _http_error(502),
            ]
        }
    )
    orchestrator = TaskOrchestrator(_https_workers(), client=client, price_per_million=WORKER_PRICES)
    for _ in range(orchestrator.circuit_failure_threshold):
        output, served, _usage = orchestrator._invoke(
            orchestrator._agent("primary_nim_agent"),
            [{"role": "system", "content": "Role: worker"}, {"role": "user", "content": "go"}],
            text="go",
            role="worker",
        )
        assert served == "backup_openai_agent"
        assert "backup" in output or served == "backup_openai_agent"
    assert orchestrator._circuit_open("primary_nim_agent") is True
    candidates = orchestrator._failover_candidates(
        orchestrator._agent("primary_nim_agent"), "go", "worker"
    )
    assert [agent.id for agent in candidates] == ["backup_openai_agent"]


class _FakeChatProvider:
    """Scripted OpenAI-compatible /chat/completions over loopback HTTP."""

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.request_count = 0
        self.responses = responses
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                self.rfile.read(length)
                index = min(outer.request_count, len(outer.responses) - 1)
                outer.request_count += 1
                status, body = outer.responses[index]
                raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_FakeChatProvider":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


class _LoopbackClient(ModelClient):
    """Full urllib transport that skips public-HTTPS egress checks for lab fixtures."""

    def _validate_provider(self, agent: ModelAgent) -> None:
        if get_credential(agent.credential_name) is None:
            raise NotConfigured(
                f"{agent.id} requires a resolvable credential '{agent.credential_name}' in the KV"
            )


def test_malformed_provider_response_failovers_instead_of_crashing() -> None:
    register_credential("NVIDIA_NIM_API_KEY", "nvapi-test")
    register_credential("OPENAI_API_KEY", "sk-test")
    good = {"choices": [{"message": {"role": "assistant", "content": "recovered from junk"}}]}
    with _FakeChatProvider([(200, {"not": "a completion"})]) as bad, _FakeChatProvider([(200, good)]) as ok:
        agents = [
            ModelAgent(
                "backup_openai_agent",
                OPENAI_MODEL,
                ok.base_url,
                credential_key="OPENAI_API_KEY",
                tags=("reasoning", "writing"),
            ),
            ModelAgent(
                "primary_nim_agent",
                NIM_MODEL,
                bad.base_url,
                credential_key="NVIDIA_NIM_API_KEY",
                tags=("reasoning", "writing"),
            ),
        ]
        orchestrator = TaskOrchestrator(
            agents,
            client=_LoopbackClient(max_retries=0, retry_backoff=0.0),
            price_per_million=WORKER_PRICES,
        )
        result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert result["answer"] == "recovered from junk"
    assert result["trace"][0]["served_agent_id"] == "backup_openai_agent"


def test_malformed_provider_response_does_not_crash_the_http_gateway() -> None:
    register_credential("OPENAI_API_KEY", "sk-test")
    with _FakeChatProvider([(200, b"{"), (200, {"choices": []})]) as provider:
        agent = ModelAgent(
            "solo_openai_agent",
            "gpt-5.5",
            provider.base_url,
            credential_key="OPENAI_API_KEY",
            tags=("reasoning", "writing"),
        )
        orchestrator = TaskOrchestrator([agent], client=_LoopbackClient(max_retries=0, retry_backoff=0.0))
        token = "sidecar_token"
        server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            import urllib.request

            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": "contextual-orchestrator",
                        "messages": [{"role": "user", "content": "Write a short status update."}],
                    }
                ).encode("utf-8"),
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    "connection": "close",
                },
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request, timeout=5)
            assert exc.value.code in {500, 502, 503}
            body = json.loads(exc.value.read().decode("utf-8"))
            assert "error" in body
        finally:
            server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
