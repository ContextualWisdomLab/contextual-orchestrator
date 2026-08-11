"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .credentials import get_credential, register_credential
from .orchestrator import ModelClient, TaskOrchestrator, load_agents
from .server import SecurityConfig, serve

DEFAULT_AUTH_TOKEN_KEY = "CONTEXTUAL_ORCHESTRATOR_TOKEN"
DEFAULT_ADMIN_TOKEN_KEY = "CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN"
DEFAULT_INFERENCE_TOKEN_KEY = "CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer for an argparse option."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("positive integer required") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("positive integer required")
    return parsed


def _json_object(value: str) -> dict[str, object]:
    """Parse a JSON object for an argparse option, rejecting other JSON values."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("valid JSON object required") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON object required")
    return parsed


def _resolve_auth_token(explicit: str, credential_name: str) -> str:
    """Resolve a server bearer token from an explicit local value or the KV."""
    if explicit:
        return explicit
    token = get_credential(credential_name)
    if not token:
        raise ValueError(f"server auth credential '{credential_name}' is not configured in the KV")
    return token


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
    parser.add_argument("--state-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_STATE_DB", "") or None,
                        help="Optional sqlite path to persist runs/audit/analytics across restarts (default: in-memory).")
    parser.add_argument("--mode", choices=["auto", "route", "conduct"], default="auto")
    parser.add_argument("--serve", action="store_true", help="Run the chat completions HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--auth-token", default="", help="Explicit local-development bearer token; prefer a KV token name.")
    parser.add_argument("--admin-token", default="", help="Explicit local-development admin token; prefer a KV token name.")
    parser.add_argument("--inference-token", default="", help="Explicit local-development inference token; prefer a KV token name.")
    parser.add_argument("--auth-token-key", default=None,
                        help="KV credential name for the single server bearer token.")
    parser.add_argument("--admin-token-key", default=None,
                        help="KV credential name for the admin bearer token.")
    parser.add_argument("--inference-token-key", default=None,
                        help="KV credential name for the inference bearer token.")
    parser.add_argument("--allow-public-bind", action="store_true")
    parser.add_argument("--insecure-disable-auth", action="store_true", help="Deprecated; API auth is always required.")
    parser.add_argument("--expose-trace-by-default", action="store_true")
    parser.add_argument("--clearfolio-url", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL") or None,
                        help="Base URL of a Clearfolio deployment to use as the admin document viewer (default: disabled).")
    parser.add_argument("--agents-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_AGENTS_DB") or None,
                        help="Optional sqlite path so runtime agent-pool changes (add/patch/remove) survive restarts.")
    parser.add_argument("--provider-ca-bundle", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE") or None,
                        help="Path to a CA bundle used to verify provider TLS (e.g. a corporate gateway root).")
    parser.add_argument("--temperature", type=float, default=0.2,
                        help="Default provider sampling temperature (default: 0.2).")
    parser.add_argument("--max-output-tokens", type=int, default=2048,
                        help="Default provider output token cap (default: 2048).")
    parser.add_argument("--local-concurrency", type=_positive_int, default=1,
                        help="Concurrent requests for explicit mlx:// local batch work (default: 1).")
    parser.add_argument("--chat-template-args", type=_json_object, default={},
                        help="JSON kwargs forwarded to local mlx-lm chat templates, e.g. '{\"enable_thinking\":false}'.")
    parser.add_argument("--budget-max-output-tokens", type=int, default=None,
                        help="Refuse new runs once estimated/reported output tokens reach this cap (default: no cap).")
    parser.add_argument("--budget-max-cost-usd", type=float, default=None,
                        help="Refuse new runs once estimated cost reaches this USD cap (needs a price table; default: no cap).")
    parser.add_argument("--cache-ttl", type=float, default=0.0,
                        help="Seconds to cache identical requests (default 0 = disabled).")
    parser.add_argument("--eval", nargs="+", metavar="PROMPT",
                        help="Measure orchestration vs a single-worker baseline on these prompts and print the report.")
    args = parser.parse_args()

    client = ModelClient(
        ca_bundle=args.provider_ca_bundle,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        local_concurrency=args.local_concurrency,
        chat_template_args=args.chat_template_args,
    )
    orchestrator = TaskOrchestrator(
        load_agents(args.agents),
        client=client,
        state_db=args.state_db,
        agents_db=args.agents_db,
        budget_max_output_tokens=args.budget_max_output_tokens,
        budget_max_cost_usd=args.budget_max_cost_usd,
        cache_ttl=args.cache_ttl,
    )

    if args.eval:
        print(json.dumps(orchestrator.compare_to_baseline(args.eval, mode=args.mode), ensure_ascii=False, indent=2))
        return

    if args.serve:
        single_requested = bool(args.auth_token or args.auth_token_key)
        split_requested = bool(
            args.admin_token or args.inference_token or args.admin_token_key or args.inference_token_key
        )
        if single_requested and split_requested:
            parser.error("choose either --auth-token or the split --admin-token/--inference-token mode")
        if split_requested and not (
            (args.admin_token or args.admin_token_key) and (args.inference_token or args.inference_token_key)
        ):
            parser.error(
                "split token mode requires admin and inference tokens, "
                "provided by --admin-token/--inference-token or "
                "--admin-token-key/--inference-token-key"
            )
        try:
            auth_token = (
                _resolve_auth_token(args.auth_token, args.auth_token_key or DEFAULT_AUTH_TOKEN_KEY)
                if not split_requested
                else ""
            )
            admin_token = (
                _resolve_auth_token(args.admin_token, args.admin_token_key or DEFAULT_ADMIN_TOKEN_KEY)
                if split_requested
                else ""
            )
            inference_token = (
                _resolve_auth_token(args.inference_token, args.inference_token_key or DEFAULT_INFERENCE_TOKEN_KEY)
                if split_requested
                else ""
            )
        except ValueError as exc:
            parser.error(str(exc))
        if not (auth_token or admin_token or inference_token):
            parser.error("--serve requires a KV auth credential or explicit local token")
        serve(
            orchestrator,
            host=args.host,
            port=args.port,
            security=SecurityConfig(
                auth_token=auth_token,
                admin_token=admin_token,
                inference_token=inference_token,
                allow_public_bind=args.allow_public_bind,
                expose_trace_by_default=args.expose_trace_by_default,
            ),
            clearfolio_url=args.clearfolio_url,
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
