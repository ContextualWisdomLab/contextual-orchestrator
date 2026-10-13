"""Native ModelClient acquisition regressions over exclusively owned wire bytes."""

import http.client
import io
import json
import urllib.error

import pytest

from contextual_orchestrator import experiential_billing_probe as probe
from contextual_orchestrator import orchestrator as core
from test_experiential_billing_probe import credential_backend, _catalog


ERROR_ENVELOPE = core.MAX_PROVIDER_ERROR_BODY_BYTES + 1


@pytest.mark.parametrize('cleanup_type', [ValueError, LookupError, OSError, RuntimeError,
                                        KeyboardInterrupt, SystemExit])
def test_native_http_error_status_survives_only_cleanup_exception(monkeypatch, cleanup_type):
    connections = native_connections(monkeypatch, lambda *_: (429, b'X-Request-Id: req-429\r\n', b'{}'))
    errors = []
    cleanup = cleanup_type('fixture cleanup fault')
    native_close = urllib.error.HTTPError.close

    def close_then_fail(error):
        errors.append(error)  # Retain exact error: garbage collection is not the close oracle.
        native_close(error)
        raise cleanup

    monkeypatch.setattr(urllib.error.HTTPError, 'close', close_then_fail)
    if isinstance(cleanup, Exception):
        assert probe._request('POST', '/v1/chat/completions', response_max_bytes=ERROR_ENVELOPE) == (
            429, {'x-request-id': 'req-429'}, {})
    else:
        with pytest.raises(cleanup_type) as caught:
            probe._request('POST', '/v1/chat/completions', response_max_bytes=ERROR_ENVELOPE)
        assert caught.value is cleanup
    assert len(errors) == 1 and errors[0].fp.closed
    assert len(connections) == 1 and connections[0].reads == [ERROR_ENVELOPE]
    assert connections[0].calls == [('POST', '/v1/chat/completions')]
    assert connections[0].wire.stream.closed and connections[0].close_calls >= 1


@pytest.mark.parametrize('lengths', ['Content-Length: 11\r\nContent-Length: 12\r\n',
                                   'Content-Length: 11, 12\r\n',
                                   'Content-Length: 11\r\nContent-Length: 11, 12\r\n'])
def test_native_conflicting_lengths_reject_before_body_read(monkeypatch, lengths):
    connections = native_connections(monkeypatch, lambda *_: (200, lengths.encode(), b'{"data":[]} '))
    try:
        with pytest.raises(ValueError, match='content length'):
            probe._request('POST', '/v1/chat/completions', response_max_bytes=ERROR_ENVELOPE)
        assert len(connections) == 1 and connections[0].reads == []
        assert connections[0].calls == [('POST', '/v1/chat/completions')]
        assert connections[0].wire.stream.closed
    finally:
        for connection in connections:
            connection.response.close()


@pytest.mark.parametrize('lengths', ['Content-Length: 11\r\nContent-Length: 11\r\n',
                                   'Content-Length: 11, 11\r\n'])
def test_native_equal_lengths_preserve_complete_json(monkeypatch, lengths):
    connections = native_connections(monkeypatch, lambda *_: (200, lengths.encode(), b'{"data":[]}'))
    assert probe._request('GET', '/v1/models', response_max_bytes=ERROR_ENVELOPE)[2] == {'data': []}
    assert connections[0].reads == [ERROR_ENVELOPE + 1]
    assert connections[0].wire.stream.closed


class OwnedWire:
    """Supply real HTTPResponse's file interface and retain physical close evidence."""

    def __init__(self, wire):
        self.stream = io.BytesIO(wire)

    def makefile(self, *_):
        return self.stream


def native_connections(monkeypatch, responder):
    """Replace only network connection and address validation; run real core open."""
    connections = []

    class Connection:
        def __init__(self, host, port, *, timeout, context):
            assert host == 'api.experientiallabs.ai' and port == 443
            assert timeout is None and context is not None
            self.sock = self
            self.close_calls = 0
            self.reads = []
            self.calls = []
            self.response = None
            connections.append(self)

        def connect(self):
            pass

        def settimeout(self, timeout):
            assert timeout is None

        def request(self, method, target, *, body, headers):
            self.calls.append((method, target))
            status, extra, raw = responder(method, target, body)
            wire = (f'HTTP/1.1 {status} Fixture\r\n'.encode() + extra + b'\r\n' + raw)
            self.wire = OwnedWire(wire)
            self.response = http.client.HTTPResponse(self.wire)
            self.response.begin()
            read = self.response.read

            def observed_read(size=None):
                self.reads.append(size)
                assert type(size) is int and size > 0
                return read(size)

            self.response.read = observed_read

        def getresponse(self):
            return self.response

        def close(self):
            self.close_calls += 1

    monkeypatch.setattr(core.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(probe.ModelClient, '_validate_provider', lambda *_: 'fixture-pinned')
    return connections


@pytest.mark.parametrize('entry', ['request', 'run_probe'])
def test_small_native_budget_refuses_before_credentials_or_send(tmp_path, monkeypatch, entry):
    connections = native_connections(monkeypatch, lambda *_: (503, b'', b'x' * ERROR_ENVELOPE))
    credential_reads = []
    monkeypatch.setattr(probe, 'get_credential', lambda name: credential_reads.append(name) or 'fixture-secret')
    path = tmp_path / 'evidence.json'
    try:
        with pytest.raises(ValueError, match='native.*byte budget'):
            if entry == 'request':
                probe._request('POST', '/v1/chat/completions', response_max_bytes=ERROR_ENVELOPE - 1)
            else:
                probe.run_probe(path, source_sha='a' * 40, run_id='123', run_attempt='1',
                                response_max_bytes=ERROR_ENVELOPE - 1)
        assert credential_reads == [] and connections == [] and not path.exists()
    finally:
        for connection in connections:
            connection.response.close()


@pytest.mark.parametrize('framing', ['close', 'length', 'chunked'])
def test_native_error_acquisition_fits_admitted_envelope(monkeypatch, framing):
    raw = b'{"usage":{"cost":0}}' + b'x' * ERROR_ENVELOPE
    headers = b'X-Request-Id: req-1\r\n'
    if framing == 'length':
        headers += f'Content-Length: {len(raw)}\r\n'.encode()
    elif framing == 'chunked':
        headers += b'Transfer-Encoding: chunked\r\n'
        raw = f'{len(raw):x}\r\n'.encode() + raw + b'\r\n0\r\n\r\n'
    connections = native_connections(monkeypatch, lambda *_: (503, headers, raw))
    assert probe._request('POST', '/v1/chat/completions', response_max_bytes=ERROR_ENVELOPE) == (
        503, {'x-request-id': 'req-1'}, {})
    assert len(connections) == 1
    connection = connections[0]
    assert connection.calls == [('POST', '/v1/chat/completions')]
    assert connection.reads == [ERROR_ENVELOPE]
    assert connection.wire.stream.closed and connection.response.isclosed()
    assert connection.close_calls >= 1


def test_native_error_is_unknown_one_post_without_replay(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.json'

    def responder(method, target, raw):
        if method == 'POST':
            assert json.loads(path.read_text())['outcome'] == 'attempt_pending'
            assert set(json.loads(raw)) == {'model', 'messages', 'safety_identifier'}
            return 503, b'', b'{"usage":{"cost":0}}' + b'x' * ERROR_ENVELOPE
        if target == '/v1/models':
            body = {'data': [{'id': 'jev-latest'}]}
        elif target == '/api/models':
            body = _catalog()
        else:
            body = {'data': [], 'next_cursor': None}
        raw = json.dumps(body).encode()
        return 200, f'Content-Length: {len(raw)}\r\n'.encode(), raw

    connections = native_connections(monkeypatch, responder)
    result = probe.run_probe(path, source_sha='a' * 40, run_id='123', run_attempt='1',
                             response_max_bytes=ERROR_ENVELOPE)
    assert result['http_status'] == 503 and result['outcome'] == 'charge_unknown'
    assert result['response_cost_usd'] is None and result['ledger_charge_usd'] is None
    assert result['cost_comparison'] == 'unknown'
    assert result['response_resource_admission'] == 'not_exceeded'
    assert sum(method == 'POST' for c in connections for method, _ in c.calls) == 1
    before = len(connections)
    with pytest.raises(ValueError, match='already exists'):
        probe.run_probe(path, source_sha='a' * 40, run_id='123', run_attempt='1',
                        response_max_bytes=ERROR_ENVELOPE)
    assert len(connections) == before
    assert all(c.wire.stream.closed and c.response.isclosed() for c in connections)
    assert next(c for c in connections if c.calls[0][0] == 'POST').reads == [ERROR_ENVELOPE]
