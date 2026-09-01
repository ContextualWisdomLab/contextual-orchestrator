"""Regression coverage for model-judge usage provenance.

A provider may authoritatively report an all-zero usage mapping, while the
repository's mock transport and fast-mlsirm can also synthesize the same value
shape when no measured usage exists. Accounting must distinguish those origins
instead of guessing from token counts alone. The transport boundary is also a
snapshot boundary: changing getters and later mutation must not rewrite the
captured evidence.
"""

from __future__ import annotations

from unittest.mock import patch

from contextual_orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.orchestrator import _FastMLSIJudgeAdapter


ZERO_USAGE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
}
RESPONSES_ZERO_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}


class _ChangingUsageResponse(dict[str, object]):
    """Expose a TOCTOU-sensitive ``get('usage')`` without altering other keys."""

    def __init__(self) -> None:
        super().__init__(
            choices=[
                {"message": {"content": '{"decision":"ACCEPT","reason":"ok"}'}}
            ]
        )
        self.usage_reads = 0

    def get(self, key: str, default: object = None) -> object:
        if key != "usage":
            return super().get(key, default)
        self.usage_reads += 1
        if self.usage_reads == 1:
            return dict(ZERO_USAGE)
        return {
            "prompt_tokens": 91,
            "completion_tokens": 37,
            "total_tokens": 128,
        }


def _adapter(*, usage_source: str | None) -> _FastMLSIJudgeAdapter:
    adapter = _FastMLSIJudgeAdapter(
        orchestrator=None,  # type: ignore[arg-type]
        text="task",
        judge="judge_agent",
        served_agent_id="judge_agent",
        served_model="judge-model",
        served_usage=dict(ZERO_USAGE),
        served_output="judge rationale",
    )
    # Regression-first compatibility: the pre-repair adapter has no declared
    # provenance field, so assigning it dynamically makes the RED exercise the
    # accounting decision rather than fail during object construction.
    adapter.served_usage_source = usage_source  # type: ignore[attr-defined]
    return adapter


def test_provider_reported_all_zero_usage_remains_reported() -> None:
    """Exact provider evidence must not be converted into estimated spend."""
    fields = TaskOrchestrator._judge_adapter_accounting_fields(
        _adapter(usage_source="provider_reported")
    )

    assert fields["judge_usage"] == ZERO_USAGE


def test_provider_reported_responses_zero_usage_remains_reported() -> None:
    """Responses-style input/output counters are equally authoritative evidence."""
    adapter = _adapter(usage_source="provider_reported")
    adapter.served_usage = dict(RESPONSES_ZERO_USAGE)

    fields = TaskOrchestrator._judge_adapter_accounting_fields(adapter)

    assert fields["judge_usage"] == RESPONSES_ZERO_USAGE


def test_synthetic_mock_all_zero_usage_remains_unmeasured() -> None:
    """The mock transport's zero fill must not become provider evidence."""
    fields = TaskOrchestrator._judge_adapter_accounting_fields(
        _adapter(usage_source="synthetic_mock")
    )

    assert "judge_usage" not in fields


def test_unknown_all_zero_usage_remains_unmeasured() -> None:
    """Missing provenance fails closed instead of asserting reported zero."""
    fields = TaskOrchestrator._judge_adapter_accounting_fields(
        _adapter(usage_source=None)
    )

    assert "judge_usage" not in fields


def test_structured_adapter_captures_provider_usage_source_at_transport_boundary() -> None:
    """Structured judge capture records whether zero usage came from a provider."""
    provider_agent = ModelAgent(
        "judge_agent",
        "judge-model",
        base_url="https://provider.example/v1",
        tags=("verification",),
    )
    orchestrator = TaskOrchestrator([provider_agent])
    adapter = _FastMLSIJudgeAdapter(orchestrator, "task", provider_agent.id)
    response = {
        "choices": [{"message": {"content": '{"decision":"ACCEPT","reason":"ok"}'}}],
        "usage": dict(ZERO_USAGE),
    }

    with patch.object(orchestrator.client, "proxy_send", return_value=response):
        adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    assert adapter.served_usage_source == "provider_reported"  # type: ignore[attr-defined]


def test_plain_adapter_captures_served_provider_usage_source() -> None:
    """Fallback-aware plain completion classifies the agent that actually served."""
    provider_agent = ModelAgent(
        "judge_agent",
        "judge-model",
        base_url="https://provider.example/v1",
        tags=("verification",),
    )
    orchestrator = TaskOrchestrator([provider_agent])
    adapter = _FastMLSIJudgeAdapter(orchestrator, "task", provider_agent.id)

    with patch.object(
        orchestrator,
        "_invoke",
        return_value=(
            "judge rationale",
            provider_agent.id,
            provider_agent.model,
            dict(ZERO_USAGE),
        ),
    ):
        adapter.complete([{"role": "user", "content": "judge"}])

    assert adapter.served_usage == ZERO_USAGE
    assert adapter.served_usage_source == "provider_reported"  # type: ignore[attr-defined]


def test_structured_adapter_reads_usage_once_at_transport_boundary() -> None:
    """A changing getter cannot substitute different usage after validation."""
    provider_agent = ModelAgent(
        "judge_agent",
        "judge-model",
        base_url="https://provider.example/v1",
        tags=("verification",),
    )
    orchestrator = TaskOrchestrator([provider_agent])
    adapter = _FastMLSIJudgeAdapter(orchestrator, "task", provider_agent.id)
    response = _ChangingUsageResponse()

    with patch.object(orchestrator.client, "proxy_send", return_value=response):
        adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    assert response.usage_reads == 1
    assert adapter.served_usage == ZERO_USAGE


def test_structured_adapter_snapshots_mutable_usage_alias() -> None:
    """Later mutation of the provider response cannot rewrite captured evidence."""
    provider_agent = ModelAgent(
        "judge_agent",
        "judge-model",
        base_url="https://provider.example/v1",
        tags=("verification",),
    )
    orchestrator = TaskOrchestrator([provider_agent])
    adapter = _FastMLSIJudgeAdapter(orchestrator, "task", provider_agent.id)
    reported_usage = dict(ZERO_USAGE)
    response = {
        "choices": [{"message": {"content": '{"decision":"ACCEPT","reason":"ok"}'}}],
        "usage": reported_usage,
    }

    with patch.object(orchestrator.client, "proxy_send", return_value=response):
        adapter.complete_structured(
            [{"role": "user", "content": "judge"}],
            response_format={"type": "json_object"},
        )

    reported_usage["prompt_tokens"] = 99
    reported_usage["total_tokens"] = 99
    assert adapter.served_usage == ZERO_USAGE


def test_structured_adapter_marks_mock_zero_usage_as_synthetic() -> None:
    """The identical mock value shape is explicitly non-authoritative."""
    mock_agent = ModelAgent(
        "judge_agent",
        "judge-model",
        base_url="mock://catalog",
        tags=("verification",),
    )
    orchestrator = TaskOrchestrator([mock_agent])
    adapter = _FastMLSIJudgeAdapter(orchestrator, "task", mock_agent.id)

    adapter.complete_structured(
        [{"role": "user", "content": "judge"}],
        response_format={"type": "json_object"},
    )

    assert adapter.served_usage == ZERO_USAGE
    assert adapter.served_usage_source == "synthetic_mock"  # type: ignore[attr-defined]
