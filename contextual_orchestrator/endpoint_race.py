"""Bounded execution for explicitly equivalent provider endpoints."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import dataclass
import time
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class EndpointEquivalenceContract:
    """Operator-reviewed fields that must match before endpoints may race."""

    contract_id: str
    model_revision: str
    reasoning_effort_profile: str
    capability_set: tuple[str, ...]
    structured_output_contract: str
    accuracy_class: str
    data_residency_policy: str
    retention_policy: str
    context_limit: int
    pricing_evidence_id: str
    hedge_eligible: bool
    cancellation_supported: bool
    execution_policy: str

    def __post_init__(self) -> None:
        values = (
            self.contract_id,
            self.model_revision,
            self.reasoning_effort_profile,
            self.structured_output_contract,
            self.accuracy_class,
            self.data_residency_policy,
            self.retention_policy,
            self.pricing_evidence_id,
        )
        if any(type(value) is not str or not value.strip() for value in values):
            raise ValueError("every equivalence field must be explicitly declared")
        if type(self.context_limit) is not int or self.context_limit <= 0:
            raise ValueError("context_limit must be a positive integer")
        if not self.capability_set or any(type(value) is not str for value in self.capability_set):
            raise ValueError("capability_set must be explicitly declared")
        object.__setattr__(self, "capability_set", tuple(sorted(set(self.capability_set))))
        if type(self.hedge_eligible) is not bool or type(self.cancellation_supported) is not bool:
            raise TypeError("hedge and cancellation declarations must be boolean")
        if self.execution_policy not in {"sequential_failover", "immediate_race"}:
            raise ValueError("unsupported endpoint execution policy")


@dataclass(frozen=True)
class EndpointAttempt(Generic[T]):
    """One endpoint call and the evidence required to execute it."""

    endpoint_id: str
    contract: EndpointEquivalenceContract
    call: Callable[[], T]
    cancellation_supported: bool = False
    cancel: Callable[[], None] | None = None


@dataclass(frozen=True)
class RaceOutcome(Generic[T]):
    """Winner plus deterministic, secret-free attempt provenance."""

    value: T
    winner_endpoint_id: str
    attempted_endpoint_ids: tuple[str, ...]
    cancellation_outcomes: tuple[tuple[str, str], ...]
    completion_ms: float


def race_first_valid(
    attempts: list[EndpointAttempt[T]],
    *,
    validate: Callable[[T], bool],
    deadline_seconds: float | None,
    max_concurrency: int,
    on_attempt_complete: Callable[[str, T | None, BaseException | None], None] | None = None,
) -> RaceOutcome[T]:
    """Return the first complete valid result from one proven equivalence class.

    Simultaneous valid completions use declaration order. Running transports that
    cannot be cancelled are safely ignored after winner publication.
    """
    if len(attempts) < 2:
        raise ValueError("a race requires at least two endpoint attempts")
    if max_concurrency < 2:
        raise ValueError("immediate_race requires concurrency capacity of at least two")
    if max_concurrency < len(attempts):
        raise ValueError("immediate_race capacity must cover every declared endpoint")
    if deadline_seconds is not None and deadline_seconds <= 0:
        raise ValueError("deadline_seconds must be positive")
    contract = attempts[0].contract
    if any(attempt.contract != contract for attempt in attempts[1:]):
        raise ValueError("endpoint equivalence cannot be proven")
    if len({attempt.endpoint_id for attempt in attempts}) != len(attempts):
        raise ValueError("endpoint identifiers must be unique")

    started = time.monotonic()
    pool = ThreadPoolExecutor(
        max_workers=min(max_concurrency, len(attempts)),
        thread_name_prefix="equivalent_endpoint_race",
    )
    def execute(attempt: EndpointAttempt[T]) -> T:
        try:
            value = attempt.call()
            if not validate(value):
                raise ValueError("endpoint returned an invalid completed response")
        except BaseException as exc:
            if on_attempt_complete is not None:
                on_attempt_complete(attempt.endpoint_id, None, exc)
            raise
        if on_attempt_complete is not None:
            on_attempt_complete(attempt.endpoint_id, value, None)
        return value

    futures: dict[Future[T], tuple[int, EndpointAttempt[T]]] = {
        pool.submit(copy_context().run, execute, attempt): (index, attempt)
        for index, attempt in enumerate(attempts)
    }
    pending = set(futures)
    last_error: BaseException | None = None
    cancellation_outcomes: dict[Future[T], str] = {}

    def cancel_loser(future: Future[T], attempt: EndpointAttempt[T]) -> str:
        if future in cancellation_outcomes:
            return cancellation_outcomes[future]
        if future.done():
            outcome = "completed"
        elif future.cancel():
            outcome = "queued_cancelled"
        elif (
            contract.cancellation_supported
            and attempt.cancellation_supported
            and attempt.cancel is not None
        ):
            attempt.cancel()
            outcome = "cancellation_requested"
        else:
            outcome = "safe_drain"
        cancellation_outcomes[future] = outcome
        return outcome

    try:
        while pending:
            remaining = (
                None
                if deadline_seconds is None
                else deadline_seconds - (time.monotonic() - started)
            )
            if remaining is not None and remaining <= 0:
                raise TimeoutError("equivalent endpoint race exceeded its deadline")
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                raise TimeoutError("equivalent endpoint race exceeded its deadline")
            for future in sorted(done, key=lambda item: futures[item][0]):
                try:
                    value = future.result()
                except BaseException as exc:  # retain the final provider cause
                    last_error = exc
                    continue
                winner = futures[future][1]
                cancellations: list[tuple[str, str]] = []
                for loser_future, (_, loser) in futures.items():
                    if loser_future is future:
                        continue
                    outcome = cancel_loser(loser_future, loser)
                    cancellations.append((loser.endpoint_id, outcome))
                pool.shutdown(wait=False, cancel_futures=True)
                return RaceOutcome(
                    value=value,
                    winner_endpoint_id=winner.endpoint_id,
                    attempted_endpoint_ids=tuple(attempt.endpoint_id for attempt in attempts),
                    cancellation_outcomes=tuple(cancellations),
                    completion_ms=round((time.monotonic() - started) * 1000, 3),
                )
    finally:
        for future in pending:
            cancel_loser(future, futures[future][1])
        pool.shutdown(wait=False, cancel_futures=True)
    raise RuntimeError("all equivalent endpoints failed validation") from last_error
