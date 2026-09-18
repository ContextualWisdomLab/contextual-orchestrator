"""Regression tests for endpoint-race observer failure settlement."""

from __future__ import annotations

import threading

from contextual_orchestrator.endpoint_race import (
    EndpointAttempt,
    EndpointEquivalenceContract,
    race_first_valid,
)


def _contract() -> EndpointEquivalenceContract:
    """Return one complete equivalence contract for callback-settlement tests."""
    return EndpointEquivalenceContract(
        contract_id="callback_settlement_contract",
        model_revision="revision_2026_09",
        reasoning_effort_profile="worker_medium",
        capability_set=("text",),
        structured_output_contract="openai_response_v1",
        accuracy_class="full_precision",
        data_residency_policy="kr_region_only",
        retention_policy="zero_retention",
        context_limit=128_000,
        pricing_evidence_id="catalog_snapshot_2026_09_02",
        hedge_eligible=True,
        cancellation_supported=False,
        execution_policy="immediate_race",
    )


def _run_unbounded_race(
    attempts: list[EndpointAttempt[str]],
    callback,
) -> BaseException:
    """Run a no-deadline race and prove it terminates even if observers fail."""
    completed = threading.Event()
    observed: dict[str, BaseException] = {}

    def run() -> None:
        try:
            race_first_valid(
                attempts,
                validate=bool,
                deadline_seconds=None,
                max_concurrency=2,
                on_attempt_complete=callback,
            )
        except BaseException as exc:
            observed["exception"] = exc
        finally:
            completed.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert completed.wait(1), "callback failure left a no-deadline race unsettled"
    assert "exception" in observed
    return observed["exception"]


def test_success_observer_failure_settles_managed_future() -> None:
    """A callback failure after a valid result must become a settled race failure."""
    shared = _contract()

    def callback(_endpoint: str, _value: str | None, _error: BaseException | None) -> None:
        raise RuntimeError("observer failed after success")

    error = _run_unbounded_race(
        [
            EndpointAttempt("first_endpoint", shared, lambda: "first"),
            EndpointAttempt("second_endpoint", shared, lambda: "second"),
        ],
        callback,
    )

    assert isinstance(error, RuntimeError)
    assert isinstance(error.__cause__, RuntimeError)
    assert str(error.__cause__) == "observer failed after success"


def test_failure_observer_failure_settles_managed_future() -> None:
    """A callback failure while reporting a provider error must not strand the race."""
    shared = _contract()
    provider_errors: list[type[BaseException]] = []

    def provider_failure() -> str:
        raise OSError("provider failed")

    def callback(_endpoint: str, _value: str | None, error: BaseException | None) -> None:
        assert error is not None
        provider_errors.append(type(error))
        raise LookupError("observer failed while reporting provider failure")

    error = _run_unbounded_race(
        [
            EndpointAttempt("first_endpoint", shared, provider_failure),
            EndpointAttempt("second_endpoint", shared, provider_failure),
        ],
        callback,
    )

    assert provider_errors == [OSError, OSError]
    assert isinstance(error, RuntimeError)
    assert isinstance(error.__cause__, LookupError)
    assert str(error.__cause__) == "observer failed while reporting provider failure"
