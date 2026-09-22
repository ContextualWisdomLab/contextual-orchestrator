"""Synthetic sidecar-shaped measurement of the observed-health quarantine.

Mirrors the construction in ``ContextualWisdomLab/.github``
``scripts/ci/contextual_orchestrator_review_launcher.py`` (read-only
reference): ``configure_logging`` at DEBUG with the sidecar timestamp format,
``register_review_credentials`` from a bootstrap mapping, a ``ModelClient``
with the review sampling settings, ``TaskOrchestrator(agents, client=client)``
and the real HTTP server. Loopback egress is blocked, so the provider is a
fake patched at the lowest transport seam (``ModelClient._open_provider``,
the pattern ``tests/test_ci_gateway_bootstrap.py`` uses) on a reserved
``.invalid`` host; the real retry loop, ``provider_attempt`` logging,
failover, judge and breaker all run and nothing leaves the process:

* ``slow_free_agent`` drops the connection (``RemoteDisconnected``) after
  ``--slow-seconds`` (the evidence p50 is 265 s; the default 0.265 s is a
  1/1000 time scale);
* ``steady_free_agent`` answers after ``--fast-seconds``.

It sends ``--requests`` sequential ``orchestrator/free`` chat completions and
prints per-request ``http_request`` latency and ``provider_attempt`` counts
parsed from the process log. **Synthetic, not provider-real**: it measures the
policy's effect on this fixed failure pattern only.

Usage::

    python3 scripts/measure_health_quarantine_sidecar.py --mode off|on|kv [--requests 8]

``on`` passes ``observed_health_quarantine=True``; ``kv`` constructs the
orchestrator exactly as the launcher does and seeds the KV switch through
``register_review_credentials`` instead.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import logging
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.debug_logging import configure_logging  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.review_gateway import (  # noqa: E402
    REVIEW_AUTH_CREDENTIAL_NAME,
    register_review_credentials,
)
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402

SIDECAR_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
SWITCH_NAME = "CONTEXTUAL_ORCHESTRATOR_OBSERVED_HEALTH_QUARANTINE"
_TOKEN = "synthetic_sidecar_measurement_token"
_TAGS = ("cost:free", "reasoning", "writing", "planning", "coding", "verification")
_HTTP = re.compile(r"http_request method=POST path=/v1/chat/completions status=(\d+) latency_ms=([\d.]+) .*request_id=(\w+)")
_ATTEMPT = re.compile(r"provider_attempt agent_id=(\S+) .* request_id=(\w+)")


class _FakeResponse:
    """Minimal context-managed provider response (the shape ``_open_provider`` returns)."""

    def __init__(self, content: str) -> None:
        self._body = json.dumps(
            {
                "id": "chatcmpl_synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self, amount: int | None = None) -> bytes:
        body, self._body = self._body, b""
        return body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return default

    def close(self) -> None:
        self._body = b""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def _fake_open_provider(slow_seconds: float, fast_seconds: float, seen: list[dict[str, Any]]):
    """Return an ``_open_provider`` replacement; nothing leaves the process."""

    def _open_provider(self, request, destination=None, *, timeout=None):
        del self, destination, timeout
        payload = json.loads(request.data.decode("utf-8")) if request.data else {}
        model = payload.get("model", "")
        messages = payload.get("messages") or []
        system = messages[0].get("content", "") if messages else ""
        kind = (
            "triage"
            if system == TaskOrchestrator.TRIAGE_SYSTEM_PROMPT
            else "structured" if payload.get("response_format") else "chat"
        )
        seen.append({"model": model, "kind": kind})
        if model == "vendor/slow-model":
            time.sleep(slow_seconds)
            raise http.client.RemoteDisconnected("synthetic remote end closed connection")
        time.sleep(fast_seconds)
        if kind == "triage":
            return _FakeResponse('{"workflow_required": false}')
        return _FakeResponse("synthetic review answer citing evidence, risks and caveats")

    return _open_provider


def run(mode: str, requests: int, slow_seconds: float, fast_seconds: float) -> dict[str, Any]:
    """Serve one sidecar-shaped process, send the requests, return parsed metrics."""
    buffer = io.StringIO()
    configure_logging("DEBUG")
    root = logging.getLogger()
    handler = logging.StreamHandler(buffer)
    root.addHandler(handler)
    for item in root.handlers:
        item.setFormatter(logging.Formatter(SIDECAR_LOG_FORMAT))
    bootstrap = {"NVIDIA_NIM_API_KEY": "synthetic-not-a-key", REVIEW_AUTH_CREDENTIAL_NAME: _TOKEN}
    if mode == "kv":
        bootstrap[SWITCH_NAME] = "enabled"
    register_review_credentials(bootstrap)
    seen: list[dict[str, Any]] = []
    ModelClient._validate_provider = lambda self, agent: None
    ModelClient._open_provider = _fake_open_provider(slow_seconds, fast_seconds, seen)
    agents = [
        ModelAgent("slow_free_agent", "vendor/slow-model", base_url="https://provider.invalid/v1",
                   api_key_env="NVIDIA_NIM_API_KEY", tags=_TAGS, priority=10),
        ModelAgent("steady_free_agent", "vendor/steady-model", base_url="https://provider.invalid/v1",
                   api_key_env="NVIDIA_NIM_API_KEY", tags=_TAGS, priority=1),
    ]
    client = ModelClient(max_output_tokens=2048, temperature=0.1)
    kwargs = {"observed_health_quarantine": True} if mode == "on" else {}
    orchestrator = TaskOrchestrator(agents, client=client, **kwargs)
    server = build_server(orchestrator, port=0, security=SecurityConfig(auth_token=_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for index in range(requests):
            body = {
                "model": TaskOrchestrator.FREE_MODEL,
                "messages": [{"role": "user", "content": f"review change set {index}"}],
            }
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"content-type": "application/json", "authorization": f"Bearer {_TOKEN}"},
                method="POST",
            )
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected - fixed http://127.0.0.1 scheme/host; the port is the ephemeral local server this script just started, never external input.
            with urllib.request.urlopen(request, timeout=60) as response:
                response.read()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        root.removeHandler(handler)
        handler.close()
    log = buffer.getvalue()
    attempts: dict[str, list[str]] = {}
    for line in log.splitlines():
        match = _ATTEMPT.search(line)
        if match:
            attempts.setdefault(match.group(2), []).append(match.group(1))
    rows = []
    for line in log.splitlines():
        match = _HTTP.search(line)
        if match:
            status, latency, request_id = match.groups()
            tried = attempts.get(request_id, [])
            rows.append(
                {
                    "status": int(status),
                    "latency_ms": float(latency),
                    "provider_attempts": len(tried),
                    "slow_attempts": tried.count("slow_free_agent"),
                }
            )
    return {
        "label": "SYNTHETIC - fake in-process provider at 1/1000 time scale; not provider-real",
        "mode": mode,
        "health_policy": orchestrator.admin_state()["routing_evidence"].get("health_policy"),
        "slow_seconds": slow_seconds,
        "requests": rows,
        "total_latency_ms": round(sum(row["latency_ms"] for row in rows), 1),
        "total_provider_attempts": sum(row["provider_attempts"] for row in rows),
        "total_slow_attempts": sum(row["slow_attempts"] for row in rows),
        "circuit_opened_lines": log.count("circuit_opened "),
        "provider_calls_by_kind": {
            kind: sum(1 for item in seen if item["kind"] == kind)
            for kind in ("triage", "chat", "structured")
        },
        "slow_calls_by_kind": {
            kind: sum(1 for item in seen if item["kind"] == kind and item["model"] == "vendor/slow-model")
            for kind in ("triage", "chat", "structured")
        },
    }


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """Parse arguments, run one mode, print JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("off", "on", "kv"), required=True)
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--slow-seconds", type=float, default=0.265)
    parser.add_argument("--fast-seconds", type=float, default=0.005)
    args = parser.parse_args(argv)
    result = run(args.mode, args.requests, args.slow_seconds, args.fast_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
