"""Security and evidence hardening for the optional NVIDIA NIM benchmark.

The benchmark was developed independently from the runtime provider transport.
This module integrates it with the repository's reviewed DNS-pinned HTTPS
boundary, gives every policy arm one equal total token and call allowance, and
attaches versioned evidence for the free-to-caller access-cost assertion.

``install_nim_benchmark_hardening`` is intentionally an explicit compatibility
installer.  It lets this stacked pull request reuse the already reviewed
provider-transport implementation from its #76 parent without duplicating that
security-sensitive arithmetic or changing the standalone runtime API.
"""

from __future__ import annotations

import contextvars
import dataclasses
import datetime as datetime_module
import http.client
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .orchestrator import ModelAgent, OrchestrationPolicy, TaskOrchestrator, estimate_tokens
from .provider_transport import _PinnedHTTPSConnection, _validated_public_addresses


ACTUAL_COST_EVIDENCE: dict[str, Any] = {
    "evidence_schema_version": "1.0.0",
    "source_title": "NVIDIA NIM General FAQ",
    "source_url": "https://docs.nvidia.com/nim/large-language-models/latest/faq.html",
    "reviewed_at_date": "2026-08-04",
    "valid_until_date": "2026-09-03",
    "access_program": "NVIDIA Developer Program API Catalog hosted endpoints",
    "access_scope": "prototyping, research, and testing",
    "production_access_note": "Production support and licensing require NVIDIA AI Enterprise.",
    "actual_cost_usd": 0.0,
    "uncertainty": (
        "Hosted-endpoint terms can change. Live runs fail closed after the validity date "
        "until an authoritative source is reviewed and this evidence is updated."
    ),
}

_DEFAULT_POLICY_TOKEN_BUDGET = 256
_policy_token_budget_context: contextvars.ContextVar[int] = contextvars.ContextVar(
    "nim_policy_total_token_budget",
    default=_DEFAULT_POLICY_TOKEN_BUDGET,
)


class PolicyTokenBudgetExceeded(RuntimeError):
    """One benchmark policy cell exceeded its shared token or call allowance."""


class EqualBudgetModelClient:
    """Delegate model calls while enforcing one equal per-cell budget.

    The wrapper applies the same total token allowance and maximum-call envelope
    to direct, route-once, conduct, and cheapest-worker cells.  Before each call
    it subtracts the estimated prompt tokens and reduces the delegate's
    ``max_output_tokens`` to the remaining allowance.  Provider-reported usage,
    when available, replaces the estimate when ``take_usage`` is consumed by the
    orchestrator.  The delegate still owns request-budget, retry, credential,
    and provider-transport behavior.
    """

    def __init__(self, delegate: Any, total_token_budget: int, maximum_calls: int) -> None:
        """Create a cell-local limiter around ``delegate``.

        Args:
            delegate: Existing benchmark model client that performs real calls.
            total_token_budget: Maximum prompt-plus-completion tokens for the cell.
            maximum_calls: Maximum provider calls available to every policy arm.

        Raises:
            ValueError: If either allowance is not a positive integer.
        """
        if isinstance(total_token_budget, bool) or total_token_budget < 1:
            raise ValueError("total_token_budget must be a positive integer")
        if isinstance(maximum_calls, bool) or maximum_calls < 1:
            raise ValueError("maximum_calls must be a positive integer")
        self._delegate = delegate
        self.total_token_budget = int(total_token_budget)
        self.maximum_calls = int(maximum_calls)
        self.observed_calls = 0
        self.observed_tokens = 0
        self._pending_estimated_tokens: int | None = None
        self._exceeded = False

    @property
    def remaining_tokens(self) -> int:
        """Return the non-negative token allowance remaining in this cell."""
        return max(0, self.total_token_budget - self.observed_tokens)

    @property
    def exceeded(self) -> bool:
        """Return whether observed provider usage crossed the configured budget."""
        return self._exceeded

    @staticmethod
    def _coerce_usage_count(value: Any) -> int | None:
        """Return one valid non-negative provider token count, otherwise ``None``."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if value < 0 or value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)

    def chat(
        self,
        agent: ModelAgent,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
    ) -> str:
        """Perform one delegated chat call within the remaining cell allowance.

        Raises:
            PolicyTokenBudgetExceeded: If the call or token allowance is exhausted.
        """
        if self._exceeded or self.observed_calls >= self.maximum_calls:
            raise PolicyTokenBudgetExceeded("policy cell maximum-call allowance exhausted")
        prompt_text = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        prompt_tokens = estimate_tokens(prompt_text)
        output_allowance = self.remaining_tokens - prompt_tokens
        if output_allowance < 1:
            raise PolicyTokenBudgetExceeded("policy cell total-token allowance exhausted")

        original_max_output_tokens = int(self._delegate.max_output_tokens)
        self._delegate.max_output_tokens = min(original_max_output_tokens, output_allowance)
        self.observed_calls += 1
        try:
            answer = self._delegate.chat(agent, messages, temperature)
        finally:
            self._delegate.max_output_tokens = original_max_output_tokens

        estimated_total = prompt_tokens + estimate_tokens(answer)
        self.observed_tokens += estimated_total
        self._pending_estimated_tokens = estimated_total
        if self.observed_tokens > self.total_token_budget:
            self._exceeded = True
            raise PolicyTokenBudgetExceeded("policy cell observed tokens exceeded its allowance")
        return answer

    def take_usage(self) -> dict[str, Any] | None:
        """Return delegated usage and replace the latest estimate when possible."""
        usage = self._delegate.take_usage()
        if self._pending_estimated_tokens is None:
            return usage
        pending_estimate = self._pending_estimated_tokens
        self._pending_estimated_tokens = None
        if not isinstance(usage, dict):
            return usage
        prompt_tokens = self._coerce_usage_count(usage.get("prompt_tokens"))
        completion_tokens = self._coerce_usage_count(usage.get("completion_tokens"))
        if prompt_tokens is None or completion_tokens is None:
            return usage
        self.observed_tokens += prompt_tokens + completion_tokens - pending_estimate
        if self.observed_tokens > self.total_token_budget:
            self._exceeded = True
        return usage


def _validated_endpoint_addresses(url: str, contract_error_type: type[Exception]) -> tuple[str, ...]:
    """Return public validation-time addresses for one HTTPS benchmark URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise contract_error_type(f"benchmark endpoint must use https: {url!r}")
    try:
        return _validated_public_addresses(
            parsed.hostname.lower(),
            parsed.port or 443,
            "benchmark",
        )
    except RuntimeError as exc:
        raise contract_error_type(f"benchmark endpoint resolves to a non-public address: {url!r}") from exc


def _request_target(parsed_url: urllib.parse.ParseResult) -> str:
    """Return the path, parameters, and query used on a direct HTTPS connection."""
    target = parsed_url.path or "/"
    if parsed_url.params:
        target = f"{target};{parsed_url.params}"
    if parsed_url.query:
        target = f"{target}?{parsed_url.query}"
    return target


def _build_secure_transport(nim_module: Any, timeout_seconds: float) -> Callable[..., tuple[int, bytes]]:
    """Build a no-proxy, no-redirect, validation-time-address-pinned transport."""
    ssl_context = ssl.create_default_context()
    approved_addresses: dict[tuple[str, int], tuple[str, ...]] = {}

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        """Perform one HTTPS round trip to an address approved by the egress guard."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise nim_module.BenchmarkContractError(
                f"benchmark endpoint must use https: {url!r}"
            )
        hostname = parsed.hostname.lower()
        port = parsed.port or 443
        pin_key = (hostname, port)
        addresses = approved_addresses.get(pin_key)
        if addresses is None:
            addresses = _validated_endpoint_addresses(url, nim_module.BenchmarkContractError)
            approved_addresses[pin_key] = addresses

        # Existing offline contract tests deliberately replace urlopen.  An
        # in-process replacement already has arbitrary code execution, so this
        # narrow compatibility seam does not weaken the provider boundary.
        active_urlopen = urllib.request.urlopen
        if getattr(active_urlopen, "__module__", "urllib.request") != "urllib.request":
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with active_urlopen(  # nosec B310 - explicitly injected offline test seam. nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                    request,
                    timeout=timeout_seconds,
                    context=ssl_context,
                ) as response:
                    return int(response.status), response.read()
            except urllib.error.HTTPError as exc:
                return int(exc.code), exc.read() if exc.fp is not None else b""

        request_headers = dict(headers)
        request_headers["Connection"] = "close"
        last_error: BaseException | None = None
        for pinned_ip in addresses:
            connection = _PinnedHTTPSConnection(
                hostname,
                pinned_ip,
                port,
                timeout_seconds,
                ssl_context,
            )
            try:
                connection.request(
                    method,
                    _request_target(parsed),
                    body=body,
                    headers=request_headers,
                )
                response = connection.getresponse()
                try:
                    return int(response.status), response.read()
                finally:
                    response.close()
                    connection.close()
            except (OSError, http.client.HTTPException) as exc:
                connection.close()
                last_error = exc
        raise urllib.error.URLError(last_error or "benchmark provider connection failed")

    return transport


def _validate_actual_cost_evidence(report: dict[str, Any]) -> None:
    """Fail when a report lacks the reviewed source behind zero actual API cost."""
    evidence = report.get("actual_cost_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("benchmark report is missing actual_cost_evidence")
    required_fields = (
        "evidence_schema_version",
        "source_title",
        "source_url",
        "reviewed_at_date",
        "valid_until_date",
        "access_program",
        "access_scope",
        "production_access_note",
        "actual_cost_usd",
        "uncertainty",
    )
    missing = [field for field in required_fields if field not in evidence]
    if missing:
        raise ValueError(f"actual cost evidence is missing fields: {missing}")
    if evidence["actual_cost_usd"] != 0.0:
        raise ValueError("actual cost evidence must preserve the reviewed zero-cost assertion")
    if not str(evidence["source_url"]).startswith("https://docs.nvidia.com/"):
        raise ValueError("actual cost evidence must cite official NVIDIA documentation")


def _require_current_actual_cost_evidence(today: datetime_module.date | None = None) -> None:
    """Fail closed after the reviewed access-cost evidence validity horizon."""
    observed_date = today or datetime_module.date.today()
    valid_until = datetime_module.date.fromisoformat(
        str(ACTUAL_COST_EVIDENCE["valid_until_date"])
    )
    if observed_date > valid_until:
        raise RuntimeError(
            "reviewed NVIDIA hosted-endpoint cost evidence expired; re-review official terms"
        )


def install_nim_benchmark_hardening(nim_module: Any) -> None:
    """Install secure transport, equal budgets, and cost provenance exactly once.

    Args:
        nim_module: Imported ``contextual_orchestrator.nim_benchmark`` module.
    """
    if getattr(nim_module, "_evidence_hardening_installed", False):
        return

    original_budgeted_client = nim_module._BudgetedModelClient
    original_evaluate_policies = nim_module.evaluate_policies
    original_run_policy_cell = nim_module.run_policy_cell
    original_run_benchmark = nim_module.run_benchmark
    original_assemble_report = nim_module.assemble_benchmark_report
    original_write_artifacts = nim_module.write_benchmark_artifacts
    original_render_markdown = nim_module.render_markdown_summary

    class HardenedBudgetedModelClient(original_budgeted_client):
        """Request-budget client whose dry-run token cap matches the CLI contract."""

        def __init__(self, request_budget: Any, **kwargs: Any) -> None:
            """Use the active benchmark token allowance when no explicit cap is supplied."""
            kwargs.setdefault("max_output_tokens", _policy_token_budget_context.get())
            super().__init__(request_budget, **kwargs)

    def require_public_https_endpoint(url: str) -> None:
        """Reject every non-HTTPS or non-globally-routable benchmark endpoint."""
        _validated_endpoint_addresses(url, nim_module.BenchmarkContractError)

    def build_default_transport(timeout_seconds: float) -> Callable[..., tuple[int, bytes]]:
        """Return the reviewed validation-time-address-pinned HTTPS transport."""
        return _build_secure_transport(nim_module, timeout_seconds)

    def evaluate_policies(
        agents: list[ModelAgent],
        manifest: dict[str, Any],
        pricing_scenario: dict[str, Any] | None,
        client: Any,
        request_budget: Any,
        timer: Callable[[], float] = nim_module.time.perf_counter,
    ) -> dict[str, Any]:
        """Evaluate every arm with one identical token and call budget per task."""
        if not agents:
            raise nim_module.BenchmarkContractError(
                "policy evaluation requires at least one chat-eligible worker"
            )
        tasks = nim_module.locked_evaluation_tasks(manifest)
        if not tasks:
            raise nim_module.BenchmarkContractError(
                "task manifest has no locked evaluation tasks"
            )
        planned = nim_module.planned_evaluation_requests(len(agents), len(tasks))
        remaining_requests = request_budget.max_total_requests - request_budget.requests_spent
        if planned > remaining_requests:
            raise nim_module.BenchmarkBudgetError(
                f"planned evaluation needs up to {planned} requests but only "
                f"{remaining_requests} remain in the budget"
            )

        agents_by_id = {agent.id: agent.model for agent in agents}
        depth_policy = dataclasses.replace(
            OrchestrationPolicy(),
            max_workflow_steps=nim_module.MAX_WORKFLOW_DEPTH,
        )
        token_budget = _policy_token_budget_context.get()
        maximum_calls = nim_module.MAX_WORKFLOW_DEPTH

        def run_cell(
            policy_name: str,
            task: dict[str, Any],
            pool: list[ModelAgent],
            mode: str,
        ) -> dict[str, Any]:
            """Run one policy/task cell and append configured versus observed budgets."""
            cell_client = EqualBudgetModelClient(client, token_budget, maximum_calls)
            orchestrator = TaskOrchestrator(pool, client=cell_client)
            orchestrator.policy = depth_policy
            cell = original_run_policy_cell(
                policy_name,
                task,
                lambda: orchestrator.complete(
                    [{"role": "user", "content": task["prompt"]}],
                    mode=mode,
                ),
                agents_by_id,
                pricing_scenario,
                timer,
            )
            cell.update(
                {
                    "configured_total_token_budget": token_budget,
                    "configured_maximum_calls": maximum_calls,
                    "observed_budget_tokens": cell_client.observed_tokens,
                    "observed_budget_calls": cell_client.observed_calls,
                    "remaining_budget_tokens": cell_client.remaining_tokens,
                }
            )
            if cell_client.exceeded and cell["run_outcome"] == "success":
                cell["run_outcome"] = "failure"
                cell["outcome_reason"] = "observed_usage_exceeded_equal_token_budget"
                cell["task_score"] = None
            return cell

        cells: list[dict[str, Any]] = []
        for agent in agents:
            for task in tasks:
                cells.append(
                    run_cell(
                        f"direct_single_worker:{agent.model}",
                        task,
                        [agent],
                        "route",
                    )
                )
        for task in tasks:
            cells.append(run_cell("route_once", task, agents, "route"))
            cells.append(run_cell("conduct_bounded", task, agents, "conduct"))

        cheapest_skip_reason = None
        cheapest = nim_module.cheapest_priced_agent(agents, pricing_scenario)
        if cheapest is None:
            cheapest_skip_reason = (
                "no_pricing_scenario_supplied"
                if pricing_scenario is None
                else "no_worker_priced_by_scenario"
            )
        else:
            for task in tasks:
                cells.append(
                    run_cell(
                        "cheapest_eligible_worker",
                        task,
                        [cheapest],
                        "route",
                    )
                )
        cells.sort(key=lambda cell: (cell["policy_name"], cell["task_id"]))
        return {
            "evaluation_cells": cells,
            "cheapest_worker_skip_reason": cheapest_skip_reason,
            "locked_task_count": len(tasks),
            "worker_count": len(agents),
        }

    def run_benchmark(
        run_mode: str,
        task_manifest_path: str,
        pricing_scenario_path: str | None,
        output_dir: str,
        endpoint: str = nim_module.NIM_DEFAULT_ENDPOINT,
        max_total_requests: int = 500,
        probe_concurrency: int = 4,
        timeout_seconds: float = 60.0,
        max_output_tokens: int = _DEFAULT_POLICY_TOKEN_BUDGET,
        max_eval_models: int = 7,
        seed: int = 7,
        git_sha: str = "",
        workflow_run_id: str = "",
        transport: Any = None,
    ) -> dict[str, Any]:
        """Run the benchmark with one shared cell budget and current cost evidence."""
        if run_mode == "live":
            try:
                _require_current_actual_cost_evidence()
            except RuntimeError as exc:
                raise nim_module.BenchmarkContractError(str(exc)) from exc
        token = _policy_token_budget_context.set(max_output_tokens)
        try:
            return original_run_benchmark(
                run_mode,
                task_manifest_path,
                pricing_scenario_path,
                output_dir,
                endpoint=endpoint,
                max_total_requests=max_total_requests,
                probe_concurrency=probe_concurrency,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                max_eval_models=max_eval_models,
                seed=seed,
                git_sha=git_sha,
                workflow_run_id=workflow_run_id,
                transport=transport,
            )
        finally:
            _policy_token_budget_context.reset(token)

    def assemble_benchmark_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """Attach the reviewed actual-cost source and equal-budget evidence."""
        report = original_assemble_report(*args, **kwargs)
        report["actual_cost_evidence"] = dict(ACTUAL_COST_EVIDENCE)
        report["honesty_labels"]["actual_cost_basis"] = (
            "reviewed_nvidia_developer_program_hosted_endpoint_access"
        )
        _validate_actual_cost_evidence(report)
        return report

    def write_benchmark_artifacts(report: dict[str, Any], output_dir: str) -> dict[str, str]:
        """Require actual-cost evidence before any benchmark artifact is written."""
        _validate_actual_cost_evidence(report)
        return original_write_artifacts(report, output_dir)

    def render_markdown_summary(report: dict[str, Any]) -> str:
        """Include the reviewed access-cost source and validity date in Markdown."""
        markdown = original_render_markdown(report).rstrip()
        evidence = report["actual_cost_evidence"]
        return (
            f"{markdown}\n\n"
            "## Actual API cost evidence\n\n"
            f"- source: {evidence['source_title']}\n"
            f"- reviewed: {evidence['reviewed_at_date']}\n"
            f"- valid until: {evidence['valid_until_date']}\n"
            f"- access context: {evidence['access_program']} — {evidence['access_scope']}\n"
            f"- uncertainty: {evidence['uncertainty']}\n"
        )

    nim_module._BudgetedModelClient = HardenedBudgetedModelClient
    nim_module.require_public_https_endpoint = require_public_https_endpoint
    nim_module.build_default_transport = build_default_transport
    nim_module.evaluate_policies = evaluate_policies
    nim_module.run_benchmark = run_benchmark
    nim_module.assemble_benchmark_report = assemble_benchmark_report
    nim_module.write_benchmark_artifacts = write_benchmark_artifacts
    nim_module.render_markdown_summary = render_markdown_summary
    nim_module.ACTUAL_COST_EVIDENCE = ACTUAL_COST_EVIDENCE
    nim_module.EqualBudgetModelClient = EqualBudgetModelClient
    nim_module.PolicyTokenBudgetExceeded = PolicyTokenBudgetExceeded
    nim_module._original_evaluate_policies = original_evaluate_policies
    nim_module._evidence_hardening_installed = True
