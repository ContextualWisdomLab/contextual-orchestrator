#!/usr/bin/env python3
"""Scrub raw content from pre-fix zdr_only rows in a ``--state-db`` sqlite file.

Before this fix, ``TaskOrchestrator._replace_workflow_run``/``run_evaluation``
persisted full prompt/answer/trace-output/verification content for every
request, zdr_only included (see
``docs/security/zdr-enforcement-audit-20260917.md`` section 3.7). Rows
written since the fix already carry only non-content metadata for zdr_only
requests, so this script only ever touches pre-fix rows.

No ``zdr_only`` flag was ever stored on a row, so a historical row cannot be
proven zdr_only after the fact. This script is therefore conservative and
explicit rather than exhaustive:

- ``--workflow-run-id`` / ``--evaluation-run-id`` scrub specific rows an
  operator has already identified (e.g. from gateway request logs) as having
  run under zdr_only. This is the precise, recommended path.
- ``--bypass-cache-heuristic`` additionally flags rows whose stored
  ``cache_status == "bypass"``. Every zdr_only run recorded that status (PR
  #1194 made the cache bypass unconditional for zdr_only), but so did a
  caller-supplied ``bypass_cache=True`` on an ordinary, non-sensitive
  request -- so this flag trades recall for precision and is opt-in, not
  the default. Treat its matches as *candidates*, not certainties.

Dry-run (report only, no writes) is the default; pass ``--apply`` to write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from typing import Any


def _content_placeholder(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {
        "zdr_redacted": True,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_size": len(encoded),
    }


def _already_redacted(value: Any) -> bool:
    return isinstance(value, dict) and value.get("zdr_redacted") is True


def _scrub_workflow_run(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (possibly scrubbed record, whether anything changed)."""
    changed = False
    for field in ("prompt_text", "answer"):
        value = record.get(field)
        if isinstance(value, str):
            record[field] = _content_placeholder(value)
            changed = True
    for step in record.get("trace", []):
        output = step.get("output")
        if isinstance(output, str):
            step["output"] = _content_placeholder(output)
            changed = True
    tool_calls = record.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = _content_placeholder(function["arguments"])
                changed = True
    verification = record.get("verification")
    if isinstance(verification, dict):
        for field in ("judge_output_text", "verifier_output"):
            value = verification.get(field)
            if isinstance(value, str):
                verification[field] = _content_placeholder(value)
                changed = True
    return record, changed


def _scrub_evaluation_run(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    for result in record.get("results", []):
        answer = result.get("answer")
        if isinstance(answer, str):
            result["answer"] = _content_placeholder(answer)
            changed = True
    return record, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("state_db", help="Path to the --state-db sqlite file")
    parser.add_argument(
        "--workflow-run-id", action="append", default=[], help="Scrub this workflow_run row (repeatable)"
    )
    parser.add_argument(
        "--evaluation-run-id", action="append", default=[], help="Scrub this evaluation_run row (repeatable)"
    )
    parser.add_argument(
        "--bypass-cache-heuristic",
        action="store_true",
        help="Also flag workflow_run rows with cache_status == 'bypass' (candidates, not certainties)",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run, report only)")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.state_db)
    try:
        candidate_run_ids = set(args.workflow_run_id)
        candidate_eval_ids = set(args.evaluation_run_id)

        if args.bypass_cache_heuristic:
            for key, payload in conn.execute(
                "SELECT key, payload FROM orchestration_records WHERE kind = 'workflow_run'"
            ):
                record = json.loads(payload)
                if record.get("cache_status") == "bypass" and not _already_redacted(
                    record.get("prompt_text")
                ):
                    candidate_run_ids.add(key)

        scrubbed_runs = 0
        skipped_already_clean = 0
        for run_id in sorted(candidate_run_ids):
            row = conn.execute(
                "SELECT payload FROM orchestration_records WHERE kind = 'workflow_run' AND key = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                print(f"workflow_run {run_id}: not found, skipping", file=sys.stderr)
                continue
            record = json.loads(row[0])
            record, changed = _scrub_workflow_run(record)
            if not changed:
                skipped_already_clean += 1
                continue
            scrubbed_runs += 1
            if args.apply:
                conn.execute(
                    "UPDATE orchestration_records SET payload = ? WHERE kind = 'workflow_run' AND key = ?",
                    (json.dumps(record, ensure_ascii=False), run_id),
                )

        scrubbed_evals = 0
        for eval_id in sorted(candidate_eval_ids):
            row = conn.execute(
                "SELECT payload FROM orchestration_records WHERE kind = 'evaluation_run' AND key = ?",
                (eval_id,),
            ).fetchone()
            if row is None:
                print(f"evaluation_run {eval_id}: not found, skipping", file=sys.stderr)
                continue
            record = json.loads(row[0])
            record, changed = _scrub_evaluation_run(record)
            if not changed:
                continue
            scrubbed_evals += 1
            if args.apply:
                conn.execute(
                    "UPDATE orchestration_records SET payload = ? WHERE kind = 'evaluation_run' AND key = ?",
                    (json.dumps(record, ensure_ascii=False), eval_id),
                )

        if args.apply:
            conn.commit()

        mode = "APPLIED" if args.apply else "DRY RUN (pass --apply to write)"
        print(f"[{mode}] workflow_run rows scrubbed: {scrubbed_runs}")
        print(f"[{mode}] workflow_run rows already clean: {skipped_already_clean}")
        print(f"[{mode}] evaluation_run rows scrubbed: {scrubbed_evals}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
