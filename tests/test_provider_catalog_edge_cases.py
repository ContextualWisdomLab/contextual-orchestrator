"""Terminal retry and metadata edge cases for the provider catalog."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.provider_catalog import (  # noqa: E402
    DEFAULT_PROVIDER_ACCOUNTS,
    CatalogHttpError,
    ProviderCatalogHttpClient,
    normalize_models_document,
)


def test_terminal_transient_error_is_not_slept_or_retried() -> None:
    """A one-attempt policy surfaces its stable transient code immediately."""
    sleeps: list[float] = []
    client = ProviderCatalogHttpClient(max_attempts=1, sleep=sleeps.append)
    client._request_json = lambda _account, _credential: (_ for _ in ()).throw(  # type: ignore[method-assign]
        CatalogHttpError("catalog_http_503", transient=True)
    )
    with pytest.raises(CatalogHttpError, match="catalog_http_503"):
        client.discover(DEFAULT_PROVIDER_ACCOUNTS[0], "credential")
    assert sleeps == []


def test_boolean_context_and_empty_display_name_are_bounded() -> None:
    """Boolean context metadata is rejected and empty display names fall back to ids."""
    model = normalize_models_document(
        {
            "data": [
                {
                    "id": "fallback-model",
                    "name": "   ",
                    "context_length": True,
                    "pricing": {"prompt": False},
                }
            ]
        }
    )[0]
    assert model.display_name == "fallback-model"
    assert model.context_window is None
    assert model.input_price_usd_per_million is None
