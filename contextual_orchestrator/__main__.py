"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace

from .cost_ledger import PriceBook
from .cost_router import CostRoutingCoordinator
from .credentials import get_credential, register_credential
from .kv_config import InMemoryConfigStore
from .model_discovery import (
    CONFIGURED_GATEWAY_CREDENTIAL_NAME,
    PROVIDER_MODEL_SOURCES,
    ProviderModelSource,
    agent_from_discovered,
    agent_id_for,
    configured_gateway_source,
    discover_all_models,
    free_discovered_models,
    refresh_price_book,
    select_bootstrap_discovered_agents,
)
from .orchestrator import (
    CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1,
    MAX_LOCAL_CONCURRENCY,
    ModelAgent,
    ModelClient,
    TaskOrchestrator,
    load_agents,
)
from .server import SecurityConfig, serve

DEFAULT_AUTH_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_TOKEN"
DEFAULT_ADMIN_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN"
DEFAULT_INFERENCE_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"


def _bootstrap_telemetry_config() -> InMemoryConfigStore:
    """Load non-secret OTEL deployment settings into the process KV at startup."""
    config = InMemoryConfigStore()
    for environment_name, key in (
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "exporter_otlp_endpoint"),
        ("OTEL_SERVICE_NAME", "service_name"),
        ("OTEL_SDK_DISABLED", "sdk_disabled"),
    ):
        value = os.environ.get(environment_name, "").strip()
        if value:
            config.set("telemetry", key, value)
    return config


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer for an argparse option."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("positive integer required") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("positive integer required")
    return parsed


def _non_negative_int(value: str) -> int:
    """Parse a non-negative integer for an argparse option (0 means "off")."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("non-negative integer required") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("non-negative integer required")
    return parsed


def _local_concurrency(value: str) -> int:
    """Parse a bounded local batch concurrency value."""
    parsed = _positive_int(value)
    if parsed > MAX_LOCAL_CONCURRENCY:
        raise argparse.ArgumentTypeError(
            f"integer in 1..{MAX_LOCAL_CONCURRENCY} required"
        )
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


def _fast_mlsirm_runtime_status() -> tuple[dict[str, object], bool]:
    """Report whether this interpreter can load the required judge contract."""
    status: dict[str, object] = {
        "python": sys.executable,
        "package": "fast-mlsirm",
    }
    try:
        import fast_mlsirm
        from fast_mlsirm import (
            CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1 as fast_contract,
        )
        from fast_mlsirm import (
            ContextualOrchestratorJudge,
            JudgeCriterion,
            JudgeFormatError,
        )
    except ModuleNotFoundError as exc:
        status.update(
            {
                "available": False,
                "reason": "missing_dependency",
                "missing_module": exc.name or "unknown",
            }
        )
        return status, False
    except Exception as exc:  # noqa: BLE001 - diagnostic command must fail closed
        status.update(
            {
                "available": False,
                "reason": "import_error",
                "error_type": type(exc).__name__,
            }
        )
        return status, False

    checks = {
        "judge_symbols": all(
            callable(symbol)
            for symbol in (ContextualOrchestratorJudge, JudgeCriterion, JudgeFormatError)
        ),
        "contextual_contract": fast_contract == CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1,
    }
    available = all(checks.values())
    status.update(
        {
            "available": available,
            "version": getattr(fast_mlsirm, "__version__", "unknown"),
            "contract": fast_contract,
            "checks": checks,
        }
    )
    return status, available


def _check_fast_mlsirm_command() -> None:
    """Validate the same-interpreter fast-mlsirm integration boundary."""
    status, available = _fast_mlsirm_runtime_status()
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    if not available:
        raise SystemExit(1)


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


def _bootstrap_discovery_sources() -> tuple[ProviderModelSource, ...]:
    """Promote a configured gateway secret to KV and return discovery sources."""
    source = configured_gateway_source(os.environ)
    if source is None:
        return PROVIDER_MODEL_SOURCES
    secret = os.environ.get(CONFIGURED_GATEWAY_CREDENTIAL_NAME, "")
    if secret.strip():
        register_credential(CONFIGURED_GATEWAY_CREDENTIAL_NAME, secret.strip())
    return (*PROVIDER_MODEL_SOURCES, source)


def _runtime_discovery_sources(
    orchestrator: TaskOrchestrator,
) -> tuple[ProviderModelSource, ...]:
    """Build runtime sources only from injected pool config and preseeded KV."""
    sources = list(PROVIDER_MODEL_SOURCES)
    allowed_hosts = ",".join(sorted(orchestrator.client.allowed_provider_hosts))
    seen: set[tuple[str, str]] = set()
    for agent in orchestrator.candidates:
        if agent.provider_name != "configured_gateway":
            continue
        try:
            source = configured_gateway_source(
                {
                    "LLM_GATEWAY_API_URL": agent.base_url,
                    "CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS": allowed_hosts,
                }
            )
        except ValueError:
            continue
        if source is None or get_credential(source.credential_name) is None:
            continue
        identity = (source.list_url, source.credential_name)
        if identity not in seen:
            sources.append(source)
            seen.add(identity)
    return tuple(sources)


def _discover_models_command(argv: list[str]) -> None:
    """Query every provider with a KV-registered credential and report the models found.

    Never fabricates a credential: a provider with nothing registered in the KV
    (see ``register-credential``) is silently skipped, so running this after
    registering a subset of BYTEZ_API_KEY / NVIDIA_NIM_API_KEY /
    NVIDIA_NIM_API_KEY_SUB / OPENROUTER_API_KEY / OPENAI_API_KEY still works.
    """
    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator discover-models",
        description="Discover models from every provider with a KV-registered credential.",
    )
    parser.add_argument(
        "--agents-db",
        default=None,
        help="Persist discovered agents (added disabled; enable via the admin API) into this sqlite agent-pool file.",
    )
    parser.add_argument(
        "--enable-cheapest",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="Enable a price-honest, provider-diverse discovered agent pool in --agents-db (auto-optimization bootstrap; "
        "requires --agents-db; 0 disables, the default, leaving every discovered agent inert).",
    )
    parser.add_argument(
        "--free-only",
        action="store_true",
        help="Report only models whose structured provider/catalog price metadata is entirely zero; "
        "unknown or name-implied prices remain excluded, while the full report keeps every model.",
    )
    args = parser.parse_args(argv)
    if args.enable_cheapest and not args.agents_db:
        parser.error("--enable-cheapest requires --agents-db")

    discovered, errors = discover_all_models(_bootstrap_discovery_sources())
    free_models = free_discovered_models(discovered)
    reported = free_models if args.free_only else discovered
    price_book = PriceBook(InMemoryConfigStore())
    priced_count = refresh_price_book(reported, price_book)

    enabled_agent_ids: list[str] = []
    if args.agents_db:
        bootstrap = TaskOrchestrator(
            [ModelAgent("bootstrap_agent", "bootstrap-model")], agents_db=args.agents_db
        )
        bootstrap.sync_discovered_agents([agent_from_discovered(model) for model in reported])
        if args.enable_cheapest:
            for model in select_bootstrap_discovered_agents(reported, price_book, args.enable_cheapest):
                agent_id = agent_id_for(model)
                bootstrap.patch_agent("default", agent_id, {"status": "active"})
                enabled_agent_ids.append(agent_id)

    report = {
        "discovered_count": len(reported),
        "free_tier_count": len(free_models),
        "free_data_privacy": {
            status: sum(1 for model in free_models if (
                "supported" if model.supports_zero_data_retention is True else
                "unsupported" if model.supports_zero_data_retention is False else "unknown"
            ) == status)
            for status in ("supported", "unsupported", "unknown")
        },
        "priced_count": priced_count,
        "providers_with_errors": sorted({error.provider_name for error in errors}),
        "enabled_agent_ids": enabled_agent_ids,
        "models": [
            {
                "provider": model.provider_name,
                "model": model.model_id,
                "agent_id": agent_id_for(model),
                "is_free": model.is_free,
                "data_privacy": (
                    "supported" if model.supports_zero_data_retention is True else
                    "unsupported" if model.supports_zero_data_retention is False else "unknown"
                ) if model.is_free else None,
            }
            for model in reported
        ],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if errors and not discovered:
        raise SystemExit(1)


def _auto_discover_runtime_agents(orchestrator: TaskOrchestrator) -> dict[str, list[str]]:
    """Discover and activate only models with explicit chat capability evidence."""
    discovered, _errors = discover_all_models(_runtime_discovery_sources(orchestrator))
    chat_models = [model for model in discovered if "chat" in model.capabilities]
    existing_ids = {agent.id for agent in orchestrator.candidates}
    agents = [
        replace(agent_from_discovered(model), disabled=False)
        for model in chat_models
        if agent_id_for(model) not in existing_ids
    ]
    if not agents:
        return {"added": [], "updated": []}
    return orchestrator.sync_discovered_agents(agents)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI options and run bootstrap, prompt completion, or the HTTP server."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "register-credential":
        _register_credential_command(arguments[1:])
        return
    if arguments and arguments[0] == "discover-models":
        _discover_models_command(arguments[1:])
        return
    if arguments and arguments[0] == "check-fast-mlsirm":
        _check_fast_mlsirm_command()
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
    parser.add_argument(
        "--insecure-admin-session-cookie",
        action="store_true",
        help="Allow the admin session cookie over local HTTP; use only for isolated development.",
    )
    parser.add_argument("--clearfolio-url", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_CLEARFOLIO_URL") or None,
                        help="Base URL of a Clearfolio deployment to use as the admin document viewer (default: disabled).")
    parser.add_argument("--agents-db", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_AGENTS_DB") or None,
                        help="Optional sqlite path so runtime agent-pool changes (add/patch/remove) survive restarts.")
    parser.add_argument("--provider-ca-bundle", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE") or None,
                        help="Path to a CA bundle used to verify provider TLS (e.g. a corporate gateway root).")
    parser.add_argument("--allowed-provider-host", action="append", dest="allowed_provider_hosts", default=None,
                        help="Explicit remote provider host allowlist; repeat for multiple hosts (default: unrestricted public hosts).")
    parser.add_argument(
        "--sampling-temperature",
        "--temperature",
        dest="sampling_temperature",
        type=float,
        default=0.2,
        help="Default provider sampling temperature (default: 0.2; --temperature is a compatibility alias).",
    )
    parser.add_argument("--max-output-tokens", type=int, default=2048,
                        help="Default provider output token cap (default: 2048).")
    parser.add_argument("--local-concurrency", type=_local_concurrency, default=1,
                        help=f"Concurrent requests for explicit mlx:// local batch work (default: 1; maximum: {MAX_LOCAL_CONCURRENCY}).")
    parser.add_argument("--max-concurrent-runs", type=_local_concurrency, default=8,
                        help=f"Maximum simultaneous HTTP orchestration runs (default: 8; maximum: {MAX_LOCAL_CONCURRENCY}).")
    parser.add_argument("--max-body-bytes", type=_positive_int, default=64 * 1024,
                        help="Maximum accepted JSON request body bytes (default: 65536).")
    parser.add_argument("--no-realtime-judge", action="store_true", default=False,
                        help="Disable real-time fast-mlsirm answer judging on direct route paths.")
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
    parser.add_argument(
        "--auto-discover-model-agents",
        action="store_true",
        help="discover source-declared chat-capable models at startup and activate them",
    )
    args = parser.parse_args(arguments)

    client = ModelClient(
        ca_bundle=args.provider_ca_bundle,
        temperature=args.sampling_temperature,
        max_output_tokens=args.max_output_tokens,
        local_concurrency=args.local_concurrency,
        chat_template_args=args.chat_template_args,
        allowed_provider_hosts=args.allowed_provider_hosts,
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
    if args.auto_discover_model_agents:
        _auto_discover_runtime_agents(orchestrator)

    if args.no_realtime_judge:
        orchestrator.policy = replace(orchestrator.policy, realtime_judge=False)

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
                _resolve_auth_token(args.auth_token, args.auth_token_key or DEFAULT_AUTH_CREDENTIAL_NAME)
                if not split_requested
                else ""
            )
            admin_token = (
                _resolve_auth_token(args.admin_token, args.admin_token_key or DEFAULT_ADMIN_CREDENTIAL_NAME)
                if split_requested
                else ""
            )
            inference_token = (
                _resolve_auth_token(args.inference_token, args.inference_token_key or DEFAULT_INFERENCE_CREDENTIAL_NAME)
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
                max_body_bytes=args.max_body_bytes,
                max_concurrent_runs=args.max_concurrent_runs,
                allow_public_bind=args.allow_public_bind,
                expose_trace_by_default=args.expose_trace_by_default,
                admin_session_secure_cookie=not args.insecure_admin_session_cookie,
            ),
            clearfolio_url=args.clearfolio_url,
            coordinator=CostRoutingCoordinator(
                orchestrator,
                config_store=_bootstrap_telemetry_config(),
            ),
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
