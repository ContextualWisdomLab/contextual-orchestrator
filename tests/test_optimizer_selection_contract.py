"""Public optimizers fail closed before work without released selection authority."""

from types import SimpleNamespace

import pytest

from contextual_orchestrator.orchestrator import evolve_orchestration, optimize_orchestration


@pytest.mark.parametrize("optimizer_kind", ["optimize", "evolve"])
def test_optimizer_rejects_before_candidate_execution(optimizer_kind: str) -> None:
    """Missing fast-mlsirm selection authority cannot incur provider work."""
    def unexpected_call(*args, **kwargs):
        raise AssertionError("candidate execution must not begin")

    candidate = SimpleNamespace(
        run=unexpected_call,
        batch_route=unexpected_call,
        spend_analytics=unexpected_call,
    )
    with pytest.raises(RuntimeError, match="released fast-mlsirm candidate-selection contract"):
        if optimizer_kind == "evolve":
            evolve_orchestration(
                unexpected_call,
                {"mode": ["route"]},
                [{"prompt": "reference task"}],
                unexpected_call,
                generations=1,
                population=1,
            )
        else:
            optimize_orchestration(
                [{"name": "reference", "orchestrator": candidate, "mode": "route"}],
                [{"prompt": "reference task"}],
                unexpected_call,
            )
