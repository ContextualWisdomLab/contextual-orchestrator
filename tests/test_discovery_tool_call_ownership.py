"""Regression coverage for operator/discovery tool-call tag ownership."""

from dataclasses import replace

from contextual_orchestrator.__main__ import _refresh_discovered_tool_call_tags
from contextual_orchestrator.model_discovery import DiscoveredModel


def _model(parallel: bool | None) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/parallel",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        supports_parallel_tool_calls=parallel,
    )


def test_same_single_operator_override_survives_discovery_withdrawal() -> None:
    """Matching negative discovery evidence must not consume operator authority."""
    operator_tags = ("discovered", "chat", "tool_call:single", "operator-tag")

    with_discovery = _refresh_discovered_tool_call_tags(operator_tags, _model(False))
    after_unknown = _refresh_discovered_tool_call_tags(
        with_discovery,
        replace(_model(False), supports_parallel_tool_calls=None),
    )

    assert "tool_call:single" in after_unknown
    assert "tool_call:multi" not in after_unknown
    assert "operator-tag" in after_unknown
    assert not any(tag.startswith("discovery:tool_call:") for tag in after_unknown)


def test_same_multi_operator_override_survives_discovery_withdrawal() -> None:
    """Matching positive discovery evidence must not consume operator authority."""
    operator_tags = ("discovered", "chat", "tool_call:multi", "operator-tag")

    with_discovery = _refresh_discovered_tool_call_tags(operator_tags, _model(True))
    after_unknown = _refresh_discovered_tool_call_tags(
        with_discovery,
        replace(_model(True), supports_parallel_tool_calls=None),
    )

    assert "tool_call:multi" in after_unknown
    assert "tool_call:single" not in after_unknown
    assert "operator-tag" in after_unknown
    assert not any(tag.startswith("discovery:tool_call:") for tag in after_unknown)
