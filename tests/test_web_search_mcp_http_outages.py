"""First-GREEN characterization of real HTTP; synthetic loopback fixtures only."""
import asyncio
import importlib
import inspect
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from contextual_orchestrator import web_search_mcp as gateway

search = importlib.import_module('contextual_orchestrator.web_search')
claims = importlib.import_module('contextual_orchestrator.vulnerability_claim')
TOKEN = 'synthetic-local-test-token-not-a-real-credential'
ROWS = [{'url': 'https://example.invalid/synthetic', 'title': 'SYNTHETIC fixture',
         'content': 'Not real SearXNG service evidence', 'engine': 'synthetic-fixture'}]


class SyntheticHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Return unchanged synthetic SearXNG JSON."""
        assert self.path.startswith('/search?')
        body = json.dumps({'results': ROWS}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep synthetic request logging quiet."""


def cleanup_actions(actions, primary=None):
    """Attempt all closes; retain body identity unless cleanup interrupts require a group."""
    errors = []
    for action in actions:
        try:
            action()
        except BaseException as error:
            errors.append(error)
    if errors:
        if any(not isinstance(error, Exception) for error in errors):
            members = errors if primary is None else [primary, *errors]
            raise BaseExceptionGroup('fixture body/cleanup failures', members)
        group = ExceptionGroup('fixture cleanup failures', errors)
        if primary is None:
            raise group
        primary.add_note(str(group))
    return errors


class OwnedWorker:
    """Own a non-daemon worker and retain every target exception explicitly."""
    def __init__(self, target, *, name, kwargs=None):
        """Start a worker whose failures are stored rather than warning-only."""
        self.errors = []
        def run():
            """Call the actual target and retain exception identity."""
            try:
                target(**(kwargs or {}))
            except BaseException as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=run, name=name)
        self.thread.start()

    def is_alive(self):
        """Report actual thread liveness."""
        return self.thread.is_alive()

    def close(self, timeout=5):
        """Join the actual thread and reject incomplete settlement."""
        self.thread.join(timeout)
        assert not self.thread.is_alive(), 'fixture worker remains alive'
        if self.errors:
            raise BaseExceptionGroup('fixture worker failures', self.errors)


class OwnedStall:
    """Accept actual sockets and send no bytes; all sockets owned until close."""
    def __init__(self):
        """Bind an owned loopback listener before starting its worker."""
        self.stop = threading.Event()
        self.accepted = threading.Event()
        self.connections = []
        self.lock = threading.Lock()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.listener.settimeout(.1)
        self.url = f'http://127.0.0.1:{self.listener.getsockname()[1]}'
        self.thread = OwnedWorker(self.serve, name='owned-search-tcp')

    def serve(self):
        """Record each actual accepted socket before fixture-specific handling."""
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.stop.is_set():
                    return
                raise
            with self.lock:
                self.connections.append(connection)
            self.accepted.set()
            self.handle_connection(connection)

    def handle_connection(self, connection):
        """Stall with no bytes until cleanup."""

    def close(self):
        """Attempt every owned close independently and reject worker faults."""
        self.stop.set()
        actions = [self.listener.close, self.thread.close]
        def close_connections():
            """Join precedes inventory; close each accepted socket independently."""
            with self.lock:
                cleanup_actions([c.close for c in self.connections])
        actions.append(close_connections)
        actions.append(self.verify_closed)
        cleanup_actions(actions)
        return {'accepted_connections': len(self.connections),
                'thread_alive': self.thread.is_alive(),
                'listener_closed': self.listener.fileno() == -1,
                'connections_closed': all(c.fileno() == -1 for c in self.connections)}

    def verify_closed(self):
        """Assert actual worker and socket absence."""
        assert not self.thread.is_alive()
        assert self.listener.fileno() == -1
        assert all(c.fileno() == -1 for c in self.connections)


class OwnedReset(OwnedStall):
    """Own the listening port and deliberately reset actual accepted peers."""
    def handle_connection(self, connection):
        """Perform abortive close on the actual owned connection."""
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        connection.close()


def test_mcp_error_envelope_redacts_cause(caplog):
    """The source-owned error result keeps cause details server-side only."""
    cause = RuntimeError('sentinel provider detail')
    with caplog.at_level('ERROR', logger='contextual_orchestrator.web_search_mcp'):
        result = gateway._mcp_tool_error('web_search', cause)
    assert result.is_error is True
    assert [item.text for item in result.content] == ['Error executing tool web_search']
    assert 'sentinel provider detail' in caplog.text


@pytest.mark.parametrize('condition', ['synthetic-success', 'missingconfig', 'owned-reset', 'stall'])
def test_streamable_http_envelope(monkeypatch, condition):
    """Characterize actual SDK envelopes, not external-service incident causes."""
    fixture = fixture_thread = stall = None
    mcp_socket = mcp_thread = http_server = None
    primary = None
    transport_errors = []
    values = {'WEB_SEARCH_MCP_TOKEN': TOKEN}
    try:
        assert inspect.signature(search.web_search).parameters['timeout'].default == 10.0
        if condition == 'owned-reset':
            stall = OwnedReset()
            values['SEARXNG_URL'] = stall.url
            original_open = search.ModelClient._open_provider
            def recorded_open(self, *args, **kwargs):
                """Return or re-raise the real provider outcome unchanged."""
                try:
                    return original_open(self, *args, **kwargs)
                except Exception as error:
                    transport_errors.append(error)
                    raise
            monkeypatch.setattr(search.ModelClient, '_open_provider', recorded_open)
        elif condition == 'synthetic-success':
            fixture = HTTPServer(('127.0.0.1', 0), SyntheticHandler)
            fixture_thread = OwnedWorker(fixture.serve_forever, name='owned-search-positive')
            values['SEARXNG_URL'] = f'http://127.0.0.1:{fixture.server_port}'
        elif condition == 'stall':
            stall = OwnedStall()
            values['SEARXNG_URL'] = stall.url
        # Only synthetic KV lookup replaced; real search/transport/parser/SDK.
        monkeypatch.setattr(gateway, 'get_credential', values.get)
        monkeypatch.setattr(search, 'get_credential', values.get)
        monkeypatch.setattr(claims, 'get_credential', values.get)
        server = gateway.build_web_search_mcp_server()
        app = server.streamable_http_app(stateless_http=True, json_response=True)
        mcp_socket = socket.socket()
        mcp_socket.bind(('127.0.0.1', 0))
        mcp_socket.listen(32)
        url = f'http://127.0.0.1:{mcp_socket.getsockname()[1]}/mcp'
        http_server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='on'))
        mcp_thread = OwnedWorker(http_server.run, kwargs={'sockets': [mcp_socket]}, name='owned-mcp-http')
        deadline = time.monotonic() + 15
        while not http_server.started and mcp_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert http_server.started, 'MCP HTTP fixture startup failed'

        async def invoke():
            """Call the real Streamable HTTP SDK with a fixture-only client budget."""
            # Fixture client budget exceeds unmodified production search timeout10.
            async with httpx2.AsyncClient(headers={'Authorization': f'Bearer {TOKEN}'},
                                          trust_env=False, timeout=httpx2.Timeout(20.0)) as client:
                async with streamable_http_client(url, http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        return await session.call_tool('web_search', {'query': 'synthetic outage characterization'})

        async def bounded():
            """Bound the invocation without changing production search defaults."""
            return await asyncio.wait_for(invoke(), timeout=25)

        started = time.monotonic()
        result = asyncio.run(bounded())
        elapsed = time.monotonic() - started
        packet = result.model_dump(mode='json', by_alias=True)
        print(json.dumps({'condition': condition, 'transport': 'streamable-http',
                          'invocation_seconds': elapsed, 'result': packet,
                          'transport_errors': [repr(e) for e in transport_errors]}, ensure_ascii=False))
        if condition in {'stall', 'owned-reset'}:
            assert stall.accepted.is_set(), 'Actual owned listener was not reached'
        if condition == 'owned-reset':
            assert transport_errors, 'No real transport exception recorded'
            assert all(isinstance(e, OSError) for e in transport_errors)
            assert not any(isinstance(e, ConnectionRefusedError) for e in transport_errors)
        if condition == 'synthetic-success':
            assert result.is_error is False
            assert 'SYNTHETIC fixture' in json.dumps(packet)
            assert 'https://example.invalid/synthetic' in json.dumps(packet)
        else:
            assert result.is_error is True
            assert result.structured_content is None
            assert result.content and all(item.type == 'text' for item in result.content)
            text = ' '.join(item.text for item in result.content)
            assert text == 'Error executing tool web_search'
            assert 'results' not in json.dumps(packet)
            assert 'SYNTHETIC fixture' not in json.dumps(packet)
            assert 'https://example.invalid/synthetic' not in json.dumps(packet)
            assert 'finding_allowed' not in json.dumps(packet)
    except BaseException as error:
        primary = error
        raise
    finally:
        actions = []
        if http_server is not None:
            actions.append(lambda: setattr(http_server, 'should_exit', True))
        if mcp_thread is not None:
            actions.append(lambda: mcp_thread.close(15))
        if mcp_socket is not None:
            actions.append(mcp_socket.close)
        if stall is not None:
            actions.append(stall.close)
        if fixture is not None:
            actions.append(fixture.shutdown)
        if fixture_thread is not None:
            actions.append(fixture_thread.close)
        if fixture is not None:
            actions.append(fixture.server_close)
        def verify_cleanup():
            """Assert resource absence after all independent close attempts."""
            assert mcp_thread is None or not mcp_thread.is_alive()
            assert mcp_socket is None or mcp_socket.fileno() == -1
            assert fixture_thread is None or not fixture_thread.is_alive()
            assert fixture is None or fixture.socket.fileno() == -1
            if stall is not None:
                stall.verify_closed()
            print(json.dumps({'condition': condition, 'cleanup_verified': True}))
        actions.append(verify_cleanup)
        cleanup_actions(actions, primary)
