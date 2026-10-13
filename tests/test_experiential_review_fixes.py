"""Offline reviewer regressions for PR1350; no provider calls."""

from pathlib import Path
from decimal import Decimal
import json
import inspect
import io
import http.client

import pytest

from contextual_orchestrator import experiential_billing_probe as probe
from contextual_orchestrator.provider_errors import MAX_PROVIDER_ERROR_BODY_BYTES
from test_experiential_billing_probe import FixtureTransport, _run, credential_backend

NATIVE_BUDGET = MAX_PROVIDER_ERROR_BODY_BYTES + 1


@pytest.mark.parametrize('cost', ['1e-400', '1.0000000000000000000000000001', '1e400', '0'])
def test_exact_money_survives_final_json(tmp_path, cost):
    """Provider USD decimals must not underflow, round, or overflow via float."""
    transport = FixtureTransport(tmp_path / 'evidence.json')
    transport.inline = transport.generation = transport.charge = cost
    result = _run(transport.path, transport)
    assert result['outcome'] == ('zero_charge_observed' if Decimal(cost) == 0 else 'charge_observed')
    assert result['cost_comparison'] == 'match'
    for key in ('response_cost_usd', 'generation_total_cost_usd', 'ledger_charge_usd'):
        assert isinstance(result[key], str)
        assert Decimal(result[key]) == Decimal(cost)
    assert json.loads(transport.path.read_text()) == result
    assert json.loads(json.dumps(result)) == result
    assert transport.posts == 1
    with pytest.raises(ValueError, match='already exists'):
        _run(transport.path, transport)
    assert transport.posts == 1


def test_close_decimals_are_not_false_agreement(tmp_path):
    """Numerically distinct receipts remain a mismatch beyond float precision."""
    transport = FixtureTransport(tmp_path / 'evidence.json')
    transport.inline = transport.generation = '1.0000000000000000000000000001'
    transport.charge = '1.0000000000000000000000000002'
    assert _run(transport.path, transport)['cost_comparison'] == 'mismatch'
    assert transport.posts == 1

def test_billing_cannot_hold_catalog_concurrency():
    """A stalled null-timeout probe must not own the hourly sync lock."""
    workflow = Path('.github/workflows/provider-catalog-sync.yml').read_text()
    header, jobs = workflow.split('\njobs:\n', 1)
    assert '\nconcurrency:' not in header
    billing, sync = jobs.split('\n  sync:\n', 1)
    assert '\n    concurrency:\n      group: provider-catalog-sync\n      cancel-in-progress: false\n' in sync
    assert '\n    concurrency:\n      group: experiential-billing\n      cancel-in-progress: false\n' in billing
    assert 'needs:' not in sync and 'needs:' not in billing


class WireSocket:
    """Feed native HTTPResponse in-memory bytes, without a real socket."""

    def __init__(self, wire):
        self.stream = io.BytesIO(wire)

    def makefile(self, *_):
        return self.stream


def _native_response(monkeypatch, body, declared=None):
    headers = b'' if declared is None else f'Content-Length: {declared}\r\n'.encode()
    response = http.client.HTTPResponse(WireSocket(
        b'HTTP/1.1 200 OK\r\nX-Request-Id: req-1\r\n' + headers + b'\r\n' + body))
    response.begin()
    reads = []
    native_read = response.read

    def read(size=None):
        reads.append(size)
        assert type(size) is int and size > 0, 'unbounded response acquisition'
        return native_read(size)

    response.read = read
    monkeypatch.setattr(probe.ModelClient, '_validate_provider', lambda *_: 'pinned')
    opens = []

    def open_response(self, request, destination, *, timeout):
        opens.append(request.get_method())
        assert destination == 'pinned' and timeout is None
        assert self.max_retries == 0
        return response

    monkeypatch.setattr(probe.ModelClient, '_open_provider', open_response)
    return response, reads, opens


def _budget_request(method, budget):
    # Legacy replay must reach the actual unsafe read, not fail on a new keyword.
    kwargs = {'response_max_bytes': budget} if 'response_max_bytes' in inspect.signature(probe._request).parameters else {}
    return probe._request(method, '/v1/chat/completions' if method == 'POST' else '/v1/models', **kwargs)


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_native_transport_enforces_explicit_budget(monkeypatch, method):
    """Oversize bodies are unsupported evidence, and never replayed."""
    response, reads, opens = _native_response(monkeypatch, b'{"padding":"' + b'x' * (NATIVE_BUDGET + 1) + b'"}')
    try:
        with pytest.raises(ValueError, match='response.*budget'):
            _budget_request(method, NATIVE_BUDGET)
        assert reads == [NATIVE_BUDGET + 1]
        assert opens == [method]
        assert response.isclosed()
    finally:
        response.close()


def test_native_transport_decimal_numbers_do_not_underflow(monkeypatch):
    body = b'{"usage":{"cost":1e-400},"other":1.0000000000000000000000000001}'
    response, reads, opens = _native_response(monkeypatch, body, len(body))
    try:
        status, _, parsed = _budget_request('POST', NATIVE_BUDGET)
        assert status == 200
        assert parsed['usage']['cost'] == Decimal('1e-400')
        assert parsed['other'] == Decimal('1.0000000000000000000000000001')
        assert reads == [NATIVE_BUDGET + 1]
        assert opens == ['POST'] and response.isclosed()
    finally:
        response.close()


@pytest.mark.parametrize('budget', [None, True, 0, -1, '64'])
def test_missing_or_invalid_budget_blocks_real_transport(tmp_path, monkeypatch, budget):
    def forbidden(*_, **__):
        pytest.fail('resource admission must precede any provider operation')
    monkeypatch.setattr(probe.ModelClient, '_validate_provider', forbidden)
    with pytest.raises(ValueError, match='byte budget'):
        probe.run_probe(tmp_path / 'evidence.json', source_sha='a' * 40, run_id='123',
                        run_attempt='1', response_max_bytes=budget)
    assert not (tmp_path / 'evidence.json').exists()


def test_workflow_requires_operator_resource_input():
    workflow = Path('.github/workflows/provider-catalog-sync.yml').read_text()
    assert 'experiential_response_max_bytes:' in workflow
    assert 'RESPONSE_MAX_BYTES: ${{ inputs.experiential_response_max_bytes }}' in workflow
    assert "response_max_bytes=int(os.environ.pop('RESPONSE_MAX_BYTES'))" in workflow


@pytest.mark.parametrize('stage', ['preflight', 'POST', 'ledger'])
def test_resource_refusal_remains_unknown_without_replay(tmp_path, stage):
    transport = FixtureTransport(tmp_path / 'evidence.json')
    def request(method, route, payload=None):
        status, headers, body = transport(method, route, payload)
        if ((stage == 'preflight' and route == '/v1/models') or
                (stage == 'POST' and method == 'POST') or
                (stage == 'ledger' and route.startswith('/api/v1/usage'))):
            raise probe.ResponseBudgetExceeded('response exceeds operator byte budget')
        if stage == 'POST' and route.startswith('/api/v1/usage'):
            body = {'data': [], 'next_cursor': None}
        return status, headers, body
    if stage == 'preflight':
        with pytest.raises(ValueError, match='discovery'):
            _run(transport.path, request)
        result = json.loads(transport.path.read_text())
        assert transport.posts == 0
    else:
        result = _run(transport.path, request)
        assert transport.posts == 1
    assert result['response_resource_admission'] == 'exceeded'
    assert result['ledger_charge_usd'] is None
    assert result['cost_comparison'] == 'unknown'
    assert result['outcome'] in {'preflight_failed', 'charge_unknown', 'ambiguous'}
    with pytest.raises(ValueError, match='already exists'):
        _run(transport.path, request)
    assert transport.posts == (0 if stage == 'preflight' else 1)


@pytest.mark.parametrize('declared', [NATIVE_BUDGET + 1, NATIVE_BUDGET * 2])
def test_declared_oversize_is_rejected_before_body_read(monkeypatch, declared):
    response, reads, opens = _native_response(monkeypatch, b'{"data":[]}', declared)
    try:
        with pytest.raises(probe.ResponseBudgetExceeded):
            probe._request('GET', '/v1/models', response_max_bytes=NATIVE_BUDGET)
        assert reads == [] and opens == ['GET'] and response.isclosed()
    finally:
        response.close()


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_truncated_valid_json_cannot_be_receipt(monkeypatch, method):
    body = b'{"usage":{"cost":0}}'
    response, reads, opens = _native_response(monkeypatch, body, len(body) + 1)
    try:
        with pytest.raises(ValueError, match='incomplete'):
            _budget_request(method, NATIVE_BUDGET)
        assert opens == [method] and response.isclosed()
    finally:
        response.close()


@pytest.mark.parametrize('budget', [NATIVE_BUDGET, NATIVE_BUDGET * 2])
def test_budget_is_admission_not_cost_truth(monkeypatch, budget):
    body = b'{"cost":0}'
    response, _, opens = _native_response(monkeypatch, body, len(body))
    try:
        assert probe._request('POST', '/v1/chat/completions', response_max_bytes=budget)[2] == {'cost': 0}
        assert opens == ['POST'] and response.isclosed()
    finally:
        response.close()


def test_no_unbounded_legacy_adapter_fallback(monkeypatch):
    response, _, opens = _native_response(monkeypatch, b'{"cost":0}')
    consumed = []
    def legacy_read():
        consumed.append(True)
        return b'{"cost":0}'
    response.read = legacy_read
    try:
        with pytest.raises(TypeError):
            probe._request('POST', '/v1/chat/completions', response_max_bytes=NATIVE_BUDGET)
        assert consumed == [] and opens == ['POST'] and response.isclosed()
    finally:
        response.close()
