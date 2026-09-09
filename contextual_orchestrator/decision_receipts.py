"""Persistence boundary for Rust-owned initial-decision measurements."""

from contextvars import ContextVar
from contextlib import contextmanager
import logging
import threading
import uuid
import hashlib
import json

_CURRENT_DECISION = ContextVar("initial_decision", default=None)
_LOGGER = logging.getLogger(__name__)


class DecisionMeasurement:
    """Bind one native clock to an HTTP request and its durable store."""

    def __init__(self, store, *, policy=None, route_mode="unclassified", request_id=None,
                 endpoint_path=None, request_method=None,
                 admission_boundary="explicit_scope"):
        """Require the native module only when measurement is explicitly enabled."""
        from ._decision_receipt import DecisionReceipt

        self.receipt = DecisionReceipt()
        self.store = store
        self.request_id = request_id or uuid.uuid4().hex
        self.identity_source = "http_request" if request_id else "measurement_scope"
        policy_snapshot = policy.as_dict() if policy is not None else None
        self.policy_hash = hashlib.sha256(json.dumps(
            policy_snapshot, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest() if policy_snapshot is not None else None
        self.route_mode = route_mode
        self.endpoint_path = endpoint_path
        self.request_method = request_method
        self.admission_boundary = admission_boundary
        self.selected_agent_ids = []
        self.selection_attempt_count = 0
        self._race_attempt_ids = set()
        self.first_provider_phase = None
        self._lock = threading.Lock()
        self._token = _CURRENT_DECISION.set(self)
        try:
            if self.store is None:
                raise RuntimeError("no durable measurement store")
            self.store.save("accepted_request", None, self.snapshot(), durable=True)
        except Exception as exc:
            _CURRENT_DECISION.reset(self._token)
            _LOGGER.warning("Decision admission write failed error_type=%s", type(exc).__name__)
            raise RuntimeError("decision measurement admission could not be persisted") from None

    def snapshot(self):
        """Return no prompts, provider credentials, or fabricated missing timings."""
        return {
            "request_id": self.request_id,
            "identity_source": self.identity_source,
            "policy_snapshot_hash": self.policy_hash,
            "route_mode": self.route_mode,
            "endpoint_path": self.endpoint_path,
            "request_method": self.request_method,
            "measurement_unit": "http_request" if self.endpoint_path else "explicit_scope",
            "admission_boundary": self.admission_boundary,
            "status": self.receipt.status,
            "selected_agent_ids": list(self.selected_agent_ids),
            "selection_attempt_count": self.selection_attempt_count,
            "selection_elapsed_ns": self.receipt.selection_elapsed_ns,
            "durable_ack_elapsed_ns": self.receipt.durable_ack_elapsed_ns,
            "first_provider_elapsed_ns": self.receipt.first_provider_elapsed_ns,
            "first_provider_phase": self.first_provider_phase,
            "first_provider_boundary": "provider_ready_before_diagnostic_commit",
            "metric_scope": "initial_task_route_decision",
        }

    def select(self, agent_ids, route_mode, *, attempt_id=None):
        """Acknowledge the first decision synchronously before provider dispatch."""
        with self._lock:
            if attempt_id is not None:
                if attempt_id in self._race_attempt_ids:
                    return
                self._race_attempt_ids.add(attempt_id)
            self.selection_attempt_count += 1
            if self.receipt.status != "accepted":
                try:
                    self.store.save("selection_attempt", None, {
                        "request_id": self.request_id,
                        "attempt_number": self.selection_attempt_count,
                        "selected_agent_ids": list(agent_ids), "route_mode": route_mode,
                    }, durable=True)
                except Exception as exc:
                    _LOGGER.warning("Decision attempt export failed error_type=%s", type(exc).__name__)
                return
            self.receipt.record_selection()
            self.route_mode = route_mode
            self.selected_agent_ids = list(agent_ids)
            if self.store is None:
                self.receipt.record_failure("store_unavailable")
                return
            try:
                self.store.save("initial_decision", None, self.snapshot(), durable=True)
            except Exception as exc:
                self.receipt.record_failure("write_failed")
                _LOGGER.warning("Initial decision measurement write failed error_type=%s", type(exc).__name__)
                return
            self.receipt.record_durable_ack()
            self._record_provider_locked(agent_ids, "task_execution")

    def _record_provider_locked(self, agent_ids, phase):
        """Keep a first-provider diagnostic independent of the task-route clock."""
        if self.first_provider_phase is not None:
            return
        self.receipt.record_provider_dispatch()
        self.first_provider_phase = phase
        try:
            self.store.save("provider_dispatch", self.request_id, {
                **self.snapshot(), "provider_agent_ids": list(agent_ids),
            }, durable=True)
        except Exception as exc:
            _LOGGER.warning("Provider diagnostic write failed error_type=%s", type(exc).__name__)

    @contextmanager
    def auxiliary_call(self, agent_ids, phase):
        """Retain auxiliary work without subtracting it from the task-route interval."""
        with self._lock:
            self._record_provider_locked(agent_ids, phase)
            started = self.receipt.current_elapsed_ns()
        outcome = "completed"
        try:
            yield
        except BaseException:
            outcome = "failed"
            raise
        finally:
            with self._lock:
                finished = self.receipt.current_elapsed_ns()
                try:
                    self.store.save("auxiliary_dispatch", self.request_id, {
                        "request_id": self.request_id, "phase": phase,
                        "provider_agent_ids": list(agent_ids), "outcome": outcome,
                        "started_elapsed_ns": started, "finished_elapsed_ns": finished,
                    }, durable=True)
                except Exception as exc:
                    _LOGGER.warning("Auxiliary diagnostic write failed error_type=%s", type(exc).__name__)

    def close(self, reason="unfinished"):
        """Persist the post-commit measurement separately; never claim its own ack."""
        try:
            with self._lock:
                if self.receipt.status in ("accepted", "selected"):
                    self.receipt.record_failure(reason)
                if self.store is not None:
                    try:
                        self.store.save("decision_receipt", None, self.snapshot(), durable=True)
                    except Exception as exc:
                        _LOGGER.warning("Decision receipt export failed error_type=%s", type(exc).__name__)
        finally:
            _CURRENT_DECISION.reset(self._token)


def record_initial_selection(agent_ids, route_mode="unclassified", *, attempt_id=None):
    """Record selection only within an explicitly enabled request measurement."""
    measurement = _CURRENT_DECISION.get()
    if measurement is not None:
        measurement.select(agent_ids, route_mode, attempt_id=attempt_id)


@contextmanager
def observe_auxiliary_dispatch(agent_ids, phase):
    """Use the request's native clock for an actual auxiliary provider call."""
    measurement = _CURRENT_DECISION.get()
    if measurement is None:
        yield
    else:
        with measurement.auxiliary_call(agent_ids, phase):
            yield


def export_decision_receipts(store, limit=256):
    """Join retained admissions without dropping missing final acknowledgements.

    This is a local ledger view, not an all-ingress census. Storage outages need
    external ingress reconciliation. Concurrent finalization may appear on the
    next read; missing values remain unfinished rather than successful zeros.
    """
    cohort = store.load_decision_window(limit)
    accepted = cohort["accepted"]
    decisions = {row["request_id"]: row for row in cohort["decisions"]}
    receipts = {row["request_id"]: row for row in cohort["receipts"]}
    diagnostics = {}
    for diagnostic in cohort["diagnostics"]:
        diagnostics.setdefault(diagnostic["request_id"], []).append(diagnostic)
    observations = []
    for admission in accepted:
        request_id = admission["request_id"]
        row = dict(admission)
        row["status"] = "unfinished"
        if request_id in decisions:
            row.update(decisions[request_id])
            row["status"] = "acknowledgement_unobserved"
        if request_id in receipts:
            row.update(receipts[request_id])
        request_diagnostics = diagnostics.get(request_id, [])
        row["auxiliary_dispatches"] = [entry for entry in request_diagnostics
                                      if entry["record_kind"] == "auxiliary_dispatch"]
        row["provider_diagnostics"] = [entry for entry in request_diagnostics
                                      if entry["record_kind"] == "provider_dispatch"]
        observations.append(row)
    return {
        "schema_version": 1,
        "measurement_complete": False,
        "reconciliation_required": True,
        "scope": "retained_local_admissions",
        "window": cohort["window"],
        "observations": observations,
    }
