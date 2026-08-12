"""CLI price-table validation for fail-closed cost-aware routing."""

from __future__ import annotations

import argparse

import pytest

from contextual_orchestrator.__main__ import _json_object


def test_price_table_accepts_finite_non_negative_values() -> None:
    """Finite zero and positive prices remain valid operator evidence."""
    assert _json_object('{"model_a": 0, "model_b": 1.25}') == {
        "model_a": 0.0,
        "model_b": 1.25,
    }


@pytest.mark.parametrize(
    "raw",
    [
        '{"model_a": NaN}',
        '{"model_a": Infinity}',
        '{"model_a": -Infinity}',
        '{"model_a": 1e999}',
    ],
)
def test_price_table_rejects_non_finite_values(raw: str) -> None:
    """NaN and infinities must never enter routing or cost evidence."""
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        _json_object(raw)


def test_price_table_rejects_boolean_and_negative_values() -> None:
    """JSON booleans and negative prices remain invalid despite Python scalar coercion."""
    with pytest.raises(argparse.ArgumentTypeError):
        _json_object('{"model_a": true}')
    with pytest.raises(argparse.ArgumentTypeError):
        _json_object('{"model_a": -0.01}')


def test_price_table_rejects_non_object_payloads() -> None:
    """Only a JSON object of model→price mappings is accepted."""
    with pytest.raises(argparse.ArgumentTypeError, match="JSON object"):
        _json_object("[1, 2]")
    with pytest.raises(argparse.ArgumentTypeError):
        _json_object("not-json")


if __name__ == "__main__":  # pragma: no cover
    test_price_table_accepts_finite_non_negative_values()
    test_price_table_rejects_boolean_and_negative_values()
    test_price_table_rejects_non_object_payloads()
    print("ok")
