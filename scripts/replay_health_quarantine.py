"""Replay sanitized Noema sidecar logs through the observed-health breaker.

Usage::

    python3 scripts/replay_health_quarantine.py <artifacts_dir> [--include-preflight] [--json OUT]

``<artifacts_dir>`` holds ``<repo>/<run>/contextual-orchestrator-sidecar.stderr.log``
files (the raw artifacts are evidence, not repository content; see
``docs/doctoring/observed-health-quarantine.md``). Each run is one sidecar
process, so each run replays against a fresh ``TaskOrchestrator`` -- the same
breaker code the gateway runs, driven by an injected clock set to the log
timestamps. Nothing here reaches a provider.

Counterfactual limits (stated, not hidden): a skipped attempt's outcome is
never fed to the policy (the gateway would not have observed it); the
successful attempt's duration is not logged, so a success is observed at its
start time; the replay cannot model which substitute candidate the gateway
would have tried instead, so "harmful" counts are upper bounds.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import re
import sys
import urllib.error
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import classify_health_failure  # noqa: E402

_TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
_ATTEMPT = re.compile(_TS + r"provider_attempt agent_id=(\S+) model=(\S+) attempt=\S+ request_id=(\S+)")
_FAILED = re.compile(
    _TS + r"provider_attempt_failed agent_id=(\S+) model=\S+ attempt=\S+ "
    r"error_type=(\S+) transient=\S+ provider_status=(\S+) request_id=(\S+)"
)
_CIRCUIT_FAILURE = re.compile(_TS + r"circuit_failure agent_id=(\S+)")
_CIRCUIT_EDGE = re.compile(_TS + r"circuit_(opened|cleared) agent_id=(\S+)")
#: Legacy reset window of the deployed pin: an attempt that started while
#: the deployed breaker was open was forced (all-open fallback or a pinned
#: model), so no breaker policy could have skipped it.
_DEPLOYED_RESET_SECONDS = 30.0
#: Statuses the gateway never charges to member health (quota is tracked by
#: the rate-limit cooldown on the passthrough path; size is the request's).
_NEVER_HEALTH = {"413"}


def _epoch(stamp: str) -> float:
    return dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S,%f").timestamp()


def _synthetic_failure(error_type: str, status: str) -> BaseException:
    """Rebuild a bounded exception shape so the real classifier decides the class."""
    if error_type == "HTTPError" and status.isdigit():
        return urllib.error.HTTPError("https://replay.invalid", int(status), "replay", None, None)
    if error_type == "RemoteDisconnected":
        return http.client.RemoteDisconnected("replay")
    if error_type == "ConnectionResetError":
        return ConnectionResetError("replay")
    if error_type in {"TimeoutError", "timeout"}:
        return TimeoutError("replay")
    return RuntimeError("replay")


def parse_run(path: Path) -> list[dict]:
    """Pair each failure line with the latest open attempt of the same request/agent.

    Sequential roles reuse one agent inside one request, so an earlier open
    attempt that never failed is a success (same pairing as the evidence
    directory's noema_phase.py).
    """
    attempts: list[dict] = []
    open_by_key: dict[tuple[str, str], deque[int]] = defaultdict(deque)
    lines = path.read_text(errors="replace").splitlines()
    deployed_open: dict[str, float | None] = {}
    for index, line in enumerate(lines):
        match = _ATTEMPT.match(line)
        if match:
            stamp, agent_id, model, request_id = match.groups()
            attempts.append(
                {
                    "start": _epoch(stamp), "end": None, "agent_id": agent_id,
                    "model": model, "request_id": request_id, "ok": True,
                    "error_type": None, "status": None, "recorded": True,
                    "forced": (
                        deployed_open.get(agent_id) is not None
                        and _epoch(stamp) - deployed_open[agent_id] < _DEPLOYED_RESET_SECONDS
                    ),
                }
            )
            open_by_key[(request_id, agent_id)].append(len(attempts) - 1)
            continue
        edge = _CIRCUIT_EDGE.match(line)
        if edge:
            deployed_open[edge.group(3)] = (
                _epoch(edge.group(1)) if edge.group(2) == "opened" else None
            )
            continue
        match = _FAILED.match(line)
        if not match:
            continue
        stamp, agent_id, error_type, status, request_id = match.groups()
        queue = open_by_key.get((request_id, agent_id))
        if not queue:
            continue
        attempt = attempts[queue.pop()]
        attempt.update(end=_epoch(stamp), ok=False, error_type=error_type, status=status)
        # Did the deployed path charge this failure to the breaker? The
        # deployed log prints circuit_failure right after a recorded failure.
        following = lines[index + 1 : index + 4]
        attempt["recorded"] = any(
            (m := _CIRCUIT_FAILURE.match(item)) and m.group(2) == agent_id for item in following
        )
    for attempt in attempts:
        if attempt["end"] is None:
            attempt["end"] = attempt["start"]
    return attempts


def _assign_steps(attempts: list[dict]) -> None:
    """Split each served request into failover steps, each ending at one success.

    A conducted request runs several roles (planner/worker/verifier/...), so
    one request can hold several successes; the candidate chain that precedes
    each success is one step.
    """
    by_request: dict[str, list[dict]] = defaultdict(list)
    for attempt in attempts:
        by_request[attempt["request_id"]].append(attempt)
    for request_id, items in by_request.items():
        step: list[dict] = []
        for attempt in sorted(items, key=lambda item: item["start"]):
            attempt["step"] = step
            step.append(attempt)
            if attempt["ok"]:
                step = []


def replay_run(
    attempts: list[dict],
    *,
    include_preflight: bool,
    totals: dict,
    policy: dict | None = None,
    demotion: bool = True,
    exclude_429: bool = False,
) -> None:
    """Drive one fresh orchestrator through one run's attempts in time order.

    ``policy`` overrides breaker attributes (for sensitivity runs);
    ``demotion=False`` ignores slow-failure demotion to isolate quarantine.
    ``exclude_429=True`` is the 429-study counterfactual: served provider
    429s are kept out of the ledger (as the passthrough path already does).
    """
    agents = {}
    for attempt in attempts:
        agents.setdefault(attempt["agent_id"], ModelAgent(attempt["agent_id"], attempt["model"]))
    orchestrator = TaskOrchestrator(list(agents.values()))
    for name, value in (policy or {}).items():
        setattr(orchestrator, name, value)
    clock = {"now": 0.0}
    orchestrator._circuit_clock = lambda: clock["now"]
    _assign_steps(attempts)

    def available(agent_id: str) -> bool:
        return not orchestrator._circuit_open(agent_id) and not orchestrator._circuit_demoted(
            agent_id
        )

    events = []
    for index, attempt in enumerate(attempts):
        events.append((attempt["start"], 1, index))
        events.append((attempt["end"], 0 if not attempt["ok"] else 2, index))
    events.sort()
    skipped: set[int] = set()
    first_after_open: set[str] = set()
    harmful_requests: set[str] = set()
    streak_429: dict[str, bool] = {}
    for stamp, kind, index in events:
        clock["now"] = stamp
        attempt = attempts[index]
        served = attempt["request_id"] != "-"
        agent_id = attempt["agent_id"]
        if kind == 1:
            if not served:
                continue
            totals["served_attempts"] += 1
            duration = attempt["end"] - attempt["start"]
            slow = not attempt["ok"] and classify_health_failure(
                _synthetic_failure(attempt["error_type"], attempt["status"])
            ) == "slow_transport"
            if not attempt["ok"]:
                totals["served_failed_seconds"] += duration
                if slow:
                    totals["served_slow_failure_seconds"] += duration
            probe_is_next = agent_id in first_after_open
            first_after_open.discard(agent_id)
            action = None
            if orchestrator._circuit_open(agent_id):
                if attempt["forced"]:
                    # The deployed breaker was already open and the attempt
                    # still ran: the never-empty fallback applies here too.
                    totals["forced_fallback_attempts"] += 1
                else:
                    action = "quarantine_skip"
            elif demotion and orchestrator._circuit_demoted(agent_id) and any(
                other["ok"] and other["agent_id"] != agent_id and available(other["agent_id"])
                for other in attempt["step"]
                if other["start"] >= attempt["start"]
            ):
                action = "demote_skip"
            if action is None:
                continue
            skipped.add(index)
            totals[action + "s"] += 1
            trip_class = (
                orchestrator.circuit_health_snapshot()[agent_id]["last_failure_class"]
            )
            if attempt["ok"]:
                # The skipped attempt was this step's eventual success.
                totals["harmful_removals"] += 1
                totals[f"harmful_removals_after_{trip_class}"] += 1
                harmful_requests.add(attempt["request_id"])
                if action == "quarantine_skip" and probe_is_next:
                    totals["false_positive_episodes"] += 1
            else:
                totals["saved_failed_seconds"] += duration
                if slow:
                    totals["saved_slow_failure_seconds"] += duration
                totals[f"saved_failed_seconds_after_{trip_class}"] += duration
                totals[f"saved_failed_seconds_by_{action}"] += duration
            continue
        if index in skipped or (not served and not include_preflight):
            continue
        if attempt["ok"]:
            orchestrator._record_success(agent_id)
            streak_429[agent_id] = False
            continue
        if attempt["status"] in _NEVER_HEALTH:
            continue
        if served and attempt["status"] == "429" and attempt["recorded"]:
            totals["served_429_charged"] += 1
            if exclude_429:
                continue
        if served and not attempt["recorded"]:
            continue  # the deployed path did not charge it to the breaker
        before = orchestrator.circuit_health_snapshot().get(agent_id, {}).get("open_count", 0)
        orchestrator._record_failure(
            agent_id,
            failure_class=classify_health_failure(
                _synthetic_failure(attempt["error_type"], attempt["status"])
            ),
        )
        streak_429[agent_id] = streak_429.get(agent_id, False) or attempt["status"] == "429"
        if orchestrator.circuit_health_snapshot()[agent_id]["open_count"] > before:
            totals["quarantine_episodes"] += 1
            if streak_429[agent_id]:
                totals["episodes_with_429_in_streak"] += 1
            streak_429[agent_id] = False
            first_after_open.add(agent_id)
            if not served:
                totals["preflight_triggered_episodes"] += 1
    totals["harmful_requests"] += len(harmful_requests)


def deployed_429_opens(path: Path) -> dict[str, int]:
    """Count deployed ``circuit_opened`` events whose charged streak held a 429.

    Reads the deployed (legacy 3/30) log itself, independent of the replay:
    the charged failures for an agent since its last clear/reset/open.
    """
    streak: dict[str, list[str]] = defaultdict(list)
    last_status: dict[str, str] = {}
    counts = {"deployed_circuit_opened": 0, "deployed_opened_with_429_in_streak": 0}
    for line in path.read_text(errors="replace").splitlines():
        failed = _FAILED.match(line)
        if failed:
            last_status[failed.group(2)] = failed.group(4)
            continue
        charged = _CIRCUIT_FAILURE.match(line)
        if charged:
            streak[charged.group(2)].append(last_status.get(charged.group(2), "?"))
            continue
        edge = re.match(_TS + r"circuit_(opened|cleared|reset) agent_id=(\S+)", line)
        if edge:
            agent_id = edge.group(3)
            if edge.group(2) == "opened":
                counts["deployed_circuit_opened"] += 1
                if "429" in streak[agent_id]:
                    counts["deployed_opened_with_429_in_streak"] += 1
            streak[agent_id] = []
    return counts


def main(argv: list[str] | None = None) -> dict:
    """Replay every run under ``artifacts_dir`` and print one bounded JSON summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifacts_dir", type=Path)
    parser.add_argument("--include-preflight", action="store_true")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--no-demotion", action="store_true")
    parser.add_argument("--exclude-429", action="store_true")
    parser.add_argument(
        "--legacy-like",
        action="store_true",
        help="baseline: the deployed default (quarantine opt-in off, legacy 3/30)",
    )
    args = parser.parse_args(argv)
    logs = sorted(args.artifacts_dir.glob("*/*/contextual-orchestrator-sidecar.stderr.log"))
    totals: dict = defaultdict(float)
    policy = {"observed_health_quarantine": not args.legacy_like}
    demotion = not (args.no_demotion or args.legacy_like)
    for path in logs:
        replay_run(
            parse_run(path),
            include_preflight=args.include_preflight,
            totals=totals,
            policy=policy,
            demotion=demotion,
            exclude_429=args.exclude_429,
        )
        deployed = deployed_429_opens(path)
        for key, value in deployed.items():
            totals[key] += value
    summary = {
        "runs": len(logs),
        "include_preflight": args.include_preflight,
        "demotion": demotion,
        "policy_overrides": policy,
        "exclude_429": args.exclude_429,
        **{key: round(value, 1) for key, value in sorted(totals.items())},
    }
    text = json.dumps(summary, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    return summary


if __name__ == "__main__":
    main()
