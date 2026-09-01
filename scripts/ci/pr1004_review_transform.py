#!/usr/bin/env python3
"""Apply PR #1004 review repairs from the already-proven RED contracts."""

from __future__ import annotations

from pathlib import Path
import re


SOURCE = Path("contextual_orchestrator/orchestrator.py")
ADR = Path("docs/planning/adrs/0035-structured-provider-orchestration.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact logical anchor and fail closed when source drifted."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    """Replace one regex-delimited source region and fail closed on drift."""
    result, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return result


def transform_orchestrator() -> None:
    """Bind repair to one candidate and keep failed spend out of success KPIs."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("    def _orchestrated_provider_completion(")
    end = text.index("\n    @contextmanager\n    def routing_endpoint_scope(", start)
    segment = text[start:end]

    segment = replace_once(
        segment,
        """        def send_synthesis(\n            payload: dict[str, Any],\n        ) -> tuple[dict[str, Any], ModelAgent]:\n""",
        """        def send_synthesis(\n            payload: dict[str, Any],\n            *,\n            allow_cross_candidate_fallback: bool = True,\n        ) -> tuple[dict[str, Any], ModelAgent]:\n""",
        "send_synthesis signature",
    )

    segment = replace_once(
        segment,
        """            ordered_candidates = [\n                *([preferred] if preferred.id not in request_exclusions else []),\n                *(\n                    candidate\n                    for candidate in synthesis_candidates\n                    if candidate.id != preferred.id\n                    and candidate.id not in request_exclusions\n                ),\n            ]\n""",
        """            ordered_candidates = (\n                [preferred]\n                if not allow_cross_candidate_fallback\n                else [\n                    *([preferred] if preferred.id not in request_exclusions else []),\n                    *(\n                        candidate\n                        for candidate in synthesis_candidates\n                        if candidate.id != preferred.id\n                        and candidate.id not in request_exclusions\n                    ),\n                ]\n            )\n""",
        "ordered candidates",
    )

    segment = replace_once(
        segment,
        """                    request_too_large = _is_request_too_large_error(exc)\n                    saw_request_too_large = saw_request_too_large or request_too_large\n                    if request_too_large and not virtual_model:\n""",
        """                    request_too_large = _is_request_too_large_error(exc)\n                    saw_request_too_large = saw_request_too_large or request_too_large\n                    if not allow_cross_candidate_fallback:\n                        if request_too_large:\n                            raise ProviderRequestTooLargeError(\n                                \"request body exceeds provider limit\"\n                            ) from exc\n                        if isinstance(exc, ProviderResponseError):\n                            raise\n                        raise classify_provider_failure(\n                            exc,\n                            agent_id=candidate.id,\n                            model=candidate.model,\n                            transport=\"structured_repair\",\n                        ) from None\n                    if request_too_large and not virtual_model:\n""",
        "repair transport boundary",
    )

    segment = replace_once(
        segment,
        """            self._replace_workflow_run(record)\n            self._run_order.appendleft(workflow_run_id)\n            if self._store is not None:\n""",
        """            self._replace_workflow_run(record)\n            if failure_code is None:\n                self._run_order.appendleft(workflow_run_id)\n            if self._store is not None:\n""",
        "failed run ordering",
    )

    helper_anchor = """            return workflow_run_id\n\n        while True:\n"""
    helper = """            return workflow_run_id\n\n        def enforce_structured_budget() -> None:\n            \"\"\"Persist incurred usage before propagating a structured budget stop.\"\"\"\n            in_flight_tokens, in_flight_cost = self._trace_budget_spend(\n                [*workflow[\"trace\"], *structured_attempt_steps]\n            )\n            try:\n                self._raise_if_spend_budget_exceeded(\n                    additional_output_tokens=in_flight_tokens,\n                    additional_cost_usd=in_flight_cost,\n                )\n            except BudgetExceededError:\n                persist_structured_record(\n                    \"\", failure_code=\"structured_budget_exceeded\"\n                )\n                raise\n\n        def next_structured_candidate(failed_agent: ModelAgent) -> ModelAgent:\n            \"\"\"Retire one failed virtual candidate or raise typed exhaustion.\"\"\"\n            request_exclusions.add(failed_agent.id)\n            next_agent = next(\n                (\n                    candidate\n                    for candidate in synthesis_candidates\n                    if candidate.id not in request_exclusions\n                ),\n                None,\n            )\n            if next_agent is None:\n                workflow_run_id = persist_structured_record(\n                    \"\", failure_code=\"structured_output_exhausted\"\n                )\n                raise StructuredOutputExhaustedError(\n                    \"every eligible structured-output candidate violated \"\n                    \"response_format\",\n                    workflow_run_id=workflow_run_id,\n                )\n            return next_agent\n\n        while True:\n"""
    segment = replace_once(segment, helper_anchor, helper, "structured helpers")

    budget_block = """            in_flight_tokens, in_flight_cost = self._trace_budget_spend(\n                [*workflow[\"trace\"], *structured_attempt_steps]\n            )\n            self._raise_if_spend_budget_exceeded(\n                additional_output_tokens=in_flight_tokens,\n                additional_cost_usd=in_flight_cost,\n            )\n"""
    if segment.count(budget_block) != 2:
        raise SystemExit(f"structured budget anchor count={segment.count(budget_block)}")
    segment = segment.replace(budget_block, "            enforce_structured_budget()\n", 2)

    segment = replace_once(
        segment,
        "                repaired, final_agent = send_synthesis(repair_upstream)\n",
        """                repaired, final_agent = send_synthesis(\n                    repair_upstream,\n                    allow_cross_candidate_fallback=False,\n                )\n""",
        "repair send",
    )

    repair_start = segment.index("            except ProviderUpstreamError as exc:", segment.index("repair_started ="))
    repair_end = segment.index("            repaired_output = provider_output", repair_start)
    old_repair_except = segment[repair_start:repair_end]
    new_repair_except = """            except ProviderUpstreamError as exc:\n                if virtual_model and _is_request_too_large_error(exc):\n                    repair_step = {\n                        \"id\": len(workflow[\"trace\"]) + len(structured_attempt_steps),\n                        \"role\": \"repair\",\n                        \"agent_id\": final_agent.id,\n                        \"subtask\": \"Strict structured-output repair\",\n                        \"access\": [synthesis_step[\"id\"]],\n                        \"latency_ms\": round(\n                            (time.perf_counter() - repair_started) * 1000, 2\n                        ),\n                        \"output\": \"\",\n                        \"validation_outcome\": \"request_too_large\",\n                    }\n                    structured_attempt_steps.append(repair_step)\n                    next_agent = next_structured_candidate(final_agent)\n                    enforce_structured_budget()\n                    final_agent = next_agent\n                    synthesis_started = time.perf_counter()\n                    continue\n                if not _is_request_too_large_error(exc):\n                    self._record_failure(final_agent.id)\n                if (\n                    final_agent.group_name\n                    and not _is_request_too_large_error(exc)\n                ):\n                    self._group_router.observe_failure(final_agent.id)\n                persist_structured_record(\n                    \"\",\n                    failure_code=exc.error_code,\n                )\n                raise\n"""
    segment = replace_once(
        segment, old_repair_except, new_repair_except, "repair exception block"
    )

    advance_start = segment.index("            request_exclusions.add(failed_agent.id)")
    advance_end = segment.index("            final_agent = next_agent", advance_start)
    old_advance = segment[advance_start:advance_end]
    new_advance = """            next_agent = next_structured_candidate(failed_agent)\n            enforce_structured_budget()\n"""
    segment = replace_once(segment, old_advance, new_advance, "candidate advance")

    text = text[:start] + segment + text[end:]

    text = regex_once(
        text,
        r'(?m)^(\s*)if not record\.get\("pending_verification"\):\n\1    self\._run_order\.appendleft\(record\["workflow_run_id"\]\)$',
        r'\1if not record.get("pending_verification") and not record.get("failure"):\n\1    self._run_order.appendleft(record["workflow_run_id"])',
        "reload failure visibility",
    )

    text = replace_once(
        text,
        """        return [\n            run for run in self._workflow_runs.values()\n            if not run.get(\"pending_verification\")\n        ]\n""",
        """        return [\n            run\n            for run in self._workflow_runs.values()\n            if not run.get(\"pending_verification\") and not run.get(\"failure\")\n        ]\n""",
        "completed run visibility",
    )

    SOURCE.write_text(text, encoding="utf-8")


def transform_docs() -> None:
    """Record the review semantics and existing research-artifact boundary."""
    adr_text = ADR.read_text(encoding="utf-8")
    adr_text = replace_once(
        adr_text,
        "## References\n",
        """## Research artifact reuse and redistribution\n\nThis correctness repair does not introduce a new routing objective; it\nrestores ADR 0035's already-accepted bounded candidate-recovery semantics.\nThe relevant routing literature is already committed in this repository as\nredistributable artifacts: [`RouteLLM`](../../papers/routellm-routing-2406.18665.pdf)\nand [`Hybrid LLM`](../../papers/hybrid-llm-query-routing-2404.14618.pdf).\nTheir cost/quality-aware routing evidence supports selecting among eligible\nmodel candidates; it does not authorize bypassing caller endpoint, privacy,\nor budget constraints. Conductor and TRINITY remain cite-link-summary\nreferences in `docs/papers/README.md` because this repository has not\nindependently established a redistribution grant for those newer preprints;\nduplicating their PDFs in this PR would therefore weaken, not strengthen,\nthe repository's copyright rule.\n\n## References\n""",
        "ADR research artifact section",
    )
    ADR.write_text(adr_text, encoding="utf-8")

    change_text = CHANGELOG.read_text(encoding="utf-8")
    change_text = replace_once(
        change_text,
        "### Fixed\n\n",
        """### Fixed\n\n- Structured-output review follow-up now charges already-incurred synthesis\n  and repair usage before propagating a budget stop, keeps failed workflow\n  evidence queryable without counting it as a normal recent/completed KPI,\n  and binds a repair to the candidate whose synthesis failed. A repair-only\n  413 retires that candidate and starts a fresh synthesis on the next\n  already-eligible candidate instead of forwarding the repair prompt across\n  providers. Existing endpoint/ZDR/cost/privacy eligibility remains unchanged\n  (Devin Review, PR #1004).\n""",
        "changelog Fixed section",
    )
    CHANGELOG.write_text(change_text, encoding="utf-8")


if __name__ == "__main__":
    transform_orchestrator()
    transform_docs()
