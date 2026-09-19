from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.server import MAX_JSON_NESTING_DEPTH, RequestError, _coerce_json  # noqa: E402


def _nested_json_bomb(depth: int) -> bytes:
    return (b'{"a":' * depth) + b"1" + (b"}" * depth)


def test_shallow_json_is_accepted() -> None:
    body = _coerce_json(b'{"a": {"b": {"c": 1}}}')
    assert body == {"a": {"b": {"c": 1}}}


def test_excessive_nesting_is_rejected_before_parsing() -> None:
    bomb = _nested_json_bomb(MAX_JSON_NESTING_DEPTH + 1)
    try:
        _coerce_json(bomb)
    except RequestError as exc:
        assert exc.code == "invalid_json"
    else:
        raise AssertionError("expected RequestError for over-deep JSON nesting")


def test_nesting_at_the_limit_is_accepted() -> None:
    payload = _nested_json_bomb(MAX_JSON_NESTING_DEPTH)
    _coerce_json(payload)  # must not raise


def test_braces_inside_strings_do_not_count_toward_depth() -> None:
    value = "{" * (MAX_JSON_NESTING_DEPTH + 5)
    body = _coerce_json(('{"a": "%s"}' % value).encode("utf-8"))
    assert body["a"] == value


if __name__ == "__main__":  # pragma: no cover
    test_shallow_json_is_accepted()
    test_excessive_nesting_is_rejected_before_parsing()
    test_nesting_at_the_limit_is_accepted()
    test_braces_inside_strings_do_not_count_toward_depth()
    print("ok")
