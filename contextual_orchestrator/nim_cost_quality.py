"""Offline cost-quality comparison harness for issue #86 (post-discovery).

Builds on :mod:`nim_discovery` dry-run plans: given a locked task manifest and
mock (or scripted) policy runners, compare Fugu-style single-route, Conductor-
style bounded conduct, and per-worker direct baselines with honest cost fields.

Optional :func:`build_orchestrator_policy_runners` drives the same comparison
through a live ``TaskOrchestrator`` (typically ``mock://`` agents) so route vs
conduct paper paths are exercised offline without NIM credentials.

Never invents prices: hypothetical paid cost stays ``\"unknown\"`` until a
versioned pricing scenario covers every model used in a cell. Live NIM egress
requires ``RUN_LIVE_NIM_TESTS=1`` and is out of scope for this offline module.

References
----------
Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* (arXiv:2305.05176).

Ong, I., et al. (2024). *RouteLLM: Learning to route LLMs with preference data*
(arXiv:2406.18665).

Ding, D., et al. (2024). *Hybrid LLM: Cost-efficient and quality-aware query
routing* (arXiv:2404.14618).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .conventions import is_two_word_snake_case
from .nim_discovery import (
    CAPABILITY_CHAT,
    CAPABILITY_UNKNOWN,
    NimDiscoveryError,
    classify_model_capability_hint,
)

PolicyRunner = Callable[[str], dict[str, Any]]


class CostQualityContractError(ValueError):
    """Raised when a cost-quality manifest, scenario, or report contract fails."""


def score_exact_number_match(expected: Mapping[str, Any], answer_text: str) -> float:
    """Return 1.0 when the expected number appears as a standalone token."""
    pattern = rf"(?<![\d.]){re.escape(str(expected['number']))}(?!\d)(?!\.\d)"
    return 1.0 if re.search(pattern, answer_text) else 0.0


def score_substring_match(expected: Mapping[str, Any], answer_text: str) -> float:
    """Return 1.0 when the expected substring appears case-insensitively."""
    return 1.0 if str(expected["substring"]).lower() in answer_text.lower() else 0.0


SCORER_REGISTRY: dict[tuple[str, str], Callable[[Mapping[str, Any], str], float]] = {
    ("exact_number_match", "1"): score_exact_number_match,
    ("substring_match", "1"): score_substring_match,
}

_VALID_TASK_SPLITS = frozenset({"locked", "exploratory"})
_POLICY_NAMES = (
    "direct_worker",
    "route_once",
    "bounded_conduct",
    "hindsight_best_single",
)


def load_task_manifest(path: str) -> dict[str, Any]:
    """Load and validate a versioned task manifest (no prompt leakage)."""
    with open(path, encoding="utf-8") as handle:
        try:
            manifest = json.load(handle)
        except ValueError as exc:
            raise CostQualityContractError(f"task manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("manifest_version"), str):
        raise CostQualityContractError(
            "task manifest must be an object with a string 'manifest_version'"
        )
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise CostQualityContractError("task manifest must carry a non-empty 'tasks' list")
    seen_task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise CostQualityContractError("every task manifest entry must be an object")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not is_two_word_snake_case(task_id):
            raise CostQualityContractError(
                f"task_id must be two-plus-word snake_case: {task_id!r}"
            )
        if task_id in seen_task_ids:
            raise CostQualityContractError(f"duplicate task_id in manifest: {task_id!r}")
        seen_task_ids.add(task_id)
        if task.get("split") not in _VALID_TASK_SPLITS:
            raise CostQualityContractError(
                f"task {task_id!r} split must be 'locked' or 'exploratory'"
            )
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise CostQualityContractError(f"task {task_id!r} must carry a non-empty prompt")
        scorer = task.get("scorer")
        if not isinstance(scorer, dict):
            raise CostQualityContractError(f"task {task_id!r} must carry a scorer object")
        scorer_key = (str(scorer.get("name")), str(scorer.get("version")))
        if scorer_key not in SCORER_REGISTRY:
            raise CostQualityContractError(
                f"task {task_id!r} names an unregistered scorer: {scorer_key}"
            )
        expected = task.get("expected")
        if not isinstance(expected, dict) or not expected:
            raise CostQualityContractError(
                f"task {task_id!r} must carry a non-empty expected object"
            )
        if SCORER_REGISTRY[scorer_key](expected, prompt) != 0.0:
            raise CostQualityContractError(
                f"task {task_id!r} leaks its expected answer into the prompt"
            )
    return manifest


def locked_evaluation_tasks(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only the locked evaluation split, in manifest order."""
    return [task for task in manifest["tasks"] if task["split"] == "locked"]


def score_task_answer(task: Mapping[str, Any], answer_text: str) -> dict[str, Any]:
    """Score one answer with the task's registered scorer identity."""
    scorer = task["scorer"]
    key = (str(scorer["name"]), str(scorer["version"]))
    score = float(SCORER_REGISTRY[key](task["expected"], answer_text))
    if not math.isfinite(score) or score < 0.0 or score > 1.0:
        raise CostQualityContractError(
            f"scorer {key} returned non-finite or out-of-range score for {task['task_id']!r}"
        )
    return {
        "task_id": task["task_id"],
        "scorer_name": key[0],
        "scorer_version": key[1],
        "score": score,
    }


def _require_finite_rate(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise CostQualityContractError(
            f"pricing scenario rate {label} must be a finite non-negative number"
        )
    return float(value)


def load_pricing_scenario(path: str | None) -> dict[str, Any] | None:
    """Load an optional USD-per-million-token scenario; ``None`` keeps costs unknown."""
    if path is None:
        return None
    with open(path, encoding="utf-8") as handle:
        try:
            scenario = json.load(handle)
        except ValueError as exc:
            raise CostQualityContractError(f"pricing scenario is not valid JSON: {exc}") from exc
    if not isinstance(scenario, dict) or not isinstance(scenario.get("scenario_version"), str):
        raise CostQualityContractError(
            "pricing scenario must be an object with a string 'scenario_version'"
        )
    if scenario.get("scenario_status") not in ("example_unreviewed", "reviewed"):
        raise CostQualityContractError(
            "pricing scenario_status must be 'example_unreviewed' or 'reviewed'"
        )
    rates = scenario.get("usd_per_million_tokens")
    if not isinstance(rates, dict):
        raise CostQualityContractError(
            "pricing scenario must carry a 'usd_per_million_tokens' object"
        )
    for model_id, rate in rates.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise CostQualityContractError("pricing model id must be a non-empty string")
        if not isinstance(rate, dict):
            raise CostQualityContractError(f"pricing entry for {model_id!r} must be an object")
        _require_finite_rate(rate.get("input"), f"{model_id}.input")
        _require_finite_rate(rate.get("output"), f"{model_id}.output")
    return scenario


def hypothetical_cost_usd(
    pricing_scenario: Mapping[str, Any] | None,
    usage_by_model: Mapping[str, Mapping[str, int]],
) -> float | str:
    """Return scenario cost, or ``\"unknown\"`` when any used model lacks a rate."""
    if pricing_scenario is None:
        return "unknown"
    rates = pricing_scenario["usd_per_million_tokens"]
    total = 0.0
    for model_id, usage in usage_by_model.items():
        rate = rates.get(model_id)
        if rate is None:
            return "unknown"
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        if prompt_tokens < 0 or completion_tokens < 0:
            raise CostQualityContractError("token counts must be non-negative")
        total += prompt_tokens * float(rate["input"]) / 1_000_000
        total += completion_tokens * float(rate["output"]) / 1_000_000
    if not math.isfinite(total):
        raise CostQualityContractError("hypothetical cost must be finite")
    return round(total, 10)


def estimate_token_counts(text: str) -> int:
    """Heuristic ~4 chars/token estimate; never claimed as provider-reported usage."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def chat_eligible_model_ids(model_ids: Sequence[str]) -> list[str]:
    """Filter catalog ids to chat/unknown capability hints for offline plans."""
    return [
        mid
        for mid in sorted({m.strip() for m in model_ids if isinstance(m, str) and m.strip()})
        if classify_model_capability_hint(mid) in {CAPABILITY_CHAT, CAPABILITY_UNKNOWN}
    ]


def validate_scripted_answers(answers_by_task_id: Any) -> dict[str, dict[str, str]]:
    """Validate ``{task_id: {policy_name: answer_text}}`` maps for offline runners."""
    if not isinstance(answers_by_task_id, Mapping):
        raise CostQualityContractError("scripted answers must be a JSON object")
    normalized: dict[str, dict[str, str]] = {}
    for task_id, policy_map in answers_by_task_id.items():
        if not isinstance(task_id, str) or not task_id.strip():
            raise CostQualityContractError("scripted answer task_id must be a non-empty string")
        if not isinstance(policy_map, Mapping):
            raise CostQualityContractError(
                f"scripted answers for {task_id!r} must be an object of policy_name -> answer"
            )
        row: dict[str, str] = {}
        for policy_name, answer in policy_map.items():
            if not isinstance(policy_name, str) or not policy_name.strip():
                raise CostQualityContractError(
                    f"scripted answer policy_name under {task_id!r} must be a non-empty string"
                )
            if not isinstance(answer, str):
                raise CostQualityContractError(
                    f"scripted answer for {task_id!r}/{policy_name!r} must be a string"
                )
            row[policy_name] = answer
        normalized[task_id] = row
    return normalized


def build_scripted_policy_runners(
    answers_by_task_id: Mapping[str, Mapping[str, str]] | None = None,
    *,
    model_id: str = "mock-scripted",
) -> dict[str, PolicyRunner]:
    """Build offline policy runners that return scripted answers per task id.

    ``answers_by_task_id[task_id][policy_name]`` supplies the answer text. Missing
    cells yield an empty answer (score 0). Used by tests and dry-run demos so CI
    never needs ``NVIDIA_NIM_API_KEY`` or network egress.
    """
    answers = validate_scripted_answers(answers_by_task_id or {})

    def _runner(policy_name: str) -> PolicyRunner:
        def run(prompt: str) -> dict[str, Any]:
            # Prompt carries an embedded task marker when callers use format_task_prompt.
            task_id = _extract_task_id_marker(prompt)
            answer = ""
            if task_id and task_id in answers:
                answer = answers[task_id].get(policy_name, "")
            return {
                "mode": policy_name,
                "answer": answer,
                "model_id": model_id,
                "trace": [{"role": "worker", "agent_id": "scripted_worker", "output": answer}],
                "verification": {"accepted": bool(answer)},
            }

        return run

    return {name: _runner(name) for name in _POLICY_NAMES if name != "hindsight_best_single"}


def build_orchestrator_policy_runners(orchestrator: Any) -> dict[str, PolicyRunner]:
    """Build policy runners backed by a ``TaskOrchestrator`` instance.

    Intended for offline mock pools (``mock://`` agents) and for hermetic CI.
    Does not read provider secrets: non-mock agents still resolve keys via KV
    ``get_credential`` inside the orchestrator.

    - ``direct_worker`` / ``route_once``: single-worker ``route_once`` path (Fugu).
    - ``bounded_conduct``: multi-step ``conduct`` path (Conductor / TRINITY roles).
    """
    if orchestrator is None or not hasattr(orchestrator, "route_once") or not hasattr(
        orchestrator, "conduct"
    ):
        raise CostQualityContractError(
            "orchestrator must provide route_once and conduct callables"
        )

    def _messages(prompt: str) -> list[dict[str, str]]:
        return [{"role": "user", "content": prompt}]

    def direct_worker(prompt: str) -> dict[str, Any]:
        result = orchestrator.route_once(_messages(prompt))
        result = dict(result)
        result["mode"] = "direct_worker"
        return result

    def route_once(prompt: str) -> dict[str, Any]:
        result = orchestrator.route_once(_messages(prompt))
        result = dict(result)
        result["mode"] = "route_once"
        return result

    def bounded_conduct(prompt: str) -> dict[str, Any]:
        result = orchestrator.conduct(_messages(prompt))
        result = dict(result)
        result["mode"] = "bounded_conduct"
        return result

    return {
        "direct_worker": direct_worker,
        "route_once": route_once,
        "bounded_conduct": bounded_conduct,
    }


def format_task_prompt(task: Mapping[str, Any]) -> str:
    """Return the scorable user prompt with a non-scoring task marker line."""
    # Marker is structural only; scorers ignore it and leakage checks use bare prompt.
    return f"[task_id={task['task_id']}]\n{task['prompt']}"


def _extract_task_id_marker(prompt: str) -> str | None:
    match = re.match(r"\[task_id=([a-z0-9_]+)\]\n", prompt)
    return match.group(1) if match else None


def _usage_from_result(prompt: str, result: Mapping[str, Any], model_id: str) -> dict[str, dict[str, int]]:
    answer = str(result.get("answer") or "")
    return {
        model_id: {
            "prompt_tokens": estimate_token_counts(prompt),
            "completion_tokens": estimate_token_counts(answer),
        }
    }


def run_policy_cell(
    *,
    task: Mapping[str, Any],
    policy_name: str,
    runner: PolicyRunner,
    model_id: str,
    pricing_scenario: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Execute one policy/task cell and return scored, secret-free evidence."""
    if policy_name not in _POLICY_NAMES:
        raise CostQualityContractError(f"unknown policy_name: {policy_name!r}")
    prompt = format_task_prompt(task)
    started = time.perf_counter()
    try:
        result = runner(prompt)
        outcome = "success"
        error_class = None
    except Exception as exc:  # noqa: BLE001 - classify for evidence only
        result = {"mode": policy_name, "answer": "", "trace": [], "verification": {"accepted": False}}
        outcome = "failed"
        error_class = type(exc).__name__
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    answer = str(result.get("answer") or "")
    score_block = score_task_answer(task, answer)
    # Failed cells did not complete a provider call — do not invent token/cost usage.
    if outcome == "success":
        usage = _usage_from_result(prompt, result, model_id)
        hyp_cost = hypothetical_cost_usd(pricing_scenario, usage)
        call_count = max(1, len(result.get("trace") or []))
        prompt_tokens = usage[model_id]["prompt_tokens"]
        completion_tokens = usage[model_id]["completion_tokens"]
        usage_source = "estimated"
    else:
        hyp_cost = "unknown"
        call_count = 0
        prompt_tokens = 0
        completion_tokens = 0
        usage_source = "none"
    content_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest() if answer else None
    return {
        "policy_name": policy_name,
        "task_id": task["task_id"],
        "model_id": model_id,
        "outcome": outcome,
        "error_class": error_class,
        "score": score_block["score"],
        "scorer_name": score_block["scorer_name"],
        "scorer_version": score_block["scorer_version"],
        "latency_ms": latency_ms,
        "call_count": call_count,
        "workflow_depth": call_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "actual_api_cost": "unknown",
        "hypothetical_paid_cost": hyp_cost,
        "pricing_scenario_id": (
            pricing_scenario.get("scenario_version") if pricing_scenario is not None else None
        ),
        "usage_source": usage_source,
        "answer_content_hash": content_hash,
        "verification_accepted": bool((result.get("verification") or {}).get("accepted")),
    }


def run_offline_cost_quality(
    *,
    tasks: Sequence[Mapping[str, Any]],
    policy_runners: Mapping[str, PolicyRunner],
    model_id: str = "mock-scripted",
    pricing_scenario: Mapping[str, Any] | None = None,
    include_hindsight_best_single: bool = True,
) -> dict[str, Any]:
    """Run fair offline policy comparisons and summarize quality/cost evidence.

    Policies present in ``policy_runners`` are executed for every locked task.
    When multiple direct-style runners share the ``direct_worker`` key only one
    direct path is used; hindsight best-single reuses per-task direct scores when
    ``include_hindsight_best_single`` is true.
    """
    if not tasks:
        raise CostQualityContractError("tasks must be non-empty")
    required = {"direct_worker", "route_once", "bounded_conduct"}
    missing = required - set(policy_runners)
    if missing:
        raise CostQualityContractError(f"policy_runners missing required policies: {sorted(missing)}")

    cells: list[dict[str, Any]] = []
    for task in tasks:
        for policy_name in ("direct_worker", "route_once", "bounded_conduct"):
            cells.append(
                run_policy_cell(
                    task=task,
                    policy_name=policy_name,
                    runner=policy_runners[policy_name],
                    model_id=model_id,
                    pricing_scenario=pricing_scenario,
                )
            )
        if include_hindsight_best_single:
            direct_for_task = [c for c in cells if c["task_id"] == task["task_id"] and c["policy_name"] == "direct_worker"]
            best = max(direct_for_task, key=lambda row: row["score"]) if direct_for_task else None
            if best is not None:
                hindsight = dict(best)
                hindsight["policy_name"] = "hindsight_best_single"
                cells.append(hindsight)

    summaries = summarize_policy_cells(cells)
    frontiers = build_pareto_frontiers(summaries)
    return {
        "measurement_status": "offline_cost_quality",
        "model_id": model_id,
        "task_count": len(tasks),
        "cell_count": len(cells),
        "cells": cells,
        "policy_summaries": summaries,
        "pareto_frontiers": frontiers,
        "pricing_scenario_id": (
            pricing_scenario.get("scenario_version") if pricing_scenario is not None else None
        ),
        "cost_honesty": (
            "actual_api_cost is unknown offline; hypothetical_paid_cost is unknown "
            "unless a pricing scenario prices every model used in the cell"
        ),
        "quality_proxy": (
            "strict scorer registry on locked tasks; mock/scripted answers only — "
            "not a live NIM quality claim"
        ),
    }


def summarize_policy_cells(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate mean score/latency and cost honesty per policy."""
    by_policy: dict[str, list[Mapping[str, Any]]] = {}
    for cell in cells:
        by_policy.setdefault(str(cell["policy_name"]), []).append(cell)
    summaries: list[dict[str, Any]] = []
    for policy_name in sorted(by_policy):
        rows = by_policy[policy_name]
        scores = [float(r["score"]) for r in rows]
        latencies = [float(r["latency_ms"]) for r in rows]
        hyp_costs = [r["hypothetical_paid_cost"] for r in rows]
        numeric_costs = [c for c in hyp_costs if isinstance(c, (int, float))]
        summaries.append(
            {
                "policy_name": policy_name,
                "cell_count": len(rows),
                "mean_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
                "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                "hypothetical_paid_cost_mean": (
                    round(sum(float(c) for c in numeric_costs) / len(numeric_costs), 10)
                    if numeric_costs and len(numeric_costs) == len(hyp_costs)
                    else "unknown"
                ),
                "success_rate": round(
                    sum(1 for r in rows if r.get("outcome") == "success") / len(rows), 6
                ),
            }
        )
    return summaries


def pareto_frontier(
    points: Sequence[Mapping[str, Any]],
    *,
    quality_key: str = "mean_score",
    cost_key: str = "hypothetical_paid_cost_mean",
    higher_quality_better: bool = True,
    lower_cost_better: bool = True,
) -> list[dict[str, Any]]:
    """Return undominated points on a quality-vs-cost frontier (numeric costs only)."""
    usable: list[Mapping[str, Any]] = []
    for point in points:
        quality = point.get(quality_key)
        cost = point.get(cost_key)
        if not isinstance(quality, (int, float)) or not math.isfinite(float(quality)):
            continue
        if not isinstance(cost, (int, float)) or not math.isfinite(float(cost)):
            continue
        usable.append(point)
    frontier: list[dict[str, Any]] = []
    for candidate in usable:
        dominated = False
        for other in usable:
            if other is candidate:
                continue
            better_or_equal_quality = (
                float(other[quality_key]) >= float(candidate[quality_key])
                if higher_quality_better
                else float(other[quality_key]) <= float(candidate[quality_key])
            )
            better_or_equal_cost = (
                float(other[cost_key]) <= float(candidate[cost_key])
                if lower_cost_better
                else float(other[cost_key]) >= float(candidate[cost_key])
            )
            strictly_better = (
                float(other[quality_key]) != float(candidate[quality_key])
                or float(other[cost_key]) != float(candidate[cost_key])
            )
            if better_or_equal_quality and better_or_equal_cost and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(dict(candidate))
    frontier.sort(key=lambda row: (-float(row[quality_key]), float(row[cost_key])))
    return frontier


def build_pareto_frontiers(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build quality-latency and quality-hypothetical-cost frontiers."""
    quality_latency = pareto_frontier(
        [
            {
                "policy_name": s["policy_name"],
                "mean_score": s["mean_score"],
                "hypothetical_paid_cost_mean": s["mean_latency_ms"],
            }
            for s in summaries
        ],
        quality_key="mean_score",
        cost_key="hypothetical_paid_cost_mean",
    )
    # Rename latency key for clarity in the latency frontier payload.
    quality_latency = [
        {
            "policy_name": row["policy_name"],
            "mean_score": row["mean_score"],
            "mean_latency_ms": row["hypothetical_paid_cost_mean"],
        }
        for row in quality_latency
    ]
    quality_cost = pareto_frontier(list(summaries))
    return {
        "quality_latency": quality_latency,
        "quality_hypothetical_cost": quality_cost,
        "notes": (
            "Points with unknown hypothetical cost are excluded from the cost frontier; "
            "latency frontier uses mean_latency_ms as the cost axis."
        ),
    }


def plan_from_discovery_models(
    model_ids: Sequence[str],
    *,
    task_manifest_id: str = "locked_eval_v1",
    hard_request_budget: int = 100,
) -> dict[str, Any]:
    """Admit a dry-run comparison plan for chat-eligible discovered models.

    Thin wrapper that reuses discovery capability hints so the cost-quality path
    stays aligned with ``build_benchmark_plan_dry_run`` admission rules.
    """
    from .nim_discovery import build_benchmark_plan_dry_run

    try:
        return build_benchmark_plan_dry_run(
            list(model_ids),
            task_manifest_id=task_manifest_id,
            hard_request_budget=hard_request_budget,
        )
    except NimDiscoveryError as exc:
        raise CostQualityContractError(str(exc)) from exc


def render_cost_quality_markdown(report: Mapping[str, Any]) -> str:
    """Render a short operator-facing markdown summary (no secrets)."""
    lines = [
        "# Offline cost-quality report",
        "",
        f"- measurement_status: `{report.get('measurement_status')}`",
        f"- model_id: `{report.get('model_id')}`",
        f"- task_count: {report.get('task_count')}",
        f"- cell_count: {report.get('cell_count')}",
        f"- pricing_scenario_id: `{report.get('pricing_scenario_id')}`",
        "",
        "## Policy summaries",
        "",
    ]
    for summary in report.get("policy_summaries") or []:
        lines.append(
            f"- **{summary['policy_name']}**: mean_score={summary['mean_score']}, "
            f"mean_latency_ms={summary['mean_latency_ms']}, "
            f"hypothetical_paid_cost_mean={summary['hypothetical_paid_cost_mean']}, "
            f"success_rate={summary['success_rate']}"
        )
    lines.extend(["", "## Cost honesty", "", str(report.get("cost_honesty") or ""), ""])
    return "\n".join(lines)
