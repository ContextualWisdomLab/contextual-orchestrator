"""Cancellation is a request outcome, not a reason to lose completed work."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import threading

import pytest


@pytest.fixture
def partition_api():
    """Load the complete leaf module without importing unrelated provider plugins."""
    source_path = Path(__file__).resolve().parents[1] / 'contextual_orchestrator/request_partitioning/__init__.py'
    module_spec = importlib.util.spec_from_file_location('cancellation_partition', source_path)
    module_api = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module_api
    module_spec.loader.exec_module(module_api)
    return module_api


@pytest.mark.parametrize('cancel_stage', ['map', 'reduce'])
def test_cancel_during_final_call_preserves_checkpoint_without_success(partition_api, cancel_stage):
    """A provider finishes after cancellation; resume must not charge it again."""
    database = sqlite3.connect(':memory:', isolation_level=None)
    try:
        cancel_event = threading.Event()
        invocation_ids = []
        request_scope = partition_api.RequestScope('tenant', 'request', 'head', 'policy', 'backend')
        request_limits = partition_api.Limits(1000, 100, 1000, 20, 10000)
        evidence_units = tuple(partition_api.EvidenceUnit(f'unit-{unit_index}', 'source') for unit_index in range(2))

        def count_request(invocation):
            # Scripted provider-accounting fixture; never a production tokenizer.
            return 950 if invocation.stage == 'map' and len(invocation.unit_ids) > 1 else 50

        def invoke_request(invocation):
            invocation_ids.append(invocation.operation_id)
            if invocation.stage == cancel_stage and (cancel_stage == 'reduce' or len(invocation_ids) == 2):
                cancel_event.set()
            return partition_api.Completion('complete evidence report', 'stop', 5)

        executor = partition_api.PartitionExecutor(partition_api.CheckpointStore(database),
            count=count_request, invoke=invoke_request)
        with pytest.raises(partition_api.PartitionError, match='^cancelled$'):
            executor.run(request_scope, 'review', evidence_units, request_limits, cancelled=cancel_event.is_set)
        assert database.execute("SELECT COUNT(*) FROM partition_call WHERE run_state='running'").fetchone()[0] == 0
        completed_before_resume = tuple(invocation_ids)
        cancel_event.clear()
        final_result = executor.run(request_scope, 'review', evidence_units, request_limits, cancelled=cancel_event.is_set)
        assert final_result.covered_unit_ids == ('unit-0', 'unit-1')
        assert all(invocation_ids.count(operation_id) == 1 for operation_id in completed_before_resume)
    finally:
        database.close()


def test_cancellation_before_run_does_not_invoke_provider(partition_api):
    """The terminal fence does not weaken the pre-dispatch cancellation check."""
    database = sqlite3.connect(':memory:', isolation_level=None)
    try:
        invocation_ids = []
        executor = partition_api.PartitionExecutor(partition_api.CheckpointStore(database),
            count=lambda invocation: 5, invoke=lambda invocation: invocation_ids.append(invocation.operation_id))
        with pytest.raises(partition_api.PartitionError, match='^cancelled$'):
            executor.run(partition_api.RequestScope('t','r','s','p','b'), 'review',
                         (partition_api.EvidenceUnit('one', 'source'),),
                         partition_api.Limits(100, 10, 100, 10, 1000), cancelled=lambda: True)
        assert invocation_ids == []
    finally:
        database.close()


def test_single_map_cancel_is_not_success_and_resume_reuses_result(partition_api):
    """The final-call fence also applies when no reduction is necessary."""
    database = sqlite3.connect(':memory:', isolation_level=None)
    try:
        cancel_event = threading.Event()
        observed_calls = []
        request_scope = partition_api.RequestScope('tenant', 'request', 'head', 'policy', 'backend')
        request_limits = partition_api.Limits(1000, 100, 1000, 20, 10000)
        evidence_units = (partition_api.EvidenceUnit('single_unit', 'source'),)

        def invoke_request(invocation):
            observed_calls.append(invocation.operation_id)
            cancel_event.set()
            return partition_api.Completion('valid report', 'stop', 5)

        executor = partition_api.PartitionExecutor(partition_api.CheckpointStore(database),
                                                  count=lambda invocation: 20, invoke=invoke_request)
        with pytest.raises(partition_api.PartitionError, match='^cancelled$'):
            executor.run(request_scope, 'review', evidence_units, request_limits, cancelled=cancel_event.is_set)
        cancel_event.clear()
        assert executor.run(request_scope, 'review', evidence_units, request_limits).text == 'valid report'
        assert len(observed_calls) == 1
    finally:
        database.close()
