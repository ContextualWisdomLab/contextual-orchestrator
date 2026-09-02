"""Apply the exact no-heuristics repair for PR #983 candidate controls."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}")
    target.write_text(text.replace(old, new, 1))


def splice(path: str, start: str, end: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text()
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{path}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{path}: end marker not found")
    target.write_text(text[:start_index] + replacement + text[end_index:])


replace_once(
    "contextual_orchestrator/server.py",
    '        if not isinstance(excluded, list) or len(excluded) > 32:\n            raise RequestError(\n                400,\n                "invalid_routing",\n                "routing.exclude_candidate_ids must be an array of at most 32 agent IDs",\n            )',
    '        if not isinstance(excluded, list):\n            raise RequestError(\n                400,\n                "invalid_routing",\n                "routing.exclude_candidate_ids must be an array of agent IDs",\n            )',
)

replace_once(
    "contextual_orchestrator/orchestrator.py",
    '            raise ValueError("exclude_candidate_ids must contain at most 32 agent IDs")',
    '            raise ValueError("exclude_candidate_ids must contain agent IDs")',
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    '        if not isinstance(excluded, (list, tuple)) or len(excluded) > 32:\n            raise ValueError("exclude_candidate_ids must contain at most 32 agent IDs")',
    '        if not isinstance(excluded, (list, tuple)):\n            raise ValueError("exclude_candidate_ids must contain agent IDs")',
)

start = '''        # conduct() records the id of the step whose output actually became\n'''
end = '''        evidence: dict[str, Any] = {\n'''
replacement = '''        # Serving identity is evidence, not an inference target. Multi-step\n        # workflows record the exact answering_step_id; provider-shaped paths\n        # may record served_agent_id explicitly. Historical records lacking\n        # either identity remain auditable for attempts but fail closed for\n        # served_candidate_id. Output equality and trace position are not\n        # admissible serving-identity evidence.\n        answering_step_id = result.get("answering_step_id")\n        answering_rows = (\n            [\n                row\n                for row in rows\n                if isinstance(row, Mapping) and row.get("id") == answering_step_id\n            ]\n            if isinstance(answering_step_id, int)\n            else []\n        )\n        served: str | None = None\n        if len(answering_rows) == 1:\n            row = answering_rows[0]\n            value = row.get("served_agent_id") or row.get("agent_id")\n            if isinstance(value, str) and value:\n                served = value\n        elif tracked_attempts != []:\n            explicit_served = [\n                value\n                for row in rows\n                if isinstance(row, Mapping)\n                for value in [row.get("served_agent_id")]\n                if isinstance(value, str) and value\n            ]\n            distinct_served = tuple(dict.fromkeys(explicit_served))\n            if len(distinct_served) == 1:\n                served = distinct_served[0]\n'''
splice("contextual_orchestrator/orchestrator.py", start, end, replacement)

replace_once(
    "README.md",
    '`routing.exclude_candidate_ids` (at most 32 unique IDs) to omit known-bad',
    '`routing.exclude_candidate_ids` (unique exact IDs) to omit evidence-ineligible',
)
replace_once(
    "docs/planning/adrs/0032-model-group-cost-aware-discovery.md",
    'pin an exact private agent ID with `routing.candidate_id` and exclude at most 32\nunique IDs with `routing.exclude_candidate_ids`.',
    'pin an exact private agent ID with `routing.candidate_id` and exclude unique exact\nIDs with `routing.exclude_candidate_ids`. Candidate membership has no repository-authored\ncardinality cutoff; normal authenticated request-size controls remain the resource boundary.',
)

replace_once(
    "tests/test_candidate_routing_controls.py",
    'def test_candidate_routing_evidence_falls_back_to_text_match_without_answering_step_id() -> None:\n    """A workflow record persisted before ``answering_step_id`` existed (or\n    any other caller that omits it) must still resolve routing evidence via\n    the prior text-matching/last-row heuristics rather than crashing or\n    silently returning no evidence."""',
    'def test_candidate_routing_evidence_fails_closed_without_answering_step_id() -> None:\n    """A historical workflow without explicit serving identity must not infer one."""',
)
replace_once(
    "tests/test_candidate_routing_controls.py",
    '    assert evidence is not None\n    assert evidence["served_candidate_id"] == "worker_agent"\n\n\ndef test_orchestrated_provider_completion_answering_step_id_identifies_synthesis_over_duplicate_internal_step()',
    '    assert evidence is not None\n    assert "served_candidate_id" not in evidence\n\n\ndef test_orchestrated_provider_completion_answering_step_id_identifies_synthesis_over_duplicate_internal_step()',
)

for path, section in (
    (
        "docs/planning/adrs/0032-model-group-cost-aware-discovery.md",
        """\n\n### No-heuristics amendment — 2026-09-02\n\nThe original request-local control used a fixed 32-ID exclusion ceiling and legacy\nserving-identity recovery from output equality/trace position. Neither decision rule\nwas identified by RouteLLM, FrugalGPT, an API standard, or measured deployment\nevidence. The cardinality ceiling is removed; authenticated request-size enforcement\nis the resource boundary. Serving identity is now reported only from exact\n`answering_step_id` or an explicit `served_agent_id`; historical rows without either\nremain attempt provenance and omit `served_candidate_id`. This is a fail-closed\nidentity rule rather than an inferred ranking/tie-break.\n""",
    ),
    (
        "docs/product-technical-gap-baseline.md",
        """\n\n## 2026-09-02 — PR #983 candidate-control no-heuristics repair\n\nLive RCA found two decision-affecting rules in the request-local candidate-control\nowner: a repository-authored 32-ID exclusion ceiling and serving-candidate inference\nfrom output equality/trace position when exact identity was absent. Neither had an\nidentified mathematical, standards, experimental, or research basis. The canonical\nrepair removes the cardinality rule, retaining normal authenticated request-size\ncontrols, and makes serving identity fail closed unless exact `answering_step_id` or\nexplicit `served_agent_id` evidence exists. Regression coverage exercises more than\n32 exclusions, missing identity, and explicit identity provenance. Exact-head hosted\nchecks remain authoritative before merge.\n""",
    ),
    (
        "CHANGELOG.md",
        """\n- Candidate routing controls no longer impose an unsupported 32-ID exclusion cutoff or infer serving identity from output text/trace order; serving identity now requires explicit provenance and otherwise fails closed.\n""",
    ),
):
    target = Path(path)
    text = target.read_text()
    if section.strip() not in text:
        target.write_text(text.rstrip() + section + "\n")
