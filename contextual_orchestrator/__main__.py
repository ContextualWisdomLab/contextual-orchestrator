"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .credentials import register_credential
from .orchestrator import TaskOrchestrator, load_agents
from .server import SecurityConfig, serve


def _register_credential_command(argv: list[str]) -> None:
    """Bootstrap: read a deploy-time secret and store it in the KV credential registry.

    Environment is used ONLY as bootstrap transport here (to select/connect to
    the KV, and optionally to carry the secret value in from the deploy step).
    The running orchestrator never reads the provider key from os.getenv — it
    resolves it from the KV via get_credential(). See docs/kv-credentials.md.
    """
    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator register-credential",
        description="Store a provider credential into the KV registry at bootstrap.",
    )
    parser.add_argument("--name", required=True, help="Credential name, e.g. OPENAI_API_KEY.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--value-stdin",
        action="store_true",
        help="Read the secret value from stdin (preferred; keeps it out of argv/env).",
    )
    source.add_argument(
        "--from-env",
        metavar="VAR",
        help="Bootstrap transport: read the secret value from this env var (e.g. --from-env OPENAI_API_KEY).",
    )
    args = parser.parse_args(argv)

    if args.from_env:
        # Bootstrap transport only: the deploy step injects secrets.OPENAI_API_KEY
        # into this one-shot process; it is never read at request time.
        if args.from_env not in os.environ:
            parser.error(f"env var {args.from_env} is not set for bootstrap transport")
        value = os.environ[args.from_env]
    else:
        # Default: read from stdin so the secret never touches argv or the app env.
        value = sys.stdin.read().strip()

    if not value:
        parser.error("empty credential value; provide a non-empty secret")

    register_credential(args.name, value)
    print(json.dumps({"registered": args.name, "backend": "kv"}, ensure_ascii=False))


def main() -> None:
    """Parse CLI options and run bootstrap, prompt completion, or the HTTP server."""
    if len(sys.argv) > 1 and sys.argv[1] == "register-credential":
        _register_credential_command(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description="Route or conduct chat requests across model agents.")
    parser.add_argument("prompt", nargs="?", help="User prompt for CLI mode.")
    parser.add_argument("--agents", default="examples/agents.mock.json", help="Agent config JSON.")
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

    orchestrator = TaskOrchestrator(load_agents(args.agents))

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
