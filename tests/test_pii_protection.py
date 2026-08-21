from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.credentials import InMemoryCredentialBackend, set_backend  # noqa: E402
from contextual_orchestrator.pii_protection import (  # noqa: E402
    DEFAULT_PII_KEY_NAME,
    ENCRYPTED_FIELDS_KEY,
    PiiFieldEncryptor,
    PiiProtectionError,
    is_encrypted_detail,
    load_pii_encryptor,
)
from contextual_orchestrator.server import RequestError, SecurityConfig  # noqa: E402


KEY_BYTES = b"0123456789abcdef0123456789abcdef"
KEY_BASE64 = "base64:" + base64.urlsafe_b64encode(KEY_BYTES).decode("ascii")


@pytest.fixture(autouse=True)
def memory_credentials() -> InMemoryCredentialBackend:
    backend = InMemoryCredentialBackend()
    backend.set(DEFAULT_PII_KEY_NAME, KEY_BASE64)
    set_backend(backend)
    yield backend
    set_backend(None)


def test_field_encryption_round_trip_and_key_formats() -> None:
    encryptor = PiiFieldEncryptor.from_secret(DEFAULT_PII_KEY_NAME, KEY_BASE64)
    detail = {"email": "alice@example.com", "count": 2, "nested": {"ok": True}}
    protected = encryptor.encrypt_fields(detail, ["email", "email"])

    assert protected["count"] == 2
    assert protected[ENCRYPTED_FIELDS_KEY]["algorithm"] == "AES-256-GCM"
    assert "alice@example.com" not in json.dumps(protected)
    assert encryptor.decrypt_fields(protected) == detail
    assert PiiFieldEncryptor.from_secret("k", "hex:" + KEY_BYTES.hex()).key == KEY_BYTES
    assert PiiFieldEncryptor.from_secret("k", KEY_BYTES.decode("ascii")).key == KEY_BYTES
    assert is_encrypted_detail(protected)
    assert not is_encrypted_detail(detail)


def test_empty_field_set_and_plain_decrypt_are_copy_operations() -> None:
    encryptor = PiiFieldEncryptor.from_secret("k", KEY_BYTES.decode("ascii"))
    detail = {"email": "alice@example.com"}
    assert encryptor.encrypt_fields(detail, ()) == detail
    assert encryptor.encrypt_fields(detail, ()) is not detail
    assert encryptor.decrypt_fields(detail) == detail
    assert encryptor.decrypt_fields(detail) is not detail


@pytest.mark.parametrize(
    "secret",
    ["", "hex:bad", "base64:not@@base64", "not-a-32-byte-key"],
)
def test_invalid_keys_fail_closed(secret: str) -> None:
    with pytest.raises(PiiProtectionError):
        PiiFieldEncryptor.from_secret("k", secret)
    with pytest.raises(PiiProtectionError):
        PiiFieldEncryptor.from_secret("", KEY_BASE64)


def test_kv_key_resolution_and_marked_event_storage() -> None:
    assert load_pii_encryptor().key == KEY_BYTES
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock")])
    orchestrator.record_analytics_event(
        "pii_event",
        {"email": "alice@example.com", "status": "ok"},
        pii_fields=("email",),
    )
    stored = orchestrator._analytics_events[-1]
    assert "alice@example.com" not in json.dumps(stored)
    assert stored["event_detail"]["status"] == "ok"
    assert "email" in stored["event_detail"][ENCRYPTED_FIELDS_KEY]["fields"]


def test_missing_kv_key_and_invalid_event_declarations_fail_closed(memory_credentials: InMemoryCredentialBackend) -> None:
    memory_credentials._store.pop(DEFAULT_PII_KEY_NAME)
    with pytest.raises(PiiProtectionError):
        load_pii_encryptor()
    memory_credentials.set(DEFAULT_PII_KEY_NAME, "bad")
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock")])
    with pytest.raises(PiiProtectionError):
        orchestrator.record_analytics_event("pii_event", {"email": "alice@example.com"}, pii_fields=("email",))

    memory_credentials.set(DEFAULT_PII_KEY_NAME, KEY_BASE64)
    encryptor = load_pii_encryptor()
    with pytest.raises(PiiProtectionError):
        encryptor.encrypt_fields({"email": "x", ENCRYPTED_FIELDS_KEY: {}}, ("email",))
    with pytest.raises(PiiProtectionError):
        encryptor.encrypt_fields({"email": "x"}, ("missing",))
    with pytest.raises(PiiProtectionError):
        encryptor.encrypt_fields({"email": float("nan")}, ("email",))
    with pytest.raises(PiiProtectionError):
        encryptor.encrypt_fields({"email": "x"}, ("",))
    with pytest.raises(PiiProtectionError):
        encryptor.encrypt_fields([], ("email",))  # type: ignore[arg-type]
    with pytest.raises(PiiProtectionError):
        encryptor.decrypt_fields([])  # type: ignore[arg-type]


def test_tampered_and_malformed_envelopes_fail_closed() -> None:
    encryptor = load_pii_encryptor()
    protected = encryptor.encrypt_fields({"email": "alice@example.com"}, ("email",))
    tampered = json.loads(json.dumps(protected))
    tampered[ENCRYPTED_FIELDS_KEY]["fields"]["email"]["ciphertext"] = "AA"
    with pytest.raises(PiiProtectionError):
        encryptor.decrypt_fields(tampered)
    for metadata in (
        {"version": 2},
        {"version": 1, "algorithm": "AES-256-GCM", "key_name": "wrong", "fields": {}},
        {"version": 1, "algorithm": "AES-256-GCM", "key_name": DEFAULT_PII_KEY_NAME, "fields": []},
    ):
        with pytest.raises(PiiProtectionError):
            encryptor.decrypt_fields({ENCRYPTED_FIELDS_KEY: metadata})
    with pytest.raises(PiiProtectionError):
        encryptor.decrypt_fields({ENCRYPTED_FIELDS_KEY: {"version": 1, "algorithm": "AES-256-GCM", "key_name": DEFAULT_PII_KEY_NAME, "fields": {"email": {"nonce": 1, "ciphertext": "AA"}}}})
    with pytest.raises(PiiProtectionError):
        encryptor.decrypt_fields({ENCRYPTED_FIELDS_KEY: {"version": 1, "algorithm": "AES-256-GCM", "key_name": DEFAULT_PII_KEY_NAME, "fields": {"email": {"nonce": "a", "ciphertext": "AA"}}}})
    with pytest.raises(PiiProtectionError):
        encryptor.decrypt_fields({ENCRYPTED_FIELDS_KEY: {"version": 1, "algorithm": "AES-256-GCM", "key_name": DEFAULT_PII_KEY_NAME, "fields": {1: {}}}})  # type: ignore[dict-item]


def test_audit_replay_is_the_only_plaintext_read_path(memory_credentials: InMemoryCredentialBackend) -> None:
    memory_credentials.set("old_pii_key", KEY_BASE64)
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock")], pii_key_name="old_pii_key")
    orchestrator._append_audit_event(
        "message_received", {"email": "alice@example.com", "source": "naruon"}, pii_fields=("email",)
    )
    encrypted = orchestrator.list_recent_audit_events()
    assert "alice@example.com" not in json.dumps(encrypted)
    orchestrator._pii_key_name = DEFAULT_PII_KEY_NAME
    restored = orchestrator.list_recent_audit_events(role="admin", purpose="audit_replay")
    assert restored[0]["event_detail"]["email"] == "alice@example.com"


def test_purpose_policy_is_role_scoped() -> None:
    security = SecurityConfig(auth_token="secret")
    assert security.authorize({"authorization": "Bearer secret"}, "inference", "127.0.0.1") == "message_delivery"
    assert security.authorize({"authorization": "Bearer secret"}, "admin", "127.0.0.1", "audit_replay") == "audit_replay"
    with pytest.raises(RequestError) as error:
        security.authorize({"authorization": "Bearer secret"}, "inference", "127.0.0.1", "audit_replay")
    assert error.value.code == "purpose_not_allowed"
    with pytest.raises(RequestError) as error:
        security.resolve_purpose("unknown")
    assert error.value.code == "invalid_scope"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
