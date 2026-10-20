"""Issue #1347 acceptance: an absent or stalled SearXNG never yields search evidence.

Real loopback sockets exercise the unchanged transport. The claim verdict path
does not use SearXNG, so search outages cannot turn a claim into a finding.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from contextual_orchestrator import vulnerability_claim as claims
from contextual_orchestrator import web_search_mcp
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)
from contextual_orchestrator.web_search import web_search


@pytest.fixture(autouse=True)
def _backend() -> Iterator[None]:
    set_backend(InMemoryCredentialBackend())
    yield
    set_backend(InMemoryCredentialBackend())


def _closed_loopback_port() -> int:
    """Return a loopback port that had a listener and now refuses connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def stalled_listener() -> Iterator[int]:
    """Accept connections but never send a byte; close every owned socket."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    server.settimeout(0.1)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept_loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except (TimeoutError, OSError):
                continue
            accepted.append(conn)

    worker = threading.Thread(target=accept_loop, daemon=True)
    worker.start()
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        worker.join(timeout=5)
        for conn in accepted:
            conn.close()
        server.close()
    assert not worker.is_alive()


def test_refused_searxng_raises_instead_of_returning_results() -> None:
    register_credential("SEARXNG_URL", f"http://127.0.0.1:{_closed_loopback_port()}")
    with pytest.raises(OSError):
        web_search("CVE-2024-1234 lodash", timeout=1)


def test_stalled_searxng_times_out_within_the_requested_bound(stalled_listener: int) -> None:
    register_credential("SEARXNG_URL", f"http://127.0.0.1:{stalled_listener}")
    started = time.monotonic()
    with pytest.raises(OSError):
        web_search("CVE-2024-1234 lodash", timeout=1)
    assert time.monotonic() - started < 10


def test_unconfigured_searxng_mcp_payload_fails_without_results() -> None:
    with pytest.raises(ValueError, match="not configured"):
        web_search_mcp.web_search_tool_payload("CVE-2024-1234 lodash")


def test_refused_searxng_mcp_payload_fails_without_results() -> None:
    register_credential("SEARXNG_URL", f"http://127.0.0.1:{_closed_loopback_port()}")
    with pytest.raises(OSError):
        web_search_mcp.web_search_tool_payload("CVE-2024-1234 lodash")


def test_claim_verdict_is_independent_of_searxng_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SearXNG refusing, a lodash claim stays unverified and is never a finding."""
    register_credential("SEARXNG_URL", f"http://127.0.0.1:{_closed_loopback_port()}")
    monkeypatch.setattr(claims, "get_credential", lambda _: str(tmp_path))
    (tmp_path / "package.json").write_text('{"dependencies":{"lodash":"4.17.20"}}')
    monkeypatch.setattr(
        claims, "_fetch_official_record",
        lambda _: (_ for _ in ()).throw(OSError("official record unavailable")),
    )
    verdict = claims.assess_vulnerability_claim("CVE-2024-1234", "lodash", "npm")
    assert verdict.status == claims.CLAIM_UNVERIFIED
    assert not verdict.finding_allowed and not verdict.versions_checked
