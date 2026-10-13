"""Offline cross-page promotion admission regressions; no provider traffic."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from contextual_orchestrator import experiential_billing_probe as probe
from test_experiential_billing_probe import (
    FixtureTransport, _catalog, _run, credential_backend,
)


def _paged_request(transport, change):
    """Provide valid model pages and vary only the promotion observation."""
    def request(method, route, payload=None):
        if route.startswith("/api/models"):
            transport.calls.append((method, route, payload))
            assert method == "GET"
            offset = int(parse_qs(urlsplit(route).query).get("offset", [0])[0])
            page = _catalog("other-model" if offset == 0 else "jev-latest")
            page.update(total=2, limit=1, offset=offset)
            # Explicit equal global observations, independent of page model rows.
            page["promotions"] = _catalog()["promotions"]
            if offset == 1:
                change(page)
            return 200, {}, page
        return transport(method, route, payload)
    return request


def test_changed_second_page_promotion_blocks_post(tmp_path):
    """A later revoked promotion must invalidate the first-page send target."""
    transport = FixtureTransport(tmp_path / "evidence.json")

    def revoke(page):
        page["promotions"][0]["free"] = False

    error = None
    try:
        _run(transport.path, _paged_request(transport, revoke))
    except ValueError as exc:
        error = exc
    assert transport.posts == 0, "inconsistent page promotions admitted an inference POST"
    assert error is not None and "discovery" in str(error)
    evidence = json.loads(transport.path.read_text())
    assert evidence["outcome"] == "preflight_failed"
    assert evidence["request_count"] == 0
    assert "promotion_id" not in evidence
    before = list(transport.calls)
    with pytest.raises(ValueError, match="already exists"):
        _run(transport.path, _paged_request(transport, revoke))
    assert transport.calls == before


@pytest.mark.parametrize("problem", ["missing", "null", "empty", "identity", "slugs", "display"])
def test_invalid_second_page_promotions_fail_closed(tmp_path, problem):
    """Unavailable or changed later observations never authorize a POST."""
    transport = FixtureTransport(tmp_path / "evidence.json")

    def change(page):
        if problem == "missing":
            page.pop("promotions")
        elif problem == "null":
            page["promotions"] = None
        elif problem == "empty":
            page["promotions"] = []
        else:
            key, value = {"identity": ("id", "promo-2"),
                          "slugs": ("slugs", ["other-model"]),
                          "display": ("display_only", True)}[problem]
            page["promotions"][0][key] = value

    with pytest.raises(ValueError, match="discovery"):
        _run(transport.path, _paged_request(transport, change))
    assert transport.posts == 0
    evidence = json.loads(transport.path.read_text())
    assert evidence["outcome"] == "preflight_failed" and evidence["request_count"] == 0


@pytest.mark.parametrize("page_index", [0, 1])
@pytest.mark.parametrize("value", [None, {}, "unavailable"])
def test_catalog_requires_explicit_promotion_lists(monkeypatch, page_index, value):
    """The catalog reader neither fills missing metadata nor consumes keys."""
    calls = []

    def forbidden(*_, **__):
        pytest.fail("catalog admission must not consume credentials or native transport")

    monkeypatch.setattr(probe, "get_credential", forbidden)
    monkeypatch.setattr(probe, "_request", forbidden)

    def request(method, route, payload=None):
        calls.append(route)
        offset = int(parse_qs(urlsplit(route).query).get("offset", [0])[0])
        page = _catalog()
        page.update(total=2, limit=1, offset=offset)
        if offset == page_index:
            if value is None:
                page.pop("promotions")
            else:
                page["promotions"] = value
        return 200, {}, page

    with pytest.raises(ValueError, match="promotions"):
        probe._catalog(request)
    assert len(calls) == page_index + 1


def test_equal_page_promotions_admit_later_model_once(tmp_path):
    """Explicit identical observations preserve a model found on the later page."""
    transport = FixtureTransport(tmp_path / "evidence.json")
    result = _run(transport.path, _paged_request(transport, lambda page: None))
    assert result["model_id"] == "jev-latest" and result["promotion_id"] == "promo-1"
    assert result["ledger_charge_usd"] == "0.5" and transport.posts == 1
    assert [route for method, route, _ in transport.calls if route.startswith("/api/models")] == [
        "/api/models", "/api/models?limit=1&offset=1",
    ]
