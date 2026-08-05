"""One-shot, test-first repair for PR #96's plain-HTTP provider seam."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace exactly one audited source anchor or fail closed."""
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"expected one repair anchor in {path}, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def add_regression_tests() -> None:
    """Add focused tests that fail against the current unrestricted HTTP seam."""
    path = Path("tests/test_provider_address_pinning.py")
    source = path.read_text(encoding="utf-8")
    if "def test_literal_loopback_host_classification(" in source:
        raise SystemExit("loopback regression tests already exist")
    old_import = "from contextual_orchestrator.orchestrator import ModelClient\n"
    new_import = (
        "from contextual_orchestrator.orchestrator import (\n"
        "    ModelClient,\n"
        "    _literal_loopback_host,\n"
        ")\n"
    )
    if source.count(old_import) != 1:
        raise SystemExit("expected one ModelClient import anchor")
    source = source.replace(old_import, new_import, 1)
    tests = r'''

@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        (None, False),
        ("localhost", True),
        ("localhost.", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("192.0.2.1", False),
        ("api.example.com", False),
        ("localhost.example", False),
    ],
)
def test_literal_loopback_host_classification(
    hostname: str | None,
    expected: bool,
) -> None:
    """Only localhost and literal loopback addresses enter the HTTP test seam."""
    assert _literal_loopback_host(hostname) is expected


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1/chat",
        "http://192.0.2.1/v1/chat",
    ],
)
def test_open_provider_rejects_non_loopback_http(url: str) -> None:
    """Direct low-level callers cannot use plain HTTP outside loopback."""
    client = ModelClient()
    with pytest.raises(RuntimeError, match="literal loopback"):
        client._open_provider(urllib.request.Request(url, method="POST"))


def test_open_provider_rejects_url_userinfo() -> None:
    """Provider URLs cannot smuggle credentials through URL user information."""
    client = ModelClient()
    request = urllib.request.Request(
        "http://user:password@127.0.0.1:8080/v1/chat",
        method="POST",
    )
    with pytest.raises(RuntimeError, match="user information"):
        client._open_provider(request)


def test_loopback_http_uses_direct_connection_and_bypasses_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integration seam connects directly and ignores ambient proxy state."""
    client = ModelClient(timeout=13)
    response = _FakeResponse(body=b"loopback")
    connection = mock.Mock()
    connection.getresponse.return_value = response
    connection_class = mock.Mock(return_value=connection)
    client._http_connection_class = connection_class
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("NO_PROXY", "")
    request = urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat?trace=yes",
        data=b"{}",
        headers={"authorization": "Bearer local-secret"},
        method="POST",
    )

    with mock.patch(
        "contextual_orchestrator.orchestrator.urllib.request.urlopen",
        side_effect=AssertionError("ambient proxy-capable opener must not run"),
    ) as urlopen:
        with client._open_provider(request) as opened:
            assert opened.read() == b"loopback"

    urlopen.assert_not_called()
    connection_class.assert_called_once_with("127.0.0.1", 8080, timeout=13)
    connection.request.assert_called_once_with(
        "POST",
        "/v1/chat?trace=yes",
        body=b"{}",
        headers={"Authorization": "Bearer local-secret", "Connection": "close"},
    )
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_loopback_http_rejects_redirect_and_closes_resources() -> None:
    """A loopback response cannot redirect credentials to another origin."""
    client = ModelClient()
    response = _FakeResponse(status=302)
    connection = mock.Mock()
    connection.getresponse.return_value = response
    client._http_connection_class = mock.Mock(return_value=connection)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        client._open_provider(
            urllib.request.Request("http://localhost:8080/v1/chat", method="POST")
        )

    assert exc_info.value.code == 302
    assert response.closed is True
    connection.close.assert_called_once_with()


def test_loopback_http_connection_failure_closes_and_is_transient() -> None:
    """A failed direct loopback connection is closed and surfaced as URLError."""
    client = ModelClient()
    connection = mock.Mock()
    connection.request.side_effect = OSError("loopback unavailable")
    client._http_connection_class = mock.Mock(return_value=connection)

    with pytest.raises(urllib.error.URLError, match="loopback unavailable"):
        client._open_provider(
            urllib.request.Request("http://[::1]:8080/v1/chat", method="POST")
        )

    connection.close.assert_called_once_with()
'''
    path.write_text(source + tests, encoding="utf-8")


def apply_production_repair() -> None:
    """Restrict plain HTTP to direct literal-loopback transport and update doctoring."""
    path = Path("contextual_orchestrator/orchestrator.py")
    replace_once(
        path,
        "import http.client\nimport json\n",
        "import http.client\nimport ipaddress\nimport json\n",
    )
    replace_once(
        path,
        "TRANSIENT_HTTP_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})\n\n\ndef is_transient_error",
        '''TRANSIENT_HTTP_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _literal_loopback_host(hostname: str | None) -> bool:
    """Return whether a host is localhost or a literal loopback IP address."""
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_transient_error''',
    )
    replace_once(
        path,
        "        # Explicit test seam; production uses the DNS-pinned TLS connection.\n        self._https_connection_class = _PinnedHTTPSConnection\n",
        "        # Explicit test seams; production uses direct loopback HTTP and DNS-pinned TLS.\n        self._http_connection_class = http.client.HTTPConnection\n        self._https_connection_class = _PinnedHTTPSConnection\n",
    )
    old = '''        parsed = urlparse(request.full_url)
        if parsed.scheme == "http":
            return urllib.request.urlopen(  # nosec B310 - public validation rejects HTTP; private loopback test seam only. nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                request,
                timeout=self.timeout,
            )
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("provider request URL must use http(s)")

        port = parsed.port or 443
        pin_key = (parsed.hostname.lower(), port)
        addresses = getattr(self._local, "provider_address_pins", {}).get(pin_key)
        if not addresses:
            raise RuntimeError("provider request has no validated address pin")

        target = parsed.path or "/"
        if parsed.params:
            target = f"{target};{parsed.params}"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        headers = dict(request.header_items())
        headers["Connection"] = "close"

        last_error: BaseException | None = None
'''
    new = '''        parsed = urlparse(request.full_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("provider request URL must use http(s)")
        if parsed.username is not None or parsed.password is not None:
            raise RuntimeError("provider request URL must not contain user information")

        target = parsed.path or "/"
        if parsed.params:
            target = f"{target};{parsed.params}"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        headers = dict(request.header_items())
        headers["Connection"] = "close"

        if parsed.scheme == "http":
            if not _literal_loopback_host(parsed.hostname):
                raise RuntimeError(
                    "plain HTTP provider requests require a literal loopback target"
                )
            connection = self._http_connection_class(
                parsed.hostname,
                parsed.port or 80,
                timeout=self.timeout,
            )
            try:
                connection.request(
                    request.get_method(),
                    target,
                    body=request.data,
                    headers=headers,
                )
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                connection.close()
                raise urllib.error.URLError(exc) from exc
            if response.status >= 300:
                status = response.status
                reason = response.reason
                response_headers = response.headers
                response.close()
                connection.close()
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    reason,
                    response_headers,
                    None,
                )
            return _ProviderHTTPResponse(response, connection)

        port = parsed.port or 443
        pin_key = (parsed.hostname.lower(), port)
        addresses = getattr(self._local, "provider_address_pins", {}).get(pin_key)
        if not addresses:
            raise RuntimeError("provider request has no validated address pin")

        last_error: BaseException | None = None
'''
    replace_once(path, old, new)

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text(encoding="utf-8")
    entry = (
        "- Restrict the private plain-HTTP provider seam to localhost or literal "
        "loopback addresses, connect directly without ambient proxies, reject URL "
        "userinfo and redirects, and close failed resources deterministically.\n"
    )
    marker = "### Security\n\n"
    if entry not in text:
        if marker not in text:
            raise SystemExit("CHANGELOG Security section missing")
        changelog.write_text(text.replace(marker, marker + entry, 1), encoding="utf-8")


def main() -> None:
    """Dispatch the one-shot workflow's red and green phases."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: repair_pr96_loopback_http_v2.py add-tests|apply-production")
    if sys.argv[1] == "add-tests":
        add_regression_tests()
    elif sys.argv[1] == "apply-production":
        apply_production_repair()
    else:
        raise SystemExit(f"unknown repair phase: {sys.argv[1]}")


if __name__ == "__main__":
    main()
