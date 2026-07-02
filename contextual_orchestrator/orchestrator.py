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

    def commercial_release_candidate_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the local buyer-facing commercial release-candidate manifest."""
        acceptance = self.commercial_acceptance_check_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = acceptance["concrete_blockers"]
        acceptance_blocked = acceptance["acceptance_status"] == "commercial_acceptance_blocked"
        runtime_state = "blocked" if acceptance_blocked or concrete_blockers else "ready"
        release_artifacts = [
            self._buyer_evidence_item(
                "commercial_acceptance_check",
                "Commercial acceptance check",
                "Deal owner",
                ["/api/v1/commercial_acceptance_checks/latest", "docs/commercial_acceptance_check.md"],
                "measured_local",
                runtime_state,
                f"acceptance_status={acceptance['acceptance_status']}",
                "Resolve blocked acceptance checks before tagging a release candidate.",
            ),
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
                    "/api/v1/commercial_acceptance_checks/latest",
                    "/api/v1/commercial_release_candidates/latest",
                ],
                "measured_local",
                runtime_state,
                "Commercial release candidate endpoint is chained after acceptance, export, decision, handoff, manifest, readiness, and analytics reports.",
                "Restore blocked runtime endpoint evidence before release-candidate handoff.",
            ),
            self._buyer_evidence_item(
                "repository_distribution_packet",
                "Repository distribution packet",
                "Procurement reviewer",
                [
                    "README.md",
                    "docs/rest_api_design.md",
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_acceptance_check.md",
                    "docs/commercial_release_candidate.md",
                ],
                "repository_artifact",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/rest_api_design.md",
                        "docs/commercial_buyer_diligence_packet.md",
                        "docs/commercial_buyer_acceptance_runbook.md",
                        "docs/commercial_buyer_evidence_manifest.md",
                        "docs/commercial_buyer_handoff_bundle.md",
                        "docs/commercial_saleability_decision.md",
                        "docs/commercial_evidence_export.md",
                        "docs/commercial_acceptance_check.md",
                        "docs/commercial_release_candidate.md",
                    )
                )
                else "blocked",
                "Repository packet contains the README, REST API contract notes, and commercial buyer documents.",
                "Restore missing distribution documents before buyer release-candidate review.",
            ),
            self._buyer_evidence_item(
                "security_package_metadata",
                "Security and package metadata",
                "Security reviewer",
                [
                    "LICENSE",
                    "SECURITY.md",
                    "pyproject.toml",
                    "requirements.lock",
                    ".github/workflows/security.yml",
                    ".github/workflows/scorecard-analysis.yml",
                ],
                "repository_artifact",
                "ready"
                if all(
                    has_file(path)
                    for path in (
                        "LICENSE",
                        "SECURITY.md",
                        "pyproject.toml",
                        "requirements.lock",
                        ".github/workflows/security.yml",
                        ".github/workflows/scorecard-analysis.yml",
                    )
                )
                else "blocked",
                "License, security policy, package metadata, locked requirements, and security workflows are present.",
                "Restore missing security or package metadata before release-candidate handoff.",
            ),
            self._buyer_evidence_item(
                "admin_operator_surface",
                "Admin operator surface",
                "Platform operator",
                ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_release_candidates/latest"],
                "repository_artifact",
                "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
                "Admin observability surface exposes the release-candidate status with bilingual labels.",
                "Expose release-candidate status in admin observability before buyer handoff.",
            ),
            self._buyer_evidence_item(
                "verification_evidence",
                "Verification evidence",
                "Technical reviewer",
                [
                    "tests/test_commercial_release_candidate.py",
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
                        "tests/test_commercial_release_candidate.py",
                        "tests/test_commercial_acceptance_check.py",
                        "tests/test_commercial_evidence_export.py",
                        "tests/test_saleability_decision.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "Focused release-candidate, acceptance, export, saleability, plugin artifact, and API contract tests are named.",
                "Restore focused verification before release-candidate handoff.",
            ),
            self._buyer_evidence_item(
                "figma_stakeholder_artifacts",
                "Figma stakeholder artifacts",
                "Stakeholder reviewer",
                ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
                "figma_artifact",
                "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
                "Record editable Figma artifacts before buyer release-candidate review.",
            ),
            self._buyer_evidence_item(
                "review_process_policy",
                "Review process policy",
                "Deal owner",
                ["docs/commercial_saleability_decision.md", "docs/commercial_release_candidate.md"],
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
                acceptance["library_split_decision"]["reason"],
                "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
            ),
        ]
        external_release_gaps = [
            self._buyer_evidence_item(
                item["item_name"],
                item["label"],
                item["reviewer"],
                item["sources"],
                item["evidence_type"],
                "warning",
                item["evidence"],
                item["next_action"],
            )
            for item in acceptance["follow_up_items"]
        ]
        summary = self._buyer_manifest_summary(release_artifacts + external_release_gaps)
        blocked_count = summary["by_completion_state"]["blocked"] + len(concrete_blockers)
        warning_count = summary["by_completion_state"]["warning"]
        if blocked_count:
            release_status = "commercial_release_blocked"
        elif warning_count:
            release_status = "commercial_release_ready_with_warnings"
        else:
            release_status = "commercial_release_ready"

        return {
            "release_status": release_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_release_candidate",
            "source_note": (
                "Commercial release candidate packages local acceptance, runtime endpoints, repository "
                "distribution documents, security metadata, admin visibility, verification commands, "
                "Figma artifact records, review-process policy, packaging decision, and explicit external "
                "release gaps; it is not a valuation guarantee, purchase commitment, or production "
                "compliance certificate."
            ),
            "release_summary": {
                "artifact_count": len(release_artifacts),
                "blocked_count": blocked_count,
                "warning_count": warning_count,
                "review_process_is_blocker": acceptance["review_process_policy"]["is_blocker"],
            },
            "release_artifacts": release_artifacts,
            "external_release_gaps": external_release_gaps,
            "concrete_blockers": concrete_blockers,
            "release_gates": [
                {
                    "gate_name": "package",
                    "rule": "runtime endpoint chain, repository packet, security metadata, admin surface, tests, Figma artifacts, review policy, and packaging decision are present",
                },
                {
                    "gate_name": "warning",
                    "rule": "only production or buyer-specific external evidence remains explicitly caveated",
                },
                {
                    "gate_name": "blocked",
                    "rule": "security failure, API contract regression, missing distribution artifact, document mismatch, product defect, or Code Connect usage",
                },
            ],
            "review_process_policy": acceptance["review_process_policy"],
            "related_runtime_reports": {
                "commercial_acceptance_status": acceptance["acceptance_status"],
                **acceptance["related_runtime_reports"],
            },
            "library_split_decision": acceptance["library_split_decision"],
            "plugin_traceability": acceptance["plugin_traceability"],
            "release_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_release_candidates/latest",
                "documentation": "docs/commercial_release_candidate.md",
            },
        }

    def commercial_gap_register_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an owner/action register for commercial release-candidate gaps."""
        release = self.commercial_release_candidate_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        concrete_blockers = release["concrete_blockers"]
        release_blocked = release["release_status"] == "commercial_release_blocked"
        gap_items = []
        for item in release["external_release_gaps"]:
            source_type = item["evidence_type"]
            if source_type == "proposed_until_production":
                gap_status = "production_input_required"
                gap_type = "production_evidence_gap"
                owner = "Operations and support owner"
            else:
                gap_status = "buyer_input_required"
                gap_type = "buyer_specific_gap"
                owner = "Buyer and deal owner"
            gap_items.append({
                "gap_name": item["item_name"],
                "label": item["label"],
                "gap_type": gap_type,
                "gap_status": gap_status,
                "owner": owner,
                "reviewer": item["reviewer"],
                "sources": item["sources"],
                "source_evidence_type": source_type,
                "current_evidence": item["evidence"],
                "required_input": item["next_action"],
                "is_blocker": False,
            })

        blocked_count = len(concrete_blockers) + (1 if release_blocked else 0)
        if blocked_count:
            gap_register_status = "commercial_gap_register_blocked"
        elif gap_items:
            gap_register_status = "commercial_gap_register_open"
        else:
            gap_register_status = "commercial_gap_register_clear"

        production_gap_count = sum(1 for item in gap_items if item["gap_type"] == "production_evidence_gap")
        buyer_specific_gap_count = sum(1 for item in gap_items if item["gap_type"] == "buyer_specific_gap")
        return {
            "gap_register_status": gap_register_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_gap_register",
            "source_note": (
                "Commercial gap register converts local release-candidate warning gaps into owner, action, "
                "source, and required-input rows for buyer due diligence; it is not a valuation guarantee, "
                "purchase commitment, or production compliance certificate."
            ),
            "gap_summary": {
                "total_gap_count": len(gap_items),
                "production_gap_count": production_gap_count,
                "buyer_specific_gap_count": buyer_specific_gap_count,
                "blocked_count": blocked_count,
                "review_process_is_blocker": release["review_process_policy"]["is_blocker"],
            },
            "gap_items": gap_items,
            "concrete_blockers": concrete_blockers,
            "gap_status_rules": [
                {
                    "gap_status": "production_input_required",
                    "rule": "production deployment, support, SLO, or operational evidence must be supplied before production claim",
                },
                {
                    "gap_status": "buyer_input_required",
                    "rule": "buyer-specific legal, procurement, ROI, or deployment context must be supplied before buyer-specific claim",
                },
                {
                    "gap_status": "blocked",
                    "rule": "concrete security, API contract, document, product defect, or Code Connect usage blocks commercial release",
                },
            ],
            "review_process_policy": release["review_process_policy"],
            "related_runtime_reports": {
                "commercial_release_status": release["release_status"],
                **release["related_runtime_reports"],
            },
            "library_split_decision": release["library_split_decision"],
            "plugin_traceability": release["plugin_traceability"],
            "gap_register_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_gap_registers/latest",
                "documentation": "docs/commercial_gap_register.md",
            },
        }

    def commercial_procurement_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a procurement/legal readiness gate over commercial evidence."""
        gap_register = self.commercial_gap_register_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        gap_by_status = {item["gap_status"]: item for item in gap_register["gap_items"]}
        production_gap = gap_by_status.get("production_input_required")
        buyer_gap = gap_by_status.get("buyer_input_required")
        concrete_blockers = gap_register["concrete_blockers"]
        procurement_items = [
            {
                "item_name": "license_and_rights",
                "label": "License and rights",
                "owner": "Procurement reviewer",
                "sources": ["LICENSE", "pyproject.toml"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready" if has_file("LICENSE") and has_file("pyproject.toml") else "blocked",
                "evidence": "MIT license and package metadata are present for buyer rights review.",
                "required_input": "Restore license or package metadata before procurement review.",
            },
            {
                "item_name": "security_package_metadata",
                "label": "Security package metadata",
                "owner": "Security reviewer",
                "sources": ["SECURITY.md", "requirements.lock", ".github/workflows/security.yml", ".github/workflows/scorecard-analysis.yml"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "SECURITY.md",
                        "requirements.lock",
                        ".github/workflows/security.yml",
                        ".github/workflows/scorecard-analysis.yml",
                    )
                )
                else "blocked",
                "evidence": "Security policy, locked dependencies, and security workflows are present.",
                "required_input": "Restore missing security metadata before procurement review.",
            },
            {
                "item_name": "distribution_packet",
                "label": "Distribution packet",
                "owner": "Deal owner",
                "sources": [
                    "README.md",
                    "docs/rest_api_design.md",
                    "docs/commercial_release_candidate.md",
                    "docs/commercial_gap_register.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/rest_api_design.md",
                        "docs/commercial_release_candidate.md",
                        "docs/commercial_gap_register.md",
                    )
                )
                else "blocked",
                "evidence": "Repository overview, REST contract, release candidate, and gap register documents are present.",
                "required_input": "Restore missing distribution documents before procurement review.",
            },
            {
                "item_name": "admin_evidence_surface",
                "label": "Admin evidence surface",
                "owner": "Platform operator",
                "sources": ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_procurement_readiness/latest"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
                "evidence": "Admin observability surface exposes procurement readiness with bilingual labels.",
                "required_input": "Expose procurement readiness in admin observability before buyer review.",
            },
            {
                "item_name": "production_support_slo_input",
                "label": "Production support and SLO input",
                "owner": production_gap["owner"] if production_gap else "Operations and support owner",
                "sources": production_gap["sources"] if production_gap else ["docs/commercial_gap_register.md"],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning" if production_gap else "ready",
                "source_gap_status": production_gap["gap_status"] if production_gap else "resolved",
                "evidence": production_gap["current_evidence"] if production_gap else "No production evidence gap is open.",
                "required_input": production_gap["required_input"] if production_gap else "No production input required.",
            },
            {
                "item_name": "buyer_legal_roi_procurement_input",
                "label": "Buyer legal, ROI, and procurement input",
                "owner": buyer_gap["owner"] if buyer_gap else "Buyer and deal owner",
                "sources": buyer_gap["sources"] if buyer_gap else ["docs/commercial_gap_register.md"],
                "evidence_type": "proposed_until_buyer_specific",
                "completion_state": "warning" if buyer_gap else "ready",
                "source_gap_status": buyer_gap["gap_status"] if buyer_gap else "resolved",
                "evidence": buyer_gap["current_evidence"] if buyer_gap else "No buyer-specific evidence gap is open.",
                "required_input": buyer_gap["required_input"] if buyer_gap else "No buyer input required.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_procurement_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Reviewer delay, review bot delay, queued model review, and pending checks without concrete failure are not blockers.",
                "required_input": "Block only on concrete security, API contract, document, or product defects.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
                "evidence": gap_register["library_split_decision"]["reason"],
                "required_input": "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in procurement_items)
        production_gap_count = 1 if production_gap else 0
        buyer_specific_gap_count = 1 if buyer_gap else 0
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            procurement_status = "commercial_procurement_blocked"
        elif warning_count:
            procurement_status = "commercial_procurement_ready_with_warnings"
        else:
            procurement_status = "commercial_procurement_ready"

        return {
            "procurement_status": procurement_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_procurement_readiness",
            "source_note": (
                "Commercial procurement readiness packages local license, security, distribution, admin, "
                "gap-register, review-process, and packaging evidence for buyer due diligence; it is not "
                "a valuation guarantee, purchase commitment, or production compliance certificate."
            ),
            "procurement_summary": {
                "item_count": len(procurement_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "production_gap_count": production_gap_count,
                "buyer_specific_gap_count": buyer_specific_gap_count,
                "review_process_is_blocker": gap_register["review_process_policy"]["is_blocker"],
            },
            "procurement_items": procurement_items,
            "concrete_blockers": concrete_blockers,
            "procurement_status_rules": [
                {
                    "procurement_status": "commercial_procurement_ready",
                    "rule": "license, security, distribution, admin, support, legal, ROI, review, and packaging evidence are ready",
                },
                {
                    "procurement_status": "commercial_procurement_ready_with_warnings",
                    "rule": "local packet is ready while production or buyer-specific inputs remain explicit warnings",
                },
                {
                    "procurement_status": "commercial_procurement_blocked",
                    "rule": "missing packet evidence, concrete product defect, API contract failure, security failure, or Code Connect usage blocks procurement",
                },
            ],
            "review_process_policy": gap_register["review_process_policy"],
            "related_runtime_reports": {
                "commercial_gap_register_status": gap_register["gap_register_status"],
                **gap_register["related_runtime_reports"],
            },
            "library_split_decision": gap_register["library_split_decision"],
            "plugin_traceability": gap_register["plugin_traceability"],
            "procurement_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_procurement_readiness/latest",
                "documentation": "docs/commercial_procurement_readiness.md",
            },
        }

    def commercial_contract_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a contract-readiness gate over procurement evidence."""
        procurement = self.commercial_procurement_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        procurement_by_name = {item["item_name"]: item for item in procurement["procurement_items"]}
        license_item = procurement_by_name["license_and_rights"]
        security_item = procurement_by_name["security_package_metadata"]
        support_item = procurement_by_name["production_support_slo_input"]
        buyer_item = procurement_by_name["buyer_legal_roi_procurement_input"]
        packaging_item = procurement_by_name["packaging_decision"]
        concrete_blockers = procurement["concrete_blockers"]
        support_slo_gap_count = 1 if support_item["completion_state"] == "warning" else 0
        buyer_order_form_gap_count = 1 if buyer_item["completion_state"] == "warning" else 0
        contract_items = [
            {
                "item_name": "license_commercial_rights",
                "label": "License and commercial rights terms",
                "owner": "Legal reviewer",
                "sources": license_item["sources"],
                "evidence_type": license_item["evidence_type"],
                "completion_state": license_item["completion_state"],
                "evidence": license_item["evidence"],
                "required_input": license_item["required_input"],
            },
            {
                "item_name": "security_privacy_terms",
                "label": "Security and privacy terms",
                "owner": "Security and legal reviewer",
                "sources": [*security_item["sources"], "docs/commercial_procurement_readiness.md"],
                "evidence_type": security_item["evidence_type"],
                "completion_state": security_item["completion_state"],
                "evidence": (
                    f"{security_item['evidence']} Runtime readiness profile uses "
                    f"auth_mode={security_profile.get('auth_mode', 'unknown') if security_profile else 'unknown'}, "
                    f"public_bind={security_profile.get('allow_public_bind', 'unknown') if security_profile else 'unknown'}, "
                    "and trace exposure controls."
                ),
                "required_input": security_item["required_input"],
            },
            {
                "item_name": "audit_export_obligations",
                "label": "Audit and export obligations",
                "owner": "Compliance reviewer",
                "sources": [
                    "/api/v1/commercial_evidence_exports/latest",
                    "docs/commercial_evidence_export.md",
                    "docs/rest_api_design.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/commercial_evidence_export.md",
                        "docs/rest_api_design.md",
                    )
                )
                else "blocked",
                "evidence": "Commercial evidence export and REST API contract describe buyer-readable audit evidence.",
                "required_input": "Restore evidence export docs and REST contract before contract review.",
            },
            {
                "item_name": "contract_packet_docs",
                "label": "Contract packet documents",
                "owner": "Deal owner",
                "sources": [
                    "README.md",
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_saleability_decision.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/commercial_contract_readiness.md",
                        "docs/commercial_procurement_readiness.md",
                        "docs/commercial_saleability_decision.md",
                    )
                )
                else "blocked",
                "evidence": "Contract packet, procurement gate, and saleability blocker policy are documented.",
                "required_input": "Restore buyer contract packet docs before legal review.",
            },
            {
                "item_name": "support_slo_terms",
                "label": "Support and SLO terms",
                "owner": support_item["owner"],
                "sources": support_item["sources"],
                "evidence_type": support_item["evidence_type"],
                "completion_state": support_item["completion_state"],
                "source_gap_status": support_item.get("source_gap_status", "resolved"),
                "evidence": support_item["evidence"],
                "required_input": support_item["required_input"],
            },
            {
                "item_name": "buyer_order_form_input",
                "label": "Buyer order-form input",
                "owner": buyer_item["owner"],
                "sources": buyer_item["sources"],
                "evidence_type": buyer_item["evidence_type"],
                "completion_state": buyer_item["completion_state"],
                "source_gap_status": buyer_item.get("source_gap_status", "resolved"),
                "evidence": buyer_item["evidence"],
                "required_input": buyer_item["required_input"],
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_contract_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a contract blocker unless a concrete failure is produced.",
                "required_input": "Block only on concrete security, API contract, document, or product defects.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": packaging_item["owner"],
                "sources": packaging_item["sources"],
                "evidence_type": packaging_item["evidence_type"],
                "completion_state": packaging_item["completion_state"],
                "evidence": packaging_item["evidence"],
                "required_input": packaging_item["required_input"],
            },
        ]
        state_counts = Counter(item["completion_state"] for item in contract_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            contract_status = "commercial_contract_blocked"
        elif warning_count:
            contract_status = "commercial_contract_ready_with_warnings"
        else:
            contract_status = "commercial_contract_ready"

        return {
            "contract_status": contract_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_contract_readiness",
            "source_note": (
                "Commercial contract readiness packages local license, security/privacy, audit export, "
                "support/SLO, buyer order-form, review-process, and packaging evidence for legal and "
                "procurement due diligence; it is not a valuation guarantee, purchase commitment, or "
                "production compliance certificate."
            ),
            "contract_summary": {
                "item_count": len(contract_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "support_slo_gap_count": support_slo_gap_count,
                "buyer_order_form_gap_count": buyer_order_form_gap_count,
                "review_process_is_blocker": procurement["review_process_policy"]["is_blocker"],
            },
            "contract_items": contract_items,
            "concrete_blockers": concrete_blockers,
            "contract_status_rules": [
                {
                    "contract_status": "commercial_contract_ready",
                    "rule": "license, security/privacy, audit/export, support/SLO, buyer order-form, review, and packaging terms are ready",
                },
                {
                    "contract_status": "commercial_contract_ready_with_warnings",
                    "rule": "local contract packet is ready while production support/SLO or buyer order-form inputs remain explicit warnings",
                },
                {
                    "contract_status": "commercial_contract_blocked",
                    "rule": "missing contract packet evidence, concrete product defect, API contract failure, security failure, or Code Connect usage blocks contract readiness",
                },
            ],
            "review_process_policy": procurement["review_process_policy"],
            "related_runtime_reports": {
                "commercial_procurement_status": procurement["procurement_status"],
                **procurement["related_runtime_reports"],
            },
            "library_split_decision": procurement["library_split_decision"],
            "plugin_traceability": procurement["plugin_traceability"],
            "contract_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_contract_readiness/latest",
                "documentation": "docs/commercial_contract_readiness.md",
            },
        }

    def commercial_onboarding_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a paid-onboarding readiness gate over contract evidence."""
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        contract_by_name = {item["item_name"]: item for item in contract["contract_items"]}
        support_item = contract_by_name["support_slo_terms"]
        buyer_item = contract_by_name["buyer_order_form_input"]
        packaging_item = contract_by_name["packaging_decision"]
        concrete_blockers = contract["concrete_blockers"]
        support_slo_action_count = 1 if support_item["completion_state"] == "warning" else 0
        buyer_input_action_count = 1 if buyer_item["completion_state"] == "warning" else 0
        onboarding_items = [
            {
                "item_name": "buyer_kickoff_packet",
                "label": "Buyer kickoff packet",
                "owner": "Deal owner",
                "sources": [
                    "README.md",
                    "docs/commercial_onboarding_readiness.md",
                    "docs/commercial_contract_readiness.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/commercial_onboarding_readiness.md",
                        "docs/commercial_contract_readiness.md",
                    )
                )
                else "blocked",
                "evidence": "Buyer kickoff packet connects product overview, contract readiness, and onboarding plan.",
                "action": "Use the packet to start paid onboarding with named buyer stakeholders.",
                "exit_criteria": "Buyer confirms kickoff owner, onboarding dates, and evidence review cadence.",
            },
            {
                "item_name": "support_slo_kickoff",
                "label": "Support and SLO kickoff",
                "owner": support_item["owner"],
                "sources": support_item["sources"],
                "evidence_type": support_item["evidence_type"],
                "completion_state": support_item["completion_state"],
                "source_gap_status": support_item.get("source_gap_status", "resolved"),
                "evidence": support_item["evidence"],
                "action": "Collect support rota, escalation path, SLO target, and incident drill evidence during paid onboarding.",
                "exit_criteria": "Buyer and operator approve support owner, response target, escalation path, and first incident drill record.",
            },
            {
                "item_name": "buyer_order_form_kickoff",
                "label": "Buyer order-form kickoff",
                "owner": buyer_item["owner"],
                "sources": buyer_item["sources"],
                "evidence_type": buyer_item["evidence_type"],
                "completion_state": buyer_item["completion_state"],
                "source_gap_status": buyer_item.get("source_gap_status", "resolved"),
                "evidence": buyer_item["evidence"],
                "action": "Collect buyer order-form, ROI, legal questionnaire, deployment, and support inputs.",
                "exit_criteria": "Buyer-specific order form and legal/procurement inputs are attached to the diligence packet.",
            },
            {
                "item_name": "telemetry_capture_plan",
                "label": "Telemetry capture plan",
                "owner": "Data analytics owner",
                "sources": ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready" if has_file("docs/analytics_spec.md") else "blocked",
                "evidence": "Analytics spec separates measured local evidence from proposed production metrics.",
                "action": "Capture production onboarding telemetry without mixing it with local prototype metrics.",
                "exit_criteria": "First buyer environment records adoption, latency, verification, trace completeness, and support events.",
            },
            {
                "item_name": "acceptance_exit_criteria",
                "label": "Acceptance exit criteria",
                "owner": "Technical buyer reviewer",
                "sources": [
                    "/api/v1/commercial_acceptance_checks/latest",
                    "docs/commercial_acceptance_check.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if has_file("docs/commercial_acceptance_check.md")
                and has_file("docs/commercial_buyer_acceptance_runbook.md")
                else "blocked",
                "evidence": "Acceptance check and buyer runbook define go/no-go review gates.",
                "action": "Run the buyer acceptance checklist after kickoff evidence is attached.",
                "exit_criteria": "Acceptance check has no concrete blockers and warnings are explicitly owned.",
            },
            {
                "item_name": "security_legal_handoff",
                "label": "Security and legal handoff",
                "owner": "Security and legal reviewer",
                "sources": ["SECURITY.md", "docs/commercial_contract_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if has_file("SECURITY.md") and has_file("docs/commercial_contract_readiness.md")
                else "blocked",
                "evidence": "Security policy and contract readiness packet are available for buyer handoff.",
                "action": "Attach security policy, dependency lock, and contract readiness rows to buyer diligence.",
                "exit_criteria": "Buyer security/legal reviewer accepts the packet or opens concrete findings.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_onboarding_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review delay is not an onboarding blocker unless a concrete failure is produced.",
                "action": "Continue onboarding work while queued reviews are pending.",
                "exit_criteria": "Only concrete security, API contract, document, or product defects block progress.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": packaging_item["owner"],
                "sources": packaging_item["sources"],
                "evidence_type": packaging_item["evidence_type"],
                "completion_state": packaging_item["completion_state"],
                "evidence": packaging_item["evidence"],
                "action": "Keep one deployable enterprise control-plane product through onboarding.",
                "exit_criteria": "Extract only after a second product, independent release cadence, or buyer provenance trigger exists.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in onboarding_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            onboarding_status = "commercial_onboarding_blocked"
        elif warning_count:
            onboarding_status = "commercial_onboarding_ready_with_warnings"
        else:
            onboarding_status = "commercial_onboarding_ready"

        return {
            "onboarding_status": onboarding_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_onboarding_readiness",
            "source_note": (
                "Commercial onboarding readiness converts local contract and procurement warnings into "
                "paid-onboarding owners, actions, and exit criteria; it is not a valuation guarantee, "
                "purchase commitment, or production compliance certificate."
            ),
            "onboarding_summary": {
                "item_count": len(onboarding_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "support_slo_action_count": support_slo_action_count,
                "buyer_input_action_count": buyer_input_action_count,
                "review_process_is_blocker": contract["review_process_policy"]["is_blocker"],
            },
            "onboarding_items": onboarding_items,
            "concrete_blockers": concrete_blockers,
            "onboarding_status_rules": [
                {
                    "onboarding_status": "commercial_onboarding_ready",
                    "rule": "kickoff packet, support/SLO, buyer input, telemetry, acceptance, security/legal, review, and packaging actions are ready",
                },
                {
                    "onboarding_status": "commercial_onboarding_ready_with_warnings",
                    "rule": "local onboarding plan is ready while production support/SLO or buyer order-form actions remain explicit warnings",
                },
                {
                    "onboarding_status": "commercial_onboarding_blocked",
                    "rule": "missing onboarding packet evidence, concrete product defect, API contract failure, security failure, or Code Connect usage blocks onboarding",
                },
            ],
            "review_process_policy": contract["review_process_policy"],
            "related_runtime_reports": {
                "commercial_contract_status": contract["contract_status"],
                **contract["related_runtime_reports"],
            },
            "library_split_decision": contract["library_split_decision"],
            "plugin_traceability": contract["plugin_traceability"],
            "onboarding_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_onboarding_readiness/latest",
                "documentation": "docs/commercial_onboarding_readiness.md",
            },
        }

    def commercial_operations_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an operations-handoff readiness gate over onboarding evidence."""
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        onboarding_by_name = {item["item_name"]: item for item in onboarding["onboarding_items"]}
        support_item = onboarding_by_name["support_slo_kickoff"]
        telemetry_item = onboarding_by_name["telemetry_capture_plan"]
        acceptance_item = onboarding_by_name["acceptance_exit_criteria"]
        security_item = onboarding_by_name["security_legal_handoff"]
        packaging_item = onboarding_by_name["packaging_decision"]
        concrete_blockers = onboarding["concrete_blockers"]
        operations_items = [
            {
                "item_name": "deployment_runbook",
                "label": "Deployment runbook",
                "owner": "Platform operator",
                "sources": [
                    "README.md",
                    "docs/commercial_operations_readiness.md",
                    "docs/commercial_onboarding_readiness.md",
                    "docs/rest_api_design.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "docs/commercial_operations_readiness.md",
                        "docs/commercial_onboarding_readiness.md",
                        "docs/rest_api_design.md",
                    )
                )
                else "blocked",
                "evidence": "Repository overview, REST contract, onboarding plan, and operations handoff plan are present.",
                "action": "Use existing stdlib server and documented endpoints for buyer operations handoff.",
                "exit_criteria": "Buyer operator can start, authenticate, inspect readiness endpoints, and run verification commands.",
            },
            {
                "item_name": "monitoring_telemetry_capture",
                "label": "Monitoring and telemetry capture",
                "owner": telemetry_item["owner"],
                "sources": telemetry_item["sources"],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning",
                "source_gap_status": "production_input_required",
                "evidence": telemetry_item["evidence"],
                "action": "Capture adoption, latency, verifier outcomes, trace completeness, support events, and deployment health in the buyer environment.",
                "exit_criteria": "First production telemetry snapshot is attached without mixing it with local prototype metrics.",
            },
            {
                "item_name": "incident_rollback_plan",
                "label": "Incident and rollback plan",
                "owner": "Operations and support owner",
                "sources": ["docs/commercial_onboarding_readiness.md", "docs/commercial_buyer_acceptance_runbook.md"],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning",
                "source_gap_status": "production_input_required",
                "evidence": "Incident drill and rollback proof require a buyer deployment or paid onboarding environment.",
                "action": "Run the first incident drill and rollback exercise during onboarding.",
                "exit_criteria": "Incident owner, escalation path, rollback steps, and drill record are attached.",
            },
            {
                "item_name": "backup_recovery_plan",
                "label": "Backup and recovery evidence",
                "owner": "Operations and data owner",
                "sources": ["docs/commercial_onboarding_readiness.md", "docs/commercial_buyer_diligence_packet.md"],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning",
                "source_gap_status": "production_input_required",
                "evidence": "Backup and recovery evidence depends on the buyer deployment topology and persistence choices.",
                "action": "Define backup scope, retention, restore owner, and first restore proof during onboarding.",
                "exit_criteria": "Buyer accepts backup scope and a restore proof is attached or explicitly waived.",
            },
            {
                "item_name": "support_slo_ownership",
                "label": "Support rota and SLO ownership",
                "owner": support_item["owner"],
                "sources": support_item["sources"],
                "evidence_type": support_item["evidence_type"],
                "completion_state": support_item["completion_state"],
                "source_gap_status": support_item.get("source_gap_status", "resolved"),
                "evidence": support_item["evidence"],
                "action": support_item["action"],
                "exit_criteria": support_item["exit_criteria"],
            },
            {
                "item_name": "acceptance_handoff",
                "label": "Acceptance handoff",
                "owner": acceptance_item["owner"],
                "sources": acceptance_item["sources"],
                "evidence_type": acceptance_item["evidence_type"],
                "completion_state": acceptance_item["completion_state"],
                "evidence": acceptance_item["evidence"],
                "action": acceptance_item["action"],
                "exit_criteria": acceptance_item["exit_criteria"],
            },
            {
                "item_name": "security_legal_handoff",
                "label": "Security and legal handoff",
                "owner": security_item["owner"],
                "sources": security_item["sources"],
                "evidence_type": security_item["evidence_type"],
                "completion_state": security_item["completion_state"],
                "evidence": security_item["evidence"],
                "action": security_item["action"],
                "exit_criteria": security_item["exit_criteria"],
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_operations_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review delay is not an operations blocker unless a concrete failure is produced.",
                "action": "Continue operations handoff work while queued reviews are pending.",
                "exit_criteria": "Only concrete security, API contract, document, or product defects block progress.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": packaging_item["owner"],
                "sources": packaging_item["sources"],
                "evidence_type": packaging_item["evidence_type"],
                "completion_state": packaging_item["completion_state"],
                "evidence": packaging_item["evidence"],
                "action": packaging_item["action"],
                "exit_criteria": packaging_item["exit_criteria"],
            },
        ]
        state_counts = Counter(item["completion_state"] for item in operations_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        production_evidence_action_count = sum(
            1 for item in operations_items if item.get("source_gap_status") == "production_input_required"
        )
        if blocked_count:
            operations_status = "commercial_operations_blocked"
        elif warning_count:
            operations_status = "commercial_operations_ready_with_warnings"
        else:
            operations_status = "commercial_operations_ready"

        return {
            "operations_status": operations_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_operations_readiness",
            "source_note": (
                "Commercial operations readiness converts local onboarding evidence and production "
                "operations gaps into handoff owners, actions, and exit criteria; it is not a valuation "
                "guarantee, purchase commitment, or production compliance certificate."
            ),
            "operations_summary": {
                "item_count": len(operations_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "production_evidence_action_count": production_evidence_action_count,
                "review_process_is_blocker": onboarding["review_process_policy"]["is_blocker"],
            },
            "operations_items": operations_items,
            "concrete_blockers": concrete_blockers,
            "operations_status_rules": [
                {
                    "operations_status": "commercial_operations_ready",
                    "rule": "deployment, monitoring, incident, backup, support, acceptance, security/legal, review, and packaging evidence are ready",
                },
                {
                    "operations_status": "commercial_operations_ready_with_warnings",
                    "rule": "local operations plan is ready while production telemetry, incident, backup, or SLO evidence remains explicit warnings",
                },
                {
                    "operations_status": "commercial_operations_blocked",
                    "rule": "missing operations packet evidence, concrete product defect, API contract failure, security failure, or Code Connect usage blocks operations handoff",
                },
            ],
            "review_process_policy": onboarding["review_process_policy"],
            "related_runtime_reports": {
                "commercial_onboarding_status": onboarding["onboarding_status"],
                **onboarding["related_runtime_reports"],
            },
            "library_split_decision": onboarding["library_split_decision"],
            "plugin_traceability": onboarding["plugin_traceability"],
            "operations_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_operations_readiness/latest",
                "documentation": "docs/commercial_operations_readiness.md",
            },
        }

    def commercial_security_attestation_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a buyer security-review attestation gate over operations evidence."""
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        operations_by_name = {item["item_name"]: item for item in operations["operations_items"]}
        runtime_profile = security_profile or {}
        concrete_blockers = operations["concrete_blockers"]
        security_attestation_items = [
            {
                "item_name": "security_policy",
                "label": "Security policy",
                "owner": "Security owner",
                "sources": ["SECURITY.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready" if has_file("SECURITY.md") else "blocked",
                "evidence": "Repository security disclosure and support policy is present.",
                "action": "Attach SECURITY.md to the buyer security review packet.",
                "exit_criteria": "Buyer can identify the vulnerability reporting path and supported scope.",
            },
            {
                "item_name": "dependency_lock_package_metadata",
                "label": "Dependency lock and package metadata",
                "owner": "Release owner",
                "sources": ["requirements.lock", "pyproject.toml"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if has_file("requirements.lock") and has_file("pyproject.toml")
                else "blocked",
                "evidence": "Pinned dependency lock and Python package metadata are present for supply-chain review.",
                "action": "Use the pinned lockfile and package metadata as the buyer dependency baseline.",
                "exit_criteria": "Buyer can inspect package metadata and reproduce the dependency installation path.",
            },
            {
                "item_name": "security_workflow_metadata",
                "label": "Security workflow metadata",
                "owner": "Security owner",
                "sources": [
                    ".github/dependabot.yml",
                    ".github/workflows/security.yml",
                    ".github/workflows/scorecard-analysis.yml",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        ".github/dependabot.yml",
                        ".github/workflows/security.yml",
                        ".github/workflows/scorecard-analysis.yml",
                    )
                )
                else "blocked",
                "evidence": "Dependabot, CodeQL, dependency review, pip-audit, SBOM, Trivy, and Scorecard workflow metadata are defined.",
                "action": "Attach workflow definitions and latest passing run evidence when the buyer review requests hosted CI proof.",
                "exit_criteria": "Buyer can inspect the configured security workflow controls and their latest run status separately.",
            },
            {
                "item_name": "runtime_access_control_profile",
                "label": "Runtime access-control profile",
                "owner": "Platform operator",
                "sources": ["contextual_orchestrator/server.py", "/api/v1/commercial_operations_readiness/latest"],
                "evidence_type": "runtime_configuration",
                "completion_state": "ready",
                "evidence": (
                    f"Runtime profile uses auth_mode={runtime_profile.get('auth_mode', 'unknown')}, "
                    f"allow_public_bind={runtime_profile.get('allow_public_bind', False)}, "
                    f"expose_trace_by_default={runtime_profile.get('expose_trace_by_default', False)}, "
                    f"rate_limit_requests={runtime_profile.get('rate_limit_requests', 'unknown')}, "
                    f"max_concurrent_runs={runtime_profile.get('max_concurrent_runs', 'unknown')}."
                ),
                "action": "Use the secret-free runtime profile as buyer-visible access-control evidence.",
                "exit_criteria": "Buyer can verify admin and inference scopes, public bind opt-in, trace exposure default, rate limit, and concurrency controls.",
            },
            {
                "item_name": "audit_export_evidence",
                "label": "Audit and evidence export",
                "owner": "Evidence owner",
                "sources": [
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_operations_readiness.md",
                    "/api/v1/commercial_evidence_exports/latest",
                    "/api/v1/commercial_operations_readiness/latest",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if has_file("docs/commercial_evidence_export.md")
                and has_file("docs/commercial_operations_readiness.md")
                else "blocked",
                "evidence": "Commercial evidence export and operations readiness documents are present for buyer audit review.",
                "action": "Package runtime evidence export with operations readiness for the security review data room.",
                "exit_criteria": "Buyer can trace security claims to runtime endpoints and Markdown artifacts.",
            },
            {
                "item_name": "vulnerability_scan_evidence",
                "label": "Vulnerability scan evidence",
                "owner": "Security owner",
                "sources": [".github/workflows/security.yml", ".github/workflows/scorecard-analysis.yml"],
                "evidence_type": "external_attestation_required",
                "completion_state": "warning",
                "source_gap_status": "external_attestation_required",
                "evidence": "Security scan workflow metadata exists, but the buyer packet still needs the latest hosted scan result or buyer-accepted equivalent.",
                "action": "Attach latest CodeQL, pip-audit, Trivy, SBOM, and Scorecard results when CI completes or the buyer requests evidence.",
                "exit_criteria": "Hosted scan outputs are attached, or the buyer explicitly accepts workflow definitions as sufficient for this stage.",
            },
            {
                "item_name": "third_party_attestation_pen_test",
                "label": "Third-party attestation or penetration test",
                "owner": "Security owner",
                "sources": ["buyer security review", "external assessor"],
                "evidence_type": "external_attestation_required",
                "completion_state": "warning",
                "source_gap_status": "external_attestation_required",
                "evidence": "Independent SOC 2, ISO 27001, penetration-test, or buyer security assessment evidence is outside the repo-local prototype.",
                "action": "Provide the buyer-requested attestation, schedule an assessment, or document an explicit waiver.",
                "exit_criteria": "Buyer accepts the third-party security evidence, scheduled assessment, or waiver.",
            },
            {
                "item_name": "buyer_privacy_dpa_questionnaire",
                "label": "Buyer privacy, DPA, and questionnaire input",
                "owner": "Deal owner",
                "sources": ["buyer DPA", "buyer privacy questionnaire", "buyer order form"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_input_required",
                "evidence": "Privacy, DPA, subprocessors, data residency, and questionnaire answers depend on buyer-specific terms.",
                "action": "Collect buyer privacy questionnaire, DPA requirements, subprocessors, and data residency constraints.",
                "exit_criteria": "Buyer-specific privacy inputs are completed or explicitly waived in the deal packet.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": operations_by_name["review_process_policy"]["sources"],
                "evidence_type": operations_by_name["review_process_policy"]["evidence_type"],
                "completion_state": operations_by_name["review_process_policy"]["completion_state"],
                "evidence": operations_by_name["review_process_policy"]["evidence"],
                "action": operations_by_name["review_process_policy"]["action"],
                "exit_criteria": operations_by_name["review_process_policy"]["exit_criteria"],
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": operations_by_name["packaging_decision"]["owner"],
                "sources": operations_by_name["packaging_decision"]["sources"],
                "evidence_type": operations_by_name["packaging_decision"]["evidence_type"],
                "completion_state": operations_by_name["packaging_decision"]["completion_state"],
                "evidence": operations_by_name["packaging_decision"]["evidence"],
                "action": operations_by_name["packaging_decision"]["action"],
                "exit_criteria": operations_by_name["packaging_decision"]["exit_criteria"],
            },
        ]
        state_counts = Counter(item["completion_state"] for item in security_attestation_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        external_attestation_gap_count = sum(
            1 for item in security_attestation_items if item.get("source_gap_status") == "external_attestation_required"
        )
        buyer_privacy_gap_count = sum(
            1 for item in security_attestation_items if item.get("source_gap_status") == "buyer_input_required"
        )
        if blocked_count:
            security_attestation_status = "commercial_security_attestation_blocked"
        elif warning_count:
            security_attestation_status = "commercial_security_attestation_ready_with_warnings"
        else:
            security_attestation_status = "commercial_security_attestation_ready"

        return {
            "security_attestation_status": security_attestation_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_security_attestation",
            "source_note": (
                "Commercial security attestation separates repo-local security evidence from external "
                "attestation, hosted scan, and buyer privacy inputs; it is not a valuation guarantee, "
                "purchase commitment, production compliance certificate, or third-party security audit."
            ),
            "security_attestation_summary": {
                "item_count": len(security_attestation_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "external_attestation_gap_count": external_attestation_gap_count,
                "buyer_privacy_gap_count": buyer_privacy_gap_count,
                "review_process_is_blocker": operations["review_process_policy"]["is_blocker"],
            },
            "security_attestation_items": security_attestation_items,
            "concrete_blockers": concrete_blockers,
            "security_attestation_status_rules": [
                {
                    "security_attestation_status": "commercial_security_attestation_ready",
                    "rule": "security policy, dependency metadata, workflow metadata, access controls, audit export, external attestation, buyer privacy input, review policy, and packaging evidence are ready",
                },
                {
                    "security_attestation_status": "commercial_security_attestation_ready_with_warnings",
                    "rule": "repo-local security packet is ready while hosted scan evidence, third-party attestation, or buyer privacy input remains explicit warnings",
                },
                {
                    "security_attestation_status": "commercial_security_attestation_blocked",
                    "rule": "missing local security packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks security attestation",
                },
            ],
            "review_process_policy": operations["review_process_policy"],
            "related_runtime_reports": {
                "commercial_operations_status": operations["operations_status"],
                **operations["related_runtime_reports"],
            },
            "library_split_decision": operations["library_split_decision"],
            "plugin_traceability": operations["plugin_traceability"],
            "security_attestation_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_security_attestations/latest",
                "documentation": "docs/commercial_security_attestation.md",
            },
        }

    def commercial_value_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a buyer economic-review gate over value and ROI evidence."""
        commercial = self.commercial_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        export = self.commercial_evidence_export_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        criteria_by_name = self._criteria_by_name(commercial["criteria"])
        value_case = criteria_by_name["commercial_value_case"]
        kpis = self._metrics_by_name(analytics["kpis"])
        guardrails = self._metrics_by_name(analytics["guardrails"])
        security_items = {item["item_name"]: item for item in security["security_attestation_items"]}
        value_items = [
            {
                "item_name": "commercial_value_case_basis",
                "label": "Commercial value-case basis",
                "owner": "Deal owner",
                "sources": ["/api/v1/commercial_readiness/latest", "docs/commercial_readiness.md"],
                "evidence_type": "local_due_diligence_snapshot",
                "completion_state": "ready" if value_case["status"] == "pass" else "warning",
                "evidence": value_case["evidence"],
                "action": "Use commercial readiness as the value-case baseline without presenting it as a valuation guarantee.",
                "exit_criteria": "Buyer sees the KRW target as a review anchor, not as a guaranteed valuation.",
            },
            {
                "item_name": "local_analytics_evidence",
                "label": "Local analytics evidence",
                "owner": "Product analytics owner",
                "sources": ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
                "evidence_type": "measured_local",
                "completion_state": "ready",
                "evidence": (
                    f"compatible_api_adoption={kpis['compatible_api_adoption'].get('value')}; "
                    f"trace_complete_workflow_rate={kpis['trace_complete_workflow_rate'].get('value_percent')}%; "
                    f"policy_safe_routing_rate={kpis['policy_safe_routing_rate'].get('value_percent')}%; "
                    f"provider_exclusion_miss_rate={guardrails['provider_exclusion_miss_rate'].get('value')}"
                ),
                "action": "Use local measured adoption, trace, policy, and provider-safety metrics as evidence only for this prototype.",
                "exit_criteria": "Buyer understands these are local measured signals, not production revenue or customer usage claims.",
            },
            {
                "item_name": "buyer_evidence_export",
                "label": "Buyer evidence export",
                "owner": "Evidence owner",
                "sources": [
                    "/api/v1/commercial_evidence_exports/latest",
                    "/api/v1/commercial_security_attestations/latest",
                    "docs/commercial_evidence_export.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready" if has_file("docs/commercial_evidence_export.md") else "blocked",
                "evidence": (
                    f"commercial_export_status={export['export_status']}; "
                    f"security_attestation_status={security['security_attestation_status']}"
                ),
                "action": "Package value evidence with export and security attestation outputs in the buyer data room.",
                "exit_criteria": "Buyer can trace economic claims back to runtime endpoints and repo artifacts.",
            },
            {
                "item_name": "pricing_package_rationale",
                "label": "Pricing and package rationale",
                "owner": "Deal owner",
                "sources": [
                    "docs/commercial_readiness.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_value_readiness.md",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/commercial_readiness.md",
                        "docs/commercial_saleability_decision.md",
                        "docs/commercial_procurement_readiness.md",
                    )
                )
                else "blocked",
                "evidence": "Commercial readiness, saleability, and procurement documents anchor the package rationale.",
                "action": "Keep the KRW 2B package rationale tied to API compatibility, evidence control plane, replay, audit, security, and operations readiness.",
                "exit_criteria": "Buyer can inspect which product capabilities support the package rationale.",
            },
            {
                "item_name": "roi_model_inputs",
                "label": "ROI model inputs",
                "owner": "Buyer sponsor and deal owner",
                "sources": ["buyer ROI model", "customer discovery", "procurement value case"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_financial_input_required",
                "evidence": "Buyer-specific baseline cost, workflow volume, error/rework cost, compliance cost, and time-saving assumptions are not repo-local facts.",
                "action": "Collect buyer baseline metrics and map them to API compatibility, trace audit, replay, and operations savings.",
                "exit_criteria": "Buyer accepts the ROI model inputs or marks them waived for the commercial review.",
            },
            {
                "item_name": "reference_customer_or_case_study",
                "label": "Reference customer or proof",
                "owner": "Deal owner",
                "sources": ["reference customer", "case study", "paid pilot result"],
                "evidence_type": "external_value_proof_required",
                "completion_state": "warning",
                "source_gap_status": "external_value_proof_required",
                "evidence": "Reference customer, paid pilot, or production proof is external to the repo-local prototype.",
                "action": "Attach a reference, pilot result, or explicit buyer waiver before treating the value case as externally proven.",
                "exit_criteria": "Buyer accepts the reference proof, pilot result, or waiver.",
            },
            {
                "item_name": "procurement_budget_owner",
                "label": "Procurement budget owner",
                "owner": "Buyer sponsor and procurement owner",
                "sources": ["buyer order form", "procurement process", "budget approval"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_financial_input_required",
                "evidence": "Budget owner, approval path, and order-form authority are buyer-specific inputs.",
                "action": "Identify sponsor, budget owner, procurement path, and order-form authority.",
                "exit_criteria": "Buyer confirms the budget owner and approval path for the KRW 2B review.",
            },
            {
                "item_name": "implementation_payback_assumption",
                "label": "Implementation payback assumption",
                "owner": "Buyer sponsor and onboarding owner",
                "sources": ["buyer onboarding plan", "implementation estimate", "operations handoff"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_financial_input_required",
                "evidence": "Implementation timeline, staffing, opportunity cost, and payback window depend on buyer deployment scope.",
                "action": "Estimate implementation effort and payback window during paid onboarding or buyer diligence.",
                "exit_criteria": "Buyer accepts the payback assumptions or marks them out of scope.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": security_items["review_process_policy"]["sources"],
                "evidence_type": security_items["review_process_policy"]["evidence_type"],
                "completion_state": security_items["review_process_policy"]["completion_state"],
                "evidence": security_items["review_process_policy"]["evidence"],
                "action": security_items["review_process_policy"]["action"],
                "exit_criteria": security_items["review_process_policy"]["exit_criteria"],
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": security_items["packaging_decision"]["owner"],
                "sources": security_items["packaging_decision"]["sources"],
                "evidence_type": security_items["packaging_decision"]["evidence_type"],
                "completion_state": security_items["packaging_decision"]["completion_state"],
                "evidence": security_items["packaging_decision"]["evidence"],
                "action": security_items["packaging_decision"]["action"],
                "exit_criteria": security_items["packaging_decision"]["exit_criteria"],
            },
        ]
        state_counts = Counter(item["completion_state"] for item in value_items)
        concrete_blockers = security["concrete_blockers"]
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_financial_gap_count = sum(
            1
            for item in value_items
            if item.get("source_gap_status") in {"buyer_financial_input_required", "external_value_proof_required"}
        )
        external_value_proof_gap_count = sum(
            1 for item in value_items if item.get("source_gap_status") == "external_value_proof_required"
        )
        if blocked_count:
            value_status = "commercial_value_blocked"
        elif warning_count:
            value_status = "commercial_value_ready_with_warnings"
        else:
            value_status = "commercial_value_ready"

        return {
            "value_status": value_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_value_readiness",
            "source_note": (
                "Commercial value readiness separates repo-local measured evidence from buyer-specific "
                "ROI, reference, budget, and payback inputs; it is not a valuation guarantee, purchase "
                "commitment, revenue proof, or financial advice."
            ),
            "value_summary": {
                "item_count": len(value_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "buyer_financial_gap_count": buyer_financial_gap_count,
                "external_value_proof_gap_count": external_value_proof_gap_count,
                "review_process_is_blocker": security["review_process_policy"]["is_blocker"],
            },
            "value_items": value_items,
            "concrete_blockers": concrete_blockers,
            "value_status_rules": [
                {
                    "value_status": "commercial_value_ready",
                    "rule": "commercial value case, local analytics, evidence export, pricing rationale, ROI inputs, reference proof, budget owner, payback assumptions, review policy, and packaging evidence are ready",
                },
                {
                    "value_status": "commercial_value_ready_with_warnings",
                    "rule": "repo-local value evidence is ready while buyer ROI inputs, reference proof, budget owner, or payback assumptions remain explicit warnings",
                },
                {
                    "value_status": "commercial_value_blocked",
                    "rule": "missing local value packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks value readiness",
                },
            ],
            "review_process_policy": security["review_process_policy"],
            "related_runtime_reports": {
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_export_status": export["export_status"],
                "commercial_status": commercial["commercial_status"],
                **security["related_runtime_reports"],
            },
            "library_split_decision": security["library_split_decision"],
            "plugin_traceability": security["plugin_traceability"],
            "value_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_value_readiness/latest",
                "documentation": "docs/commercial_value_readiness.md",
            },
        }

    def commercial_close_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the final buyer-close gate over commercial readiness evidence."""
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        contract = self.commercial_contract_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        export = self.commercial_evidence_export_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = [
            *value["concrete_blockers"],
            *security["concrete_blockers"],
            *contract["concrete_blockers"],
            *onboarding["concrete_blockers"],
            *operations["concrete_blockers"],
            *export["concrete_blockers"],
        ]
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        close_items = [
            {
                "item_name": "sellable_product_packet",
                "label": "Sellable product packet",
                "owner": "Deal owner",
                "sources": [
                    "/api/v1/commercial_value_readiness/latest",
                    "/api/v1/commercial_security_attestations/latest",
                    "/api/v1/commercial_evidence_exports/latest",
                    "docs/commercial_value_readiness.md",
                    "docs/commercial_security_attestation.md",
                    "docs/commercial_evidence_export.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if value["value_status"] != "commercial_value_blocked"
                and security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and export["export_status"] != "commercial_export_blocked"
                and has_file("docs/commercial_value_readiness.md")
                and has_file("docs/commercial_security_attestation.md")
                and has_file("docs/commercial_evidence_export.md")
                else "blocked",
                "evidence": (
                    f"value_status={value['value_status']}; "
                    f"security_attestation_status={security['security_attestation_status']}; "
                    f"commercial_export_status={export['export_status']}"
                ),
                "action": "Attach the repo-local product, security, value, and evidence export packet to buyer close review.",
                "exit_criteria": "Buyer can inspect the sellable packet without treating it as a purchase commitment or valuation guarantee.",
            },
            {
                "item_name": "contract_close_packet",
                "label": "Contract close packet",
                "owner": "Legal and procurement owner",
                "sources": [
                    "/api/v1/commercial_contract_readiness/latest",
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if contract["contract_status"] != "commercial_contract_blocked"
                and has_file("docs/commercial_contract_readiness.md")
                else "blocked",
                "evidence": f"contract_status={contract['contract_status']}",
                "action": "Use contract readiness as the local legal/procurement packet and track final signatures separately.",
                "exit_criteria": "Buyer legal/procurement sees local contract evidence and the remaining signature inputs.",
            },
            {
                "item_name": "onboarding_operations_packet",
                "label": "Onboarding and operations packet",
                "owner": "Customer success and platform owner",
                "sources": [
                    "/api/v1/commercial_onboarding_readiness/latest",
                    "/api/v1/commercial_operations_readiness/latest",
                    "docs/commercial_onboarding_readiness.md",
                    "docs/commercial_operations_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and operations["operations_status"] != "commercial_operations_blocked"
                and has_file("docs/commercial_onboarding_readiness.md")
                and has_file("docs/commercial_operations_readiness.md")
                else "blocked",
                "evidence": (
                    f"onboarding_status={onboarding['onboarding_status']}; "
                    f"operations_status={operations['operations_status']}"
                ),
                "action": "Attach onboarding and operations readiness as the go-live support packet.",
                "exit_criteria": "Buyer can identify implementation, support, operations, and acceptance owners.",
            },
            {
                "item_name": "buyer_evidence_export_packet",
                "label": "Buyer evidence export packet",
                "owner": "Evidence owner",
                "sources": [
                    "/api/v1/commercial_evidence_exports/latest",
                    "docs/commercial_evidence_export.md",
                    "docs/figma_artifacts.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if export["export_status"] != "commercial_export_blocked"
                and has_file("docs/commercial_evidence_export.md")
                and has_file("docs/figma_artifacts.md")
                else "blocked",
                "evidence": f"commercial_export_status={export['export_status']}",
                "action": "Use the portable export packet as the buyer data-room index.",
                "exit_criteria": "Buyer can trace close evidence to runtime endpoints, docs, and Figma/FigJam artifacts.",
            },
            {
                "item_name": "signed_order_form_msa",
                "label": "Signed order form or MSA",
                "owner": "Buyer sponsor, procurement owner, and deal owner",
                "sources": ["buyer order form", "MSA", "signature packet"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": "Signed order form, MSA, commercial terms, and authority confirmation are buyer-side close inputs.",
                "action": "Collect final signed order form or MSA, or attach an explicit buyer waiver.",
                "exit_criteria": "Buyer and seller signature authority accept the order form or MSA.",
            },
            {
                "item_name": "dpa_security_acceptance",
                "label": "DPA and security acceptance",
                "owner": "Buyer security, privacy, and legal owner",
                "sources": ["buyer DPA", "security review acceptance", "privacy questionnaire"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": "DPA, security acceptance, privacy questionnaire, and attestation waivers are buyer-specific close inputs.",
                "action": "Collect DPA/security acceptance or documented waiver from buyer security and legal reviewers.",
                "exit_criteria": "Buyer signs or waives DPA/security acceptance requirements.",
            },
            {
                "item_name": "budget_approval_purchase_order",
                "label": "Budget approval and purchase order",
                "owner": "Buyer finance and procurement owner",
                "sources": ["budget approval", "purchase order", "finance approval"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": "Budget approval, purchase order, and finance authority are external buyer procurement evidence.",
                "action": "Collect buyer budget approval and PO or attach approved alternative payment authority.",
                "exit_criteria": "Buyer procurement confirms budget authority and payment path for KRW 2B.",
            },
            {
                "item_name": "go_live_authorization",
                "label": "Go-live authorization",
                "owner": "Buyer business sponsor and implementation owner",
                "sources": ["go-live approval", "implementation authorization", "acceptance signoff"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": "Go-live authorization and implementation acceptance require named buyer approval.",
                "action": "Collect go-live authorization or mark production activation out of scope for the signed deal.",
                "exit_criteria": "Buyer authorizes go-live, paid onboarding, or a scoped post-signature implementation plan.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_close_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a close blocker unless a concrete product, security, API-contract, or document failure is produced.",
                "action": "Keep commercial close work moving while queued review processes are pending.",
                "exit_criteria": "Only concrete failures block close readiness.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if value["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": value["library_split_decision"]["reason"],
                "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
                "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this close gate.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in close_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_signature_gap_count = sum(
            1 for item in close_items if item.get("source_gap_status") == "buyer_signature_required"
        )
        if blocked_count:
            close_status = "commercial_close_blocked"
        elif warning_count:
            close_status = "commercial_close_ready_with_warnings"
        else:
            close_status = "commercial_close_ready"

        return {
            "close_status": close_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_close_readiness",
            "source_note": (
                "Commercial close readiness separates repo-local sellable product evidence from buyer "
                "signature, legal, procurement, security acceptance, and go-live authorization inputs; "
                "it is not a valuation guarantee, purchase commitment, signed order, legal opinion, "
                "or production compliance certificate."
            ),
            "close_summary": {
                "item_count": len(close_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "buyer_signature_gap_count": buyer_signature_gap_count,
                "review_process_is_blocker": value["review_process_policy"]["is_blocker"],
            },
            "close_items": close_items,
            "concrete_blockers": concrete_blockers,
            "close_status_rules": [
                {
                    "close_status": "commercial_close_ready",
                    "rule": "sellable product packet, contract packet, onboarding/operations packet, evidence export, signatures, DPA/security acceptance, budget/PO, go-live authorization, review policy, and packaging evidence are ready",
                },
                {
                    "close_status": "commercial_close_ready_with_warnings",
                    "rule": "repo-local close packet is ready while buyer signatures, DPA/security acceptance, budget/PO, or go-live authorization remain explicit warnings",
                },
                {
                    "close_status": "commercial_close_blocked",
                    "rule": "missing local close evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks close readiness",
                },
            ],
            "review_process_policy": value["review_process_policy"],
            "related_runtime_reports": {
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_contract_status": contract["contract_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_operations_status": operations["operations_status"],
                "commercial_export_status": export["export_status"],
                **value["related_runtime_reports"],
            },
            "library_split_decision": value["library_split_decision"],
            "plugin_traceability": value["plugin_traceability"],
            "close_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_close_readiness/latest",
                "documentation": "docs/commercial_close_readiness.md",
            },
        }

    def commercial_go_to_market_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a buyer-facing GTM readiness index over commercial evidence."""
        close = self.commercial_close_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        value = self.commercial_value_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        security = self.commercial_security_attestation_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        export = self.commercial_evidence_export_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        handoff = self.buyer_handoff_bundle_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        saleability = self.saleability_decision_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = [
            *close["concrete_blockers"],
            *value["concrete_blockers"],
            *security["concrete_blockers"],
            *export["concrete_blockers"],
            *saleability["concrete_blockers"],
        ]
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        gtm_items = [
            {
                "item_name": "commercial_close_packet",
                "label": "Commercial close packet",
                "owner": "Deal owner",
                "sources": ["/api/v1/commercial_close_readiness/latest", "docs/commercial_close_readiness.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if close["close_status"] != "commercial_close_blocked"
                and has_file("docs/commercial_close_readiness.md")
                else "blocked",
                "evidence": f"close_status={close['close_status']}",
                "action": "Use close readiness as the buyer-facing final readiness packet.",
                "exit_criteria": "Buyer sees local close packet status and remaining buyer-side signature gaps.",
            },
            {
                "item_name": "economic_value_packet",
                "label": "Economic value packet",
                "owner": "Deal owner and analytics owner",
                "sources": [
                    "/api/v1/commercial_value_readiness/latest",
                    "/api/v1/analytics_snapshots/latest",
                    "docs/commercial_value_readiness.md",
                    "docs/analytics_spec.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if value["value_status"] != "commercial_value_blocked"
                and has_file("docs/commercial_value_readiness.md")
                and has_file("docs/analytics_spec.md")
                else "blocked",
                "evidence": (
                    f"value_status={value['value_status']}; "
                    f"kpi_count={len(analytics['kpis'])}; guardrail_count={len(analytics['guardrails'])}"
                ),
                "action": "Show value evidence with measured-local versus buyer-specific metric separation.",
                "exit_criteria": "Buyer can inspect value claims without treating them as revenue proof or financial advice.",
            },
            {
                "item_name": "security_trust_packet",
                "label": "Security trust packet",
                "owner": "Security owner",
                "sources": [
                    "/api/v1/commercial_security_attestations/latest",
                    "docs/commercial_security_attestation.md",
                    "SECURITY.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if security["security_attestation_status"] != "commercial_security_attestation_blocked"
                and has_file("docs/commercial_security_attestation.md")
                and has_file("SECURITY.md")
                else "blocked",
                "evidence": f"security_attestation_status={security['security_attestation_status']}",
                "action": "Use security attestation as the buyer trust packet and keep external attestations separate.",
                "exit_criteria": "Buyer can inspect local security controls and external attestation gaps.",
            },
            {
                "item_name": "buyer_evidence_packet",
                "label": "Buyer evidence packet",
                "owner": "Evidence owner",
                "sources": [
                    "/api/v1/commercial_evidence_exports/latest",
                    "/api/v1/buyer_handoff_bundles/latest",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if export["export_status"] != "commercial_export_blocked"
                and handoff["bundle_status"] != "buyer_handoff_blocked"
                and has_file("docs/commercial_evidence_export.md")
                and has_file("docs/commercial_buyer_handoff_bundle.md")
                else "blocked",
                "evidence": f"commercial_export_status={export['export_status']}; buyer_handoff_status={handoff['bundle_status']}",
                "action": "Attach evidence export and handoff bundle as the buyer data-room index.",
                "exit_criteria": "Buyer can trace GTM claims to runtime endpoints, docs, tests, and Figma artifacts.",
            },
            {
                "item_name": "saleability_decision_packet",
                "label": "Saleability decision packet",
                "owner": "Deal owner",
                "sources": ["/api/v1/saleability_decisions/latest", "docs/commercial_saleability_decision.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if saleability["saleability_status"] != "saleability_blocked"
                and has_file("docs/commercial_saleability_decision.md")
                else "blocked",
                "evidence": f"saleability_status={saleability['saleability_status']}",
                "action": "Use saleability decision as the GTM go/no-go baseline.",
                "exit_criteria": "Buyer and stakeholder review can distinguish warnings from concrete blockers.",
            },
            {
                "item_name": "admin_operator_evidence",
                "label": "Admin operator evidence",
                "owner": "Product design owner",
                "sources": ["/admin", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
                else "blocked",
                "evidence": "Admin surface exposes readiness status, source notes, measurement status, and warning/blocker summaries.",
                "action": "Use the existing admin observability surface instead of creating a separate sales dashboard.",
                "exit_criteria": "Operator can inspect GTM readiness from the current admin surface.",
            },
            {
                "item_name": "analytics_truthfulness_packet",
                "label": "Analytics truthfulness packet",
                "owner": "Data analytics owner",
                "sources": ["docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready" if has_file("docs/analytics_spec.md") else "blocked",
                "evidence": "Analytics spec separates measured local evidence from proposed production or buyer-specific inputs.",
                "action": "Keep GTM metrics from claiming production revenue, signed buyer proof, or unmeasured telemetry.",
                "exit_criteria": "Stakeholders can see which KPI fields are measured and which are proposed inputs.",
            },
            {
                "item_name": "stakeholder_artifacts_packet",
                "label": "Stakeholder artifacts packet",
                "owner": "Figma and Product Design owner",
                "sources": [
                    "docs/figma_artifacts.md",
                    "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                    "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                ],
                "evidence_type": "figma_artifact",
                "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "evidence": "Editable Figma/FigJam stakeholder artifacts are recorded and Figma Code Connect is excluded.",
                "action": "Use editable stakeholder artifacts for GTM review instead of screenshot-only evidence.",
                "exit_criteria": "Stakeholders can open the design file and FigJam board for GTM review.",
            },
            {
                "item_name": "buyer_signature_budget_follow_up",
                "label": "Buyer signature and budget follow-up",
                "owner": "Buyer sponsor, procurement owner, and deal owner",
                "sources": ["buyer order form", "MSA", "DPA", "security acceptance", "purchase order", "go-live approval"],
                "evidence_type": "buyer_input_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": (
                    f"buyer_signature_gap_count={close['close_summary']['buyer_signature_gap_count']}; "
                    "signed order/MSA, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
                ),
                "action": "Collect buyer signatures, approvals, or waivers before representing the packet as closed-won.",
                "exit_criteria": "Buyer accepts or waives all signature, budget, security acceptance, and go-live inputs.",
            },
            {
                "item_name": "production_external_proof_follow_up",
                "label": "Production and external proof follow-up",
                "owner": "Security, operations, and deal owner",
                "sources": ["hosted scan output", "third-party attestation", "reference proof", "production telemetry"],
                "evidence_type": "external_or_production_input_required",
                "completion_state": "warning",
                "source_gap_status": "external_or_production_input_required",
                "evidence": (
                    f"security_warning_count={security['security_attestation_summary']['warning_count']}; "
                    f"value_warning_count={value['value_summary']['warning_count']}; "
                    f"export_warning_count={export['export_summary']['warning_count']}"
                ),
                "action": "Attach hosted scan, third-party attestation, reference proof, and production telemetry when available.",
                "exit_criteria": "Buyer accepts external proof, production proof, or an explicit waiver.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_go_to_market_readiness.md", "docs/commercial_saleability_decision.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a GTM blocker unless a concrete failure is produced.",
                "action": "Continue GTM readiness work while queued reviews are pending.",
                "exit_criteria": "Only concrete product, security, API contract, or document failures block GTM readiness.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if close["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": close["library_split_decision"]["reason"],
                "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
                "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this GTM gate.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in gtm_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_signature_gap_count = close["close_summary"]["buyer_signature_gap_count"]
        external_or_production_gap_count = (
            security["security_attestation_summary"]["external_attestation_gap_count"]
            + value["value_summary"]["external_value_proof_gap_count"]
            + export["export_summary"]["warning_count"]
        )
        if blocked_count:
            gtm_status = "commercial_go_to_market_blocked"
        elif warning_count:
            gtm_status = "commercial_go_to_market_ready_with_warnings"
        else:
            gtm_status = "commercial_go_to_market_ready"

        return {
            "go_to_market_status": gtm_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_go_to_market_readiness",
            "source_note": (
                "Commercial go-to-market readiness indexes repo-local sellable product, evidence, "
                "admin, analytics, and stakeholder artifacts separately from buyer signatures, "
                "external proof, and production telemetry; it is not a valuation guarantee, purchase "
                "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "go_to_market_summary": {
                "item_count": len(gtm_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "buyer_signature_gap_count": buyer_signature_gap_count,
                "external_or_production_gap_count": external_or_production_gap_count,
                "review_process_is_blocker": close["review_process_policy"]["is_blocker"],
            },
            "go_to_market_items": gtm_items,
            "concrete_blockers": concrete_blockers,
            "go_to_market_status_rules": [
                {
                    "go_to_market_status": "commercial_go_to_market_ready",
                    "rule": "close, value, security, evidence, saleability, admin, analytics, stakeholder artifacts, buyer inputs, external proof, review policy, and packaging evidence are ready",
                },
                {
                    "go_to_market_status": "commercial_go_to_market_ready_with_warnings",
                    "rule": "repo-local GTM packet is ready while buyer signatures, budget/PO, DPA/security acceptance, production telemetry, reference proof, hosted scan, or third-party attestation remain explicit warnings",
                },
                {
                    "go_to_market_status": "commercial_go_to_market_blocked",
                    "rule": "missing local GTM packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks GTM readiness",
                },
            ],
            "review_process_policy": close["review_process_policy"],
            "related_runtime_reports": {
                "commercial_close_status": close["close_status"],
                "commercial_value_status": value["value_status"],
                "commercial_security_attestation_status": security["security_attestation_status"],
                "commercial_export_status": export["export_status"],
                "buyer_handoff_status": handoff["bundle_status"],
                "saleability_status": saleability["saleability_status"],
                **close["related_runtime_reports"],
            },
            "library_split_decision": close["library_split_decision"],
            "plugin_traceability": close["plugin_traceability"],
            "go_to_market_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_go_to_market_readiness/latest",
                "documentation": "docs/commercial_go_to_market_readiness.md",
            },
        }

    def commercial_launch_readiness_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the buyer launch/trial readiness gate over commercial evidence."""
        gtm = self.commercial_go_to_market_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        operations = self.commercial_operations_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        onboarding = self.commercial_onboarding_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        acceptance = self.commercial_acceptance_check_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = [
            *gtm["concrete_blockers"],
            *operations["concrete_blockers"],
            *onboarding["concrete_blockers"],
            *acceptance["concrete_blockers"],
        ]
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        launch_items = [
            {
                "item_name": "go_to_market_packet",
                "label": "Go-to-market packet",
                "owner": "Deal owner",
                "sources": [
                    "/api/v1/commercial_go_to_market_readiness/latest",
                    "docs/commercial_go_to_market_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
                and has_file("docs/commercial_go_to_market_readiness.md")
                else "blocked",
                "evidence": f"go_to_market_status={gtm['go_to_market_status']}",
                "action": "Use the GTM packet as the launch/trial entry evidence.",
                "exit_criteria": "Buyer can inspect the launch packet without treating it as a signed deal or production proof.",
            },
            {
                "item_name": "runtime_launch_path",
                "label": "Runtime launch path",
                "owner": "Platform operator",
                "sources": [
                    "README.md",
                    "contextual_orchestrator/server.py",
                    "contextual_orchestrator/api_contract.py",
                    "docs/rest_api_design.md",
                    "/v1/chat/completions",
                    "/admin",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "README.md",
                        "contextual_orchestrator/server.py",
                        "contextual_orchestrator/api_contract.py",
                        "docs/rest_api_design.md",
                    )
                )
                else "blocked",
                "evidence": "Stdlib server, OpenAI-compatible endpoint, admin console, and REST contract are present.",
                "action": "Run the existing server and admin/API smoke tests for buyer trial setup.",
                "exit_criteria": "Buyer can start the runtime, authenticate admin calls, and inspect launch readiness JSON.",
            },
            {
                "item_name": "acceptance_test_packet",
                "label": "Acceptance test packet",
                "owner": "Technical reviewer",
                "sources": [
                    "/api/v1/commercial_acceptance_checks/latest",
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_go_to_market_readiness.py",
                    "tests/test_commercial_launch_readiness.py",
                    "pytest -q",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if acceptance["acceptance_status"] != "commercial_acceptance_blocked"
                and all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_acceptance_check.py",
                        "tests/test_commercial_go_to_market_readiness.py",
                        "tests/test_commercial_launch_readiness.py",
                    )
                )
                else "blocked",
                "evidence": f"acceptance_status={acceptance['acceptance_status']}",
                "action": "Use focused acceptance and launch tests as the local verification packet.",
                "exit_criteria": "Focused launch, GTM, acceptance, API, and artifact tests pass before buyer handoff.",
            },
            {
                "item_name": "operator_runbook_packet",
                "label": "Operator runbook packet",
                "owner": "Customer success and platform owner",
                "sources": [
                    "/api/v1/commercial_operations_readiness/latest",
                    "/api/v1/commercial_onboarding_readiness/latest",
                    "docs/commercial_operations_readiness.md",
                    "docs/commercial_onboarding_readiness.md",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if operations["operations_status"] != "commercial_operations_blocked"
                and onboarding["onboarding_status"] != "commercial_onboarding_blocked"
                and has_file("docs/commercial_operations_readiness.md")
                and has_file("docs/commercial_onboarding_readiness.md")
                else "blocked",
                "evidence": (
                    f"operations_status={operations['operations_status']}; "
                    f"onboarding_status={onboarding['onboarding_status']}"
                ),
                "action": "Attach onboarding and operations readiness as the launch runbook.",
                "exit_criteria": "Buyer sees implementation, support, telemetry, incident, backup, and acceptance owners.",
            },
            {
                "item_name": "admin_observability_packet",
                "label": "Admin observability packet",
                "owner": "Product design owner",
                "sources": ["/admin", "/admin/state", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if admin_state["agents"] and has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
                else "blocked",
                "evidence": (
                    f"agent_count={len(admin_state['agents'])}; "
                    "admin surface exposes launch, source, measurement, and warning summaries."
                ),
                "action": "Use the current admin observability surface rather than a separate sales dashboard.",
                "exit_criteria": "Operator can review launch readiness from the existing admin console.",
            },
            {
                "item_name": "buyer_environment_inputs",
                "label": "Buyer environment inputs",
                "owner": "Buyer implementation owner and platform operator",
                "sources": ["buyer environment URL", "deployment topology", "admin token handoff", "data retention decision"],
                "evidence_type": "buyer_environment_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_environment_required",
                "evidence": "Buyer deployment URL, topology, credentials handoff, retention, and network policy are not repo-local evidence.",
                "action": "Collect buyer environment details or attach explicit trial-scope waivers.",
                "exit_criteria": "Buyer provides environment inputs or agrees the launch is limited to repo-local/demo execution.",
            },
            {
                "item_name": "production_telemetry_inputs",
                "label": "Production telemetry inputs",
                "owner": "Operations and analytics owner",
                "sources": [
                    "/api/v1/commercial_operations_readiness/latest",
                    "/api/v1/analytics_snapshots/latest",
                    "production request logs",
                    "incident drill record",
                    "backup restore proof",
                ],
                "evidence_type": "proposed_until_production",
                "completion_state": "warning",
                "source_gap_status": "production_input_required",
                "evidence": (
                    f"operations_production_evidence_action_count="
                    f"{operations['operations_summary']['production_evidence_action_count']}; "
                    f"analytics_measurement_status={analytics['measurement_status']}"
                ),
                "action": "Capture production telemetry, SLO evidence, incident drill, and restore proof in the buyer environment.",
                "exit_criteria": "First production telemetry snapshot and operations proof are attached or explicitly waived.",
            },
            {
                "item_name": "commercial_signature_inputs",
                "label": "Commercial signature inputs",
                "owner": "Buyer sponsor, procurement owner, and deal owner",
                "sources": ["signed order/MSA", "DPA/security acceptance", "purchase order", "go-live authorization"],
                "evidence_type": "buyer_signature_required",
                "completion_state": "warning",
                "source_gap_status": "buyer_signature_required",
                "evidence": (
                    f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}; "
                    "signed order, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
                ),
                "action": "Collect signatures, approvals, or waivers before representing launch readiness as closed-won.",
                "exit_criteria": "Buyer accepts all signature, DPA/security, budget, and go-live inputs.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_launch_readiness.md", "docs/commercial_go_to_market_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review process delay is not a launch blocker unless a concrete failure is produced.",
                "action": "Continue launch readiness work while queued review processes are pending.",
                "exit_criteria": "Only concrete product, security, API contract, or document failures block launch readiness.",
            },
            {
                "item_name": "packaging_decision",
                "label": "Packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if gtm["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": gtm["library_split_decision"]["reason"],
                "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
                "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this launch gate.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in launch_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        buyer_environment_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "buyer_environment_required"
        )
        production_telemetry_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "production_input_required"
        )
        commercial_signature_gap_count = sum(
            1 for item in launch_items if item.get("source_gap_status") == "buyer_signature_required"
        )
        external_input_group_count = (
            buyer_environment_gap_count + production_telemetry_gap_count + commercial_signature_gap_count
        )
        if blocked_count:
            launch_status = "commercial_launch_blocked"
        elif warning_count:
            launch_status = "commercial_launch_ready_with_warnings"
        else:
            launch_status = "commercial_launch_ready"

        return {
            "launch_status": launch_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_launch_readiness",
            "source_note": (
                "Commercial launch readiness packages repo-local GTM, runtime, acceptance, operator, admin, "
                "analytics, Figma, review-process, and packaging evidence separately from buyer environment, "
                "production telemetry, and commercial signature inputs; it is not a valuation guarantee, "
                "purchase commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "launch_summary": {
                "item_count": len(launch_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "external_input_group_count": external_input_group_count,
                "buyer_environment_gap_count": buyer_environment_gap_count,
                "production_telemetry_gap_count": production_telemetry_gap_count,
                "commercial_signature_gap_count": commercial_signature_gap_count,
                "review_process_is_blocker": gtm["review_process_policy"]["is_blocker"],
            },
            "launch_items": launch_items,
            "concrete_blockers": concrete_blockers,
            "launch_status_rules": [
                {
                    "launch_status": "commercial_launch_ready",
                    "rule": "GTM, runtime, acceptance, operator, admin, buyer environment, production telemetry, commercial signature, review policy, and packaging evidence are ready",
                },
                {
                    "launch_status": "commercial_launch_ready_with_warnings",
                    "rule": "repo-local launch packet is ready while buyer environment, production telemetry, or commercial signature inputs remain explicit warnings",
                },
                {
                    "launch_status": "commercial_launch_blocked",
                    "rule": "missing local launch packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks launch readiness",
                },
            ],
            "review_process_policy": gtm["review_process_policy"],
            "related_runtime_reports": {
                "commercial_go_to_market_status": gtm["go_to_market_status"],
                "commercial_operations_status": operations["operations_status"],
                "commercial_onboarding_status": onboarding["onboarding_status"],
                "commercial_acceptance_status": acceptance["acceptance_status"],
                "analytics_measurement_status": analytics["measurement_status"],
                **gtm["related_runtime_reports"],
            },
            "library_split_decision": gtm["library_split_decision"],
            "plugin_traceability": gtm["plugin_traceability"],
            "launch_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_launch_readiness/latest",
                "documentation": "docs/commercial_launch_readiness.md",
            },
        }

    def commercial_completion_scorecard_report(
        self,
        target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
        locale_bundles: dict[str, dict[str, str]] | None = None,
        security_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the final KRW 2B commercial completion scorecard."""
        commercial = self.commercial_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        gtm = self.commercial_go_to_market_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        launch = self.commercial_launch_readiness_report(
            target_contract_value_krw=target_contract_value_krw,
            locale_bundles=locale_bundles,
            security_profile=security_profile,
        )
        analytics = self.analytics_snapshot(locale_bundles=locale_bundles)
        admin_state = self.admin_state()
        root = Path(__file__).resolve().parents[1]

        def has_file(path: str) -> bool:
            return (root / path).is_file()

        concrete_blockers = list(launch["concrete_blockers"])
        if commercial["commercial_status"] == "not_commercial_ready":
            concrete_blockers.append("commercial_readiness_failed")
        if launch["launch_status"] == "commercial_launch_blocked":
            concrete_blockers.append("commercial_launch_blocked")
        concrete_blockers = list(dict.fromkeys(concrete_blockers))
        scorecard_items = [
            {
                "item_name": "product_design_evidence",
                "label": "Product Design evidence",
                "owner": "Product design owner",
                "sources": [
                    "docs/plugin_driven_design_brief.md",
                    "docs/commercial_plugin_operating_model.md",
                    "docs/screen_design.md",
                    "/admin",
                    "/api/v1/commercial_readiness/latest",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "docs/plugin_driven_design_brief.md",
                        "docs/commercial_plugin_operating_model.md",
                        "docs/screen_design.md",
                    )
                )
                and admin_state["agents"]
                else "blocked",
                "evidence": "Buyer, operator, security/compliance, and procurement workflows map to admin and readiness evidence.",
                "action": "Keep buyer evidence paths visible in the existing admin control plane.",
                "exit_criteria": "Every persona has a product/API/docs evidence path.",
            },
            {
                "item_name": "figma_artifacts",
                "label": "Figma artifacts",
                "owner": "Figma owner",
                "sources": [
                    "docs/figma_artifacts.md",
                    "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                    "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                ],
                "evidence_type": "figma_artifact",
                "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
                "evidence": "Editable design, FigJam diagrams, and stakeholder artifact records exist without Code Connect.",
                "action": "Use Figma/FigJam artifacts for stakeholder review without generating Code Connect metadata.",
                "exit_criteria": "Figma artifacts are recorded and Code Connect remains unused.",
            },
            {
                "item_name": "superpowers_plan_evidence",
                "label": "Superpowers plan evidence",
                "owner": "Implementation owner",
                "sources": [
                    "docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md",
                    "docs/superpowers/plans/2026-07-02-commercial-launch-readiness.md",
                    "tests/test_commercial_completion_scorecard.py",
                ],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if has_file("docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md")
                and has_file("tests/test_commercial_completion_scorecard.py")
                else "blocked",
                "evidence": "Dated plans and focused tests define files, expected failures, implementation, and verification commands.",
                "action": "Keep TDD plans and verification commands committed with the scorecard.",
                "exit_criteria": "Plan and focused test exist for the runtime scorecard.",
            },
            {
                "item_name": "ponytail_packaging_decision",
                "label": "Ponytail packaging decision",
                "owner": "Procurement and security reviewer",
                "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready"
                if launch["library_split_decision"]["decision"] == "keep_single_product"
                else "warning",
                "evidence": launch["library_split_decision"]["reason"],
                "action": "Keep one repository and one deployable product until extraction triggers are real.",
                "exit_criteria": "No separate library, Git submodule, or extracted package is created for this increment.",
            },
            {
                "item_name": "data_analytics_truthfulness",
                "label": "Data Analytics truthfulness",
                "owner": "Analytics owner",
                "sources": [
                    "docs/analytics_spec.md",
                    "/api/v1/analytics_snapshots/latest",
                    "/api/v1/commercial_launch_readiness/latest",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot"
                else "blocked",
                "evidence": "Measured local evidence and proposed production or buyer-specific inputs are separated.",
                "action": "Do not present proposed buyer or production inputs as measured product results.",
                "exit_criteria": "Every commercial KPI has an evidence type and source expectation.",
            },
            {
                "item_name": "runtime_endpoint_chain",
                "label": "Runtime endpoint chain",
                "owner": "Platform operator",
                "sources": [
                    "/api/v1/commercial_readiness/latest",
                    "/api/v1/commercial_go_to_market_readiness/latest",
                    "/api/v1/commercial_launch_readiness/latest",
                    "/api/v1/commercial_completion_scorecards/latest",
                ],
                "evidence_type": "repository_and_runtime_artifact",
                "completion_state": "ready"
                if commercial["commercial_status"] != "not_commercial_ready"
                and gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
                and launch["launch_status"] != "commercial_launch_blocked"
                else "blocked",
                "evidence": (
                    f"commercial_status={commercial['commercial_status']}; "
                    f"go_to_market_status={gtm['go_to_market_status']}; "
                    f"launch_status={launch['launch_status']}"
                ),
                "action": "Expose completion status through the same admin-protected runtime API chain.",
                "exit_criteria": "Runtime chain has no blocked local evidence gate.",
            },
            {
                "item_name": "verification_packet",
                "label": "Verification packet",
                "owner": "Technical reviewer",
                "sources": [
                    "tests/test_commercial_completion_scorecard.py",
                    "tests/test_commercial_launch_readiness.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                    "pytest -q",
                ],
                "evidence_type": "measured_local",
                "completion_state": "ready"
                if all(
                    has_file(path)
                    for path in (
                        "tests/test_commercial_completion_scorecard.py",
                        "tests/test_commercial_launch_readiness.py",
                        "tests/test_plugin_driven_artifacts.py",
                        "tests/test_api_contract.py",
                    )
                )
                else "blocked",
                "evidence": "Focused completion, launch, artifact, and API contract tests are present.",
                "action": "Run focused tests and full pytest before presenting completion status.",
                "exit_criteria": "Focused tests, compileall, full pytest, and diff hygiene pass.",
            },
            {
                "item_name": "review_process_policy",
                "label": "Review process policy",
                "owner": "Deal owner",
                "sources": ["docs/commercial_completion_scorecard.md", "docs/commercial_launch_readiness.md"],
                "evidence_type": "repository_artifact",
                "completion_state": "ready",
                "evidence": "Review delay, model-review delay, and queued review automation are not product blockers.",
                "action": "Block only on concrete security, API contract, document, or functional defects.",
                "exit_criteria": "Review process delay remains non-blocking without concrete failure evidence.",
            },
            {
                "item_name": "production_buyer_followups",
                "label": "Production and buyer follow-ups",
                "owner": "Buyer sponsor, operations owner, and deal owner",
                "sources": [
                    "/api/v1/commercial_launch_readiness/latest",
                    "buyer environment",
                    "production telemetry",
                    "commercial signatures",
                ],
                "evidence_type": "external_input_required",
                "completion_state": "warning",
                "source_gap_status": "external_input_required",
                "evidence": (
                    f"external_input_group_count={launch['launch_summary']['external_input_group_count']}; "
                    f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}"
                ),
                "action": "Collect buyer environment, production telemetry, and signature inputs or explicit waivers.",
                "exit_criteria": "Buyer supplies or waives remaining external inputs.",
            },
        ]
        state_counts = Counter(item["completion_state"] for item in scorecard_items)
        blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
        warning_count = state_counts.get("warning", 0)
        if blocked_count:
            completion_status = "commercial_completion_blocked"
        elif warning_count:
            completion_status = "commercial_completion_ready_with_warnings"
        else:
            completion_status = "commercial_completion_ready"

        return {
            "completion_status": completion_status,
            "target_contract_value_krw": target_contract_value_krw,
            "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
            "measurement_status": "local_commercial_completion_scorecard",
            "source_note": (
                "Commercial completion scorecard aggregates repo-local product design, Figma, Superpowers, "
                "Ponytail, Data Analytics, runtime, verification, review-process, and packaging evidence "
                "separately from buyer and production follow-ups; it is not a valuation guarantee, purchase "
                "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
            ),
            "completion_summary": {
                "item_count": len(scorecard_items),
                "ready_count": state_counts.get("ready", 0),
                "warning_count": warning_count,
                "blocked_count": blocked_count,
                "external_input_group_count": launch["launch_summary"]["external_input_group_count"],
                "review_process_is_blocker": launch["review_process_policy"]["is_blocker"],
                "code_connect_used": False,
            },
            "completion_items": scorecard_items,
            "concrete_blockers": concrete_blockers,
            "completion_status_rules": [
                {
                    "completion_status": "commercial_completion_ready",
                    "rule": "product design, Figma, Superpowers, Ponytail, Data Analytics, runtime, verification, review policy, packaging, and external inputs are ready",
                },
                {
                    "completion_status": "commercial_completion_ready_with_warnings",
                    "rule": "repo-local program completion evidence is ready while buyer environment, production telemetry, commercial signatures, or other external inputs remain explicit warnings",
                },
                {
                    "completion_status": "commercial_completion_blocked",
                    "rule": "security failure, API contract regression, document mismatch, reproducible product defect, missing local completion evidence, or Code Connect usage blocks completion",
                },
            ],
            "review_process_policy": launch["review_process_policy"],
            "related_runtime_reports": {
                "commercial_readiness_status": commercial["commercial_status"],
                "commercial_go_to_market_status": gtm["go_to_market_status"],
                "commercial_launch_status": launch["launch_status"],
                "analytics_measurement_status": analytics["measurement_status"],
            },
            "library_split_decision": launch["library_split_decision"],
            "plugin_traceability": launch["plugin_traceability"],
            "completion_links": {
                "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
                "runtime_endpoint": "/api/v1/commercial_completion_scorecards/latest",
                "documentation": "docs/commercial_completion_scorecard.md",
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
