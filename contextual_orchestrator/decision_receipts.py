"""Persistence boundary for Rust-owned initial-decision measurements."""

from contextvars import ContextVar
import logging
import threading
import uuid

_CURRENT_DECISION = ContextVar("initial_decision", default=None)
_LOGGER = logging.getLogger(__name__)


class DecisionMeasurement:
    """Bind one native clock to an HTTP request and its durable store."""

    def __init__(self, store):
        """Require the native module only when measurement is explicitly enabled."""
        from ._decision_receipt import DecisionReceipt

        self.receipt = DecisionReceipt()
        self.store = store
        self.request_id = uuid.uuid4().hex
        self.selected_agent_ids = []
        self._lock = threading.Lock()
        self._token = _CURRENT_DECISION.set(self)

    def snapshot(self):
        """Return no prompts, provider credentials, or fabricated missing timings."""
        return {
            "request_id": self.request_id,
            "status": self.receipt.status,
            "selected_agent_ids": list(self.selected_agent_ids),
            "selection_elapsed_ns": self.receipt.selection_elapsed_ns,
            "durable_ack_elapsed_ns": self.receipt.durable_ack_elapsed_ns,
            "metric_scope": "initial_provider_dispatch",
        }

    def select(self, agent_ids):
        """Acknowledge the first decision synchronously before provider dispatch."""
        with self._lock:
            if self.receipt.status != "accepted":
                return
            self.receipt.record_selection()
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


def record_initial_selection(agent_ids):
    """Record selection only within an explicitly enabled request measurement."""
    measurement = _CURRENT_DECISION.get()
    if measurement is not None:
        measurement.select(agent_ids)
