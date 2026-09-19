"""Boundary coverage for PII key decoding and AAD context guards."""

from __future__ import annotations

import base64

import pytest

from contextual_orchestrator.pii_protection import (
    ENCRYPTED_FIELDS_VERSION,
    LEGACY_ENCRYPTED_FIELDS_VERSION,
    PiiProtectionError,
    _decode_secret,
    _field_aad,
)


def test_passphrase_salt_must_decode_to_at_least_16_bytes() -> None:
    """A truncated salt cannot produce a brute-force-resistant derived key."""
    short_salt = base64.urlsafe_b64encode(b"tiny-salt").decode("ascii")
    with pytest.raises(PiiProtectionError, match="at least 16 bytes"):
        _decode_secret(f"passphrase:{short_salt}:human-secret")


def test_passphrase_with_empty_passphrase_part_is_rejected() -> None:
    """``passphrase:<salt>:`` without a passphrase is a configuration error."""
    salt = base64.urlsafe_b64encode(b"salt-with-16-bytes!").decode("ascii")
    with pytest.raises(PiiProtectionError, match="passphrase is empty"):
        _decode_secret(f"passphrase:{salt}:")


def test_key_derivation_failure_surfaces_as_configuration_error(monkeypatch) -> None:
    """A broken crypto environment must not leak raw hashlib errors."""
    import hashlib

    def exploding_scrypt(*_args, **_kwargs):
        raise ValueError("openssl backend unavailable")

    monkeypatch.setattr(hashlib, "scrypt", exploding_scrypt)
    salt = base64.urlsafe_b64encode(b"salt-with-16-bytes!").decode("ascii")
    with pytest.raises(PiiProtectionError, match="could not be derived"):
        _decode_secret(f"passphrase:{salt}:human-secret")


def test_decoded_keys_must_be_exactly_32_bytes() -> None:
    """Short or long generated keys are rejected before AES-GCM use."""
    short = base64.urlsafe_b64encode(b"too-short").decode("ascii")
    with pytest.raises(PiiProtectionError, match="32 bytes"):
        _decode_secret(f"base64:{short}")
    long_bytes = b"x" * 33
    with pytest.raises(PiiProtectionError, match="32 bytes"):
        _decode_secret("hex:" + long_bytes.hex())


def test_field_aad_rejects_invalid_contexts_and_versions() -> None:
    """AAD construction is total only for known versions and non-empty labels."""
    with pytest.raises(PiiProtectionError, match="context is invalid"):
        _field_aad("", "email", ENCRYPTED_FIELDS_VERSION)
    with pytest.raises(PiiProtectionError, match="context is invalid"):
        _field_aad("key", "", ENCRYPTED_FIELDS_VERSION)
    with pytest.raises(PiiProtectionError, match="context is invalid"):
        _field_aad(None, "email", ENCRYPTED_FIELDS_VERSION)  # type: ignore[arg-type]
    with pytest.raises(PiiProtectionError, match="unsupported encrypted field version"):
        _field_aad("key_name", "email", 99)


def test_legacy_aad_rejects_colon_containing_context() -> None:
    """Legacy v1 AAD strings are colon-delimited and must stay unambiguous."""
    with pytest.raises(PiiProtectionError, match="legacy encrypted PII context"):
        _field_aad("legacy:key", "email", LEGACY_ENCRYPTED_FIELDS_VERSION)
    with pytest.raises(PiiProtectionError, match="legacy encrypted PII context"):
        _field_aad("legacy-key", "user:email", LEGACY_ENCRYPTED_FIELDS_VERSION)

    v2 = _field_aad("legacy/key", "email", ENCRYPTED_FIELDS_VERSION)
    assert b"legacy/key" in v2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
