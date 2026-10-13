"""Portable fixture-only lifecycle controls; no production repair is claimed."""
import ast
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

# Load only the current sibling, never a historical report or old source string.
PATH = Path(__file__).with_name('test_web_search_mcp_http_outages.py')
spec = importlib.util.spec_from_file_location('http_outage_fixture', PATH)
assert spec is not None and spec.loader is not None
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def fail(error):
    """Raise the exact injected object."""
    raise error


def leaves(error):
    """Retain nested worker groups while exposing their original leaf identities."""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in leaves(child)]
    return [error]


@pytest.mark.parametrize('error_type', [KeyboardInterrupt, SystemExit, RuntimeError])
def test_tcp_worker_fault_closes_accepted_sockets(error_type):
    """A real dead reset worker cannot bypass actual accepted-socket settlement."""
    error = error_type('accepted-worker')

    class InterruptedReset(fixture.OwnedReset):
        """Interrupt after real accept, before the usual abortive close."""
        def handle_connection(self, connection):
            """Fail with the original object while the accepted socket is open."""
            raise error

    owner = InterruptedReset()
    peer = None
    try:
        peer = socket.create_connection(('127.0.0.1', owner.listener.getsockname()[1]), timeout=2)
        assert owner.accepted.wait(2)
        owner.thread.thread.join(5)
        assert not owner.thread.is_alive()
        assert owner.thread.errors[0] is error
        assert len(owner.connections) == 1
        assert owner.connections[0].fileno() != -1
        with pytest.raises(BaseExceptionGroup) as caught:
            owner.close()
        # All observations precede the independent fixture recovery below.
        assert owner.listener.fileno() == -1
        assert all(c.fileno() == -1 for c in owner.connections)
        assert not owner.thread.is_alive()
        assert leaves(caught.value) == [error]
        assert leaves(caught.value)[0] is error
        assert isinstance(caught.value, ExceptionGroup) is isinstance(error, Exception)
    finally:
        owner.stop.set()
        owner.listener.close()
        owner.thread.thread.join(5)
        for connection in owner.connections:
            connection.close()
        if peer is not None:
            peer.close()


@pytest.mark.parametrize('worker_type', [KeyboardInterrupt, SystemExit, RuntimeError])
@pytest.mark.parametrize('primary_type', [RuntimeError, KeyboardInterrupt])
def test_mcp_finally_worker_fault_attempts_other_owners(worker_type, primary_type):
    """The actual current MCP finally settles later owners before propagating faults."""
    error = worker_type('mcp-worker')
    primary = primary_type('body-primary')
    worker = fixture.OwnedWorker(lambda: fail(error), name='mcp-crossed-fault')
    listener = socket.socket()
    reset = None
    try:
        worker.thread.join(5)
        assert not worker.is_alive()
        assert worker.errors[0] is error
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        reset = fixture.OwnedReset()
        assert listener.fileno() != -1
        assert reset.listener.fileno() != -1
        assert reset.thread.is_alive()
        module = ast.parse(PATH.read_text())
        test = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'test_streamable_http_envelope')
        owned_try = next(n for n in test.body if isinstance(n, ast.Try))
        final_code = compile(ast.Module(body=owned_try.finalbody, type_ignores=[]), str(PATH), 'exec')
        server = SimpleNamespace(should_exit=False)
        scope = dict(http_server=server, mcp_thread=worker, mcp_socket=listener,
                     stall=reset, fixture=None, fixture_thread=None, primary=primary,
                     cleanup_actions=fixture.cleanup_actions, condition='crossed-control', json=json)
        with pytest.raises(BaseException) as caught:
            try:
                raise primary
            finally:
                exec(final_code, scope)
        # No independent finally has run: these are candidate-owned effects.
        assert server.should_exit
        assert listener.fileno() == -1
        reset.verify_closed()
        assert not worker.is_alive()
        if isinstance(error, Exception):
            assert caught.value is primary
            assert primary.__notes__
        else:
            assert type(caught.value) is BaseExceptionGroup
            actual = leaves(caught.value)
            assert len(actual) == 2
            assert actual[0] is primary
            assert actual[1] is error
    finally:
        listener.close()
        worker.thread.join(5)
        if reset is not None:
            reset.close()


@pytest.mark.parametrize('primary_type', [RuntimeError, KeyboardInterrupt])
def test_cleanup_preserves_primary_and_attempts_siblings(primary_type):
    """Ordinary faults keep the body primary identity and attempt all siblings."""
    primary = primary_type('body')
    errors = [OSError('one'), ValueError('two')]
    seen = []
    def bad(error):
        """Record then raise an exact ordinary error."""
        seen.append(error)
        raise error
    with pytest.raises(BaseException) as caught:
        try:
            raise primary
        except BaseException as actual:
            returned = fixture.cleanup_actions(
                [lambda: bad(errors[0]), lambda: bad(errors[1]), lambda: seen.append('later')], actual)
            assert all(a is b for a, b in zip(returned, errors, strict=True))
            raise
    assert caught.value is primary
    assert seen == [*errors, 'later']


def test_cleanup_only_aggregate():
    """Two ordinary cleanup faults remain exact ExceptionGroup members."""
    errors = [OSError('one'), ValueError('two')]
    with pytest.raises(ExceptionGroup) as caught:
        fixture.cleanup_actions([lambda e=e: fail(e) for e in errors])
    assert all(a is b for a, b in zip(caught.value.exceptions, errors, strict=True))


@pytest.mark.parametrize('primary_type', [type(None), RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize('interrupt_type', [KeyboardInterrupt, SystemExit])
def test_cleanup_interrupt_preserves_objects_and_attempts_siblings(primary_type, interrupt_type):
    """Mixed cleanup never coerces or hides interruptions, body, or ordinary faults."""
    primary = None if primary_type is type(None) else primary_type('body')
    ordinary = OSError('close')
    interrupt = interrupt_type('cleanup')
    seen = []
    with pytest.raises(BaseException) as caught:
        fixture.cleanup_actions([lambda: fail(ordinary), lambda: fail(interrupt),
                                 lambda: seen.append('later')], primary)
    assert seen == ['later']
    expected = [ordinary, interrupt] if primary is None else [primary, ordinary, interrupt]
    assert type(caught.value) is BaseExceptionGroup
    assert all(a is b for a, b in zip(leaves(caught.value), expected, strict=True))


@pytest.mark.parametrize('error_type', [RuntimeError, KeyboardInterrupt, SystemExit])
def test_dead_worker_fault_cannot_pass(error_type):
    """A dead worker still exposes its exact retained error without warnings."""
    error = error_type('worker')
    worker = fixture.OwnedWorker(lambda: fail(error), name='fault-control')
    try:
        worker.thread.join(5)
        assert not worker.is_alive()
        assert worker.errors[0] is error
        with pytest.raises(BaseExceptionGroup) as caught:
            worker.close()
        assert caught.value.exceptions[0] is error
    finally:
        worker.thread.join(5)


def test_worker_success_settles():
    """A normal real worker joins with no hidden fault."""
    worker = fixture.OwnedWorker(lambda: None, name='worker-positive')
    worker.close()
    assert not worker.is_alive()
    assert worker.errors == []


def test_owned_reset_listener_contract():
    """Real reset owns the port through accept and closes the actual peer."""
    owner = fixture.OwnedReset()
    try:
        with socket.create_connection(('127.0.0.1', owner.listener.getsockname()[1]), timeout=2) as peer:
            assert owner.accepted.wait(2)
            with pytest.raises((ConnectionResetError, BrokenPipeError)):
                peer.recv(1)
    finally:
        owner.close()
    assert not owner.thread.is_alive()
    assert owner.listener.fileno() == -1
    assert owner.connections and all(c.fileno() == -1 for c in owner.connections)
