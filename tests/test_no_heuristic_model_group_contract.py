"""Measured group telemetry must not synthesize an unvalidated route objective."""

from __future__ import annotations

import pytest

from contextual_orchestrator.model_group import ModelGroupRouter


def test_posterior_and_latency_remain_separate_diagnostic_evidence() -> None:
    router = ModelGroupRouter()
    router.observe_success("member_one", 0.5, output_tokens=20, total_tokens=40)

    report = router.member_report("member_one")

    assert report["success_posterior_mean"] == pytest.approx(2.0 / 3.0)
    assert report["ewma_latency_seconds"] == pytest.approx(0.5)
    assert report["ewma_tokens_per_second"] == pytest.approx(40.0)
    assert report["score"] is None


def test_member_score_is_retired_as_routing_authority() -> None:
    router = ModelGroupRouter()
    router.observe_success("member_one", 0.1)

    with pytest.raises(RuntimeError, match="composite routing score"):
        router.member_score("member_one")


def test_multiple_group_members_are_not_ranked_by_diagnostic_telemetry() -> None:
    router = ModelGroupRouter()
    router.observe_failure("member_one")
    router.observe_success("member_two", 0.1)

    with pytest.raises(RuntimeError, match="routing model"):
        router.ranked_member_ids(["member_one", "member_two"])


def test_single_group_member_needs_no_routing_model() -> None:
    router = ModelGroupRouter()

    assert router.ranked_member_ids(["only_member"]) == ["only_member"]
