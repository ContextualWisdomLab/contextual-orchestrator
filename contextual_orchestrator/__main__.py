"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .credentials import get_credential, register_credential
from .orchestrator import ModelClient, TaskOrchestrator, load_agents
from .server import SecurityConfig, serve


def _read_stdin_credential() -> str:
    """Read a piped secret, tolerating the UTF-8 BOM emitted by Windows tools."""

    return sys.stdin.read().lstrip("\ufeff").strip()


def _read_stdin_credentials() -> dict[str, str]:
    """Read a JSON object of named secrets from stdin."""

    raw = _read_stdin_credential()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("stdin must contain a JSON object of named secrets") from exc
    if not isinstance(values, dict) or not values:
        raise ValueError("stdin must contain a non-empty JSON object of named secrets")
    if any(
        not isinstance(name, str)
        or not name
        or not isinstance(value, str)
        or not value
        for name, value in values.items()
    ):
        raise ValueError("credential names and values must be non-empty strings")
    return values


def _resolve_credential(parser: argparse.ArgumentParser, name: str | None) -> str:
    """Resolve a runtime secret by KV name, never by argv or environment value."""

    if not name:
        return ""
    value = get_credential(name)
    if not value:
        parser.error(f"credential {name!r} is not registered in the KV")
    return value


def _register_credential_command(argv: list[str]) -> None:
    """Bootstrap: read a deploy-time secret and store it in the KV credential registry.

    Secret values enter through stdin only. The running orchestrator resolves
    them from the KV via get_credential(). See docs/kv-credentials.md.
    """
    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator register-credential",
        description="Store a provider credential into the KV registry at bootstrap.",
    )
    parser.add_argument("--name", required=True, help="Credential name, e.g. OPENAI_API_KEY.")
    parser.add_argument(
        "--value-stdin",
        action="store_true",
        help="Read the secret value from stdin (the only supported secret transport).",
    )
    args = parser.parse_args(argv)

    value = _read_stdin_credential()

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
    parser.add_argument("--auth-token-credential", metavar="NAME", help="KV name for the shared API token.")
    parser.add_argument("--admin-token-credential", metavar="NAME", help="KV name for the admin API token.")
    parser.add_argument("--inference-token-credential", metavar="NAME", help="KV name for the inference API token.")
    bootstrap = parser.add_mutually_exclusive_group()
    bootstrap.add_argument(
        "--bootstrap-credential-stdin",
        metavar="NAME",
        help="Read one provider secret from stdin into the KV before serving.",
    )
    bootstrap.add_argument(
        "--bootstrap-credentials-stdin",
        action="store_true",
        help="Read a JSON object of named secrets from stdin into the KV before serving.",
    )
    parser.add_argument("--allow-public-bind", action="store_true")
    parser.add_argument("--insecure-disable-auth", action="store_true", help="Deprecated; API auth is always required.")
    parser.add_argument("--expose-trace-by-default", action="store_true")
    parser.add_argument("--clearfolio-url", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL") or None,
                        help="Base URL of a Clearfolio deployment to use as the admin document viewer (default: disabled).")
    parser.add_argument("--agents-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_AGENTS_DB") or None,
                        help="Optional sqlite path so runtime agent-pool changes (add/patch/remove) survive restarts.")
    parser.add_argument("--provider-ca-bundle", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE") or None,
                        help="Path to a CA bundle used to verify provider TLS (e.g. a corporate gateway root).")
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

    if args.bootstrap_credential_stdin:
        if not args.serve:
            parser.error("--bootstrap-credential-stdin requires --serve")
        value = _read_stdin_credential()
        if not value:
            parser.error("empty credential value on stdin")
        register_credential(args.bootstrap_credential_stdin, value)
        del value
    elif args.bootstrap_credentials_stdin:
        if not args.serve:
            parser.error("--bootstrap-credentials-stdin requires --serve")
        try:
            values = _read_stdin_credentials()
        except ValueError as exc:
            parser.error(str(exc))
        for name, value in values.items():
            register_credential(name, value)
        del values, value

    client = ModelClient(ca_bundle=args.provider_ca_bundle, verify_tls=not args.insecure_skip_tls_verify)
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
        auth_token = _resolve_credential(parser, args.auth_token_credential)
        admin_token = _resolve_credential(parser, args.admin_token_credential)
        inference_token = _resolve_credential(parser, args.inference_token_credential)
        if not (auth_token or admin_token or inference_token):
            parser.error(
                "--serve requires --auth-token-credential or split "
                "--admin-token-credential/--inference-token-credential"
            )
        if not auth_token and (admin_token or inference_token) and not (admin_token and inference_token):
            parser.error(
                "split token mode requires both --admin-token-credential and "
                "--inference-token-credential"
            )
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
