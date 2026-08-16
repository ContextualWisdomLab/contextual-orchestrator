"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .credentials import register_credential, resolve_server_auth_tokens, seed_server_auth_from_environ
from .kv_config import (
    resolve_serve_runtime_paths,
    seed_provider_egress_from_environ,
    seed_serve_runtime_from_environ,
)
from .orchestrator import ModelClient, TaskOrchestrator, load_agents
from .server import SecurityConfig, serve


def serve_security_tokens(args: argparse.Namespace) -> tuple[str, str, str]:
    """Seed env authenticators into the KV once, then resolve serve tokens.

    Explicit CLI flags win. Env is bootstrap transport only. Buyer next
    action: pass ``--auth-token`` or start once with
    ``CONTEXTUAL_ORCHESTRATOR_TOKEN`` so the KV can copy it.
    """
    seed_server_auth_from_environ()
    return resolve_server_auth_tokens(
        auth_token=args.auth_token,
        admin_token=args.admin_token,
        inference_token=args.inference_token,
    )


def serve_runtime_paths(args: argparse.Namespace) -> tuple[str | None, str | None, str | None, str | None]:
    """Seed env sqlite/Clearfolio/TLS paths into the KV once, then resolve them.

    Explicit CLI flags win. Env is bootstrap transport only. Buyer next
    action: pass ``--state-db``, ``--agents-db``, ``--clearfolio-url``, and
    ``--provider-ca-bundle``, or start once with the matching
    ``CONTEXTUAL_ORCHESTRATOR_*`` variables so the KV can copy them.
    """
    seed_serve_runtime_from_environ()
    return resolve_serve_runtime_paths(
        state_db=args.state_db,
        agents_db=args.agents_db,
        clearfolio_url=args.clearfolio_url,
        provider_ca_bundle=args.provider_ca_bundle,
    )


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
    parser.add_argument(
        "--state-db",
        default="",
        help="Optional sqlite path to persist runs/audit/analytics. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_STATE_DB into the serve_runtime KV once.",
    )
    parser.add_argument("--mode", choices=["auto", "route", "conduct"], default="auto")
    parser.add_argument("--serve", action="store_true", help="Run the chat completions HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--auth-token",
        default="",
        help="Gateway Bearer token. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_TOKEN into the credential KV once.",
    )
    parser.add_argument(
        "--admin-token",
        default="",
        help="Admin Bearer token. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN into the credential KV once.",
    )
    parser.add_argument(
        "--inference-token",
        default="",
        help="Inference Bearer token. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN into the credential KV once.",
    )
    parser.add_argument("--allow-public-bind", action="store_true")
    parser.add_argument("--insecure-disable-auth", action="store_true", help="Deprecated; API auth is always required.")
    parser.add_argument("--expose-trace-by-default", action="store_true")
    parser.add_argument(
        "--clearfolio-url",
        default="",
        help="Clearfolio viewer URL. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL into the serve_runtime KV once.",
    )
    parser.add_argument(
        "--agents-db",
        default="",
        help="Optional sqlite path for runtime agent-pool changes. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_AGENTS_DB into the serve_runtime KV once.",
    )
    parser.add_argument(
        "--provider-ca-bundle",
        default="",
        help="Provider TLS CA bundle path. When omitted, bootstrap copies CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE into the serve_runtime KV once.",
    )
    parser.add_argument("--insecure-skip-tls-verify", action="store_true",
                        help="Dev only: do not verify provider TLS certificates (insecure).")
    parser.add_argument("--budget-max-output-tokens", type=int, default=None,
                        help="Refuse new runs once estimated/reported output tokens reach this cap (default: no cap).")
    parser.add_argument("--budget-max-cost-usd", type=float, default=None,
                        help="Refuse new runs once estimated cost reaches this USD cap (needs a price table; default: no cap).")
    parser.add_argument("--cache-ttl", type=float, default=0.0,
                        help="Seconds to cache identical requests (default 0 = disabled).")
    parser.add_argument("--eval", nargs="+", metavar="PROMPT",
                        help="Measure orchestration vs a single-worker baseline on these prompts and print the report.")
    args = parser.parse_args()

    seed_provider_egress_from_environ()
    state_db, agents_db, clearfolio_url, provider_ca_bundle = serve_runtime_paths(args)
    client = ModelClient(ca_bundle=provider_ca_bundle, verify_tls=not args.insecure_skip_tls_verify)
    orchestrator = TaskOrchestrator(
        load_agents(args.agents),
        client=client,
        state_db=state_db,
        agents_db=agents_db,
        budget_max_output_tokens=args.budget_max_output_tokens,
        budget_max_cost_usd=args.budget_max_cost_usd,
        cache_ttl=args.cache_ttl,
    )

    if args.eval:
        print(json.dumps(orchestrator.compare_to_baseline(args.eval, mode=args.mode), ensure_ascii=False, indent=2))
        return

    if args.serve:
        auth_token, admin_token, inference_token = serve_security_tokens(args)
        if not (auth_token or admin_token or inference_token):
            parser.error(
                "--serve requires --auth-token, split --admin-token/--inference-token, "
                "or matching CONTEXTUAL_ORCHESTRATOR_* environment variables "
                "so bootstrap can copy them into the credential KV"
            )
        if not auth_token and (admin_token or inference_token) and not (
            admin_token and inference_token
        ):
            parser.error("split token mode requires both --admin-token and --inference-token")
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
            clearfolio_url=clearfolio_url,
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
