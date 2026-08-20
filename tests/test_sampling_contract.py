"""Unit tests for provider sampling-parameter omission and passthrough."""

from __future__ import annotations

import json

from contextual_orchestrator.sampling_contract import install_sampling_contract


class _FakeModelClient:
    def __init__(
        self,
        timeout=90,
        max_output_tokens=2048,
        max_retries=2,
        local_max_retries=0,
        retry_backoff=0.5,
        retry_backoff_cap=8.0,
        temperature=0.2,
        local_concurrency=1,
        ca_bundle=None,
        verify_tls=True,
        allowed_provider_hosts=None,
    ) -> None:
        self.default_temperature = 0.2
        self.temperature = temperature
        self.batch_payload = b""
        self.configuration = {
            "timeout": timeout,
            "max_output_tokens": max_output_tokens,
            "max_retries": max_retries,
            "local_max_retries": local_max_retries,
            "retry_backoff": retry_backoff,
            "retry_backoff_cap": retry_backoff_cap,
            "local_concurrency": local_concurrency,
            "ca_bundle": ca_bundle,
            "verify_tls": verify_tls,
            "allowed_provider_hosts": allowed_provider_hosts,
        }

    def _send_with_retry(self, _agent, payload, _destination=None, *, timeout=None):
        return {"payload": payload, "timeout": timeout}

    def _stream_send(self, _agent, payload, _destination=None):
        return iter([payload])

    def _batch_upload(self, _agent, payload, _destination=None):
        self.batch_payload = payload
        return "file_001"


def test_installation_omits_unrequested_temperature_across_transports() -> None:
    install_sampling_contract(_FakeModelClient)
    install_sampling_contract(_FakeModelClient)
    client = _FakeModelClient(timeout=17, allowed_provider_hosts=["gateway.example.com"])

    assert client.default_temperature is None
    assert client.temperature is None
    assert client.configuration["timeout"] == 17
    assert client.configuration["allowed_provider_hosts"] == ["gateway.example.com"]
    assert client._send_with_retry(
        None,
        {"model": "provider/model", "temperature": None},
        timeout=3.0,
    ) == {"payload": {"model": "provider/model"}, "timeout": 3.0}
    assert list(
        client._stream_send(
            None,
            {"model": "provider/model", "temperature": None},
        )
    ) == [{"model": "provider/model"}]

    lines = [
        {
            "custom_id": "omitted",
            "body": {"model": "provider/model", "temperature": None},
        },
        {
            "custom_id": "explicit",
            "body": {"model": "provider/model", "temperature": 0.2},
        },
        {"custom_id": "opaque", "body": "unchanged"},
    ]
    payload = "\n".join(json.dumps(line) for line in lines).encode("utf-8")
    assert client._batch_upload(None, payload) == "file_001"
    uploaded = [json.loads(line) for line in client.batch_payload.decode("utf-8").splitlines()]
    assert "temperature" not in uploaded[0]["body"]
    assert uploaded[1]["body"]["temperature"] == 0.2
    assert uploaded[2]["body"] == "unchanged"


def test_installation_preserves_explicit_client_temperature() -> None:
    install_sampling_contract(_FakeModelClient)
    client = _FakeModelClient(temperature=0.2)

    assert client.default_temperature == 0.2
    assert client.temperature == 0.2
    assert client._send_with_retry(
        None,
        {"model": "provider/model", "temperature": 0.2},
    )["payload"]["temperature"] == 0.2


def test_explicit_null_client_temperature_remains_omit_equivalent() -> None:
    install_sampling_contract(_FakeModelClient)
    client = _FakeModelClient(temperature=None)

    assert client.default_temperature is None
    assert client.temperature is None
