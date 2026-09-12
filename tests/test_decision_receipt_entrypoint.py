"""Decision measurements require explicit opt-in through supported entrypoints."""

from types import SimpleNamespace
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from contextual_orchestrator import server as server_module
from contextual_orchestrator.__main__ import main


@pytest.mark.parametrize("enabled", [False, True])
def test_serve_forwards_decision_receipt_option(monkeypatch, enabled):
    """The default stays off and an explicit opt-in reaches the existing builder."""
    built_server = MagicMock()
    server_builder = MagicMock(return_value=built_server)
    monkeypatch.setattr(server_module, "build_server", server_builder)
    server_options = {"decision_receipts": True} if enabled else {}

    server_module.serve(SimpleNamespace(), **server_options)

    assert server_builder.call_args.kwargs["decision_receipts"] is enabled
    built_server.serve_forever.assert_called_once_with()
    built_server.server_close.assert_called_once_with()


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_forwards_decision_receipt_option(enabled):
    """Only the explicit CLI switch enables decision measurements."""
    agent_config = Path(__file__).resolve().parents[1] / "examples/agents.mock.json"
    arguments = ["--serve", "--auth-token", "local-test-token", "--agents", str(agent_config)]
    if enabled:
        arguments.append("--decision-receipts")
    with patch("contextual_orchestrator.__main__.serve") as serve_gateway:
        main(arguments)

    assert serve_gateway.call_args.kwargs["decision_receipts"] is enabled


@pytest.mark.parametrize("native_available", [False, True])
def test_serve_rejects_missing_receipt_prerequisites(native_available):
    """Native or durable-store absence fails before a listener is created."""
    native_module = SimpleNamespace(DecisionReceipt=object) if native_available else None
    expected_error = ValueError if native_available else ModuleNotFoundError
    with (
        patch.dict(sys.modules, {"contextual_orchestrator._decision_receipt": native_module}),
        patch.object(server_module, "ResponsiveThreadingHTTPServer") as listener_factory,
        pytest.raises(expected_error),
    ):
        server_module.serve(SimpleNamespace(_store=None), decision_receipts=True)
    listener_factory.assert_not_called()
