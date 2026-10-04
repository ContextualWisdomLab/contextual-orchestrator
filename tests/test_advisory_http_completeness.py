"""Native HTTP parser framing must be complete before accepting advisory evidence."""

import http.client
import importlib
import json
import socket
from contextlib import contextmanager

import pytest

from contextual_orchestrator import vulnerability_claim as claims
from test_vulnerability_claim import _npm_lock, _versioned_record

_FRAMING_CASES = [("length", False), ("length", True),
                  ("chunked", False), ("chunked", True), ("close", False)]


def _wire_response(body, framing, truncated):
    """Construct complete or declared-incomplete native HTTP framing."""
    if framing == "length":
        return (b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(body) + (10 if truncated else 0)).encode()
                + b"\r\nConnection: close\r\n\r\n" + body)
    if framing == "chunked":
        return (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                + hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n"
                + (b"" if truncated else b"0\r\n\r\n"))
    return b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + body


@contextmanager
def _native_response(body, framing, truncated):
    """Own both socket endpoints and the actual stdlib HTTPResponse."""
    receiving, sending = socket.socketpair()
    response = None
    try:
        receiving.settimeout(2)
        sending.settimeout(2)
        sending.sendall(_wire_response(body, framing, truncated))
        sending.shutdown(socket.SHUT_WR)
        response = http.client.HTTPResponse(receiving)
        response.begin()
        if framing == "length":
            assert response.length == len(body) + (10 if truncated else 0)
        else:
            assert response.length is None
        yield response
    finally:
        if response is not None:
            response.close()
        receiving.close()
        sending.close()


@pytest.mark.parametrize("framing,truncated", _FRAMING_CASES)
@pytest.mark.parametrize("identifier", ["CVE-2024-1234", "GHSA-jf85-cpcp-j695"])
def test_advisory_framing_controls_evidence(tmp_path, monkeypatch, framing, truncated, identifier):
    """Reject incomplete CVE/GHSA bodies through the actual claim evaluator."""
    monkeypatch.setattr(claims, "get_credential", lambda _: str(tmp_path))
    _npm_lock(tmp_path, "1.5.0")
    if identifier.startswith("CVE"):
        payload = _versioned_record(identifier, [{
            "version": "1.0.0", "lessThan": "2.0.0",
            "versionType": "semver", "status": "affected",
        }])
    else:
        payload = {"ghsa_id": identifier, "withdrawn_at": None,
                   "vulnerabilities": [{"package": {"ecosystem": "npm", "name": "lodash"}}]}
    with _native_response(json.dumps(payload).encode(), framing, truncated) as response:
        monkeypatch.setattr(claims.ModelClient, "_validate_provider", lambda *_: "pinned")
        monkeypatch.setattr(claims.ModelClient, "_open_provider", lambda *_args, **_kwargs: response)
        verdict = claims.assess_vulnerability_claim(identifier, "lodash", "npm")
        assert response.closed
        if truncated:
            assert verdict.status == "unverified"
            assert not verdict.finding_allowed and not verdict.versions_checked
            assert verdict.repository_package_present is True
            assert verdict.package_match is None
        elif identifier.startswith("CVE"):
            assert verdict.status == "supported"
            assert verdict.finding_allowed and verdict.versions_checked
            assert verdict.affected_installed_versions == ("1.5.0",)
        else:
            assert verdict.status == "unverified" and verdict.package_match is True
            assert not verdict.finding_allowed and not verdict.versions_checked


@pytest.mark.parametrize("framing,truncated", _FRAMING_CASES)
def test_search_framing_never_yields_partial_results(monkeypatch, framing, truncated):
    """Refuse a truncated SearXNG JSON envelope while retaining complete rows."""
    search = importlib.import_module("contextual_orchestrator.web_search")
    monkeypatch.setattr(search, "get_credential", lambda name:
                        "https://searxng.example" if name == "SEARXNG_URL" else None)
    body = json.dumps({"results": [{"url": "https://example.com/advisory", "title": "fixture"}]}).encode()
    with _native_response(body, framing, truncated) as response:
        monkeypatch.setattr(search.ModelClient, "_validate_provider", lambda *_: "pinned")
        monkeypatch.setattr(search.ModelClient, "_open_provider", lambda *_args, **_kwargs: response)
        if truncated:
            with pytest.raises((ValueError, http.client.IncompleteRead)):
                search.web_search("fixture")
        else:
            rows = search.web_search("fixture")
            assert len(rows) == 1 and rows[0].url == "https://example.com/advisory"
        assert response.closed
