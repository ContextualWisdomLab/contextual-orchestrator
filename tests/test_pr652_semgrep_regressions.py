"""Regression tests for the exact Semgrep root causes on PR #652."""

from __future__ import annotations

import sqlite3
import urllib.request

from contextual_orchestrator.cost_ledger import SqlLedgerStore
from contextual_orchestrator.orchestrator import ModelClient


def test_sql_ledger_rejects_unknown_paramstyle() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        try:
            SqlLedgerStore(connection, paramstyle="format")
        except ValueError as exc:
            assert "unsupported ledger paramstyle" in str(exc)
        else:
            raise AssertionError("unrecognized placeholder grammar must fail closed")
    finally:
        connection.close()


def test_provider_transport_rejects_local_file_before_io() -> None:
    client = ModelClient()
    request = urllib.request.Request("file:///etc/passwd")
    try:
        client._open_provider(request)
    except RuntimeError as exc:
        assert "absolute URL" in str(exc) or "requires https" in str(exc)
    else:
        raise AssertionError("local-file provider transport must fail before I/O")
