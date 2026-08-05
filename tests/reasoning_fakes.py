"""Deterministic runtime fakes shared by reasoning-control tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Iterator

from contextual_orchestrator.reasoning_control import ReasoningDecision, ReasoningPolicy, ReasoningProfile
from contextual_orchestrator.reasoning_runtime import (
    agent_reasoning_profile,
    configure_agent_reasoning,
    current_reasoning_decision,
    install_reasoning_control,
    orchestrator_reasoning_policy,
    reasoning_override,
)


@dataclass(frozen=True)
class FakeAgent:
    """Small hashable stand-in for the repository's model-agent value object."""

    id: str
    model: str
    tags: tuple[str, ...] = ()
    disabled: bool = False
    provider_exclusions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FakeAgent":
        """Build an agent from normal configuration fields."""
        return cls(
            id=value["id"],
            model=value["model"],
            tags=tuple(value.get("tags", ())),
        )

    def to_config(self) -> dict[str, Any]:
        """Return normal configuration fields."""
        return {"id": self.id, "model": self.model, "tags": list(self.tags)}


@dataclass(frozen=True)
class FakePolicy:
    """Stand-in for the repository's orchestration policy snapshot."""

    verifier_required: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return the base policy snapshot."""
        return {"verifier_required": self.verifier_required}


class FakeClient:
    """Provider client seam that exposes payloads and deterministic usage."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._usage: dict[str, Any] | None = None

    def take_usage(self) -> dict[str, Any] | None:
        """Return and clear the most recent deterministic usage record."""
        usage, self._usage = self._usage, None
        return usage

    def chat(self, agent: FakeAgent, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Construct a normal chat payload and delegate to the send seam."""
        payload = {
            "model": agent.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        return self._send(agent, payload)

    def _send(self, agent: FakeAgent, payload: dict[str, Any]) -> str:
        """Record one chat payload and produce effort-dependent deterministic output."""
        self.sent.append(payload)
        effort = payload.get("reasoning_effort", "none")
        reasoning_tokens = {"minimal": 2, "low": 4, "medium": 12, "high": 24}.get(effort, 0)
        self._usage = {
            "total_tokens": 20 + reasoning_tokens,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        }
        role = "worker"
        system = messages_system(payload.get("messages", []))
        for candidate in ("thinker", "worker", "verifier", "synthesizer"):
            if f"Role: {candidate}" in system:
                role = candidate
        if role == "worker":
            return "42" if effort in {"medium", "high"} else "41"
        if role == "verifier":
            user = messages_user(payload.get("messages", []))
            return "verified accepted" if "42" in user else "reject incorrect result"
        if role == "synthesizer":
            return "final 42"
        return "plan"

    def stream_chat(
        self,
        agent: FakeAgent,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Yield the same answer in two deterministic chunks."""
        value = self.chat(agent, messages, temperature)
        yield value[:1]
        yield value[1:]

    def _stream_send(self, agent: FakeAgent, payload: dict[str, Any]) -> Iterator[str]:
        """Record a streaming payload and yield one marker."""
        self.sent.append(payload)
        yield "stream"

    def proxy_send(self, agent: FakeAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Delegate full-shape passthrough to the raw send seam."""
        return self._send_raw(agent, endpoint, payload)

    def _send_raw(self, agent: FakeAgent, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record passthrough payload and return it for assertions."""
        self.sent.append(payload)
        return {"endpoint": endpoint, "payload": payload}

    def batch_chat(
        self,
        agent: FakeAgent,
        requests: dict[str, list[dict[str, str]]],
        temperature: float = 0.2,
        poll_interval: float = 5.0,
        poll_timeout: float = 3600.0,
    ) -> dict[str, dict[str, Any]]:
        """Build Batch JSONL, pass through upload, and return deterministic results."""
        lines = [
            json.dumps(
                {
                    "custom_id": custom_id,
                    "body": {"model": agent.model, "messages": messages, "temperature": temperature},
                }
            )
            for custom_id, messages in requests.items()
        ]
        self._batch_upload(agent, "\n".join(lines).encode("utf-8"))
        return {
            custom_id: {
                "content": "batch",
                "usage": {"total_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 2}},
            }
            for custom_id in requests
        }

    def _batch_upload(self, agent: FakeAgent, payload: bytes) -> str:
        """Record decoded Batch JSONL bodies."""
        self.sent.extend(json.loads(line)["body"] for line in payload.decode().splitlines())
        return "file_1"


def messages_system(messages: list[dict[str, str]]) -> str:
    """Return concatenated system content from a fake chat payload."""
    return "\n".join(item.get("content", "") for item in messages if item.get("role") == "system")


def messages_user(messages: list[dict[str, str]]) -> str:
    """Return concatenated user content from a fake chat payload."""
    return "\n".join(item.get("content", "") for item in messages if item.get("role") == "user")


class FakeOrchestrator:
    """Minimal orchestration core matching the extension's stable seams."""

    def __init__(self, agents: list[FakeAgent], client: FakeClient | None = None) -> None:
        self.agents = agents
        self.client = client or FakeClient()
        self.policy = FakePolicy()

    def _agent(self, agent_id: str) -> FakeAgent:
        return next(agent for agent in self.agents if agent.id == agent_id)

    def _select_agent(self, _text: str, role: str) -> FakeAgent:
        return next((agent for agent in self.agents if role in agent.tags), self.agents[0])

    def _invoke(
        self,
        primary: FakeAgent,
        messages: list[dict[str, str]],
        *,
        text: str,
        role: str,
    ) -> tuple[str, str, dict[str, Any] | None]:
        output = self.client.chat(primary, messages)
        return output, primary.id, self.client.take_usage()

    def route_once(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        task = messages_user(messages)
        agent = self._select_agent(task, "worker")
        output, served, usage = self._invoke(agent, messages, text=task, role="worker")
        return {
            "mode": "route",
            "answer": output,
            "trace": [
                {
                    "id": 0,
                    "role": "worker",
                    "agent_id": agent.id,
                    "served_agent_id": served,
                    "subtask": "Direct route",
                    "access": [],
                    "output": output,
                    "usage": usage,
                }
            ],
            "verification": {"accepted": True},
        }

    def conduct(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        task = messages_user(messages)
        trace: list[dict[str, Any]] = []
        outputs: dict[int, str] = {}
        roles = ("thinker", "worker", "verifier", "synthesizer")
        access = ((), (0,), (0, 1), (0, 1, 2))
        for index, role in enumerate(roles):
            agent = self._select_agent(task, role)
            prior = "\n".join(outputs[item] for item in access[index])
            step_messages = [
                {"role": "system", "content": f"Role: {role}. Complete the subtask."},
                {
                    "role": "user",
                    "content": f"Original task:\n{task}\n\nAccessed prior work:\n{prior}\n\nSubtask:\n{role}",
                },
            ]
            output, served, usage = self._invoke(agent, step_messages, text=task, role=role)
            outputs[index] = output
            trace.append(
                {
                    "id": index,
                    "role": role,
                    "agent_id": agent.id,
                    "served_agent_id": served,
                    "subtask": role,
                    "access": list(access[index]),
                    "output": output,
                    "usage": usage,
                }
            )
        verification = self._judge_verifier_output(outputs[2], outputs[0], outputs[1])
        return {
            "mode": "conduct",
            "answer": outputs[3] if verification["accepted"] else outputs[1],
            "trace": trace,
            "verification": verification,
        }

    def _dispatch(self, messages: list[dict[str, str]], mode: str) -> dict[str, Any]:
        return self.route_once(messages) if mode == "route" else self.conduct(messages)

    def stream_route(
        self,
        messages: list[dict[str, str]],
        workflow_run_id: str | None = None,
    ) -> Iterator[str]:
        agent = self._select_agent(messages_user(messages), "worker")
        yield from self.client.stream_chat(agent, messages)

    def batch_route(self, prompts: list[str]) -> list[dict[str, Any]]:
        agent = self._select_agent("", "worker")
        requests = {
            f"task_{index}": [{"role": "user", "content": prompt}]
            for index, prompt in enumerate(prompts)
        }
        results = self.client.batch_chat(agent, requests)
        return [
            {
                "trace": [
                    {
                        "id": 0,
                        "role": "worker",
                        "agent_id": agent.id,
                        "subtask": "batch",
                        "access": [],
                        "output": results[f"task_{index}"]["content"],
                        "usage": results[f"task_{index}"]["usage"],
                    }
                ],
                "verification": {"accepted": True},
            }
            for index in range(len(prompts))
        ]

    def proxy_completion(self, body: dict[str, Any], *, endpoint: str = "chat/completions") -> dict[str, Any]:
        agent = self._select_agent("", "worker")
        return self.client.proxy_send(agent, endpoint, body)

    def _plan_generated(self, task: str) -> str:
        agent = self._select_agent(task, "thinker")
        return self.client.chat(agent, [{"role": "system", "content": "Role: thinker"}, {"role": "user", "content": task}])

    def _model_judge_verification(self, task: str, fallback: dict[str, Any]) -> dict[str, Any]:
        agent = self._select_agent(task, "verifier")
        result = self.client.chat(agent, [{"role": "system", "content": "Role: verifier"}, {"role": "user", "content": task}])
        return {"accepted": "accepted" in result, "verifier_output": result, **fallback}

    def _judge_verifier_output(self, verifier: str, _thinker: str, worker: str) -> dict[str, Any]:
        return {"accepted": "accepted" in verifier and worker == "42", "verifier_output": verifier}


def common_profile() -> ReasoningProfile:
    """Return the profile shared by all fake role agents."""
    return ReasoningProfile(
        supported_levels=("minimal", "low", "medium", "high"),
        default_level="low",
        maximum_level="high",
    )


def make_orchestrator() -> FakeOrchestrator:
    """Build and configure four distinct role agents."""
    agents = [
        FakeAgent("thinker_agent", "thinker-model", ("thinker",)),
        FakeAgent("worker_agent", "worker-model", ("worker",)),
        FakeAgent("verifier_agent", "verifier-model", ("verifier",)),
        FakeAgent("synth_agent", "synth-model", ("synthesizer",)),
    ]
    for agent in agents:
        configure_agent_reasoning(agent, common_profile())
    return FakeOrchestrator(agents, reasoning_policy=ReasoningPolicy())


install_reasoning_control(FakeAgent, FakeClient, FakeOrchestrator, FakePolicy)
install_reasoning_control(FakeAgent, FakeClient, FakeOrchestrator, FakePolicy)
