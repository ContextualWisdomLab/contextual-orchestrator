"""Behavioral contracts for the outer, routing-independent request boundary."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "contextual_orchestrator/request_partitioning/__init__.py"


@pytest.fixture
def api():
    spec = importlib.util.spec_from_file_location("partitioning_under_test", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup(api):
    db = sqlite3.connect(":memory:", isolation_level=None)
    store = api.CheckpointStore(db)
    scope = api.RequestScope("tenant-a", "request-1", "head-1", "policy-v1", "gateway-v1")
    limits = api.Limits(context_tokens=500, output_tokens=30, output_bytes=500,
                        max_calls=200, max_reserved_tokens=100000)
    calls = []

    def count(invocation):
        # A synthetic exact accounting contract, NOT a production tokenizer.
        return len(invocation.prompt.encode("utf-8"))

    def invoke(invocation):
        calls.append(invocation)
        return api.Completion("report:" + str(len(calls)), "stop", 5)

    engine = api.PartitionExecutor(store, count=count, invoke=invoke)
    yield scope, limits, calls, engine, db
    db.close()


def units(api, count=84):
    return tuple(api.EvidenceUnit(f"file-{i}", "x" * 90) for i in range(count))


def test_84_file_request_covers_each_unit_without_oversized_call(api, setup):
    scope, limits, calls, engine, db = setup
    result = engine.run(scope, "review", units(api), limits)
    leaves = [c for c in calls if c.stage == "map"]
    assert len(leaves) > 1
    assert sorted(x for c in leaves for x in c.unit_ids) == sorted(f"file-{i}" for i in range(84))
    assert len({x for c in leaves for x in c.unit_ids}) == 84
    assert all(len(c.prompt.encode()) + limits.output_tokens <= limits.context_tokens for c in calls)
    assert result.covered_unit_ids == tuple(f"file-{i}" for i in range(84))
    assert result.text.startswith("report:")


def test_completed_request_resume_performs_no_more_model_calls(api, setup):
    scope, limits, calls, engine, db = setup
    first = engine.run(scope, "review", units(api, 12), limits)
    count = len(calls)
    second = api.PartitionExecutor(api.CheckpointStore(db), count=engine.count, invoke=engine.invoke)
    assert second.run(scope, "review", units(api, 12), limits) == first
    assert len(calls) == count


def test_cancel_before_next_dispatch_then_resume_reuses_completed_children(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="cancelled"):
        engine.run(scope, "review", units(api, 12), limits, cancelled=lambda: len(calls) >= 2)
    assert len(calls) == 2
    first_ids = [c.operation_id for c in calls]
    result = engine.run(scope, "review", units(api, 12), limits)
    assert len(result.covered_unit_ids) == 12
    assert sum(c.operation_id in first_ids for c in calls) == 2


def test_inflight_unknown_is_not_silently_replayed(api, setup):
    scope, limits, calls, engine, db = setup
    def fail(invocation):
        calls.append(invocation)
        raise OSError("lost response after provider accepted")
    broken = api.PartitionExecutor(engine.store, count=engine.count, invoke=fail)
    with pytest.raises(OSError):
        broken.run(scope, "review", units(api, 1), limits)
    with pytest.raises(api.PartitionError, match="reconciliation_required"):
        engine.run(scope, "review", units(api, 1), limits)
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [("tenant_id", "tenant-b"), ("source_revision", "head-2"),
                                        ("policy_revision", "policy-v2"), ("backend_revision", "gateway-v2")])
def test_changed_identity_cannot_reuse_old_checkpoints(api, setup, field, value):
    scope, limits, calls, engine, db = setup
    engine.run(scope, "review", units(api, 1), limits)
    values = dict(vars(scope)); values[field] = value
    engine.run(api.RequestScope(**values), "review", units(api, 1), limits)
    assert len(calls) == 2


def test_changed_evidence_or_task_cannot_reuse_old_result(api, setup):
    scope, limits, calls, engine, db = setup
    engine.run(scope, "review", units(api, 1), limits)
    engine.run(scope, "review", (api.EvidenceUnit("file-0", "different"),), limits)
    engine.run(scope, "other task", units(api, 1), limits)
    assert len(calls) == 3


def test_oversized_atomic_unit_fails_before_any_model_work(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="atomic_unit_too_large"):
        engine.run(scope, "review", units(api, 2) + (api.EvidenceUnit("huge", "x"*5000),), limits)
    assert not calls


def test_duplicate_or_empty_inventory_is_rejected(api, setup):
    scope, limits, calls, engine, db = setup
    for work in [(), (api.EvidenceUnit("x", "a"), api.EvidenceUnit("x", "b"))]:
        with pytest.raises(api.PartitionError, match="inventory"):
            engine.run(scope, "review", work, limits)
    assert not calls


@pytest.mark.parametrize("bad", [None, True, -1, 2.5])
def test_unavailable_or_invalid_token_count_fails_closed(api, setup, bad):
    scope, limits, calls, engine, db = setup
    invalid = api.PartitionExecutor(engine.store, count=lambda inv: bad, invoke=engine.invoke)
    with pytest.raises(api.PartitionError, match="token_count_unavailable"):
        invalid.run(scope, "review", units(api, 1), limits)
    assert not calls


@pytest.mark.parametrize("reason,text,tokens", [("length", "partial", 5), ("tool_calls", "pending", 5),
                                               ("stop", "", 5), ("stop", "x", None),
                                               ("stop", "x", True), ("stop", "x", 31),
                                               ("stop", "x"*501, 5)])
def test_partial_or_unbounded_completion_never_becomes_checkpoint(api, setup, reason, text, tokens):
    scope, limits, calls, engine, db = setup
    bad = api.PartitionExecutor(engine.store, count=engine.count,
        invoke=lambda inv: api.Completion(text, reason, tokens))
    with pytest.raises(api.PartitionError, match="incomplete_completion"):
        bad.run(scope, "review", units(api, 1), limits)
    with pytest.raises(api.PartitionError, match="reconciliation_required"):
        engine.run(scope, "review", units(api, 1), limits)


def test_global_call_budget_is_enforced_across_restart(api, setup):
    scope, limits, calls, engine, db = setup
    limits = api.Limits(500, 30, 500, 1, 100000)
    for _ in range(2):
        with pytest.raises(api.PartitionError, match="budget_exhausted"):
            engine.run(scope, "review", units(api, 12), limits)
    assert len(calls) == 1


def test_reserved_token_budget_blocks_before_provider_call(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="budget_exhausted"):
        engine.run(scope, "review", units(api, 1), api.Limits(500, 30, 500, 200, 1))
    assert not calls


def test_reducer_must_make_progress_instead_of_recursive_overflow(api, setup):
    scope, limits, calls, engine, db = setup
    def bulky(inv):
        calls.append(inv)
        return api.Completion("x"*300, "stop", 5)
    oversized = api.PartitionExecutor(engine.store, count=engine.count, invoke=bulky)
    with pytest.raises(api.PartitionError, match="reduction_not_progressing"):
        oversized.run(scope, "review", units(api, 5), limits)
    assert all(c.stage == "map" for c in calls)


def test_counter_is_checked_again_after_planning(api, setup):
    scope, limits, calls, engine, db = setup
    counters = 0
    def drift(inv):
        nonlocal counters
        counters += 1
        return 100 if counters == 1 else 9999
    guarded = api.PartitionExecutor(engine.store, count=drift, invoke=engine.invoke)
    with pytest.raises(api.PartitionError):
        guarded.run(scope, "review", units(api, 1), limits)
    assert not calls


def test_store_rejects_connection_inside_caller_transaction(api):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE caller_data (value_text TEXT)")
    db.execute("INSERT INTO caller_data VALUES ('not committed')")
    with pytest.raises(api.PartitionError, match="autocommit_connection_required"):
        api.CheckpointStore(db)
    assert db.in_transaction
    db.close()


def test_reference_ids_not_recopied_into_every_reduction_prompt(api, setup):
    scope, limits, calls, engine, db = setup
    engine.run(scope, "review", units(api, 84), limits)
    reductions = [c for c in calls if c.stage == "reduce"]
    assert reductions
    # Lineage is carried outside the model prompt, not an ever-growing manifest.
    assert all('file-83' not in c.prompt for c in reductions)


@pytest.mark.parametrize("value", ["", " ", None, 0])
def test_scope_needs_explicit_nonempty_identity(api, value):
    with pytest.raises(api.PartitionError, match="invalid_scope"):
        api.RequestScope(value, "request", "head", "policy", "backend")


@pytest.mark.parametrize("values", [(0, 1, 1, 1, 1), (20, 20, 1, 1, 1),
                                     (20, 1, True, 1, 1), (20, 1, 1, -1, 1)])
def test_limits_reject_invalid_or_no_input_allowance(api, values):
    with pytest.raises(api.PartitionError, match="invalid_limits"):
        api.Limits(*values)


@pytest.mark.parametrize("uid,text", [("", "x"), ("x"*129, "x"), ("id", ""), ("id", None)])
def test_evidence_units_reject_invalid_atomic_inputs(api, uid, text):
    with pytest.raises(api.PartitionError, match="invalid_inventory_unit"):
        api.EvidenceUnit(uid, text)


def test_empty_task_is_rejected(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="invalid_task"):
        engine.run(scope, "", units(api, 1), limits)


def test_changed_checkpoint_digest_is_not_trusted(api, setup):
    scope, limits, calls, engine, db = setup
    engine.run(scope, "review", units(api, 1), limits)
    db.execute("UPDATE partition_call SET prompt_digest='changed'")
    with pytest.raises(api.PartitionError, match="checkpoint_identity_mismatch"):
        engine.run(scope, "review", units(api, 1), limits)
    assert len(calls) == 1


def test_completed_checkpoint_body_is_still_validated(api, setup):
    scope, limits, calls, engine, db = setup
    engine.run(scope, "review", units(api, 1), limits)
    db.execute("UPDATE partition_call SET response_text=''")
    with pytest.raises(api.PartitionError, match="incomplete_completion"):
        engine.run(scope, "review", units(api, 1), limits)


def test_completion_cannot_be_committed_without_matching_claim(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="checkpoint_completion_conflict"):
        engine.store.complete("unknown", api.Invocation("unknown", "map", ("u",), "p", 30),
                              api.Completion("report", "stop", 1))


def test_sqlite_automatic_rollback_does_not_get_a_second_rollback(api, setup):
    scope, limits, calls, engine, db = setup
    db.execute("CREATE TRIGGER storage_failure BEFORE INSERT ON partition_call "
               "BEGIN SELECT RAISE(ROLLBACK, 'storage rejected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="storage rejected"):
        engine.run(scope, "review", units(api, 1), limits)
    assert not db.in_transaction and not calls


def test_oversized_first_unit_never_dispatches(api, setup):
    scope, limits, calls, engine, db = setup
    with pytest.raises(api.PartitionError, match="atomic_unit_too_large"):
        engine.run(scope, "review", (api.EvidenceUnit("huge", "x"*5000),), limits)
    assert not calls


def test_capacity_one_reports_cannot_recur_without_progress(api, setup):
    scope, limits, calls, engine, db = setup
    def count(inv):
        return 100 if inv.stage == "map" else (100 if len(json.loads(inv.prompt)["evidence"]) == 1 else 9999)
    # Force multiple map calls with a real capacity measure; single report fits,
    # but no pair fits. The reducer must terminate, not repeat singleton calls.
    def actual_count(inv):
        if inv.stage == "map":
            return len(inv.prompt.encode())
        return count(inv)
    kernel = api.PartitionExecutor(engine.store, count=actual_count, invoke=engine.invoke)
    with pytest.raises(api.PartitionError, match="reduction_not_progressing"):
        kernel.run(scope, "review", units(api, 12), limits)
    assert all(c.stage == "map" for c in calls)


def test_lineage_corruption_does_not_claim_complete_coverage(api, setup, monkeypatch):
    scope, limits, calls, engine, db = setup
    original = engine._perform
    def corrupt(*args, **kwargs):
        record = original(*args, **kwargs)
        return api._Record(record.reference, record.text, ("wrong-unit",))
    monkeypatch.setattr(engine, "_perform", corrupt)
    with pytest.raises(api.PartitionError, match="coverage_mismatch"):
        engine.run(scope, "review", units(api, 1), limits)


def test_two_connections_cannot_claim_the_same_provider_operation(api, tmp_path):
    path = tmp_path / "checkpoints.sqlite3"
    first_db = sqlite3.connect(path, isolation_level=None)
    second_db = sqlite3.connect(path, isolation_level=None)
    first, second = api.CheckpointStore(first_db), api.CheckpointStore(second_db)
    limits = api.Limits(500, 30, 500, 10, 10000)
    call = api.Invocation("operation", "map", ("source",), "prompt", 30)
    assert first.claim("plan", call, 10, limits) is None
    with pytest.raises(api.PartitionError, match="reconciliation_required"):
        second.claim("plan", call, 10, limits)
    first.complete("plan", call, api.Completion("complete", "stop", 1))
    assert second.claim("plan", call, 10, limits).text == "complete"
    first_db.close(); second_db.close()
