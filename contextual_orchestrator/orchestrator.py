from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import time
import urllib.request
from typing import Any

from .conventions import require_object_name


ChatMessage = dict[str, str]


@dataclass(frozen=True)
class ModelAgent:
    id: str
    model: str
    base_url: str = "mock://local"
    api_key_env: str = ""
    tags: tuple[str, ...] = ()
    priority: int = 0
    disabled: bool = False

    def __post_init__(self) -> None:
        require_object_name(self.id, "agent.id")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelAgent":
        require_object_name(value["id"], "agent.id")
        return cls(
            id=value["id"],
            model=value["model"],
            base_url=value.get("base_url", "mock://local"),
            api_key_env=value.get("api_key_env", ""),
            tags=tuple(value.get("tags", ())),
            priority=int(value.get("priority", 0)),
            disabled=bool(value.get("disabled", False)),
        )


@dataclass(frozen=True)
class WorkflowStep:
    id: int
    role: str
    agent_id: str
    subtask: str
    access: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "agent_id": self.agent_id,
            "subtask": self.subtask,
            "access": list(self.access),
        }


class ModelClient:
    def __init__(self, timeout: int = 90) -> None:
        self.timeout = timeout

    def chat(self, agent: ModelAgent, messages: list[ChatMessage], temperature: float = 0.2) -> str:
        if agent.base_url.startswith("mock://"):
            return self._mock(agent, messages)

        api_key = os.environ.get(agent.api_key_env or "OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(f"{agent.id} requires ${agent.api_key_env or 'OPENAI_API_KEY'}")

        payload = {
            "model": agent.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
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

    def _mock(self, agent: ModelAgent, messages: list[ChatMessage]) -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        role = "worker"
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        match = re.search(r"Role: ([a-z]+)", system)
        if match:
            role = match.group(1)
        return f"[{agent.id}:{role}] {last[:220]}"


def load_agents(path: str) -> list[ModelAgent]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [ModelAgent.from_dict(item) for item in data["agents"]]


class TaskOrchestrator:
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
        if not self.agents:
            raise ValueError("at least one enabled agent is required")
        self.client = client or ModelClient()

    def complete(self, messages: list[ChatMessage], mode: str = "auto") -> dict[str, Any]:
        text = self._latest_user_text(messages)
        if mode == "route" or (mode == "auto" and not self._needs_workflow(text)):
            return self.route_once(messages)
        return self.conduct(messages)

    def route_once(self, messages: list[ChatMessage]) -> dict[str, Any]:
        text = self._latest_user_text(messages)
        agent = self._select_agent(text, "worker")
        answer = self.client.chat(agent, messages)
        return {
            "mode": "route",
            "answer": answer,
            "trace": [{"role": "worker", "agent_id": agent.id, "access": []}],
        }

    def conduct(self, messages: list[ChatMessage]) -> dict[str, Any]:
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
            outputs[step.id] = self.client.chat(agent, step_messages)
            row = step.as_dict()
            row["output"] = outputs[step.id]
            trace.append(row)

        return {"mode": "conduct", "answer": outputs[steps[-1].id], "trace": trace}

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
            role_score = sum(3 for tag in agent.tags if tag in self.ROLE_TAGS.get(role, ()))
            domain_score = 0
            for tag, hints in self.DOMAIN_HINTS.items():
                if tag in agent.tags and any(hint in lowered for hint in hints):
                    domain_score += 2
            return (role_score + domain_score + agent.priority, len(agent.tags), agent.id)

        return max(self.agents, key=score)

    def _agent(self, agent_id: str) -> ModelAgent:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(agent_id)

    def _needs_workflow(self, text: str) -> bool:
        lowered = text.lower()
        hits = sum(1 for hint in self.COMPLEX_HINTS if hint in lowered)
        return hits >= 2 or len(text) > 700

    def _latest_user_text(self, messages: list[ChatMessage]) -> str:
        return next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")

    def admin_state(self) -> dict[str, Any]:
        return {
            "agents": [
                {
                    "id": agent.id,
                    "model": agent.model,
                    "base_url": agent.base_url,
                    "tags": list(agent.tags),
                    "priority": agent.priority,
                }
                for agent in self.agents
            ],
            "policy": {
                "roles": list(self.ROLE_TAGS),
                "complex_hints": list(self.COMPLEX_HINTS),
                "workflow_steps": ["thinker", "worker", "verifier", "synthesizer"],
                "supported_locales": ["en", "ko"],
            },
        }


def chat_completion_response(result: dict[str, Any], model: str = "contextual-orchestrator") -> dict[str, Any]:
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
        "orchestration": {"mode": result["mode"], "trace": result["trace"]},
    }
