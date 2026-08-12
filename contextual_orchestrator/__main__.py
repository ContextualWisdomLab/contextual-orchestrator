"""Command-line entrypoint for routing prompts, serving the API, or KV bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .credentials import register_credential
from .orchestrator import ModelClient, TaskOrchestrator, load_agents
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



def _discover_nim_models_command(argv: list[str]) -> None:
    """List NIM model IDs via KV credential and print agent-pool JSON candidates."""
    from .nim_discovery import (
        DEFAULT_NIM_MODELS_URL,
        NimDiscoveryError,
        build_benchmark_plan_dry_run,
        build_capability_inventory,
        discover_nim_models,
        models_to_agent_pool_entries,
        validate_nim_models_url,
    )

    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator discover-nim-models",
        description="Discover NVIDIA NIM model IDs using the KV credential NVIDIA_NIM_API_KEY.",
    )
    parser.add_argument(
        "--models-url",
        default=DEFAULT_NIM_MODELS_URL,
        help=(
            "HTTPS NVIDIA catalog URL (default: integrate.api.nvidia.com/v1/models). "
            "Only allowlisted NVIDIA hosts with path /v1/models are accepted; "
            "the API key is never sent to other origins."
        ),
    )
    parser.add_argument(
        "--as-agent-pool",
        action="store_true",
        help="Emit agent-pool JSON entries instead of the discovery report.",
    )
    parser.add_argument(
        "--capability-inventory",
        action="store_true",
        help="Emit offline capability-hint inventory for discovered model ids (issue #86 dry path).",
    )
    parser.add_argument(
        "--benchmark-dry-run",
        action="store_true",
        help="Emit a fail-closed dry-run benchmark plan with unknown costs (issue #86).",
    )
    parser.add_argument(
        "--hard-request-budget",
        type=int,
        default=100,
        help="Hard call budget for --benchmark-dry-run admission (default: 100).",
    )
    args = parser.parse_args(argv)
    try:
        models_url = validate_nim_models_url(args.models_url)
    except NimDiscoveryError as exc:
        parser.error(str(exc))
    report = discover_nim_models(models_url=models_url)
    model_ids = report.get("model_ids") or []
    if args.benchmark_dry_run:
        try:
            plan = build_benchmark_plan_dry_run(
                model_ids, hard_request_budget=args.hard_request_budget
            )
        except NimDiscoveryError as exc:
            parser.error(str(exc))
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    elif args.capability_inventory:
        print(json.dumps(build_capability_inventory(model_ids), ensure_ascii=False, indent=2))
    elif args.as_agent_pool:
        print(json.dumps(models_to_agent_pool_entries(model_ids), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


def _nim_cost_quality_offline_command(argv: list[str]) -> None:
    """Run the offline cost-quality harness against a locked task manifest (issue #86)."""
    from .nim_cost_quality import (
        CostQualityContractError,
        build_scripted_policy_runners,
        load_pricing_scenario,
        load_task_manifest,
        locked_evaluation_tasks,
        render_cost_quality_markdown,
        run_offline_cost_quality,
    )

    parser = argparse.ArgumentParser(
        prog="python -m contextual_orchestrator nim-cost-quality-offline",
        description=(
            "Offline cost-quality comparison for issue #86 (post-discovery). "
            "Uses scripted answers by default so CI never needs NVIDIA_NIM_API_KEY. "
            "Never invents prices: hypothetical cost stays unknown without a scenario."
        ),
    )
    parser.add_argument(
        "--task-manifest",
        default="examples/nim_task_manifest_offline.json",
        help="Path to the versioned task manifest (locked split only).",
    )
    parser.add_argument(
        "--pricing-scenario",
        default=None,
        help="Optional USD-per-million-token scenario JSON; omit to keep costs unknown.",
    )
    parser.add_argument(
        "--scripted-answers",
        default=None,
        help=(
            "Optional JSON map {task_id: {policy_name: answer}}. "
            "When omitted, answers are empty (scores zero) for structural dry-run only."
        ),
    )
    parser.add_argument(
        "--model-id",
        default="mock-scripted",
        help="Model id recorded on cells and used for pricing lookups (default: mock-scripted).",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit a short markdown summary instead of the full JSON report.",
    )
    args = parser.parse_args(argv)
    try:
        manifest = load_task_manifest(args.task_manifest)
        tasks = locked_evaluation_tasks(manifest)
        pricing = load_pricing_scenario(args.pricing_scenario)
        answers: dict = {}
        if args.scripted_answers:
            with open(args.scripted_answers, encoding="utf-8") as handle:
                answers = json.load(handle)
            if not isinstance(answers, dict):
                parser.error("--scripted-answers must be a JSON object")
        runners = build_scripted_policy_runners(answers, model_id=args.model_id)
        report = run_offline_cost_quality(
            tasks=tasks,
            policy_runners=runners,
            model_id=args.model_id,
            pricing_scenario=pricing,
        )
    except (CostQualityContractError, OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.markdown:
        print(render_cost_quality_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    """Parse CLI options and run bootstrap, prompt completion, or the HTTP server."""
    if len(sys.argv) > 1 and sys.argv[1] == "register-credential":
        _register_credential_command(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "discover-nim-models":
        _discover_nim_models_command(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "nim-cost-quality-offline":
        _nim_cost_quality_offline_command(sys.argv[2:])
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
    parser.add_argument("--auth-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_TOKEN", ""))
    parser.add_argument("--admin-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN", ""))
    parser.add_argument("--inference-token", default=os.environ.get("CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN", ""))
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
        if not (args.auth_token or args.admin_token or args.inference_token):
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
            clearfolio_url=args.clearfolio_url,
        )
        return

    if not args.prompt:
        parser.error("prompt is required unless --serve is set")

    result = orchestrator.complete([{"role": "user", "content": args.prompt}], mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
