"""Provider-neutral usage export boundary for the canonical Billing SDK."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .cost_ledger import UsageRecord, UsageRecordSink


class CanonicalUsageRecordSink(UsageRecordSink):
    """Build and enqueue canonical events without persisting model content."""

    def __init__(
        self,
        *,
        event_builder: Callable[..., Mapping[str, Any]],
        enqueue: Callable[[Mapping[str, Any]], None],
        identity: Mapping[str, str | None],
    ) -> None:
        self._event_builder = event_builder
        self._enqueue = enqueue
        self._identity = dict(identity)

    def emit_usage_record(self, record: UsageRecord) -> None:
        """Convert one ledger record and durably enqueue the resulting event."""
        event = self._event_builder(record.as_dict(), **self._identity)
        self._enqueue(event)


__all__ = ["CanonicalUsageRecordSink"]
