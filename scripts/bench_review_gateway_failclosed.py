"""Compare review request paths with a loopback-only synthetic provider.

Run this same file from each checkout; the current directory selects the source
revision. No external provider, credential, or research payload is used.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))

from contextual_orchestrator import review_gateway  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    set_backend,
)
from contextual_orchestrator.model_discovery import DiscoveredModel  # noqa: E402
from contextual_orchestrator.provider_errors import ProviderUpstreamError  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def percentile(values: list[float], percent: int) -> float:
    """Return the empirical nearest-rank percentile in milliseconds."""
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * percent + 99) // 100 - 1)]


def main() -> None:
    """Measure identical direct and HTTP requests on the checked-out source."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests-per-round", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--provider-delay-ms", type=float, default=10)
    parser.add_argument("--expected-explicit-status", type=int, choices=(200, 400), required=True)
    args = parser.parse_args()
    if min(args.requests_per_round, args.rounds, args.concurrency) < 1 or args.warmup < 0:
        parser.error("request, round, and concurrency counts must be positive; warmup cannot be negative")
    if args.provider_delay_ms < 0:
        parser.error("provider delay cannot be negative")

    provider_calls = 0
    provider_paths: Counter[str] = Counter()
    provider_lock = threading.Lock()

    class ProviderHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal provider_calls
            with provider_lock:
                provider_calls += 1
                provider_paths[self.path] += 1
            time.sleep(args.provider_delay_ms / 1000)
            payload = json.dumps({
                "id": "synthetic-response",
                "object": "chat.completion",
                "model": "router-review",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "synthetic-ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    set_backend(InMemoryCredentialBackend())
    gateway = None
    gateway_thread = None
    try:
        discovered = DiscoveredModel(
            provider_name="openrouter",
            model_id="router-review",
            credential_name="OPENROUTER_API_KEY",
            chat_base_url=f"local://127.0.0.1:{provider.server_address[1]}/v1",
            auth_scheme="Bearer",
            prompt_price_per_1k=0.0,
            completion_price_per_1k=0.0,
            is_free=True,
            capabilities=("chat",),
            input_modalities=("text",),
            output_modalities=("text",),
        )
        with patch.object(review_gateway, "discover_all_models", return_value=([discovered], [])):
            orchestrator = review_gateway.build_review_orchestrator({"OPENROUTER_API_KEY": "synthetic-only"})
        gateway = build_server(
            orchestrator,
            port=0,
            security=SecurityConfig(
                auth_token="synthetic-only",
                rate_limit_requests=100_000,
                max_concurrent_runs=max(32, args.concurrency),
            ),
        )
        gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        gateway_thread.start()
        endpoint = f"http://127.0.0.1:{gateway.server_address[1]}/v1/chat/completions"
        body = {
            "model": "router-review",
            "messages": [{"role": "user", "content": "synthetic review request"}],
        }

        def direct() -> tuple[int, str]:
            try:
                orchestrator.proxy_completion(json.loads(json.dumps(body)))
                return 200, "ok"
            except ProviderUpstreamError as exc:
                return exc.client_status, exc.error_code

        def http(model: str) -> tuple[int, str]:
            request = urllib.request.Request(
                endpoint,
                data=json.dumps({**body, "model": model}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer synthetic-only"},
                method="POST",
            )
            try:
                response = urllib.request.urlopen(request, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                payload = json.load(response)
                return response.status, payload.get("error", {}).get("code", "ok")

        scenarios = {
            "direct_explicit": direct,
            "http_explicit": lambda: http("router-review"),
            "http_free_control": lambda: http("orchestrator/free"),
        }
        summaries = {}
        for name, call in scenarios.items():
            for _ in range(args.warmup):
                call()
            before = provider_calls
            before_paths = provider_paths.copy()
            latencies: list[float] = []
            outcomes: Counter[str] = Counter()
            rates: list[float] = []

            def timed() -> tuple[int, str, float]:
                start = time.perf_counter()
                status, code = call()
                return status, code, (time.perf_counter() - start) * 1000

            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                for _ in range(args.rounds):
                    start = time.perf_counter()
                    for status, code, elapsed_ms in pool.map(lambda unused: timed(), range(args.requests_per_round)):
                        outcomes[f"{status}:{code}"] += 1
                        latencies.append(elapsed_ms)
                    rates.append(args.requests_per_round / (time.perf_counter() - start))
            expected = (
                "503:allocation_evidence_unavailable"
                if name == "http_free_control"
                else "200:ok" if args.expected_explicit_status == 200
                else "400:review_model_not_allowed"
            )
            if set(outcomes) != {expected}:
                raise AssertionError(f"{name}: unexpected outcomes {dict(outcomes)}")
            sends = provider_calls - before
            if (expected == "200:ok" and sends < len(latencies)) or (
                expected != "200:ok" and sends != 0
            ):
                raise AssertionError(f"{name}: unexpected provider send count {sends}")
            summaries[name] = {
                "samples": len(latencies),
                "outcomes": dict(sorted(outcomes.items())),
                "provider_sends": sends,
                "provider_paths": dict(provider_paths - before_paths),
                "latency_ms_p50": round(statistics.median(latencies), 3),
                "latency_ms_p95": round(percentile(latencies, 95), 3),
                "round_throughput_rps": [round(rate, 2) for rate in rates],
                "throughput_rps_mean": round(statistics.mean(rates), 2),
                "throughput_rps_range": [round(min(rates), 2), round(max(rates), 2)],
            }
        print(json.dumps({
            "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "runner": "local loopback HTTP gateway and synthetic provider",
            "host": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "settings": vars(args),
            "scenarios": summaries,
        }, sort_keys=True))
    finally:
        if gateway is not None:
            gateway.shutdown()
            if gateway_thread is not None:
                gateway_thread.join(timeout=5)
            gateway.server_close()
        provider.shutdown()
        provider_thread.join(timeout=5)
        provider.server_close()
        set_backend(None)


if __name__ == "__main__":
    main()
