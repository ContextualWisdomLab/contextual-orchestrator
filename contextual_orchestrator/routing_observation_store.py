"""Time-windowed durable observations for measured model-group routing.

The store keeps one immutable row per completed provider attempt.  A positive
operator-selected window limits which rows participate in a router's current
state; no decay, cross-model weighting, or inferred provider equivalence is
introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from typing import Protocol


@dataclass(frozen=True)
class RoutingObservation:
    """One completed routing attempt restored from durable storage."""

    member_id: str
    success: bool
    latency_seconds: float | None
    output_tokens: int | None


class RoutingObservationStore(Protocol):
    """Minimal store contract consumed by :class:`ModelGroupRouter`."""

    def append(
        self,
        ledger_name: str,
        member_id: str,
        *,
        success: bool,
        latency_seconds: float | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Append one completed attempt to the current observation window."""

    def load(self, ledger_name: str) -> list[RoutingObservation]:
        """Return current-window observations in completion order."""

    def delete_members(self, ledger_name: str, member_ids: Iterable[str]) -> None:
        """Delete observations whose group membership is no longer valid."""

    def close(self) -> None:
        """Release store resources owned by the router."""


class SqliteRoutingObservationStore:
    """Share measured routing observations through a SQLite database.

    The store opens a short-lived connection for each operation so separate
    gateway processes can use the same database.  Rows older than the explicit
    ``window_seconds`` are ignored and removed on writes.  A retention window
    is intentionally used instead of an invented decay coefficient.
    """

    _TABLE_NAME = "routing_observations"
    _CREATE_TABLE_SQL = (
        "CREATE TABLE IF NOT EXISTS routing_observations ("
        "observation_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ledger_name TEXT NOT NULL, member_id TEXT NOT NULL, "
        "observed_at REAL NOT NULL, success INTEGER NOT NULL CHECK(success IN (0, 1)), "
        "latency_seconds REAL, output_tokens INTEGER)"
    )
    _CREATE_INDEX_SQL = (
        "CREATE INDEX IF NOT EXISTS routing_observations_ledger_time "
        "ON routing_observations(ledger_name, observed_at, observation_id)"
    )

    def __init__(
        self,
        path: str | os.PathLike[str],
        window_seconds: int,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(path, (str, os.PathLike)) or not str(path):
            raise TypeError("path must be a non-empty filesystem path")
        if isinstance(window_seconds, bool) or type(window_seconds) is not int or window_seconds < 1:
            raise ValueError("window_seconds must be a positive integer")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._path = path
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(self._CREATE_TABLE_SQL)
                connection.execute(self._CREATE_INDEX_SQL)
                connection.commit()
            finally:
                connection.close()

    @property
    def window_seconds(self) -> int:
        """Return the operator-selected observation retention window."""
        return self._window_seconds

    def _connect(self) -> sqlite3.Connection:
        """Open one cross-process-safe SQLite connection."""
        return sqlite3.connect(self._path, timeout=30.0)

    def _now(self) -> float:
        """Return a finite wall-clock value used for the retention boundary."""
        value = float(self._clock())
        if not math.isfinite(value):
            raise ValueError("clock must return a finite number")
        return value

    @staticmethod
    def _validate_ledger_name(ledger_name: str) -> None:
        """Validate the fixed logical ledger identifier."""
        if type(ledger_name) is not str or not ledger_name.strip():
            raise ValueError("ledger_name must be a non-empty string")

    @staticmethod
    def _validate_member_id(member_id: str) -> None:
        """Validate an opaque member identifier before persistence."""
        if type(member_id) is not str or not member_id:
            raise ValueError("member_id must be a non-empty string")

    def append(
        self,
        ledger_name: str,
        member_id: str,
        *,
        success: bool,
        latency_seconds: float | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Append one validated attempt and prune rows outside the time window."""
        self._validate_ledger_name(ledger_name)
        self._validate_member_id(member_id)
        if type(success) is not bool:
            raise TypeError("success must be a boolean")
        if success:
            if isinstance(latency_seconds, bool) or not isinstance(latency_seconds, (int, float)):
                raise TypeError("successful observations require numeric latency_seconds")
            latency = float(latency_seconds)
            if not math.isfinite(latency) or latency < 0:
                raise ValueError("latency_seconds must be finite and nonnegative")
            if output_tokens is not None and (
                isinstance(output_tokens, bool)
                or type(output_tokens) is not int
                or output_tokens <= 0
            ):
                raise ValueError("output_tokens must be a positive integer when provided")
        elif latency_seconds is not None or output_tokens is not None:
            raise ValueError("failed observations cannot contain success-only measurements")
        now = self._now()
        connection = self._connect()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM routing_observations WHERE observed_at < ?",
                    (now - self._window_seconds,),
                )
                connection.execute(
                    "INSERT INTO routing_observations "
                    "(ledger_name, member_id, observed_at, success, latency_seconds, output_tokens) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        ledger_name.strip(),
                        member_id,
                        now,
                        int(success),
                        None if not success else float(latency_seconds),
                        None if not success else output_tokens,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def load(self, ledger_name: str) -> list[RoutingObservation]:
        """Return only observations still inside the configured time window."""
        self._validate_ledger_name(ledger_name)
        cutoff = self._now() - self._window_seconds
        connection = self._connect()
        with self._lock:
            try:
                rows = connection.execute(
                    "SELECT member_id, success, latency_seconds, output_tokens "
                    "FROM routing_observations "
                    "WHERE ledger_name = ? AND observed_at >= ? "
                    "ORDER BY observation_id",
                    (ledger_name.strip(), cutoff),
                ).fetchall()
            finally:
                connection.close()
        return [
            RoutingObservation(
                member_id=row[0],
                success=bool(row[1]),
                latency_seconds=row[2],
                output_tokens=row[3],
            )
            for row in rows
        ]

    def delete_members(self, ledger_name: str, member_ids: Iterable[str]) -> None:
        """Remove stale group-context observations without touching other ledgers."""
        self._validate_ledger_name(ledger_name)
        members = tuple(dict.fromkeys(member_ids))
        for member_id in members:
            self._validate_member_id(member_id)
        if not members:
            return
        connection = self._connect()
        with self._lock:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for member_id in members:
                    connection.execute(
                        "DELETE FROM routing_observations WHERE ledger_name = ? AND member_id = ?",
                        (ledger_name.strip(), member_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def close(self) -> None:
        """Keep the lifecycle contract; operations use short-lived connections."""
        return


__all__ = ["RoutingObservation", "RoutingObservationStore", "SqliteRoutingObservationStore"]
