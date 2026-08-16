"""Cost-performance worker selection: one chooser, not a YAML/list walk.

Fugu (Sakana AI, 2026) selects a single worker for the low-latency path.
FrugalGPT / RouteLLM / Hybrid LLM maximize quality per unit cost; unpriced
models are not given invented prices (Chen et al., 2023; Ong et al., 2024;
Ding et al., 2024). TRINITY role tags gate capability. Conductor workflows
are out of scope here — ``route_once`` picks one worker.

Exceptions re-run the same chooser on the remaining healthy pool. Seed JSON
order and prompt keywords must not decide the winner.
"""

from __future__ import annotations

from pathlib import Path
import sys
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    NotConfigured,
    register_credential,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


class _ScriptedClient(ModelClient):
    """Records call order and scripts per-agent outcomes."""

    def __init__(self, outcomes: dict[str, list[object]] | None = None) -> None:
        super().__init__(max_retries=0, retry_backoff=0.0)
        self.outcomes = {key: list(value) for key, value in (outcomes or {}).items()}
        self.calls: list[str] = []

    def chat(self, agent: ModelAgent, messages: list, temperature: float = 0.2) -> str:  # type: ignore[override]
        self.calls.append(agent.id)
        queue = self.outcomes.setdefault(agent.id, [])
        if not queue:
            return f"[{agent.id}] ok"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://provider.example/chat/completions", code, "err", None, None)


def _equivalent_priced_pool(*, expensive_first: bool) -> list[ModelAgent]:
    expensive = ModelAgent(
        "expensive_review_agent",
        "pricey-review-model",
        tags=("reasoning", "writing", "coding"),
    )
    cheap = ModelAgent(
        "cheap_review_agent",
        "thrifty-review-model",
        tags=("reasoning", "writing", "coding"),
    )
    return [expensive, cheap] if expensive_first else [cheap, expensive]


PRICES = {"thrifty-review-model": 1.0, "pricey-review-model": 40.0}


def test_cheaper_capable_worker_wins_over_more_expensive_equivalent() -> None:
    client = _ScriptedClient()
    orchestrator = TaskOrchestrator(
        _equivalent_priced_pool(expensive_first=True),
        client=client,
        price_per_million=PRICES,
    )
    result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert result["trace"][0]["agent_id"] == "cheap_review_agent"
    assert client.calls == ["cheap_review_agent"]


def test_seed_json_order_does_not_determine_the_winner() -> None:
    client_a = _ScriptedClient()
    client_b = _ScriptedClient()
    first = TaskOrchestrator(
        _equivalent_priced_pool(expensive_first=True),
        client=client_a,
        price_per_million=PRICES,
    )
    reversed_pool = TaskOrchestrator(
        _equivalent_priced_pool(expensive_first=False),
        client=client_b,
        price_per_million=PRICES,
    )
    prompt = [{"role": "user", "content": "Write a short status update."}]
    assert first.route_once(prompt)["trace"][0]["agent_id"] == "cheap_review_agent"
    assert reversed_pool.route_once(prompt)["trace"][0]["agent_id"] == "cheap_review_agent"
    assert client_a.calls == client_b.calls == ["cheap_review_agent"]


def test_prompt_keywords_do_not_override_cost_performance() -> None:
    # Old keyword scoring would boost a "coding" specialist on this prompt.
    # Both workers are equivalently capable; the expensive one must not win.
    expensive = ModelAgent(
        "keyword_heavy_agent",
        "pricey-review-model",
        tags=("reasoning", "writing", "coding", "implementation"),
    )
    cheap = ModelAgent(
        "thrifty_general_agent",
        "thrifty-review-model",
        tags=("reasoning", "writing", "coding", "implementation"),
    )
    orchestrator = TaskOrchestrator(
        [expensive, cheap],
        client=_ScriptedClient(),
        price_per_million=PRICES,
    )
    result = orchestrator.route_once(
        [{"role": "user", "content": "Please implement and debug this repository test code."}]
    )
    assert result["mode"] == "route"
    assert result["trace"][0]["agent_id"] == "thrifty_general_agent"


def test_429_reselects_with_chooser_not_next_in_file_order() -> None:
    # File order is expensive, then cheap. Chooser must pick cheap first.
    # After cheap 429s, re-run the chooser on the remaining pool (expensive),
    # not "the next name after expensive in the YAML".
    client = _ScriptedClient({"cheap_review_agent": [_http_error(429)]})
    orchestrator = TaskOrchestrator(
        _equivalent_priced_pool(expensive_first=True),
        client=client,
        price_per_million=PRICES,
    )
    result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert client.calls[0] == "cheap_review_agent"
    assert client.calls[1] == "expensive_review_agent"
    assert result["trace"][0]["served_agent_id"] == "expensive_review_agent"
    assert result["trace"][0]["failover_from"] == "cheap_review_agent"
    assert result["answer"] == "[expensive_review_agent] ok"


def test_unpriced_equivalent_is_not_given_an_invented_price() -> None:
    # Honest prior: when a priced capable worker exists, unpriced workers lose
    # (missing price is not treated as free).
    priced = ModelAgent("priced_review_agent", "thrifty-review-model", tags=("reasoning", "writing"))
    unpriced = ModelAgent("unpriced_review_agent", "mystery-review-model", tags=("reasoning", "writing"))
    orchestrator = TaskOrchestrator(
        [unpriced, priced],
        client=_ScriptedClient(),
        price_per_million={"thrifty-review-model": 2.0},
    )
    result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert result["trace"][0]["agent_id"] == "priced_review_agent"


def test_missing_credential_is_not_a_candidate() -> None:
    register_credential("OPENAI_API_KEY", "sk-only")
    missing = ModelAgent(
        "nim_missing_agent",
        "thrifty-review-model",
        "https://integrate.api.nvidia.com/v1",
        credential_key="NVIDIA_NIM_API_KEY",
        tags=("reasoning", "writing"),
    )
    present = ModelAgent(
        "openai_ready_agent",
        "pricey-review-model",
        "https://api.openai.com/v1",
        credential_key="OPENAI_API_KEY",
        tags=("reasoning", "writing"),
    )
    orchestrator = TaskOrchestrator(
        [missing, present],
        client=_ScriptedClient(),
        price_per_million=PRICES,
    )
    result = orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])
    assert result["trace"][0]["agent_id"] == "openai_ready_agent"


def test_empty_healthy_pool_fail_closes_without_github_models() -> None:
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "remote_openai_agent",
                "gpt-5.5",
                "https://api.openai.com/v1",
                credential_key="OPENAI_API_KEY",
                tags=("reasoning",),
            )
        ],
        client=_ScriptedClient(),
        price_per_million={"gpt-5.5": 5.0},
    )
    with pytest.raises(NotConfigured):
        orchestrator.route_once([{"role": "user", "content": "Write a short status update."}])


if __name__ == "__main__":  # pragma: no cover
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
