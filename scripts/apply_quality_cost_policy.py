#!/usr/bin/env python3
"""Apply the bounded adaptive quality-first cost-aware implementation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_PATH = ROOT / "contextual_orchestrator" / "orchestrator.py"
SERVER_PATH = ROOT / "contextual_orchestrator" / "server.py"
ADR_PATH = ROOT / "docs" / "adr" / "0020-quality-first-cost-aware-auto.md"


def replace_pattern(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return updated


orchestrator = ORCHESTRATOR_PATH.read_text(encoding="utf-8")

if "JUDGMENT_HINTS = (" not in orchestrator:
    orchestrator = replace_pattern(
        orchestrator,
        r"(    COMPLEX_HINTS = \(.*?\n    \)\n)(\n    def __init__)",
        r'''\1
    JUDGMENT_HINTS = (
        "adjudicate",
        "assess",
        "classify",
        "evaluate",
        "evaluation",
        "judge",
        "review whether",
        "score",
        "verify whether",
        "검토",
        "분류",
        "심사",
        "채점",
        "판정",
        "평가",
    )
\2''',
        "judgment hints",
    )

orchestrator = replace_pattern(
    orchestrator,
    r"    def _dispatch\(.*?\n    def would_route",
    '''    def _dispatch(
        self, messages: list[ChatMessage], mode: str, *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        """Select the least-cost execution tier that meets the detected quality need."""
        text = self._latest_user_text(messages)
        selected_mode = self._adaptive_mode(text) if mode == "auto" else mode
        if selected_mode == "verify":
            return self.route_and_verify(messages, reasoning_effort=reasoning_effort)
        if selected_mode == "route":
            return self.route_once(messages, reasoning_effort=reasoning_effort)
        return self.conduct(messages, reasoning_effort=reasoning_effort)

    def would_route''',
    "adaptive dispatch",
)

orchestrator = replace_pattern(
    orchestrator,
    r"    def would_route\(.*?\n    def stream_route",
    '''    def would_route(self, messages: list[ChatMessage], mode: str = "auto") -> bool:
        """Return whether the selected policy tier is the direct single-worker path."""
        text = self._latest_user_text(messages)
        selected_mode = self._adaptive_mode(text) if mode == "auto" else mode
        return selected_mode == "route"

    def stream_route''',
    "adaptive streaming decision",
)

orchestrator = replace_pattern(
    orchestrator,
    r"    def _score_agent\(.*?\n    def _ranked_agents",
    '''    def _score_agent(
        self, agent: ModelAgent, role: str, lowered: str
    ) -> tuple[int, int, float, int, str]:
        """Rank capability first and known lower price only after capability ties.

        ``priority`` and capability tags represent the operator's quality evidence.
        Price is never allowed to override a stronger capability score. A model
        without price metadata ranks below an equally capable priced model, so
        unknown cost is not silently interpreted as free.
        """
        if agent.disabled:
            return (-20_000, 0, float("-inf"), len(agent.tags), agent.id)
        if role in agent.provider_exclusions:
            return (-10_000, 0, float("-inf"), len(agent.tags), agent.id)
        role_score = sum(3 for tag in agent.tags if tag in self.ROLE_TAGS.get(role, ()))
        domain_score = 0
        for tag, hints in self.DOMAIN_HINTS.items():
            if tag in agent.tags and any(hint in lowered for hint in hints):
                domain_score += 2
        capability_score = role_score + domain_score + agent.priority
        configured_price = self.price_per_million.get(agent.model)
        price_known = int(configured_price is not None)
        cost_rank = -float(configured_price) if configured_price is not None else float("-inf")
        return (capability_score, price_known, cost_rank, len(agent.tags), agent.id)

    def _ranked_agents''',
    "quality-first cost-aware agent ranking",
)

if "def _adaptive_mode(" not in orchestrator:
    orchestrator = replace_pattern(
        orchestrator,
        r"(    def _needs_workflow\(self, text: str\) -> bool:)",
        '''    def _adaptive_mode(self, text: str) -> str:
        """Choose route, verify, or conduct from the request's quality requirement.

        The policy is lexicographic rather than a blended score: complex work
        receives the full conducted workflow; bounded judgment work receives an
        independent verifier; only low-risk simple work receives one direct call.
        This maximizes the available execution tier before cost is minimized
        inside capability-equivalent choices.
        """
        lowered = text.lower()
        if self._needs_workflow(text):
            return "conduct"
        if any(hint in lowered for hint in self.JUDGMENT_HINTS):
            return "verify"
        return "route"

\1''',
        "adaptive mode selector",
    )

ORCHESTRATOR_PATH.write_text(orchestrator, encoding="utf-8")

server = SERVER_PATH.read_text(encoding="utf-8")
marker = "adaptive_structured_output = ("
if marker not in server:
    server = replace_pattern(
        server,
        r'''                    if PASSTHROUGH_TRIGGER_KEYS & set\(body\):\n.*?                        self\._send\(proxied\)\n                        return\n                    messages = _validate_messages''',
        '''                    passthrough_keys = PASSTHROUGH_TRIGGER_KEYS & set(body)
                    requested_mode_value = (
                        body.get("orchestration")
                        or body.get("orchestration_mode")
                        or body.get("mode")
                    )
                    explicit_mode_requested = any(
                        key in body for key in ("orchestration", "orchestration_mode", "mode")
                    )
                    adaptive_structured_output = (
                        passthrough_keys == {"response_format"}
                        and explicit_mode_requested
                        and requested_mode_value in {"auto", "verify", "conduct"}
                    )
                    if passthrough_keys and not adaptive_structured_output:
                        # Tool/function calls and compatibility-mode structured output
                        # retain full single-provider response passthrough.
                        started_at = time.perf_counter()
                        proxied = self._run(
                            lambda: orchestrator.proxy_completion(body, endpoint="chat/completions")
                        )
                        orchestrator.record_analytics_event(
                            "chat_completion_passthrough",
                            {
                                "endpoint_path": "/v1/chat/completions",
                                "actor_scope": "inference",
                                "status_code": 200,
                                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            },
                        )
                        self._send(proxied)
                        return
                    if adaptive_structured_output:
                        # The caller explicitly selected orchestration and retains
                        # strict downstream schema validation. Removing only the
                        # provider-native schema hint prevents the single-provider
                        # passthrough from defeating adaptive route/verify/conduct.
                        body = dict(body)
                        body.pop("response_format", None)
                    messages = _validate_messages''',
        "explicit adaptive structured-output path",
    )

SERVER_PATH.write_text(server, encoding="utf-8")

ADR_PATH.parent.mkdir(parents=True, exist_ok=True)
if ADR_PATH.exists():
    raise RuntimeError(f"refusing to replace existing ADR: {ADR_PATH}")
ADR_PATH.write_text(
    '''# ADR-0020: Quality-first, cost-aware adaptive orchestration is the product default

- Status: Accepted
- Date: 2026-08-16

## Context

A consumer that hard-codes `route` turns the orchestration control plane into a
single-model proxy. Conversely, forcing every request through a full multi-agent
workflow spends more without proving that the additional computation was needed.
The product needs one stable default that can allocate test-time computation while
retaining explicit modes for controlled ablation and emergency rollback.

## Decision

`auto` is the default product policy and follows a lexicographic objective:

1. satisfy the detected quality and safety requirement;
2. among capability-equivalent candidates, select a model with known lower cost;
3. never interpret missing price metadata as zero cost.

The bounded execution tiers are:

- `route` for low-risk simple requests;
- `verify` for judgment, evaluation, classification, and adjudication requests;
- `conduct` for complex, long, multi-step, research, security, architecture, and
  implementation requests.

Explicit `route`, `verify`, and `conduct` remain supported for experiments,
incident response, and operator overrides. They are not consumer defaults.

For `response_format`, an explicit adaptive mode opts into the orchestrated path;
the consumer remains responsible for strict schema validation. An implicit mode
retains full provider passthrough for backward compatibility. Tool/function-call
payloads remain passthrough because their side-effect protocol cannot be safely
merged across agents.

## Consequences

Simple work may still use one model when that is the least-cost quality-sufficient
plan. The default, however, is owned by contextual-orchestrator rather than by a
consumer-selected model or fixed workflow. Traces must record the selected tier,
provider, model, verification result, and usage so later empirical quality/cost
calibration can replace heuristics without changing consumer contracts.

## References

Omidvar, H., & Akhlaghi, V. (2026). *A communication-theoretic framework for LLM agents: Cost-aware adaptive reliability* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2605.09121

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv. https://doi.org/10.48550/arXiv.2606.21228
''',
    encoding="utf-8",
)
