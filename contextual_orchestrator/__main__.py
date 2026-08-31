"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import logging
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
    general_free_serving_candidates,
    is_routable_discovered_model,
    refresh_price_book,
    select_bootstrap_discovered_agents,
)
from .orchestrator import (
    CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1,
    MAX_LOCAL_CONCURRENCY,
    ModelClient,
    TaskOrchestrator,
    load_agents,
)
from .privacy_policy_analysis import (
    analyze_discovered_privacy_policies,
)
from .server import DEFAULT_MAX_JSON_BODY_BYTES, SecurityConfig, serve

DEFAULT_AUTH_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_TOKEN"
DEFAULT_ADMIN_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN"
DEFAULT_INFERENCE_CREDENTIAL_NAME = "CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"
#: Env-var escape hatch so an already-deployed server can turn on DEBUG-level
#: logging (env is read once at process start, same as CONTEXTUAL_ORCHESTRATOR_STATE_DB
#: below) without editing its CLI invocation.
VERBOSE_ENV_VAR = "CONTEXTUAL_ORCHESTRATOR_VERBOSE"
_VERBOSE_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
#: The only loggers verbose mode raises to DEBUG. Each one is individually
#: audited here (not merely "the modules this feature touched") to confirm
#: every .debug() call site under it logs bounded, secret-free metadata --
#: never a raw exception (str(exc)), a credential, or prompt/response
#: content: orchestrator.py's route/conduct/provider/circuit-breaker sites
#: (ADR 0125), server.py's request/response lifecycle sites, and
#: model_discovery.py's discover_provider_models() account/error_code/
#: model_count sites (#941). Deliberately excludes every OTHER logger in this
#: package -- e.g. openrouter_uptime.py's pre-existing
#: ``logger.debug("...: %s", exc)`` logs str(exc) directly and has not been
#: rewritten to stop doing that, so it must never become reachable just
#: because an operator asked to see routing/discovery decisions. Setting
#: level on the root or a package-level "contextual_orchestrator" logger
#: would raise every child logger's EFFECTIVE level through inheritance,
#: silently re-opening exactly that leak for this logger and any other
#: not-yet-audited or third-party logger sharing the process -- so this
#: enables DEBUG on each named leaf logger individually instead.
_VERBOSE_LOGGER_NAMES = (
    "contextual_orchestrator.orchestrator",
    "contextual_orchestrator.server",
    "contextual_orchestrator.model_discovery",
)


def _env_flag(name: str) -> bool:
    """Return whether an environment variable is set to a truthy flag value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _configure_logging(verbose: bool) -> None:
    """Turn on DEBUG-level logging for this package's audited loggers only.

    A no-op when ``verbose`` is false: this repository never introduces
    unrequested log noise, and ``.debug()`` call sites across the package stay
    silent unless a caller explicitly opts in here or via ``VERBOSE_ENV_VAR``.

    When true, this installs one shared timestamp/level/logger-name formatter
    (``basicConfig`` with no ``level=``, so the *root* logger's level is left
    untouched -- WARNING and above already reach stderr by default via
    Python's handler-of-last-resort, and this only adds consistent
    formatting for that existing output) and then raises the level to DEBUG
    on exactly the loggers named in ``_VERBOSE_LOGGER_NAMES``, never the root
    logger and never a whole-package logger. See that constant's comment for
    why the distinction matters. ``force=True`` lets a later call (or a test
    invoking ``main()`` more than once in one process) replace an earlier
    handler instead of silently no-op'ing, matching stdlib
    ``logging.basicConfig`` semantics for a process whose configuration is
    decided exactly once at startup.
    """
    if not verbose:
        return
    logging.basicConfig(format=_VERBOSE_LOG_FORMAT, force=True)
    for logger_name in _VERBOSE_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(logging.DEBUG)


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
    parser.add_argument(
        "--verbose", "--debug",
        dest="verbose",
        action="store_true",
        default=_env_flag(VERBOSE_ENV_VAR),
        help=f"Enable DEBUG-level logging (default: off; also settable via {VERBOSE_ENV_VAR}).",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

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

    Providers without a KV credential are skipped. The sole bootstrap exception
    is an explicitly configured gateway: this one-shot command promotes its
    allowlisted URL and API key from bootstrap transport into the KV before
    discovery. Runtime auto-discovery never reads that environment transport.
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
    parser.add_argument(
        "--analyze-privacy-policies",
        action="store_true",
        help=(
            "Crawl declared policy sources and run a model-backed privacy assessment; "
            "this opt-in action may incur provider charges."
        ),
    )
    parser.add_argument(
        "--provider-ca-bundle",
        default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_PROVIDER_CA_BUNDLE") or None,
        help="Optional reviewed CA bundle for configured-gateway discovery TLS verification.",
    )
    parser.add_argument(
        "--verbose", "--debug",
        dest="verbose",
        action="store_true",
        default=_env_flag(VERBOSE_ENV_VAR),
        help="Emit secret-free provider discovery diagnostics to stderr (default: off; "
        f"also settable via {VERBOSE_ENV_VAR}).",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    if args.enable_cheapest and not args.agents_db:
        parser.error("--enable-cheapest requires --agents-db")

    try:
        sources = _bootstrap_discovery_sources()
    except ValueError as exc:
        parser.error(str(exc))
    discovered, errors = discover_all_models(
        sources,
        ca_bundle=args.provider_ca_bundle,
    )
    privacy_assessments = []
    if args.analyze_privacy_policies:
        discovered, privacy_assessments = analyze_discovered_privacy_policies(discovered)
    # free_tier_count and general_free_serving_count are always computed over
    # the complete `discovered` population, independent of --free-only (which
    # only filters `reported`, the per-model listing below): both answer a
    # global "how many, out of everything found" question, matching each
    # other's population by design rather than "reported"'s row-level filter.
    free_models = free_discovered_models(discovered)
    general_free_serving_models = general_free_serving_candidates(discovered)
    reported = free_models if args.free_only else discovered
    price_book = PriceBook(InMemoryConfigStore())
    priced_count = refresh_price_book(reported, price_book)

    enabled_agent_ids: list[str] = []
    if args.agents_db:
        discovered_agents = [
            agent_from_discovered(model)
            for model in reported
            if not model.evidence_only
        ]
        bootstrap = TaskOrchestrator(
            discovered_agents,
            agents_db=args.agents_db,
            allow_empty_agents=True,
        )
        try:
            bootstrap.sync_discovered_agents(discovered_agents)
            if args.enable_cheapest:
                for model in select_bootstrap_discovered_agents(reported, price_book, args.enable_cheapest):
                    agent_id = agent_id_for(model)
                    bootstrap.patch_agent("default", agent_id, {"status": "active"})
                    enabled_agent_ids.append(agent_id)
        finally:
            bootstrap.close()

    report = {
        "discovered_count": len(reported),
        "free_tier_count": len(free_models),
        "general_free_serving_count": len(general_free_serving_models),
        "free_data_privacy": {
            status: sum(1 for model in free_models if (
                "supported" if model.supports_zero_data_retention is True else
                "unsupported" if model.supports_zero_data_retention is False else "unknown"
            ) == status)
            for status in ("supported", "unsupported", "unknown")
        },
        "priced_count": priced_count,
        "providers_with_errors": sorted({error.provider_name for error in errors}),
        "privacy_policy_analysis": [
            assessment.as_dict() for assessment in privacy_assessments
        ],
        "enabled_agent_ids": enabled_agent_ids,
        "models": [
            {
                "provider": model.provider_name,
                "model": model.model_id,
                "agent_id": agent_id_for(model),
                "is_free": model.is_free,
                "data_privacy": {
                    "zero_data_retention": (
                        "supported" if model.supports_zero_data_retention is True else
                        "unsupported" if model.supports_zero_data_retention is False else "unknown"
                    ),
                    "no_training": (
                        "supported" if model.supports_no_training is True else
                        "unsupported" if model.supports_no_training is False else "unknown"
                    ),
                    "no_prompt_retention": (
                        "supported" if model.supports_no_prompt_retention is True else
                        "unsupported" if model.supports_no_prompt_retention is False else "unknown"
                    ),
                    "policy_sources": list(model.privacy_policy_urls),
                },
            }
            for model in reported
        ],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if errors and not discovered:
        raise SystemExit(1)


def _auto_discover_runtime_agents(orchestrator: TaskOrchestrator) -> dict[str, list[str]]:
    """Discover and activate routable chat models without runtime env transport.

    The shared discovery predicate keeps ordinary chat rows discoverable even
    when a provider omits structured capability metadata, while still refusing
    evidence-only or non-chat rows.
    """
    discovered, _errors = discover_all_models(
        _runtime_discovery_sources(orchestrator),
        ca_bundle=orchestrator.client.ca_bundle,
    )
    chat_models = [model for model in discovered if is_routable_discovered_model(model)]
    existing_ids = {agent.id for agent in orchestrator.candidates}
    agents = [
        replace(
            agent_from_discovered(model),
            disabled=False,
        )
        for model in chat_models
        if agent_id_for(model) not in existing_ids
    ]
    result = (
        orchestrator.sync_discovered_agents(agents)
        if agents
        else {"added": [], "updated": []}
    )
    if any(model.provider_name == "configured_gateway" for model in chat_models):
        for agent in tuple(orchestrator.candidates):
            if (
                agent.provider_name == "configured_gateway"
                and not agent.model.strip()
                and any(
                    candidate.id != agent.id and not candidate.disabled
                    for candidate in orchestrator.candidates
                )
            ):
                orchestrator.remove_agent("default", agent.id)
    has_real_runtime_agent = any(
        not candidate.disabled
        and not candidate.base_url.startswith("mock://")
        and "bootstrap_seed" not in candidate.tags
        for candidate in orchestrator.agents
    )
    for candidate in tuple(orchestrator.agents):
        if has_real_runtime_agent and "bootstrap_seed" in candidate.tags:
            orchestrator.patch_agent(
                "default", candidate.id, {"status": "disabled"}
            )
            result["updated"].append(candidate.id)
    return result


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
    parser.add_argument(
        "--release-authority-json",
        default=None,
        help="Path to a persisted exact-head release-authority snapshot collected by the governance CLI.",
    )
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
    parser.add_argument(
        "--production",
        action="store_true",
        help="Require split admin/inference server credentials; single-token mode is local-only.",
    )
    parser.add_argument(
        "--rate-limit-requests",
        type=_positive_int,
        default=None,
        help="Per-client requests allowed per fixed window (default: SecurityConfig's 60). "
        "Size this above your measured peak concurrency — load tests and health "
        "probes from one NAT egress share the same bucket.",
    )
    parser.add_argument(
        "--rate-limit-window-seconds",
        type=_positive_int,
        default=None,
        help="Fixed rate-limit window length in seconds (default: SecurityConfig's 60).",
    )
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
    parser.add_argument(
        "--max-body-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_JSON_BODY_BYTES,
        help=f"Maximum accepted JSON request body bytes (default: {DEFAULT_MAX_JSON_BODY_BYTES}).",
    )
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
    parser.add_argument(
        "--verbose", "--debug",
        dest="verbose",
        action="store_true",
        default=_env_flag(VERBOSE_ENV_VAR),
        help="Enable DEBUG-level logging (timestamp, level, logger name) to stderr for the "
        f"orchestrator's route/conduct/provider-retry/circuit-breaker control flow and model "
        f"discovery; secrets and full prompt/response text are never logged (default: off; "
        f"also settable via {VERBOSE_ENV_VAR}=true and a restart, so a deployed server can turn "
        f"it on without editing its CLI invocation).",
    )
    args = parser.parse_args(arguments)
    _configure_logging(args.verbose)

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
        release_authority = None
        if args.release_authority_json:
            try:
                with open(args.release_authority_json, encoding="utf-8") as authority_file:
                    release_authority = json.load(authority_file)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                parser.error(f"release authority snapshot could not be read: {exc}")
            if not isinstance(release_authority, dict):
                parser.error("release authority snapshot must be a JSON object")
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
        if (args.production or args.allow_public_bind) and not split_requested:
            parser.error(
                "--production/--allow-public-bind requires split "
                "--admin-token/--inference-token credentials; single-token mode is local-only"
            )
        if (args.production or args.allow_public_bind) and args.insecure_admin_session_cookie:
            parser.error(
                "--production/--allow-public-bind cannot use --insecure-admin-session-cookie"
            )
        try:
            SecurityConfig().check_bind(args.host, allow_public_bind=args.allow_public_bind)
        except ValueError as exc:
            parser.error(str(exc))
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
        if (
            (args.production or args.allow_public_bind)
            and split_requested
            and admin_token == inference_token
        ):
            parser.error(
                "--production/--allow-public-bind requires admin and inference tokens "
                "to resolve to distinct credential values"
            )
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
                **(
                    {}
                    if args.rate_limit_requests is None
                    else {"rate_limit_requests": args.rate_limit_requests}
                ),
                **(
                    {}
                    if args.rate_limit_window_seconds is None
                    else {"rate_limit_window_seconds": args.rate_limit_window_seconds}
                ),
            ),
            clearfolio_url=args.clearfolio_url,
            coordinator=CostRoutingCoordinator(
                orchestrator,
                config_store=_bootstrap_telemetry_config(),
            ),
            release_authority=release_authority,
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
