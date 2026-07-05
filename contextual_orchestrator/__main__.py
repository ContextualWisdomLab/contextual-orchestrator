"""Command-line entrypoint for routing prompts or serving the orchestration API."""

from __future__ import annotations

import argparse
import json
import os

from .orchestrator import TaskOrchestrator, load_agents
from .server import SecurityConfig, serve


def main() -> None:
    """Parse CLI options and run either prompt completion or the HTTP server."""
    parser = argparse.ArgumentParser(description="Route or conduct chat requests across model agents.")
    parser.add_argument("prompt", nargs="?", help="User prompt for CLI mode.")
    parser.add_argument("--agents", default="examples/agents.mock.json", help="Agent config JSON.")
    parser.add_argument("--state-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_STATE_DB", "") or None,
                        help="Optional sqlite path to persist runs/audit/analytics across restarts (default: in-memory).")
    parser.add_argument("--mode", choices=["auto", "route", "conduct"], default="auto")
    parser.add_argument("--serve", action="store_true", help="Run the chat completions HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--auth-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_TOKEN", ""))
    parser.add_argument("--admin-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN", ""))
    parser.add_argument("--inference-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN", ""))
    parser.add_argument("--allow-public-bind", action="store_true")
    parser.add_argument("--insecure-disable-auth", action="store_true", help="Only allowed for loopback local development.")
    parser.add_argument("--expose-trace-by-default", action="store_true")
    args = parser.parse_args()

    orchestrator = TaskOrchestrator(load_agents(args.agents), state_db=args.state_db)

    if args.serve:
        if not (args.auth_token or args.admin_token or args.inference_token) and not args.insecure_disable_auth:
            parser.error(
                "--serve requires --auth-token, split --admin-token/--inference-token, "
                "or matching CONTEXTUAL_ORCHESTRATOR_* environment variables"
            )
        if not args.auth_token and (args.admin_token or args.inference_token) and not (
            args.admin_token and args.inference_token
        ):
            parser.error("split token mode requires both --admin-token and --inference-token")
        serve(
            orchestrator,
            host=args.host,
            port=args.port,
            security=SecurityConfig(
                auth_token=args.auth_token,
                admin_token=args.admin_token,
                inference_token=args.inference_token,
                allow_public_bind=args.allow_public_bind,
                expose_trace_by_default=args.expose_trace_by_default,
            ),
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
