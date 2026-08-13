"""Unit fixtures for batch embeddings encoding_format / dimensions honesty."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    _validate_embeddings_dimensions,
    _validate_embeddings_encoding_format,
)


def test_unit_encoding_format_omit_ok() -> None:
    assert _validate_embeddings_encoding_format({}) is None


def test_unit_encoding_format_float_ok() -> None:
    assert (
        _validate_embeddings_encoding_format(
            {"encoding_format": "float"},
            endpoint_path="/v1/batch/embeddings",
        )
        == "float"
    )


def test_unit_encoding_format_base64_named_error() -> None:
    try:
        _validate_embeddings_encoding_format(
            {"encoding_format": "base64"},
            endpoint_path="/v1/batch/embeddings",
        )
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_encoding_format"
        assert "/v1/batch/embeddings" in exc.message
        return
    raise AssertionError("expected RequestError")


def test_unit_encoding_format_non_string() -> None:
    try:
        _validate_embeddings_encoding_format({"encoding_format": 1})
    except RequestError as exc:
        assert exc.code == "invalid_encoding_format"
        return
    raise AssertionError("expected RequestError")


def test_unit_dimensions_omit_ok() -> None:
    _validate_embeddings_dimensions({})


def test_unit_dimensions_any_value_named_error() -> None:
    try:
        _validate_embeddings_dimensions(
            {"dimensions": 256},
            endpoint_path="/v1/batch/embeddings",
        )
    except RequestError as exc:
        assert exc.status == 400
        assert exc.code == "invalid_dimensions"
        assert "/v1/batch/embeddings" in exc.message
        return
    raise AssertionError("expected RequestError")


def test_unit_dimensions_null_named_error() -> None:
    try:
        _validate_embeddings_dimensions(
            {"dimensions": None},
            endpoint_path="/v1/batch/embeddings",
        )
    except RequestError as exc:
        assert exc.code == "invalid_dimensions"
        return
    raise AssertionError("expected RequestError")


if __name__ == "__main__":
    test_unit_encoding_format_omit_ok()
    test_unit_encoding_format_float_ok()
    test_unit_encoding_format_base64_named_error()
    test_unit_encoding_format_non_string()
    test_unit_dimensions_omit_ok()
    test_unit_dimensions_any_value_named_error()
    test_unit_dimensions_null_named_error()
    print("ok")
