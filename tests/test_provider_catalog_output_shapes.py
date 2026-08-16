"""Native provider output variants and safe summary contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.credentials import (  # noqa: E402
    InMemoryCredentialBackend,
    set_backend,
)
from contextual_orchestrator.orchestrator import ModelAgent  # noqa: E402
from contextual_orchestrator.provider_catalog import (  # noqa: E402
    DEFAULT_PROVIDER_ACCOUNTS,
    ProviderAwareModelClient,
    _safe_cli_summary,
    bootstrap_provider_credentials,
)


def test_bytez_text_mapping_is_accepted_without_usage_fabrication() -> None:
    """A native Bytez text field is accepted while usage remains explicitly absent."""
    set_backend(InMemoryCredentialBackend())
    try:
        account = DEFAULT_PROVIDER_ACCOUNTS[2]
        bootstrap_provider_credentials(
            {account.credential_name: "secret-value"},
            require_all=False,
            accounts=(account,),
        )
        agent = ModelAgent(
            "bytez_worker",
            "owner/model",
            account.base_url,
            credential_key=account.credential_name,
            provider_name="bytez",
        )
        client = ProviderAwareModelClient(
            bytez_request=lambda _agent, _messages, _credential: {
                "output": {"text": "text-answer"}
            }
        )
        assert client.chat(agent, [{"role": "user", "content": "hello"}]) == "text-answer"
        assert client.take_usage() is None
    finally:
        set_backend(None)


def test_safe_bootstrap_summary_exposes_names_and_counts_only() -> None:
    """The CI summary is stable, JSON-serializable, and contains no unknown input fields."""
    summary = _safe_cli_summary(
        {
            "registered_credentials": ["OPENAI_API_KEY"],
            "missing_credentials": ["BYTEZ_API_KEY"],
            "secret_value": "must-not-copy",
        },
        {
            "candidate_model_count": 4,
            "provider_accounts": {"openai_primary": {"status": "refreshed"}},
            "provider_body": "must-not-copy",
        },
    )
    assert summary == {
        "registered_credentials": ["OPENAI_API_KEY"],
        "missing_credentials": ["BYTEZ_API_KEY"],
        "candidate_model_count": 4,
        "provider_accounts": {"openai_primary": {"status": "refreshed"}},
        "measurement_status": "provider_catalog_bootstrap",
    }
    assert "must-not-copy" not in json.dumps(summary)
