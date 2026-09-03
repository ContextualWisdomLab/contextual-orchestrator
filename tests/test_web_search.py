"""SearXNG-backed ``web_search`` tool: validated transport, no real network calls."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.web_search import (
    MAX_RESPONSE_BYTES,
    MAX_RESULTS,
    MAX_TIMEOUT_SECONDS,
    WebSearchResult,
    web_search,
)


class _Response:
    """Minimal stand-in for ``http.client.HTTPResponse`` used by ``_open_provider``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def _searxng_response(results: list[dict[str, object]]) -> bytes:
    return json.dumps({"results": results}).encode("utf-8")


@pytest.fixture(autouse=True)
def _reset_credentials():
    """Isolate each test's KV credentials in a fresh in-memory backend."""
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(None)


def test_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        web_search("   ")


def test_rejects_too_long_query() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        web_search("x" * 513)


def test_rejects_non_string_categories() -> None:
    with pytest.raises(ValueError, match="categories"):
        web_search("q", categories="")


def test_rejects_non_string_language() -> None:
    with pytest.raises(ValueError, match="language"):
        web_search("q", language="")


@pytest.mark.parametrize("bad", [0, -1, MAX_RESULTS + 1, True, 3.5])
def test_rejects_out_of_range_max_results(bad: object) -> None:
    with pytest.raises(ValueError, match="max_results"):
        web_search("q", max_results=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        True,
        False,
        0,
        -1.0,
        float("nan"),
        float("inf"),
        float("-inf"),
        MAX_TIMEOUT_SECONDS + 1,
        "10",
        None,
        10**400,  # too large for float(): math.isfinite() would raise OverflowError
    ],
)
def test_rejects_invalid_timeout(bad: object) -> None:
    with pytest.raises(ValueError, match="timeout"):
        web_search("q", timeout=bad)  # type: ignore[arg-type]


def test_rejects_unsupported_engine() -> None:
    with pytest.raises(ValueError, match="unsupported search engine"):
        web_search("q", engine="bing")


def test_requires_configured_searxng_url() -> None:
    with pytest.raises(ValueError, match="not configured"):
        web_search("q")


def test_rejects_url_with_userinfo() -> None:
    register_credential("SEARXNG_URL", "https://user:pass@searxng.example")
    with pytest.raises(ValueError, match="invalid"):
        web_search("q")


def test_rejects_unsupported_scheme() -> None:
    register_credential("SEARXNG_URL", "ftp://searxng.example")
    with pytest.raises(ValueError, match="invalid"):
        web_search("q")


def test_rejects_non_loopback_http_url() -> None:
    register_credential("SEARXNG_URL", "http://searxng.internal:8080")
    with pytest.raises(RuntimeError, match="https"):
        web_search("q")


def test_returns_parsed_results_bounded_and_type_checked() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example")
    rows = [
        "not a row",
        {
            "url": "https://a.example/1",
            "title": "Result A",
            "content": "snippet a",
            "engine": "duckduckgo",
            "score": 1.5,
            "publishedDate": "2026-08-01",
        },
        {"missing_url": True},
        {"url": "https://b.example/2", "title": "Result B"},
        {"url": 5, "title": "not a string url"},
        {"url": "https://c.example/3", "title": "Result C", "score": True},
    ]
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(_searxng_response(rows)),
        ) as opened,
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        results = web_search("test query", max_results=2)

    assert results == [
        WebSearchResult(
            url="https://a.example/1",
            title="Result A",
            content="snippet a",
            engine="duckduckgo",
            score=1.5,
            published_date="2026-08-01",
        ),
        WebSearchResult(url="https://b.example/2", title="Result B", content="", engine=""),
    ]
    request = opened.call_args.args[0]
    assert request.full_url.startswith("https://searxng.example/search?")
    assert "q=test+query" in request.full_url
    assert "format=json" in request.full_url
    assert "authorization" not in {key.lower() for key in request.headers}


def test_sends_bearer_token_when_configured() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example")
    register_credential("SEARXNG_TOKEN", "secret-token")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(_searxng_response([])),
        ) as opened,
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        assert web_search("q") == []

    request = opened.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer secret-token"


def test_oversized_response_raises() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example")
    oversized = _searxng_response([{"url": "https://a.example", "title": "pad " + "x" * MAX_RESPONSE_BYTES}])
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(oversized),
        ),
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        with pytest.raises(ValueError, match="size limit"):
            web_search("q")


def test_rejects_non_dict_payload() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(json.dumps([1, 2, 3]).encode()),
        ),
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        with pytest.raises(TypeError, match="invalid JSON envelope"):
            web_search("q")


def test_rejects_missing_results_list() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(json.dumps({"number_of_results": 0}).encode()),
        ),
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        with pytest.raises(TypeError, match="omitted a results list"):
            web_search("q")


def test_works_over_loopback_http() -> None:
    register_credential("SEARXNG_URL", "http://127.0.0.1:8080")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(_searxng_response([])),
        ) as opened,
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("127.0.0.1", 8080))],
        ),
    ):
        assert web_search("q") == []

    request = opened.call_args.args[0]
    assert request.full_url.startswith("http://127.0.0.1:8080/search?")


def test_queries_configured_deployment_subpath() -> None:
    """A SearXNG instance reverse-proxied under a path prefix must keep it.

    Regression: ``_searxng_origins`` used to build ``request_base_url`` from
    only the scheme and host, discarding ``SEARXNG_URL``'s path component.
    ``https://host/searxng`` was therefore queried at ``https://host/search``
    (the host root) instead of ``https://host/searxng/search``.
    """
    register_credential("SEARXNG_URL", "https://searxng.example/searxng")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(_searxng_response([])),
        ) as opened,
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        assert web_search("q") == []

    request = opened.call_args.args[0]
    assert request.full_url.startswith("https://searxng.example/searxng/search?")


def test_queries_configured_deployment_subpath_with_trailing_slash() -> None:
    register_credential("SEARXNG_URL", "https://searxng.example/searxng/")
    with (
        patch(
            "contextual_orchestrator.web_search.ModelClient._open_provider",
            return_value=_Response(_searxng_response([])),
        ) as opened,
        patch(
            "contextual_orchestrator.web_search.ModelClient._resolve_addresses",
            return_value=[(2, ("93.184.216.34", 443))],
        ),
    ):
        assert web_search("q") == []

    request = opened.call_args.args[0]
    assert request.full_url.startswith("https://searxng.example/searxng/search?")


def test_web_search_result_as_dict_round_trip() -> None:
    result = WebSearchResult(
        url="https://a.example",
        title="A",
        content="c",
        engine="duckduckgo",
        score=0.9,
        published_date="2026-08-01",
    )
    assert result.as_dict() == {
        "url": "https://a.example",
        "title": "A",
        "content": "c",
        "engine": "duckduckgo",
        "score": 0.9,
        "published_date": "2026-08-01",
    }
