"""Contracts for the time-windowed durable routing-observation boundary."""

from __future__ import annotations

import sqlite3

import pytest

from contextual_orchestrator.__main__ import main
from contextual_orchestrator.model_group import ModelGroupRouter
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.routing_observation_store import (
    SqliteRoutingObservationStore,
)


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_store_shares_current_window_and_keeps_ledgers_separate(tmp_path) -> None:
    clock = _Clock()
    path = tmp_path / "routing.sqlite"
    first = SqliteRoutingObservationStore(path, 10, clock=clock)
    second = SqliteRoutingObservationStore(path, 10, clock=clock)

    first.append("transport", "member_a", success=True, latency_seconds=0.2, output_tokens=20)
    first.append("transport", "member_b", success=False)
    first.append("quality", "member_a", success=True, latency_seconds=0.5)

    assert second.window_seconds == 10
    assert [(row.member_id, row.success) for row in second.load("transport")] == [
        ("member_a", True),
        ("member_b", False),
    ]
    assert [row.member_id for row in second.load("quality")] == ["member_a"]

    clock.value = 111
    assert second.load("transport") == []
    first.append("transport", "member_c", success=False)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM routing_observations").fetchone()[0] == 1
    first.close()
    second.close()


def test_store_deletes_only_requested_members(tmp_path) -> None:
    store = SqliteRoutingObservationStore(tmp_path / "routing.sqlite", 60)
    store.append("transport", "member_a", success=False)
    store.append("transport", "member_b", success=False)
    store.append("quality", "member_a", success=False)

    store.delete_members("transport", ["member_a", "member_a"])

    assert [row.member_id for row in store.load("transport")] == ["member_b"]
    assert [row.member_id for row in store.load("quality")] == ["member_a"]
    store.delete_members("transport", [])


@pytest.mark.parametrize(
    ("path", "window", "clock", "error"),
    [
        ("", 1, None, TypeError),
        ("routing.sqlite", 0, None, ValueError),
        ("routing.sqlite", True, None, ValueError),
        ("routing.sqlite", 1, object(), TypeError),
    ],
)
def test_store_constructor_validates_configuration(path, window, clock, error, tmp_path) -> None:
    with pytest.raises(error):
        SqliteRoutingObservationStore(
            tmp_path / path if path else path,
            window,
            **({"clock": clock} if clock is not None else {}),
        )


def test_store_validates_attempt_shape(tmp_path) -> None:
    store = SqliteRoutingObservationStore(tmp_path / "routing.sqlite", 60)
    with pytest.raises(ValueError):
        store.append("", "member", success=False)
    with pytest.raises(ValueError):
        store.append("transport", "", success=False)
    with pytest.raises(TypeError):
        store.append("transport", "member", success=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.append("transport", "member", success=True, latency_seconds=True)
    with pytest.raises(ValueError):
        store.append("transport", "member", success=True, latency_seconds=-1)
    with pytest.raises(ValueError):
        store.append("transport", "member", success=False, latency_seconds=0.1)
    with pytest.raises(ValueError):
        store.append("transport", "member", success=True, latency_seconds=0.1, output_tokens=0)
    with pytest.raises(ValueError):
        store.append("transport", "member", success=False, output_tokens=1)
    store.close()


def test_router_restores_and_refreshes_shared_observations(tmp_path) -> None:
    clock = _Clock()
    store = SqliteRoutingObservationStore(tmp_path / "routing.sqlite", 10, clock=clock)
    first = ModelGroupRouter(observation_store=store, ledger_name="transport")
    first.register_member("member_a")
    first.register_member("member_b")
    first.observe_success("member_a", 0.2, output_tokens=20)
    first.observe_failure("member_b")

    restored = ModelGroupRouter(observation_store=store, ledger_name="transport")
    restored.register_member("member_a")
    restored.register_member("member_b")
    restored.refresh()

    assert restored.member_observation_count("member_a") == 1
    assert restored.member_observation_count("member_b") == 1
    assert restored.member_report("member_a")["ewma_latency_seconds"] == 0.2
    assert restored.ranked_member_ids(["member_b", "member_a"]) == ["member_a", "member_b"]

    clock.value = 111
    restored.refresh()
    assert restored.member_observation_count("member_a") == 0
    assert restored.member_observation_count("member_b") == 0


def test_router_preserves_updated_priors_during_refresh(tmp_path) -> None:
    store = SqliteRoutingObservationStore(tmp_path / "routing.sqlite", 60)
    router = ModelGroupRouter(
        prior_resolver=lambda _member_id: (1.0, 1.0),
        observation_store=store,
        ledger_name="quality",
    )
    router.register_member("member_a")
    router.update_prior("member_a", 3.0, 4.0)
    router.refresh()

    report = router.member_report("member_a")
    assert report["success_posterior_mean"] == 0.428571
    assert report["success_count"] == 0
    assert report["failure_count"] == 0


def test_router_serializes_store_operations_with_memory_updates() -> None:
    class _LockCheckingStore:
        router: ModelGroupRouter | None = None

        def _assert_observation_io_locked(self) -> None:
            assert self.router is not None
            assert self.router._observation_io_lock.locked()
            assert not self.router._lock.locked()

        def append(self, *args, **kwargs) -> None:
            self._assert_observation_io_locked()

        def load(self, ledger_name: str) -> list:
            self._assert_observation_io_locked()
            return []

        def delete_members(self, ledger_name: str, member_ids) -> None:
            self._assert_observation_io_locked()

    store = _LockCheckingStore()
    router = ModelGroupRouter(observation_store=store)
    store.router = router
    router.register_member("member_a")
    router.observe_success("member_a", 0.2)
    router.observe_failure("member_a")
    router.refresh()
    router.reset_members({"member_a"})
    router.forget_members(set())


def test_measured_member_order_refreshes_each_ledger_once(tmp_path, monkeypatch) -> None:
    agents = [
        ModelAgent("member_a", "mock-a", group_name="shared_model"),
        ModelAgent("member_b", "mock-b", group_name="shared_model"),
        ModelAgent("member_c", "mock-c", group_name="shared_model"),
    ]
    orchestrator = TaskOrchestrator(
        agents,
        state_db=str(tmp_path / "state.sqlite"),
        routing_observation_window_seconds=60,
    )
    try:
        quality_refreshes = 0
        transport_refreshes = 0
        quality_refresh = orchestrator._quality_router.refresh
        transport_refresh = orchestrator._group_router.refresh

        def count_quality_refresh() -> None:
            nonlocal quality_refreshes
            quality_refreshes += 1
            quality_refresh()

        def count_transport_refresh() -> None:
            nonlocal transport_refreshes
            transport_refreshes += 1
            transport_refresh()

        monkeypatch.setattr(orchestrator._quality_router, "refresh", count_quality_refresh)
        monkeypatch.setattr(orchestrator._group_router, "refresh", count_transport_refresh)

        assert orchestrator._measured_member_order([agent.id for agent in agents]) == [
            agent.id for agent in agents
        ]
        assert quality_refreshes == 1
        assert transport_refreshes == 1
    finally:
        orchestrator.close()


def test_admin_state_refreshes_each_routing_ledger_once(tmp_path, monkeypatch) -> None:
    agents = [
        ModelAgent("member_a", "mock-a", group_name="shared_model"),
        ModelAgent("member_b", "mock-b", group_name="shared_model"),
    ]
    orchestrator = TaskOrchestrator(
        agents,
        state_db=str(tmp_path / "state.sqlite"),
        routing_observation_window_seconds=60,
    )
    refreshes = {"transport": 0, "quality": 0}
    original_transport_refresh = orchestrator._group_router.refresh
    original_quality_refresh = orchestrator._quality_router.refresh

    def count_transport_refresh() -> None:
        refreshes["transport"] += 1
        original_transport_refresh()

    def count_quality_refresh() -> None:
        refreshes["quality"] += 1
        original_quality_refresh()

    try:
        monkeypatch.setattr(orchestrator._group_router, "refresh", count_transport_refresh)
        monkeypatch.setattr(orchestrator._quality_router, "refresh", count_quality_refresh)
        orchestrator.admin_state()
        assert refreshes == {"transport": 1, "quality": 1}
    finally:
        orchestrator.close()


def test_stream_preserves_emitted_answer_when_observation_write_fails(
    tmp_path, monkeypatch, caplog
) -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("member_a", "mock-model", group_name="shared_model")],
        state_db=str(tmp_path / "state.sqlite"),
        routing_observation_window_seconds=60,
    )

    def fail_append(*args, **kwargs):
        raise OSError("simulated storage outage")

    try:
        monkeypatch.setattr(orchestrator._routing_observation_store, "append", fail_append)
        assert list(
            orchestrator.stream_route(
                [{"role": "user", "content": "stream this"}],
                model_name="contextual-orchestrator",
            )
        )
        assert "durable routing observation failed" in caplog.text
    finally:
        orchestrator.close()


def test_provider_failure_observation_outage_does_not_mask_active_failure(
    tmp_path, monkeypatch, caplog
) -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("member_a", "mock-model", group_name="shared_model")],
        state_db=str(tmp_path / "state.sqlite"),
        routing_observation_window_seconds=60,
    )

    def fail_append(*args, **kwargs):
        raise OSError("simulated storage outage")

    provider_error = RuntimeError("provider failure")
    try:
        monkeypatch.setattr(orchestrator._routing_observation_store, "append", fail_append)
        try:
            raise provider_error
        except RuntimeError as error:
            orchestrator._record_group_failure("member_a")
            assert error is provider_error
        assert "durable routing observation failed" in caplog.text
    finally:
        orchestrator.close()


def test_router_rejects_incomplete_store_contract() -> None:
    with pytest.raises(TypeError):
        ModelGroupRouter(observation_store=object())  # type: ignore[arg-type]


def test_router_deletes_persisted_context_when_members_leave(tmp_path) -> None:
    store = SqliteRoutingObservationStore(tmp_path / "routing.sqlite", 60)
    router = ModelGroupRouter(observation_store=store)
    router.register_member("member_a")
    router.observe_failure("member_a")
    router.reset_members({"member_a"})
    router.register_member("member_a")
    assert router.member_observation_count("member_a") == 0
    router.observe_failure("member_a")
    router.forget_members(set())
    assert store.load("transport") == []


def test_task_orchestrator_opt_in_store_survives_restart_and_reports_policy(tmp_path) -> None:
    path = tmp_path / "state.sqlite"
    agents = [ModelAgent("member_a", "mock-model", group_name="shared_model")]
    first = TaskOrchestrator(
        agents,
        state_db=str(path),
        routing_observation_window_seconds=60,
    )
    try:
        first._group_router.observe_success("member_a", 0.25)
        assert first.admin_state()["routing_observation_policy"] == {
            "enabled": True,
            "window_seconds": 60,
            "retention_policy": "time_window_only",
        }
    finally:
        first.close()

    second = TaskOrchestrator(
        agents,
        state_db=str(path),
        routing_observation_window_seconds=60,
    )
    try:
        assert second._group_router.member_observation_count("member_a") == 1
    finally:
        second.close()


def test_task_orchestrator_requires_state_db_for_durable_observations() -> None:
    with pytest.raises(ValueError, match="requires state_db"):
        TaskOrchestrator(
            [ModelAgent("member_a", "mock-model")],
            routing_observation_window_seconds=60,
        )


def test_cli_requires_state_db_for_durable_observations(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--routing-observation-window-seconds", "60"])
    assert exc_info.value.code == 2
    assert "requires --state-db" in capsys.readouterr().err
