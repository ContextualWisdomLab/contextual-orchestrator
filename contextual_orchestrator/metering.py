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
        raw_record = record.as_dict()
        safe_record = {
            name: raw_record[name]
            for name in (
                "usage_record_id",
                "created_at",
                "workflow_run_id",
                "request_channel",
                "route_mode",
                "provider_name",
                "model_name",
                "prompt_tokens",
                "completion_tokens",
                "measurement_status",
            )
            if name in raw_record
        }
        event = self._event_builder(safe_record, **self._identity)
        self._enqueue(event)


__all__ = ["CanonicalUsageRecordSink"]
