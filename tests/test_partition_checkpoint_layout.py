"""A resumed request may not silently replace its already executed partition."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest


@pytest.fixture
def api():
    source = Path(__file__).resolve().parents[1] / 'contextual_orchestrator/request_partitioning/__init__.py'
    spec = importlib.util.spec_from_file_location('partition_layout_subject', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scope(api):
    return api.RequestScope('tenant', 'request', 'head', 'policy', 'backend')


def limits(api):
    return api.Limits(100, 10, 1000, 100, 10000)


def units(api, size=4):
    return tuple(api.EvidenceUnit(f'unit-{index}', f'source {index}') for index in range(size))


def counter(max_map=1, max_reduce=20, single_tokens=20):
    # A scripted exact accounting port, not a byte/character production estimate.
    def count(call):
        count_limit = max_map if call.stage == 'map' else max_reduce
        return single_tokens if len(json.loads(call.prompt)['evidence']) <= count_limit else 100
    return count


@pytest.mark.parametrize('first_capacity,next_capacity', [(1, 2), (2, 1)])
def test_map_layout_drift_cannot_repeat_completed_evidence(api, tmp_path, first_capacity, next_capacity):
    state_path = tmp_path / 'checkpoints.sqlite3'
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
        original = api.PartitionExecutor(api.CheckpointStore(db), count=counter(max_map=first_capacity), invoke=invoke)
        with pytest.raises(api.PartitionError, match='cancelled'):
            original.run(scope(api), 'review', units(api), limits(api), cancelled=lambda: bool(calls))
    completed_calls = len(calls)
    with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
        resumed = api.PartitionExecutor(api.CheckpointStore(db), count=counter(max_map=next_capacity), invoke=invoke)
        with pytest.raises(api.PartitionError, match='checkpoint_partition_changed'):
            resumed.run(scope(api), 'review', units(api), limits(api))
    assert len(calls) == completed_calls


def test_reducer_layout_is_also_bound_before_dispatch(api):
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        store = api.CheckpointStore(db)
        original = api.PartitionExecutor(store, count=counter(max_reduce=2), invoke=invoke)
        with pytest.raises(api.PartitionError, match='cancelled'):
            original.run(scope(api), 'review', units(api), limits(api),
                         cancelled=lambda: any(call.stage == 'reduce' for call in calls))
        previous_calls = len(calls)
        resumed = api.PartitionExecutor(store, count=counter(max_reduce=3), invoke=invoke)
        with pytest.raises(api.PartitionError, match='checkpoint_partition_changed'):
            resumed.run(scope(api), 'review', units(api), limits(api))
        assert len(calls) == previous_calls


@pytest.mark.parametrize('next_tokens', [19, 21])
def test_unchanged_layout_cannot_reuse_different_accounting(api, next_tokens):
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        store = api.CheckpointStore(db)
        original = api.PartitionExecutor(store, count=counter(single_tokens=20), invoke=invoke)
        original.run(scope(api), 'review', units(api, 1), limits(api))
        resumed = api.PartitionExecutor(store, count=counter(single_tokens=next_tokens), invoke=invoke)
        with pytest.raises(api.PartitionError, match='checkpoint_accounting_changed'):
            resumed.run(scope(api), 'review', units(api, 1), limits(api))
        assert len(calls) == 1


def test_same_layout_resumes_without_repeating_completed_units(api, tmp_path):
    state_path = tmp_path / 'checkpoints.sqlite3'
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=invoke)
        with pytest.raises(api.PartitionError, match='cancelled'):
            engine.run(scope(api), 'review', units(api, 90), limits(api), cancelled=lambda: len(calls) >= 2)
    with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=invoke)
        result = engine.run(scope(api), 'review', units(api, 90), limits(api))
        assert result.covered_unit_ids == tuple(unit.unit_id for unit in units(api, 90))
        assert len([call for call in calls if call.stage == 'map']) == 90
        complete_count = len(calls)
        assert engine.run(scope(api), 'review', units(api, 90), limits(api)) == result
        assert len(calls) == complete_count


def test_explicit_new_backend_revision_creates_a_new_plan(api):
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(max_map=1), invoke=invoke)
        first = engine.run(scope(api), 'review', units(api, 2), limits(api))
        engine.count = counter(max_map=2)
        second = engine.run(replace(scope(api), backend_revision='backend-2'), 'review', units(api, 2), limits(api))
        assert first.plan_id != second.plan_id
        assert first.covered_unit_ids == second.covered_unit_ids


def test_unknown_provider_outcome_still_requires_reconciliation(api):
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        calls = []
        def lost_response(call):
            calls.append(call)
            raise OSError('response lost after submission')
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=lost_response)
        with pytest.raises(OSError):
            engine.run(scope(api), 'review', units(api, 1), limits(api))
        with pytest.raises(api.PartitionError, match='reconciliation_required'):
            engine.run(scope(api), 'review', units(api, 1), limits(api))
        assert len(calls) == 1


def test_missing_manifest_is_not_retroactively_attested(api):
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=invoke)
        engine.run(scope(api), 'review', units(api, 1), limits(api))
        db.execute('DELETE FROM partition_manifest')
        with pytest.raises(api.PartitionError, match='checkpoint_manifest_required'):
            engine.run(scope(api), 'review', units(api, 1), limits(api))
        assert len(calls) == 1
        assert db.execute('SELECT COUNT(*) FROM partition_manifest').fetchone()[0] == 0
        assert not db.in_transaction


def test_manifest_failure_rolls_back_without_dispatch(api):
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        calls = []
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=lambda call: calls.append(call))
        db.execute("CREATE TRIGGER fail_manifest BEFORE INSERT ON partition_manifest "
                   "BEGIN SELECT RAISE(ROLLBACK, 'storage unavailable'); END")
        with pytest.raises(sqlite3.IntegrityError, match='storage unavailable'):
            engine.run(scope(api), 'review', units(api, 1), limits(api))
        assert calls == []
        assert not db.in_transaction
        assert db.execute('SELECT COUNT(*) FROM partition_call').fetchone()[0] == 0


def test_different_concurrent_layouts_cannot_both_be_admitted(api, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    state_path = tmp_path / 'shared.sqlite3'
    with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
        api.CheckpointStore(db)
    barrier = Barrier(2)
    def bind(content):
        with closing(sqlite3.connect(state_path, isolation_level=None)) as db:
            store = api.CheckpointStore(db)
            barrier.wait()
            try:
                store.bind_partition('same-plan', 'same-partition', (
                    api.Invocation(content, 'map', ('unit-0',), content, 10),))
                return 'bound'
            except api.PartitionError as error:
                return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(bind, ('first-layout', 'second-layout')))
    assert sorted(outcomes) == ['bound', 'checkpoint_partition_changed']


def test_layout_binding_does_not_reset_call_budget(api):
    calls = []
    def invoke(call):
        calls.append(call)
        return api.Completion('report', 'stop', 1)
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=counter(), invoke=invoke)
        limited = replace(limits(api), max_calls=2)
        for _ in range(2):
            with pytest.raises(api.PartitionError, match='budget_exhausted'):
                engine.run(scope(api), 'review', units(api, 4), limited)
        assert len(calls) == 2


def test_oversized_unit_still_fails_before_manifest_or_model_work(api):
    calls = []
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as db:
        engine = api.PartitionExecutor(api.CheckpointStore(db), count=lambda call: 100,
                                      invoke=lambda call: calls.append(call))
        with pytest.raises(api.PartitionError, match='atomic_unit_too_large'):
            engine.run(scope(api), 'review', units(api, 1), limits(api))
        assert calls == []
        assert db.execute('SELECT COUNT(*) FROM partition_manifest').fetchone()[0] == 0
