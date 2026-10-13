"""The serving CLI must retain cost evidence when its SQL ledger is selected."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import threading
from unittest.mock import patch

import pytest

from contextual_orchestrator.__main__ import main
from contextual_orchestrator.server import build_server
from test_cost_review_server import _request


def test_serving_cli_retains_usage_across_restart_and_closes_connections(tmp_path):
    state_db = tmp_path / "state.db"
    usage_db = tmp_path / "usage.db"
    usage_ids = []
    connections = []

    def inspect_server(orchestrator, *, coordinator, **_kwargs):
        assert coordinator.price_book is coordinator.ledger.price_book
        connections.append(coordinator.ledger.store._conn)
        server = build_server(orchestrator, port=0, security=_kwargs["security"], coordinator=coordinator)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            if not usage_ids:
                status, _ = _request("POST", base_url + "/v1/chat/completions", "local-token", {
                    "model": "orchestrator/auto", "mode": "route",
                    "messages": [{"role": "user", "content": "hello"}],
                })
                assert status == 200
                usage_ids.extend(row["usage_record_id"] for row in coordinator.ledger.records())
                assert usage_ids
            else:
                status, result = _request("GET", base_url + "/api/v1/llm_usage_records", "local-token")
                assert status == 200
                assert {row["usage_record_id"] for row in result["items"]} == set(usage_ids)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            orchestrator.close()

    argv = ["contextual-orchestrator", "--serve", "--auth-token", "local-token",
            "--state-db", str(state_db), "--usage-ledger-db", str(usage_db)]
    for _ in range(2):
        with patch.object(sys, "argv", argv), patch("contextual_orchestrator.__main__.serve", inspect_server):
            main()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[-1].execute("SELECT 1")

    assert len(usage_ids) == 1
    if os.name == "posix":
        assert stat.S_IMODE(usage_db.stat().st_mode) == 0o600


def test_usage_ledger_path_is_rejected_outside_server_mode(tmp_path, capsys):
    with patch.object(sys, "argv", ["contextual-orchestrator", "--usage-ledger-db", str(tmp_path / "usage.db")]):
        with pytest.raises(SystemExit) as exit_info:
            main()
    assert exit_info.value.code == 2
    assert "--usage-ledger-db requires --serve" in capsys.readouterr().err
    assert not (tmp_path / "usage.db").exists()


@pytest.mark.parametrize("path", ["", "   ", ":memory:"])
def test_usage_ledger_rejects_non_durable_paths(path, capsys):
    with patch.object(sys, "argv", ["contextual-orchestrator", "--serve", "--usage-ledger-db", path]):
        with pytest.raises(SystemExit) as exit_info:
            main()
    assert exit_info.value.code == 2
    assert "--usage-ledger-db must name an on-disk SQLite file" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="owner-only permissions are POSIX-specific")
@pytest.mark.parametrize("unsafe", ["group_readable", "symlink"])
def test_usage_ledger_rejects_untrusted_existing_file(tmp_path, capsys, unsafe):
    usage_db = tmp_path / "usage.db"
    if unsafe == "group_readable":
        usage_db.write_bytes(b"keep")
        usage_db.chmod(0o644)
        original = usage_db
    else:
        original = tmp_path / "private.db"
        original.write_bytes(b"keep")
        original.chmod(0o600)
        usage_db.symlink_to(original)
    argv = ["contextual-orchestrator", "--serve", "--auth-token", "local-token",
            "--usage-ledger-db", str(usage_db)]
    with patch.object(sys, "argv", argv), patch("contextual_orchestrator.__main__.serve") as serve:
        with pytest.raises(SystemExit) as exit_info:
            main()
    assert exit_info.value.code == 2
    assert "owner-only regular file" in capsys.readouterr().err
    serve.assert_not_called()
    assert original.read_bytes() == b"keep"
