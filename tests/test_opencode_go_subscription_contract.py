"""OpenCode Go billing semantics must not leak into the zero-cost serving pool."""

from contextual_orchestrator.model_discovery import (
    PROVIDER_MODEL_SOURCES,
    _parse_openai_compatible,
)


def test_opencode_go_paid_subscription_is_not_classified_free_from_zero_unit_rates() -> None:
    """A monthly-paid entitlement is not a free provider even when token rates are zero."""
    source = next(
        item for item in PROVIDER_MODEL_SOURCES if item.provider_name == "opencode_go"
    )
    payload = {
        "data": [
            {
                "id": "kimi-k3",
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
                "is_free": True,
            }
        ]
    }

    assert source.requires_paid_subscription is True
    discovered = _parse_openai_compatible(payload, source)
    assert len(discovered) == 1
    assert discovered[0].is_free is False
