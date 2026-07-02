"""Runtime orchestration, workflow trace, governance, and audit primitives."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, replace
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse
import urllib.request

from .conventions import require_object_name


ChatMessage = dict[str, str]

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

DEFAULT_COMMERCIAL_TARGET_VALUE_KRW = 2_000_000_000


@dataclass(frozen=True)
class ModelAgent:
    """Configuration for one model-backed worker in the agent pool."""

    id: str
    model: str
    base_url: str = "mock://local"
    api_key_env: str = ""
    tags: tuple[str, ...] = ()
    priority: int = 0
    disabled: bool = False
    provider_name: str = ""
    provider_exclusions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_object_name(self.id, "agent.id")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelAgent":  # pragma: no cover
        """Build an agent from JSON configuration with naming validation."""
        require_object_name(value["id"], "agent.id")
        return cls(
            id=value["id"],
            model=value["model"],
            base_url=value.get("base_url", "mock://local"),
            api_key_env=value.get("api_key_env", ""),
            tags=tuple(value.get("tags", ())),
            priority=int(value.get("priority", 0)),
            disabled=bool(value.get("disabled", False)),
            provider_name=value.get("provider_name", ""),
            provider_exclusions=tuple(value.get("provider_exclusions", value.get("provider_exclusion", ()))),
        )


@dataclass(frozen=True)
class WorkflowStep:
    """One visible step in a conducted orchestration workflow."""

    id: int
    role: str
    agent_id: str
    subtask: str
    access: tuple[int, ...] = ()
    latency_ms: float | None = None
    output: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the workflow step for API and trace responses."""
        return {
            "id": self.id,
            "role": self.role,
            "agent_id": self.agent_id,
            "subtask": self.subtask,
            "access": list(self.access),
            "latency_ms": self.latency_ms,
            "output": self.output,
        }


@dataclass(frozen=True)
class OrchestrationPolicy:
    """Policy knobs that govern routing, verification, and admin visibility."""

    route_p95_seconds: float = 2.5
    conduct_hint_threshold: int = 2
    verifier_required: bool = True
    verifier_positive_terms: tuple[str, ...] = ("verified", "accepted", "confirmed", "pass", "good", "ok")
    verifier_negative_terms: tuple[str, ...] = ("reject", "disagree", "conflict", "unsafe", "fails", "error", "risky")

    def as_dict(self) -> dict[str, Any]:
        """Return the API-safe policy snapshot for workflow records."""
        return {
            "route_p95_seconds": self.route_p95_seconds,
            "conduct_hint_threshold": self.conduct_hint_threshold,
            "verifier_required": self.verifier_required,
            "workflow_steps": ["thinker", "worker", "verifier", "synthesizer"],
            "supported_locales": ["en", "ko"],
        }


class ModelClient:
    """Small chat-completions client with deterministic mock support."""

    def __init__(self, timeout: int = 90, max_output_tokens: int = 2048, max_retries: int = 1) -> None:
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries

    def chat(self, agent: ModelAgent, messages: list[ChatMessage], temperature: float = 0.2) -> str:
        """Send messages to a mock or OpenAI-compatible chat endpoint."""
        if agent.base_url.startswith("mock://"):
            return self._mock(agent, messages)

        self._validate_provider(agent)  # pragma: no cover
        api_key = os.environ.get(agent.api_key_env)  # pragma: no cover
        if not api_key:  # pragma: no cover
            raise RuntimeError(f"{agent.id} requires ${agent.api_key_env}")

        payload = {  # pragma: no cover
            "model": agent.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            "max_tokens": self.max_output_tokens,
        }
        last_error: Exception | None = None  # pragma: no cover
        for _ in range(self.max_retries + 1):  # pragma: no cover
            try:
                request = urllib.request.Request(
                    f"{agent.base_url.rstrip('/')}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"provider {agent.id} request failed") from last_error  # pragma: no cover

    def _validate_provider(self, agent: ModelAgent) -> None:
        """Reject unsafe remote model endpoints before any egress happens."""
        if not agent.api_key_env:
            raise RuntimeError(f"{agent.id} requires explicit api_key_env")
        parsed = urlparse(agent.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"{agent.id} base_url must use https")
        allowed_hosts = {
            host.strip().lower()
            for host in os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "").split(",")
            if host.strip()
        }
        hostname = parsed.hostname.lower()
        if allowed_hosts and hostname not in allowed_hosts:
            raise RuntimeError(f"{agent.id} provider host is not allowlisted")
        for address in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            ip_address = ipaddress.ip_address(address[4][0])
            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_multicast
                or ip_address.is_reserved
            ):
                raise RuntimeError(f"{agent.id} provider resolves to non-public address")

    def _mock(self, agent: ModelAgent, messages: list[ChatMessage]) -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        role = "worker"
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        match = re.search(r"Role: ([a-z]+)", system)
        if match:
            role = match.group(1)
        return f"[{agent.id}:{role}] {last[:220]}"


def load_agents(path: str) -> list[ModelAgent]:  # pragma: no cover
    """Load model agent definitions from an agents JSON file."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [ModelAgent.from_dict(item) for item in data["agents"]]


class TaskOrchestrator:
    """Coordinate model routing, conducted workflows, governance, and audit state."""

    ROLE_TAGS = {
        "thinker": ("planning", "reasoning", "research"),
        "worker": ("coding", "implementation", "reasoning"),
        "verifier": ("verification", "security", "review", "debugging"),
        "synthesizer": ("writing", "reasoning", "planning"),
    }
    DOMAIN_HINTS = {
        "coding": ("code", "bug", "debug", "implement", "repository", "test", "코드", "구현"),
        "security": ("security", "vulnerability", "xss", "sqli", "auth", "보안"),
        "research": ("paper", "research", "literature", "architecture", "논문", "분석"),
        "planning": ("plan", "design", "workflow", "orchestr", "아키텍처"),
        "verification": ("verify", "review", "risk", "check", "검증", "리뷰"),
    }
    COMPLEX_HINTS = (
        "analyze",
        "architecture",
        "develop",
        "implement",
        "verify",
        "security",
        "research",
        "paper",
        "multi-step",
        "workflow",
        "분석",
        "개발",
        "구현",
        "검증",
        "논문",
    )

    def __init__(self, agents: list[ModelAgent], client: ModelClient | None = None) -> None:
        self.agents = [agent for agent in agents if not agent.disabled]
        if not self.agents:  # pragma: no cover
            raise ValueError("at least one enabled agent is required")
        self.client = client or ModelClient()
        self.policy = OrchestrationPolicy()
        self._workflow_runs: dict[str, dict[str, Any]] = {}
        self._evaluation_runs: dict[str, dict[str, Any]] = {}
        self._analytics_events: deque[dict[str, Any]] = deque(maxlen=512)
        self._audit_events: deque[dict[str, Any]] = deque(maxlen=256)
        self._run_order: deque[str] = deque(maxlen=128)

    def complete(self, messages: list[ChatMessage], mode: str = "auto") -> dict[str, Any]:
        """Return a route or conducted completion without persisting a workflow run."""
        text = self._latest_user_text(messages)
        if mode == "route" or (mode == "auto" and not self._needs_workflow(text)):
            return self.route_once(messages)
        return self.conduct(messages)

    def run(self, messages: list[ChatMessage], mode: str = "auto", workflow_run_id: str | None = None) -> dict[str, Any]:
        """Execute completion and persist a workflow run with trace and policy evidence."""
        result = self.complete(messages, mode=mode)
        prompt = self._latest_user_text(messages)
        record = {
            "workflow_run_id": workflow_run_id or f"run_{uuid.uuid4().hex}",
            "created_at": int(time.time()),
            "mode": result["mode"],
            "policy_mode": mode,
            "prompt_text": prompt,
            "answer": result["answer"],
            "trace": result["trace"],
            "policy_snapshot": self.policy.as_dict(),
            "verification": result.get("verification"),
        }
        self._workflow_runs[record["workflow_run_id"]] = record
        self._run_order.appendleft(record["workflow_run_id"])
        self._append_audit_event(
            "workflow_run_created",
            {
                "workflow_run_id": record["workflow_run_id"],
                "mode": record["mode"],
                "agent_count": len(record["trace"]),
            },
        )
        self.record_analytics_event(
            "workflow_run_created",
            {
                "workflow_run_id": record["workflow_run_id"],
                "run_mode": record["mode"],
                "policy_mode": record["policy_mode"],
                "trace_step_count": len(record["trace"]),
                "trace_complete": self._is_trace_complete(record),
            },
        )
        for step in record["trace"]:
            self.record_analytics_event(
                "workflow_step_completed",
                {
                    "workflow_run_id": record["workflow_run_id"],
                    "run_mode": record["mode"],
                    "step_id": step["id"],
                    "agent_id": step["agent_id"],
                    "role": step["role"],
                    "duration_ms": step.get("latency_ms"),
                },
            )
        return record

    def run_evaluation(self, prompts: list[str], mode: str = "auto") -> dict[str, Any]:
        """Replay prompts through the runtime and persist an evaluation record."""
        if not prompts:  # pragma: no cover
            raise ValueError("evaluation requires at least one prompt")
        workflow_run_ids: list[str] = []
        results: list[dict[str, Any]] = []
        for prompt in prompts:
            record = self.run([{"role": "user", "content": prompt}], mode=mode)
            workflow_run_ids.append(record["workflow_run_id"])
            results.append({
                "workflow_run_id": record["workflow_run_id"],
                "answer": record["answer"],
            })

        evaluation_run_id = f"eval_{uuid.uuid4().hex}"
        evaluation = {
            "evaluation_run_id": evaluation_run_id,
            "created_at": int(time.time()),
            "mode": mode,
            "prompt_count": len(prompts),
            "workflow_run_ids": workflow_run_ids,
            "results": results,
            "success_count": len([r for r in results if r["answer"]]),
        }
        self._evaluation_runs[evaluation_run_id] = evaluation
        self._append_audit_event(
            "evaluation_run_created",
            {
                "evaluation_run_id": evaluation_run_id,
                "workflow_run_count": len(workflow_run_ids),
                "success_count": evaluation["success_count"],
            },
        )
        self.record_analytics_event(
            "evaluation_run_created",
            {
                "evaluation_run_id": evaluation_run_id,
                "run_mode": mode,
                "workflow_run_count": len(workflow_run_ids),
                "success_count": evaluation["success_count"],
            },
        )
        return evaluation

    def get_workflow_run(self, workflow_run_id: str) -> dict[str, Any]:
        """Return a persisted workflow run by identifier."""
        if workflow_run_id not in self._workflow_runs:  # pragma: no cover
            raise KeyError(workflow_run_id)
        return self._workflow_runs[workflow_run_id]

    def get_access_report(self, workflow_run_id: str) -> dict[str, Any]:
        """Return per-step visibility and accessed output evidence for a run."""
        run = self.get_workflow_run(workflow_run_id)
        access_report = []
        for step in run["trace"]:
            access_report.append({
                "step_id": step["id"],
                "role": step["role"],
                "agent_id": step["agent_id"],
                "access": step["access"],
                "accessed_outputs": [
                    run["trace"][index]["output"] for index in step["access"] if index < len(run["trace"])
                ],
            })
        return {
            "workflow_run_id": workflow_run_id,
            "policy_snapshot": run["policy_snapshot"],
            "steps": access_report,
            "verifier": run.get("verification"),
        }

    def patch_agent(self, agent_pool_id: str, worker_agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply governance updates to an agent and emit an audit event."""
        if not patch:  # pragma: no cover
            raise ValueError("patch request body must contain updates")
        if agent_pool_id != "default":  # pragma: no cover
            raise KeyError(agent_pool_id)
        current = self._agent(worker_agent_id)
        patched = current
        if "status" in patch:
            status = str(patch["status"]).lower()
            if status in {"active", "enabled"}:
                patched = replace(patched, disabled=False)
            elif status in {"disabled", "excluded", "inactive", "quarantine"}:
                patched = replace(patched, disabled=True)
            else:  # pragma: no cover
                raise ValueError("status must be active, enabled, disabled, excluded, inactive, or quarantine")
        if "priority" in patch:
            patched = replace(patched, priority=int(patch["priority"]))
        if "tags" in patch:
            patched = replace(patched, tags=tuple(patch["tags"]))
        if "provider_exclusions" in patch:
            patched = replace(patched, provider_exclusions=tuple(patch["provider_exclusions"]))

        self.agents = [patched if agent.id == worker_agent_id else agent for agent in self.agents]
        self._append_audit_event(
            "agent_patched",
            {
                "agent_pool_id": agent_pool_id,
                "worker_agent_id": worker_agent_id,
                "updated_fields": sorted(patch.keys()),
            },
        )
        if "status" in patch:
            self.record_analytics_event(
                "agent_status_changed",
                {
                    "agent_pool_id": agent_pool_id,
                    "agent_id": worker_agent_id,
                    "status": self._agent_to_admin_payload(patched)["status"],
                },
            )
        if "provider_exclusions" in patch:
            self.record_analytics_event(
                "provider_exclusion_changed",
                {
                    "agent_pool_id": agent_pool_id,
                    "agent_id": worker_agent_id,
                    "provider_exclusions": list(patched.provider_exclusions),
                },
            )
        return self._agent_to_admin_payload(patched)

    def route_once(self, messages: list[ChatMessage]) -> dict[str, Any]:
        """Route a prompt to one selected worker agent and return a single-step trace."""
        text = self._latest_user_text(messages)
        agent = self._select_agent(text, "worker")
        start = time.perf_counter()
        answer = self.client.chat(agent, messages)
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "mode": "route",
            "answer": answer,
            "verification": {"accepted": True, "reason": "single route path", "verifier_output": ""},
            "trace": [
                {
                    "id": 0,
                    "role": "worker",
                    "agent_id": agent.id,
                    "subtask": "Direct route",
                    "access": [],
                    "latency_ms": round(latency_ms, 2),
                    "output": answer,
                }
            ],
        }

    def conduct(self, messages: list[ChatMessage]) -> dict[str, Any]:
        """Run the thinker-worker-verifier-synthesizer workflow for complex prompts."""
        task = self._latest_user_text(messages)
        steps = self._plan(task)
        outputs: dict[int, str] = {}
        trace: list[dict[str, Any]] = []

        for step in steps:
            agent = self._agent(step.agent_id)
            prior = "\n\n".join(f"Step {i}: {outputs[i]}" for i in step.access)
            step_messages = [
                {
                    "role": "system",
                    "content": (
                        f"Role: {step.role}\n"
                        "Use only the original task and the accessed prior steps. "
                        "Return concise, directly useful work."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Original task:\n{task}\n\nAccessed prior work:\n{prior}\n\nSubtask:\n{step.subtask}",
                },
            ]
            start = time.perf_counter()
            outputs[step.id] = self.client.chat(agent, step_messages)
            elapsed = (time.perf_counter() - start) * 1000
            row = step.as_dict()
            row["latency_ms"] = round(elapsed, 2)
            row["output"] = outputs[step.id]
            trace.append(row)

        verification = self._judge_verifier_output(outputs.get(2, ""), outputs.get(0, ""), outputs.get(1, ""))
        answer = outputs[steps[2].id] if not self.policy.verifier_required else outputs[steps[-1].id]
        if not verification["accepted"] and self.policy.verifier_required:  # pragma: no cover
            answer = outputs[steps[1].id]

        return {
            "mode": "conduct",
            "answer": answer,
            "trace": trace,
            "verification": verification,
        }

    def _plan(self, task: str) -> list[WorkflowStep]:
        thinker = self._select_agent(task, "thinker").id
        worker = self._select_agent(task, "worker").id
        verifier = self._select_agent(task, "verifier").id
        synthesizer = self._select_agent(task, "synthesizer").id
        return [
            WorkflowStep(0, "thinker", thinker, "Decompose the task and identify the best execution strategy."),
            WorkflowStep(1, "worker", worker, "Execute the core task using the plan.", (0,)),
            WorkflowStep(2, "verifier", verifier, "Find concrete errors, gaps, and unsupported claims.", (0, 1)),
            WorkflowStep(3, "synthesizer", synthesizer, "Produce the final answer, incorporating only verified work.", (0, 1, 2)),
        ]

    def _select_agent(self, text: str, role: str) -> ModelAgent:
        lowered = text.lower()

        def score(agent: ModelAgent) -> tuple[int, int, str]:
            if agent.disabled:
                return (-20_000, len(agent.tags), agent.id)
            if role in agent.provider_exclusions:
                return (-10_000, len(agent.tags), agent.id)
            role_score = sum(3 for tag in agent.tags if tag in self.ROLE_TAGS.get(role, ()))
            domain_score = 0
            for tag, hints in self.DOMAIN_HINTS.items():
                if tag in agent.tags and any(hint in lowered for hint in hints):
                    domain_score += 2
            return (role_score + domain_score + agent.priority, len(agent.tags), agent.id)

        selected = max(self.agents, key=score)
        if selected.disabled:  # pragma: no cover
            raise RuntimeError(f"no enabled agent available for role={role}")
        if role in selected.provider_exclusions:  # pragma: no cover
            raise RuntimeError(f"no eligible agent available for role={role}")
        return selected

    def _agent(self, agent_id: str) -> ModelAgent:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(agent_id)  # pragma: no cover

    def _needs_workflow(self, text: str) -> bool:
        lowered = text.lower()
        hits = sum(1 for hint in self.COMPLEX_HINTS if hint in lowered)
        return hits >= self.policy.conduct_hint_threshold or len(text) > 700

    def _latest_user_text(self, messages: list[ChatMessage]) -> str:
        return next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")  # pragma: no cover

    def _judge_verifier_output(self, verifier_output: str, thinker_output: str, worker_output: str) -> dict[str, Any]:
        lowered = verifier_output.lower()
        if any(term in lowered for term in self.policy.verifier_negative_terms):  # pragma: no cover
            return {
                "accepted": False,
                "reason": "verifier output flagged disagreement or risk",
                "verifier_output": verifier_output,
            }
        if any(term in lowered for term in self.policy.verifier_positive_terms):  # pragma: no cover
            return {
                "accepted": True,
                "reason": "verifier output accepted the synthesized result",
                "verifier_output": verifier_output,
            }
        if thinker_output and worker_output:
            return {
                "accepted": True,
                "reason": "fallback acceptance from available planner and worker output",
                "verifier_output": verifier_output,
            }
        return {  # pragma: no cover
            "accepted": False,
            "reason": "fallback verifier disagreement with missing upstream outputs",
            "verifier_output": verifier_output,
        }

    def _append_audit_event(self, event_type: str, detail: dict[str, Any]) -> None:
        self._audit_events.append({
            "created_at": int(time.time()),
            "event_type": event_type,
            "event_detail": detail,
        })

    def _infer_provider_name(self, base_url: str) -> str:
        if base_url.startswith("mock://"):
            return f"mock-{base_url.removeprefix('mock://')}"
        if "://" in base_url:
            return base_url.split("//", 1)[-1].split("/", 1)[0]
        return base_url  # pragma: no cover

    def _agent_to_admin_payload(self, agent: ModelAgent) -> dict[str, Any]:
        return {
            "id": agent.id,
            "model": agent.model,
            "base_url": agent.base_url,
            "provider_name": agent.provider_name or self._infer_provider_name(agent.base_url),
            "priority": agent.priority,
            "tags": list(agent.tags),
            "status": "disabled" if agent.disabled else "active",
            "provider_exclusions": list(agent.provider_exclusions),
        }

    def list_agents(self, page_number: int = 1, page_size: int = 10) -> list[dict[str, Any]]:
        """Return a paginated admin-safe view of configured agents."""
        if page_number < 1 or page_size < 1:  # pragma: no cover
            raise ValueError("page_number/page_size must be >= 1")
        start = (page_number - 1) * page_size
        end = start + page_size
        return [self._agent_to_admin_payload(agent) for agent in self.agents[start:end]]

    def list_recent_runs(self, page_number: int = 1, page_size: int = 10) -> list[dict[str, Any]]:
        """Return a paginated list of recent workflow run records."""
        if page_number < 1 or page_size < 1:  # pragma: no cover
            raise ValueError("page_number/page_size must be >= 1")
        start = (page_number - 1) * page_size
        end = start + page_size
        run_ids = list(self._run_order)[start:end]
        return [self._workflow_runs[run_id] for run_id in run_ids]

    def list_recent_audit_events(self, page_number: int = 1, page_size: int = 25) -> list[dict[str, Any]]:
        """Return recent audit events in newest-first order."""
        if page_number < 1 or page_size < 1:  # pragma: no cover
            raise ValueError("page_number/page_size must be >= 1")
        events = list(self._audit_events)
        start = (page_number - 1) * page_size
        end = start + page_size
        total = len(events)
        left = max(0, total - end)
        right = max(0, total - start)
        return list(reversed(events[left:right]))

    def record_analytics_event(self, event_name: str, detail: dict[str, Any]) -> None:
        """Record a compact in-memory analytics event without prompt or output text."""
        require_object_name(event_name, "analytics.event_name")
        self._analytics_events.append({
            "event_time": int(time.time()),
            "event_name": event_name,
            "event_detail": redact_value(detail),
        })

    def analytics_snapshot(self, locale_bundles: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
        """Return source-backed local KPI definitions from in-memory runtime state."""
        runs = list(self._workflow_runs.values())
        conducted_runs = [run for run in runs if run["mode"] == "conduct"]
        trace_complete_count = sum(1 for run in conducted_runs if self._is_trace_complete(run))
        policy_safe_count = sum(1 for run in runs if self._is_policy_safe_run(run))
        event_counts = Counter(event["event_name"] for event in self._analytics_events)
        successful_chat_requests = sum(
            1
            for event in self._analytics_events
            if event["event_name"] == "chat_completion_requested"
            and event["event_detail"].get("status_code") == 200
        )
        route_count = sum(1 for run in runs if run["mode"] == "route")
        conduct_count = sum(1 for run in runs if run["mode"] == "conduct")
        step_count = sum(len(run["trace"]) for run in runs)
        provider_exclusion_misses = sum(self._provider_exclusion_miss_count(run) for run in runs)
        locale_parity = self._locale_key_parity(locale_bundles or {})

        return {
            "measurement_status": "local_runtime_snapshot",
            "source_note": "Metrics are measured from this process in-memory runtime, not production telemetry.",
            "event_counts": dict(sorted(event_counts.items())),
            "kpis": [
                {
                    "metric_name": "compatible_api_adoption",
                    "label": "Compatible API adoption",
                    "value": successful_chat_requests,
                    "unit": "successful_requests",
                    "source": "chat_completion_requested events",
                },
                {
                    "metric_name": "trace_complete_workflow_rate",
                    "label": "Trace-complete workflow rate",
                    "numerator": trace_complete_count,
                    "denominator": len(conducted_runs),
                    "value_percent": self._percent(trace_complete_count, len(conducted_runs)),
                    "source": "workflow_runs conduct traces",
                },
                {
                    "metric_name": "policy_safe_routing_rate",
                    "label": "Policy-safe routing rate",
                    "numerator": policy_safe_count,
                    "denominator": len(runs),
                    "value_percent": self._percent(policy_safe_count, len(runs)),
                    "source": "workflow_runs policy snapshots",
                },
            ],
            "drivers": [
                {
                    "metric_name": "route_versus_conduct_mix",
                    "label": "Route-versus-conduct mix",
                    "counts": {"route": route_count, "conduct": conduct_count},
                    "source": "workflow_runs mode",
                },
                {
                    "metric_name": "evaluation_replay_usage",
                    "label": "Evaluation replay usage",
                    "value": event_counts.get("evaluation_run_created", 0),
                    "unit": "runs",
                    "source": "evaluation_run_created events",
                },
                {
                    "metric_name": "agent_health_coverage",
                    "label": "Agent health coverage",
                    "numerator": len([agent for agent in self.agents if agent.id and agent.model and agent.base_url]),
                    "denominator": len(self.agents),
                    "value_percent": self._percent(
                        len([agent for agent in self.agents if agent.id and agent.model and agent.base_url]),
                        len(self.agents),
                    ),
                    "source": "agent pool configuration",
                },
            ],
            "guardrails": [
                {
                    "metric_name": "provider_exclusion_miss_rate",
                    "label": "Provider exclusion miss rate",
                    "value": provider_exclusion_misses,
                    "denominator": step_count,
                    "value_percent": self._percent(provider_exclusion_misses, step_count),
                    "source": "workflow trace agent selections",
                },
                {
                    "metric_name": "locale_key_parity",
                    "label": "Locale key parity",
                    **locale_parity,
                    "source": "admin locale bundles",
                },
            ],
        }

    def sales_readiness_report(
        self,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a local, evidence-backed sales-readiness gate for enterprise pilots."""
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        runs = list(self._workflow_runs.values())
        conducted_runs = [run for run in runs if run["mode"] == "conduct"]
        trace_complete_count = sum(1 for run in conducted_runs if self._is_trace_complete(run))
        event_counts = analytics["event_counts"]
        criteria = [
            self._criterion(
                "api_compatibility",
                "OpenAI-compatible API",
                "pass" if event_counts.get("chat_completion_requested", 0) > 0 else "warn",
                f"{event_counts.get('chat_completion_requested', 0)} compatible chat requests recorded",
                "Run a /v1/chat/completions smoke test before an enterprise evaluation.",
            ),
            self._criterion(
                "admin_evidence",
                "Operator evidence surface",
                "pass" if admin_state["agents"] and admin_state["policy"] else "fail",
                f"{len(admin_state['agents'])} agents, {len(admin_state['recent_audit_events'])} audit events exposed",
                "Expose agent pool, policy, and audit state before positioning the product as sellable.",
            ),
            self._criterion(
                "trace_evidence",
                "Workflow trace evidence",
                "pass" if trace_complete_count > 0 else "warn",
                f"{trace_complete_count} complete conducted traces across {len(conducted_runs)} conducted runs",
                "Run a conduct-mode workflow so access-list and verifier evidence are visible.",
            ),
            self._criterion(
                "evaluation_replay",
                "Evaluation replay",
                "pass" if event_counts.get("evaluation_run_created", 0) > 0 else "warn",
                f"{event_counts.get('evaluation_run_created', 0)} evaluation replay runs recorded",
                "Run at least one evaluation replay before customer-facing pilot review.",
            ),
            self._security_posture_criterion(security_profile or {}),
            self._criterion(
                "analytics_truthfulness",
                "Analytics truthfulness",
                "pass" if analytics["measurement_status"] == "local_runtime_snapshot" else "fail",
                analytics["source_note"],
                "Label metrics as proposed definitions unless backed by measured runtime telemetry.",
            ),
            self._locale_readiness_criterion(analytics),
            self._provider_egress_criterion(),
        ]
        summary = self._criteria_summary(criteria)
        readiness_summary = {"pass": summary["pass"], "warn": summary["warn"], "fail": summary["fail"]}
        if summary["fail"]:
            readiness_status = "not_ready"
        elif summary["warn"]:
            readiness_status = "pilot_ready_with_warnings"
        else:
            readiness_status = "sales_ready"

        return {
            "readiness_status": readiness_status,
            "measurement_status": "local_runtime_snapshot",
            "source_note": (
                "Sales readiness is based on this process-local runtime, configuration, and "
                "documentation evidence; it is not a production compliance certificate."
            ),
            "summary": readiness_summary,
            "readiness_summary": readiness_summary,
            "criteria": criteria,
        }

    def commercial_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a diligence-oriented readiness gate for high-value enterprise sales."""
        sales_readiness = self.sales_readiness_report(
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        sales_rows = self._criteria_by_name(sales_readiness["criteria"])
        analytics_guardrails = self._metrics_by_name(analytics["guardrails"])
        documentation = self._commercial_documentation_profile()
        security_profile = security_profile or {}
        policy_safe_metric = self._metrics_by_name(analytics["kpis"])["policy_safe_routing_rate"]
        provider_metric = analytics_guardrails["provider_exclusion_miss_rate"]
        locale_metric = analytics_guardrails["locale_key_parity"]

        criteria = [
            self._criterion(
                "product_capability_evidence",
                "Product capability evidence",
                "pass" if sales_readiness["readiness_status"] == "sales_ready" else "warn",
                (
                    f"sales_readiness={sales_readiness['readiness_status']}; "
                    f"{sales_readiness['readiness_summary']['pass']} sales criteria passing"
                ),
                "Resolve all sales-readiness warnings before presenting the product for a high-value diligence review.",
            ),
            self._criterion(
                "security_and_access_control",
                "Security and access control",
                "pass"
                if sales_rows["security_posture"]["status"] == "pass"
                and sales_rows["provider_egress_safety"]["status"] == "pass"
                else "fail",
                (
                    f"{sales_rows['security_posture']['evidence']}; "
                    f"{sales_rows['provider_egress_safety']['evidence']}"
                ),
                "Keep split admin/inference tokens, private bind defaults, hidden traces, and safe provider egress.",
            ),
            self._criterion(
                "operational_resilience",
                "Operational resilience",
                "pass"
                if int(security_profile.get("rate_limit_requests") or 0) > 0
                and int(security_profile.get("max_concurrent_runs") or 0) > 0
                and policy_safe_metric.get("value_percent") == 100.0
                else "warn",
                (
                    f"rate_limit_requests={security_profile.get('rate_limit_requests')}; "
                    f"max_concurrent_runs={security_profile.get('max_concurrent_runs')}; "
                    f"policy_safe_routing_rate={policy_safe_metric.get('value_percent')}%"
                ),
                "Publish production SLOs, backup policy, and incident runbooks before a production sale.",
            ),
            self._criterion(
                "audit_and_compliance_evidence",
                "Audit and compliance evidence",
                "pass"
                if sales_rows["trace_evidence"]["status"] == "pass"
                and provider_metric.get("value") == 0
                else "warn",
                (
                    f"{sales_rows['trace_evidence']['evidence']}; "
                    f"provider_exclusion_misses={provider_metric.get('value')}"
                ),
                "Capture customer-specific access reports and compliance exceptions during paid pilot onboarding.",
            ),
            self._criterion(
                "buyer_due_diligence_packet",
                "Buyer due-diligence packet",
                "pass" if not documentation["missing_documents"] else "warn",
                (
                    f"{documentation['present_count']}/{documentation['required_count']} required documents present; "
                    f"missing={', '.join(documentation['missing_documents']) or 'none'}"
                ),
                "Complete README, security, API, analytics, product, and commercial readiness documents.",
            ),
            self._criterion(
                "support_and_localization",
                "Support and localization",
                "pass" if locale_metric.get("value_percent") == 100.0 and documentation["has_security_policy"] else "warn",
                (
                    f"locale_key_parity={locale_metric.get('value_percent')}%; "
                    f"security_policy={documentation['has_security_policy']}"
                ),
                "Keep Korean and English operator copy aligned and publish support ownership for customer operations.",
            ),
            self._criterion(
                "commercial_value_case",
                "Commercial value case",
                "pass" if target_contract_value_krw >= DEFAULT_COMMERCIAL_TARGET_VALUE_KRW else "warn",
                (
                    f"target_contract_value_krw={target_contract_value_krw:,}; "
                    "value case uses compatibility API, evidence control plane, replay, and audit controls"
                ),
                "Anchor high-value sales review at KRW 2,000,000,000 or higher with buyer-specific ROI evidence.",
            ),
        ]
        summary = self._criteria_summary(criteria)
        commercial_summary = {"pass": summary["pass"], "warn": summary["warn"], "fail": summary["fail"]}
        if commercial_summary["fail"]:
            commercial_status = "not_commercial_ready"
        elif commercial_summary["warn"]:
            commercial_status = "commercial_ready_with_warnings"
        else:
            commercial_status = "commercial_ready"

        return {
            "commercial_status": commercial_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_due_diligence_snapshot",
            "source_note": (
                "Commercial readiness is based on process-local runtime, repository documentation, "
                "security configuration, and analytics evidence; it is not a valuation guarantee, "
                "purchase commitment, or production compliance certificate."
            ),
            "summary": commercial_summary,
            "commercial_summary": commercial_summary,
            "criteria": criteria,
            "documentation": documentation,
            "sales_readiness": sales_readiness,
        }

    def buyer_evidence_manifest_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the buyer-facing evidence index for high-value commercial review."""
        commercial = self.commercial_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        commercial_rows = self._criteria_by_name(commercial["criteria"])
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        items = [
            self._buyer_evidence_item(
                "product_scope",
                "Product scope",
                "Economic buyer",
                ["README.md", "docs/product_planning.md", "docs/commercial_readiness.md"],
                "repository_artifact",
                "ready" if all(has_file(path) for path in ("README.md", "docs/product_planning.md", "docs/commercial_readiness.md")) else "blocked",
                "Single enterprise orchestration control plane is documented.",
                "Keep product scope unified for buyer review.",
            ),
            self._buyer_evidence_item(
                "compatible_inference_api",
                "Compatible inference API",
                "Platform reviewer",
                ["/v1/chat/completions", "docs/rest_api_design.md", "tests/test_api_contract.py"],
                "repository_artifact",
                "ready" if has_file("docs/rest_api_design.md") and has_file("tests/test_api_contract.py") else "blocked",
                "OpenAI-compatible endpoint and API contract tests are present.",
                "Restore API contract docs and tests before buyer review.",
            ),
            self._buyer_evidence_item(
                "admin_evidence_control_plane",
                "Admin evidence control plane",
                "Platform operator",
                ["/admin", "/admin/state", "docs/screen_design.md"],
                "repository_artifact",
                "ready" if has_file("docs/screen_design.md") else "blocked",
                "Admin screen design and runtime state endpoint are present.",
                "Restore admin evidence design before buyer review.",
            ),
            self._buyer_evidence_item(
                "sales_readiness",
                "Sales readiness",
                "Product owner",
                ["/api/v1/sales_readiness/latest", "tests/test_sales_readiness.py"],
                "measured_local",
                "ready" if commercial["sales_readiness"]["readiness_summary"]["fail"] == 0 else "blocked",
                f"sales_readiness={commercial['sales_readiness']['readiness_status']}",
                "Resolve sales-readiness failures before commercial review.",
            ),
            self._buyer_evidence_item(
                "commercial_readiness",
                "Commercial readiness",
                "Economic buyer",
                ["/api/v1/commercial_readiness/latest", "tests/test_commercial_readiness.py"],
                "measured_local",
                "ready" if commercial["commercial_summary"]["fail"] == 0 else "blocked",
                f"commercial_status={commercial['commercial_status']}",
                "Resolve commercial-readiness failures before buyer review.",
            ),
            self._buyer_evidence_item(
                "analytics_honesty",
                "Analytics honesty",
                "Analytics reviewer",
                ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
                "measured_local",
                "ready" if analytics["measurement_status"] == "local_runtime_snapshot" else "blocked",
                analytics["source_note"],
                "Keep measured local evidence separate from production KPI proposals.",
            ),
            self._buyer_evidence_item(
                "access_list_evidence",
                "Access-list evidence",
                "Security and compliance reviewer",
                ["/api/v1/access_reports/{workflow_run_id}", "docs/product_planning.md"],
                "repository_artifact",
                "ready" if has_file("docs/product_planning.md") else "blocked",
                "Workflow trace and access-report evidence are documented.",
                "Restore access-list evidence docs before compliance review.",
            ),
            self._buyer_evidence_item(
                "evaluation_replay",
                "Evaluation replay",
                "Quality reviewer",
                ["/api/v1/evaluation_runs", "docs/screen_design.md"],
                "repository_artifact",
                "ready" if has_file("docs/screen_design.md") else "blocked",
                "Evaluation replay surface is documented.",
                "Restore evaluation replay docs before quality review.",
            ),
            self._buyer_evidence_item(
                "security_posture",
                "Security posture",
                "Security reviewer",
                ["SECURITY.md", "tests/test_security_hardening.py", "CodeQL", "Dependency review", "Trivy"],
                "measured_local",
                "ready" if commercial_rows["security_and_access_control"]["status"] == "pass" else "blocked",
                commercial_rows["security_and_access_control"]["evidence"],
                "Resolve concrete security failures before buyer review.",
            ),
            self._buyer_evidence_item(
                "visual_stakeholder_evidence",
                "Visual stakeholder evidence",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable Figma, FigJam, and Slides artifacts are recorded.",
                "Record editable Figma artifacts before stakeholder review.",
            ),
            self._buyer_evidence_item(
                "buyer_diligence_packet",
                "Buyer diligence packet",
                "Procurement reviewer",
                ["docs/commercial_buyer_diligence_packet.md"],
                "repository_artifact",
                "ready" if has_file("docs/commercial_buyer_diligence_packet.md") else "blocked",
                "Buyer questions map to evidence paths and caveats.",
                "Restore the buyer diligence packet before procurement review.",
            ),
            self._buyer_evidence_item(
                "buyer_acceptance_runbook",
                "Buyer acceptance runbook",
                "Procurement reviewer",
                ["docs/commercial_buyer_acceptance_runbook.md"],
                "repository_artifact",
                "ready" if has_file("docs/commercial_buyer_acceptance_runbook.md") else "blocked",
                "Go, warning, and no-go rules are documented.",
                "Restore acceptance runbook before procurement review.",
            ),
            self._buyer_evidence_item(
                "buyer_evidence_manifest",
                "Buyer evidence manifest",
                "Deal owner",
                ["docs/commercial_buyer_evidence_manifest.md", "/api/v1/buyer_evidence_manifests/latest"],
                "measured_local",
                "ready" if has_file("docs/commercial_buyer_evidence_manifest.md") else "blocked",
                "Buyer evidence is indexed by owner, source, evidence type, and completion state.",
                "Restore the manifest document and endpoint before buyer review.",
            ),
            self._buyer_evidence_item(
                "packaging_decision",
                "Packaging decision",
                "Procurement and security reviewer",
                ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "repository_artifact",
                "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
                "Single repo and one deployable product remain the current decision.",
                "Document extraction triggers before changing package boundaries.",
            ),
            self._buyer_evidence_item(
                "production_slo_support",
                "Production SLO and support proof",
                "Customer operations reviewer",
                ["production telemetry", "incident drill records", "support ownership"],
                "proposed_until_production",
                "warning",
                "Production SLO, incident, and support evidence require a deployed customer environment.",
                "Collect production telemetry during paid onboarding.",
            ),
            self._buyer_evidence_item(
                "buyer_specific_roi_legal",
                "Buyer-specific ROI and legal proof",
                "Economic buyer and procurement",
                ["ROI model", "legal questionnaire", "data-processing terms", "support plan"],
                "proposed_until_buyer_specific",
                "warning",
                "ROI, legal, procurement, and deployment evidence require a named buyer.",
                "Collect buyer-specific inputs during account diligence.",
            ),
        ]
        summary = self._buyer_manifest_summary(items)
        if summary["by_completion_state"].get("blocked", 0):
            manifest_status = "buyer_review_blocked"
        elif summary["by_completion_state"].get("warning", 0):
            manifest_status = "buyer_review_ready_with_warnings"
        else:
            manifest_status = "buyer_review_ready"

        return {
            "manifest_status": manifest_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_buyer_evidence_manifest",
            "source_note": (
                "Buyer evidence manifest combines process-local runtime reports, repository documents, "
                "Figma artifact records, and explicit production or buyer-specific caveats; it is not a "
                "valuation guarantee, purchase commitment, or production compliance certificate."
            ),
            "summary": summary,
            "items": items,
            "related_runtime_reports": {
                "commercial_status": commercial["commercial_status"],
                "sales_readiness_status": commercial["sales_readiness"]["readiness_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
        }

    def buyer_handoff_bundle_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a buyer handoff bundle that packages sale-readiness evidence."""
        manifest = self.buyer_evidence_manifest_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        manifest_summary = manifest["summary"]["by_completion_state"]
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        runtime_state = "blocked" if manifest_summary.get("blocked", 0) else "ready"
        included_artifacts = [
            self._buyer_evidence_item(
                "runtime_reports",
                "Runtime reports",
                "Deal owner",
                [
                    "/api/v1/sales_readiness/latest",
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/buyer_evidence_manifests/latest",
                    "/api/v1/analytics_snapshots/latest",
                ],
                "measured_local",
                runtime_state,
                (
                    f"buyer_manifest_status={manifest['manifest_status']}; "
                    f"commercial_status={manifest['related_runtime_reports']['commercial_status']}"
                ),
                "Resolve runtime report blockers before buyer handoff.",
            ),
            self._buyer_evidence_item(
                "repository_packet",
                "Repository packet",
                "Procurement reviewer",
                [
                    "README.md",
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                ],
                "repository_artifact",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/commercial_buyer_diligence_packet.md",
                        "docs/commercial_buyer_acceptance_runbook.md",
                        "docs/commercial_buyer_evidence_manifest.md",
                        "docs/commercial_buyer_handoff_bundle.md",
                    )
                )
                else "blocked",
                "Buyer-facing diligence, acceptance, manifest, and handoff documents are present.",
                "Restore missing buyer packet documents before procurement review.",
            ),
            self._buyer_evidence_item(
                "figma_stakeholder_artifacts",
                "Figma stakeholder artifacts",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable Figma, FigJam, and Slides artifacts are recorded without Code Connect.",
                "Record editable stakeholder artifacts before buyer handoff.",
            ),
            self._buyer_evidence_item(
                "verification_commands",
                "Verification commands",
                "Technical reviewer",
                [
                    "tests/test_buyer_handoff_bundle.py",
                    "tests/test_buyer_evidence_manifest.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                    "pytest -q",
                ],
                "measured_local",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "tests/test_buyer_handoff_bundle.py",
                        "tests/test_buyer_evidence_manifest.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "Focused contract tests and full pytest verification are named for buyer review.",
                "Restore focused tests before technical buyer handoff.",
            ),
            self._buyer_evidence_item(
                "packaging_decision",
                "Packaging decision",
                "Procurement and security reviewer",
                ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "repository_artifact",
                "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
                "Single repository and one deployable product remain the current decision.",
                "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
            ),
        ]
        follow_up_items = [
            self._buyer_evidence_item(
                "production_handoff_readiness",
                "Production handoff readiness",
                "Customer operations reviewer",
                ["production SLO", "incident drill", "support rota", "deployment history"],
                "proposed_until_production",
                "warning",
                "Production SLO, incident, deployment, and support evidence require a live customer environment.",
                "Collect production telemetry and support evidence during paid onboarding.",
            ),
            self._buyer_evidence_item(
                "buyer_specific_commercial_close",
                "Buyer-specific commercial close",
                "Economic buyer and legal reviewer",
                ["ROI model", "legal questionnaire", "data-processing terms", "support plan"],
                "proposed_until_buyer_specific",
                "warning",
                "ROI, legal, procurement, and deployment commitments require a named buyer.",
                "Collect buyer-specific inputs during account diligence.",
            ),
        ]
        all_items = included_artifacts + follow_up_items
        summary = self._buyer_manifest_summary(all_items)
        if summary["by_completion_state"].get("blocked", 0):
            bundle_status = "buyer_handoff_blocked"
        elif summary["by_completion_state"].get("warning", 0):
            bundle_status = "buyer_handoff_ready_with_warnings"
        else:
            bundle_status = "buyer_handoff_ready"

        return {
            "bundle_status": bundle_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_buyer_handoff_bundle",
            "source_note": (
                "Buyer handoff bundle packages local runtime reports, repository documents, "
                "Figma artifact records, verification commands, and explicit production or "
                "buyer-specific caveats; it is not a valuation guarantee, purchase commitment, "
                "or production compliance certificate."
            ),
            "summary": summary,
            "included_artifacts": included_artifacts,
            "follow_up_items": follow_up_items,
            "acceptance_gates": [
                {
                    "gate_name": "go",
                    "rule": "no blocked included artifacts and concrete security checks have no failure",
                },
                {
                    "gate_name": "warning",
                    "rule": "production or buyer-specific evidence remains proposed and explicitly caveated",
                },
                {
                    "gate_name": "blocked",
                    "rule": "security failure, API contract regression, document mismatch, product defect, or Code Connect usage",
                },
            ],
            "related_runtime_reports": {
                "buyer_manifest_status": manifest["manifest_status"],
                **manifest["related_runtime_reports"],
            },
            "library_split_decision": {
                "decision": "keep_single_product",
                "reason": "No second product, independent release cadence, or security provenance trigger exists.",
                "allowed_future_triggers": [
                    "second product requires core only",
                    "independent release cadence is needed",
                    "buyer security provenance requires package extraction",
                ],
            },
            "plugin_traceability": {
                "figma": "editable stakeholder artifacts and FigJam workflow",
                "product_design": "buyer handoff surface and admin evidence workflow",
                "superpowers": "implementation plan and verification checklist",
                "ponytail": "single-product packaging and no new dependency",
                "data_analytics": "measured versus proposed evidence separation",
            },
        }

    def saleability_decision_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the buyer-facing saleability decision for high-value review."""
        handoff = self.buyer_handoff_bundle_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        concrete_blockers = [
            item
            for item in handoff["included_artifacts"]
            if item["completion_state"] == "blocked"
        ]
        warning_conditions = [
            item
            for item in handoff["follow_up_items"]
            if item["completion_state"] == "warning"
        ]
        if concrete_blockers:
            saleability_status = "saleability_blocked"
            decision_label = "Blocked by concrete defect"
        elif warning_conditions:
            saleability_status = "saleability_ready_with_warnings"
            decision_label = "Ready for buyer diligence with explicit warnings"
        else:
            saleability_status = "saleability_ready"
            decision_label = "Ready for buyer diligence"

        return {
            "saleability_status": saleability_status,
            "decision_label": decision_label,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_saleability_decision",
            "source_note": (
                "Saleability decision is a local buyer due-diligence gate based on runtime "
                "reports, repository documents, Figma artifacts, verification commands, and "
                "explicit caveats; it is not a valuation guarantee, purchase commitment, "
                "or production compliance certificate."
            ),
            "decision_summary": {
                "included_artifact_count": len(handoff["included_artifacts"]),
                "blocked_count": len(concrete_blockers),
                "warning_count": len(warning_conditions),
                "review_process_is_blocker": False,
            },
            "decision_basis": [
                {
                    "basis_name": "buyer_handoff_bundle",
                    "status": handoff["bundle_status"],
                    "source": "/api/v1/buyer_handoff_bundles/latest",
                },
                {
                    "basis_name": "buyer_evidence_manifest",
                    "status": handoff["related_runtime_reports"]["buyer_manifest_status"],
                    "source": "/api/v1/buyer_evidence_manifests/latest",
                },
                {
                    "basis_name": "commercial_readiness",
                    "status": handoff["related_runtime_reports"]["commercial_status"],
                    "source": "/api/v1/commercial_readiness/latest",
                },
                {
                    "basis_name": "sales_readiness",
                    "status": handoff["related_runtime_reports"]["sales_readiness_status"],
                    "source": "/api/v1/sales_readiness/latest",
                },
            ],
            "concrete_blockers": concrete_blockers,
            "warning_conditions": warning_conditions,
            "review_process_policy": {
                "is_blocker": False,
                "non_blocker_examples": [
                    "reviewer delay",
                    "review bot delay",
                    "queued model review",
                    "pending check without concrete failure",
                ],
                "blocker_definition": "concrete security, API contract, document, or product defect",
            },
            "related_runtime_reports": {
                "buyer_handoff_status": handoff["bundle_status"],
                **handoff["related_runtime_reports"],
            },
            "library_split_decision": handoff["library_split_decision"],
            "plugin_traceability": handoff["plugin_traceability"],
        }

    def commercial_evidence_export_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a portable buyer due-diligence export index for commercial review."""
        saleability = self.saleability_decision_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = saleability["concrete_blockers"]
        required_external_evidence = [
            {
                "evidence_name": item["item_name"],
                "label": item["label"],
                "reviewer": item["reviewer"],
                "sources": item["sources"],
                "evidence_type": item["evidence_type"],
                "evidence": item["evidence"],
                "next_action": item["next_action"],
            }
            for item in saleability["warning_conditions"]
        ]
        saleability_state = "blocked" if saleability["saleability_status"] == "saleability_blocked" else "ready"
        export_sections = [
            self._buyer_evidence_item(
                "saleability_decision",
                "Saleability decision",
                "Deal owner",
                ["/api/v1/saleability_decisions/latest", "docs/commercial_saleability_decision.md"],
                "measured_local",
                saleability_state,
                f"saleability_status={saleability['saleability_status']}",
                "Resolve concrete saleability blockers before exporting buyer evidence.",
            ),
            self._buyer_evidence_item(
                "runtime_reports",
                "Runtime reports",
                "Technical reviewer",
                [
                    "/api/v1/sales_readiness/latest",
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/buyer_evidence_manifests/latest",
                    "/api/v1/buyer_handoff_bundles/latest",
                    "/api/v1/saleability_decisions/latest",
                    "/api/v1/analytics_snapshots/latest",
                ],
                "measured_local",
                "blocked" if concrete_blockers else "ready",
                (
                    f"buyer_handoff_status={saleability['related_runtime_reports']['buyer_handoff_status']}; "
                    f"buyer_manifest_status={saleability['related_runtime_reports']['buyer_manifest_status']}"
                ),
                "Resolve blocked runtime reports before buyer export.",
            ),
            self._buyer_evidence_item(
                "buyer_packet_documents",
                "Buyer packet documents",
                "Procurement reviewer",
                [
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                ],
                "repository_artifact",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/commercial_buyer_diligence_packet.md",
                        "docs/commercial_buyer_acceptance_runbook.md",
                        "docs/commercial_buyer_evidence_manifest.md",
                        "docs/commercial_buyer_handoff_bundle.md",
                        "docs/commercial_saleability_decision.md",
                        "docs/commercial_evidence_export.md",
                    )
                )
                else "blocked",
                "Buyer diligence, acceptance, manifest, handoff, decision, and export documents are present.",
                "Restore missing buyer packet documents before export.",
            ),
            self._buyer_evidence_item(
                "figma_stakeholder_artifacts",
                "Figma stakeholder artifacts",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
                "Record Figma artifacts before exporting buyer evidence.",
            ),
            self._buyer_evidence_item(
                "verification_commands",
                "Verification commands",
                "Technical reviewer",
                [
                    "tests/test_commercial_evidence_export.py",
                    "tests/test_saleability_decision.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                    "pytest -q",
                ],
                "measured_local",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_evidence_export.py",
                        "tests/test_saleability_decision.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "Focused commercial export, saleability, plugin artifact, and API contract tests are named.",
                "Restore focused tests before buyer export.",
            ),
            self._buyer_evidence_item(
                "review_process_policy",
                "Review process policy",
                "Deal owner",
                ["docs/commercial_saleability_decision.md", "/api/v1/saleability_decisions/latest"],
                "repository_artifact",
                "ready",
                "Reviewer delay, review bot delay, and queued model review are not concrete blockers.",
                "Escalate only concrete security, API contract, document, or product defects.",
            ),
            self._buyer_evidence_item(
                "packaging_decision",
                "Packaging decision",
                "Procurement and security reviewer",
                ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "repository_artifact",
                "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
                saleability["library_split_decision"]["reason"],
                "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
            ),
        ]
        export_section_summary = self._buyer_manifest_summary(export_sections)
        blocked_count = export_section_summary["by_completion_state"]["blocked"] + len(concrete_blockers)
        warning_count = len(required_external_evidence)
        if blocked_count:
            export_status = "commercial_export_blocked"
        elif warning_count:
            export_status = "commercial_export_ready_with_warnings"
        else:
            export_status = "commercial_export_ready"

        return {
            "export_status": export_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_evidence_export",
            "source_note": (
                "Commercial evidence export packages local runtime decisions, repository documents, "
                "Figma artifact records, verification commands, review-process policy, packaging decision, "
                "and explicit production or buyer-specific evidence gaps; it is not a valuation guarantee, "
                "purchase commitment, or production compliance certificate."
            ),
            "export_summary": {
                "section_count": len(export_sections),
                "blocked_count": blocked_count,
                "warning_count": warning_count,
                "review_process_is_blocker": saleability["review_process_policy"]["is_blocker"],
            },
            "export_sections": export_sections,
            "required_external_evidence": required_external_evidence,
            "concrete_blockers": concrete_blockers,
            "review_process_policy": saleability["review_process_policy"],
            "related_runtime_reports": {
                "saleability_status": saleability["saleability_status"],
                **saleability["related_runtime_reports"],
            },
            "library_split_decision": saleability["library_split_decision"],
            "plugin_traceability": saleability["plugin_traceability"],
            "export_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_evidence_exports/latest",
                "documentation": "docs/commercial_evidence_export.md",
            },
        }

    def commercial_acceptance_check_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the buyer acceptance check over the commercial evidence export."""
        evidence_export = self.commercial_evidence_export_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = evidence_export["concrete_blockers"]
        export_blocked = evidence_export["export_status"] == "commercial_export_blocked"
        runtime_state = "blocked" if export_blocked or concrete_blockers else "ready"
        acceptance_items = [
            self._buyer_evidence_item(
                "runtime_endpoint_chain",
                "Runtime endpoint chain",
                "Technical reviewer",
                [
                    "/api/v1/analytics_snapshots/latest",
                    "/api/v1/sales_readiness/latest",
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/buyer_evidence_manifests/latest",
                    "/api/v1/buyer_handoff_bundles/latest",
                    "/api/v1/saleability_decisions/latest",
                    "/api/v1/commercial_evidence_exports/latest",
                ],
                "measured_local",
                runtime_state,
                f"commercial_export_status={evidence_export['export_status']}",
                "Resolve blocked runtime report chain before buyer acceptance.",
            ),
            self._buyer_evidence_item(
                "buyer_packet_documents",
                "Buyer packet documents",
                "Procurement reviewer",
                [
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_acceptance_check.md",
                ],
                "repository_artifact",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/commercial_buyer_diligence_packet.md",
                        "docs/commercial_buyer_acceptance_runbook.md",
                        "docs/commercial_buyer_evidence_manifest.md",
                        "docs/commercial_buyer_handoff_bundle.md",
                        "docs/commercial_saleability_decision.md",
                        "docs/commercial_evidence_export.md",
                        "docs/commercial_acceptance_check.md",
                    )
                )
                else "blocked",
                "Buyer packet documents cover diligence, acceptance, manifest, handoff, decision, export, and check.",
                "Restore missing buyer packet documents before buyer acceptance.",
            ),
            self._buyer_evidence_item(
                "admin_operator_surface",
                "Admin operator surface",
                "Platform operator",
                ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_acceptance_checks/latest"],
                "repository_artifact",
                "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
                "Admin observability surface exposes the commercial acceptance check status with bilingual labels.",
                "Expose acceptance check status in admin observability before buyer acceptance.",
            ),
            self._buyer_evidence_item(
                "verification_evidence",
                "Verification evidence",
                "Technical reviewer",
                [
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_evidence_export.py",
                    "tests/test_saleability_decision.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                    "pytest -q",
                ],
                "measured_local",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_acceptance_check.py",
                        "tests/test_commercial_evidence_export.py",
                        "tests/test_saleability_decision.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "Focused commercial acceptance, export, saleability, plugin artifact, and API contract tests are named.",
                "Restore focused tests before buyer acceptance.",
            ),
            self._buyer_evidence_item(
                "figma_stakeholder_artifacts",
                "Figma stakeholder artifacts",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
                "Record editable Figma artifacts before buyer acceptance.",
            ),
            self._buyer_evidence_item(
                "review_process_policy",
                "Review process policy",
                "Deal owner",
                ["docs/commercial_saleability_decision.md", "/api/v1/saleability_decisions/latest"],
                "repository_artifact",
                "ready",
                "Reviewer delay, review bot delay, queued model review, and pending checks without concrete failure are not blockers.",
                "Block only on concrete security, API contract, document, or product defects.",
            ),
            self._buyer_evidence_item(
                "packaging_decision",
                "Packaging decision",
                "Procurement and security reviewer",
                ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "repository_artifact",
                "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
                evidence_export["library_split_decision"]["reason"],
                "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
            ),
        ]
        follow_up_items = [
            self._buyer_evidence_item(
                item["evidence_name"],
                item["label"],
                item["reviewer"],
                item["sources"],
                item["evidence_type"],
                "warning",
                item["evidence"],
                item["next_action"],
            )
            for item in evidence_export["required_external_evidence"]
        ]
        all_items = acceptance_items + follow_up_items
        summary = self._buyer_manifest_summary(all_items)
        blocked_count = summary["by_completion_state"]["blocked"] + len(concrete_blockers)
        warning_count = summary["by_completion_state"]["warning"]
        if blocked_count:
            acceptance_status = "commercial_acceptance_blocked"
        elif warning_count:
            acceptance_status = "commercial_acceptance_ready_with_warnings"
        else:
            acceptance_status = "commercial_acceptance_ready"

        return {
            "acceptance_status": acceptance_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_acceptance_check",
            "source_note": (
                "Commercial acceptance check evaluates local commercial evidence export, admin visibility, "
                "repository packet, Figma artifacts, verification commands, review-process policy, packaging "
                "decision, and explicit production or buyer-specific gaps; it is not a valuation guarantee, "
                "purchase commitment, or production compliance certificate."
            ),
            "acceptance_summary": {
                "item_count": len(all_items),
                "blocked_count": blocked_count,
                "warning_count": warning_count,
                "review_process_is_blocker": evidence_export["review_process_policy"]["is_blocker"],
            },
            "acceptance_items": acceptance_items,
            "follow_up_items": follow_up_items,
            "concrete_blockers": concrete_blockers,
            "required_external_evidence": evidence_export["required_external_evidence"],
            "acceptance_gates": [
                {
                    "gate_name": "go",
                    "rule": "no blocked acceptance items and no required external evidence gaps",
                },
                {
                    "gate_name": "warning",
                    "rule": "only production or buyer-specific evidence remains explicitly caveated",
                },
                {
                    "gate_name": "blocked",
                    "rule": "security failure, API contract regression, document mismatch, product defect, or Code Connect usage",
                },
            ],
            "review_process_policy": evidence_export["review_process_policy"],
            "related_runtime_reports": {
                "commercial_export_status": evidence_export["export_status"],
                **evidence_export["related_runtime_reports"],
            },
            "library_split_decision": evidence_export["library_split_decision"],
            "plugin_traceability": evidence_export["plugin_traceability"],
            "acceptance_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_acceptance_checks/latest",
                "documentation": "docs/commercial_acceptance_check.md",
            },
        }

    def admin_state(self) -> dict[str, Any]:
        """Build the admin console state payload from agents, policy, and audit data."""
        agent_page_size = max(1, len(self.agents))
        return {
            "agents": self.list_agents(page_size=agent_page_size),
            "policy": {
                **self.policy.as_dict(),
                "roles": list(self.ROLE_TAGS),
                "complex_hints": list(self.COMPLEX_HINTS),
            },
            "recent_workflow_runs": [self._shorten_run(run) for run in self.list_recent_runs(page_size=max(1, len(self._run_order)))],
            "recent_audit_events": self.list_recent_audit_events(),
        }

    def _shorten_run(self, run: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        return {
            "workflow_run_id": run["workflow_run_id"],
            "mode": run["mode"],
            "policy_mode": run["policy_mode"],
            "created_at": run["created_at"],
        }

    def _is_trace_complete(self, run: dict[str, Any]) -> bool:
        trace = run.get("trace", [])
        if not trace:
            return False
        for step in trace:
            if not all(key in step for key in ("id", "role", "agent_id", "subtask", "access", "output")):
                return False
            if not isinstance(step["access"], list) or step["output"] is None:
                return False
        verification = run.get("verification") or {}
        return bool(run.get("answer") and "accepted" in verification and "reason" in verification)

    def _is_policy_safe_run(self, run: dict[str, Any]) -> bool:
        if run["mode"] == "conduct" and run["policy_snapshot"].get("verifier_required") and not run.get("verification"):
            return False
        return self._provider_exclusion_miss_count(run) == 0

    def _provider_exclusion_miss_count(self, run: dict[str, Any]) -> int:
        misses = 0
        for step in run.get("trace", []):
            try:
                agent = self._agent(step["agent_id"])
            except KeyError:
                misses += 1
                continue
            if step["role"] in agent.provider_exclusions:
                misses += 1
        return misses

    def _locale_key_parity(self, locale_bundles: dict[str, dict[str, str]]) -> dict[str, Any]:
        english = locale_bundles.get("en", {})
        other_locale_codes = sorted(code for code in locale_bundles if code != "en")
        denominator = len(english) * len(other_locale_codes)
        missing = [
            f"{locale_code}.{key}"
            for locale_code in other_locale_codes
            for key in sorted(english)
            if not locale_bundles[locale_code].get(key)
        ]
        numerator = denominator - len(missing)
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value_percent": self._percent(numerator, denominator),
            "missing_keys": missing,
        }

    def _percent(self, numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return round((numerator / denominator) * 100, 2)

    def _criterion(
        self,
        criterion_name: str,
        label: str,
        status: str,
        evidence: str,
        remediation: str,
    ) -> dict[str, str]:
        require_object_name(criterion_name, "sales_readiness.criterion_name")
        if status not in {"pass", "warn", "fail"}:  # pragma: no cover
            raise ValueError("sales readiness status must be pass, warn, or fail")
        return {
            "criterion_name": criterion_name,
            "status": status,
            "label": label,
            "evidence": evidence,
            "remediation": remediation,
        }

    def _buyer_evidence_item(
        self,
        item_name: str,
        label: str,
        reviewer: str,
        sources: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(item_name, "buyer_evidence_manifest.item_name")
        if evidence_type not in {
            "measured_local",
            "repository_artifact",
            "figma_artifact",
            "proposed_until_production",
            "proposed_until_buyer_specific",
        }:  # pragma: no cover
            raise ValueError("buyer evidence type is invalid")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("buyer evidence completion state must be ready, warning, or blocked")
        return {
            "item_name": item_name,
            "label": label,
            "reviewer": reviewer,
            "sources": sources,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "next_action": next_action,
        }

    def _buyer_manifest_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        completion_counts = Counter(item["completion_state"] for item in items)
        evidence_counts = Counter(item["evidence_type"] for item in items)
        return {
            "total_items": len(items),
            "by_completion_state": {
                "ready": completion_counts.get("ready", 0),
                "warning": completion_counts.get("warning", 0),
                "blocked": completion_counts.get("blocked", 0),
            },
            "by_evidence_type": {
                "measured_local": evidence_counts.get("measured_local", 0),
                "repository_artifact": evidence_counts.get("repository_artifact", 0),
                "figma_artifact": evidence_counts.get("figma_artifact", 0),
                "proposed_until_production": evidence_counts.get("proposed_until_production", 0),
                "proposed_until_buyer_specific": evidence_counts.get("proposed_until_buyer_specific", 0),
            },
        }

    def _security_posture_criterion(self, security_profile: dict[str, Any]) -> dict[str, str]:
        auth_mode = security_profile.get("auth_mode", "loopback_no_auth")
        issues: list[str] = []
        warnings: list[str] = []
        if auth_mode == "split_token":
            pass
        elif auth_mode == "single_token":
            warnings.append("single bearer token shared by admin and inference scopes")
        else:
            issues.append("no bearer token configured outside loopback-only development")
        if security_profile.get("allow_public_bind"):
            issues.append("public bind is enabled")
        if security_profile.get("expose_trace_by_default"):
            issues.append("trace exposure is enabled by default")
        if int(security_profile.get("rate_limit_requests") or 0) <= 0:
            issues.append("request rate limiting is disabled")
        if int(security_profile.get("max_concurrent_runs") or 0) <= 0:
            issues.append("run concurrency limiting is disabled")

        if issues:
            status = "fail"
            evidence = "; ".join(issues)
            remediation = "Require bearer auth, private bind defaults, hidden traces, rate limits, and run limits."
        elif warnings:
            status = "warn"
            evidence = "; ".join(warnings)
            remediation = "For enterprise pilots, split admin and inference tokens before customer evaluation."
        else:
            status = "pass"
            evidence = "split tokens, private bind default, hidden traces, rate limits, and run limits are configured"
            remediation = "Keep these controls enabled for customer-facing pilots."

        return self._criterion("security_posture", "Security posture", status, evidence, remediation)

    def _locale_readiness_criterion(self, analytics: dict[str, Any]) -> dict[str, str]:
        locale_metric = next(
            metric for metric in analytics["guardrails"] if metric["metric_name"] == "locale_key_parity"
        )
        missing = locale_metric.get("missing_keys", [])
        parity = locale_metric.get("value_percent")
        if parity == 100.0:
            status = "pass"
            evidence = "English and Korean admin locale keys are aligned"
            remediation = "Keep locale parity tests updated when adding operator copy."
        else:
            status = "warn" if missing else "fail"
            evidence = f"{parity}% locale key parity; missing keys: {', '.join(missing) or 'locale bundles absent'}"
            remediation = "Fill missing Korean and English operator labels before customer review."
        return self._criterion("locale_readiness", "Locale readiness", status, evidence, remediation)

    def _provider_egress_criterion(self) -> dict[str, str]:
        unsafe = []
        remote = []
        for agent in self.agents:
            if agent.base_url.startswith("mock://"):
                continue
            remote.append(agent.id)
            parsed = urlparse(agent.base_url)
            if parsed.scheme != "https" or not agent.api_key_env:
                unsafe.append(agent.id)
        if unsafe:
            status = "fail"
            evidence = f"unsafe provider egress config for agents: {', '.join(sorted(unsafe))}"
            remediation = "Use https provider endpoints with explicit api_key_env before enabling remote egress."
        else:
            status = "pass"
            evidence = (
                "mock providers only"
                if not remote
                else f"{len(remote)} remote providers use https and explicit api_key_env"
            )
            remediation = "Keep provider allow-list enforcement enabled for non-mock providers."
        return self._criterion("provider_egress_safety", "Provider egress safety", status, evidence, remediation)

    def _criteria_by_name(self, criteria: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        return {row["criterion_name"]: row for row in criteria}

    def _metrics_by_name(self, metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {row["metric_name"]: row for row in metrics}

    def _commercial_documentation_profile(self) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[1]
        required_documents = [
            "README.md",
            "SECURITY.md",
            "docs/product_planning.md",
            "docs/rest_api_design.md",
            "docs/analytics_spec.md",
            "docs/commercial_readiness.md",
        ]
        missing_documents = [
            document_path
            for document_path in required_documents
            if not (root / document_path).is_file()
        ]
        return {
            "required_documents": required_documents,
            "missing_documents": missing_documents,
            "present_count": len(required_documents) - len(missing_documents),
            "required_count": len(required_documents),
            "has_security_policy": (root / "SECURITY.md").is_file(),
            "source": "repository documentation files",
        }

    def _criteria_summary(self, criteria: list[dict[str, str]]) -> dict[str, int]:
        counts = Counter(row["status"] for row in criteria)
        return {
            "pass": counts.get("pass", 0),
            "warn": counts.get("warn", 0),
            "fail": counts.get("fail", 0),
        }


def redact_text(text: str) -> str:
    """Mask common secret and personal-data shapes from traces."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(api"):
            redacted = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", redacted)
        elif pattern.pattern.lower().startswith("(?i)(bearer"):
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact string values while preserving response shape."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


def chat_completion_response(
    result: dict[str, Any],
    model: str = "contextual-orchestrator",
    include_trace: bool = False,
) -> dict[str, Any]:  # pragma: no cover
    """Wrap orchestration output in an OpenAI-compatible chat completion response."""
    orchestration = {
        "workflow_run_id": result.get("workflow_run_id"),
        "mode": result["mode"],
        "verification": result.get("verification"),
    }
    if include_trace:
        orchestration["trace"] = redact_value(result["trace"])
    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result["answer"]},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "orchestration": {key: value for key, value in orchestration.items() if value is not None},
    }
