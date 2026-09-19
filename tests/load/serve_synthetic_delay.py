"""Run the real HTTP gateway with a synthetic delayed provider for k6.

The fixture keeps load evidence deterministic and non-identifying while still
exercising authentication, request parsing, routing, run-slot admission,
provider waiting, response framing, and liveness on the production server.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, serve  # noqa: E402


class DelayedModelClient(ModelClient):
    """Model client whose provider call has a measured synthetic delay."""

    def __init__(self, delay_seconds: float) -> None:
        super().__init__(max_retries=0)
        self.delay_seconds = delay_seconds

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, object]],
        temperature: float | None = None,
    ) -> str:
        """Wait like an upstream provider, then return a deterministic reply."""
        del agent, messages, temperature
        time.sleep(self.delay_seconds)
        return "synthetic-load-response"


def main() -> None:
    """Parse load-fixture controls and serve until interrupted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18089)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-concurrent-runs", type=int, default=64)
    parser.add_argument("--token", default="synthetic-load-token")
    args = parser.parse_args()
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")
    orchestrator = TaskOrchestrator(
        [ModelAgent("synthetic_slow_agent", "synthetic-slow-model", tags=("reasoning",))],
        client=DelayedModelClient(args.delay_seconds),
    )
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(
            auth_token=args.token,
            allow_public_bind=args.host in {"0.0.0.0", "::", ""},
            rate_limit_requests=100_000,
            max_concurrent_runs=args.max_concurrent_runs,
        ),
    )


if __name__ == "__main__":
    main()
