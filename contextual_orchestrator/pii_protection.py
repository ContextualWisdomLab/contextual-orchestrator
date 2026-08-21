"""Purpose-limited access and field-level protection for stored event data."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .credentials import get_credential


ENCRYPTED_FIELDS_KEY = "__encrypted_fields__"
ENCRYPTED_FIELDS_VERSION = 1
ENCRYPTED_FIELDS_ALGORITHM = "AES-256-GCM"
DEFAULT_PII_KEY_NAME = "CONTEXTUAL_ORCHESTRATOR_PII_ENCRYPTION_KEY"
PASSPHRASE_PREFIX = "passphrase:"
PURPOSES_BY_SCOPE = {
    "inference": frozenset({"message_delivery"}),
    "admin": frozenset({"operator_read", "audit_replay"}),
}
DEFAULT_PURPOSE_BY_SCOPE = {
    "inference": "message_delivery",
    "admin": "operator_read",
}


class PiiProtectionError(ValueError):
    """Raised when marked PII cannot be safely protected or restored."""


def _decode_secret(secret: str, *, key_name: str = "") -> bytes:
    """Decode an explicit key encoding or derive a key from a marked passphrase.

    Raw unprefixed 32-byte strings are rejected because a human passphrase can
    otherwise be mistaken for a uniformly random AES key. Operators may use
    ``base64:`` or ``hex:`` for generated key bytes, or ``passphrase:`` for a
    password-derived key.
    """
    if not isinstance(secret, str) or not secret:
        raise PiiProtectionError("PII encryption key is empty")
    if secret.startswith(PASSPHRASE_PREFIX):
        passphrase = secret[len(PASSPHRASE_PREFIX) :]
        if not passphrase:
            raise PiiProtectionError("PII encryption passphrase is empty")
        try:
            return hashlib.scrypt(
                passphrase.encode("utf-8"),
                salt=f"contextual-orchestrator:pii-key:{key_name}".encode("utf-8"),
                n=2**14,
                r=8,
                p=1,
                dklen=32,
            )
        except (TypeError, ValueError):
            raise PiiProtectionError("PII encryption passphrase could not be derived") from None
    if secret.startswith("hex:"):
        try:
            decoded = bytes.fromhex(secret[4:])
        except ValueError as exc:
            raise PiiProtectionError("PII encryption key is not valid hex") from exc
    elif secret.startswith("base64:"):
        try:
            decoded = base64.urlsafe_b64decode(secret[7:] + "=" * (-len(secret[7:]) % 4))
        except (binascii.Error, ValueError) as exc:
            raise PiiProtectionError("PII encryption key is not valid base64") from exc
    else:
        decoded = secret.encode("utf-8")
        if len(decoded) != 32:
            try:
                decoded = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
            except (binascii.Error, ValueError):
                decoded = b""
        else:
            raise PiiProtectionError(
                "PII encryption key must use base64:, hex:, or passphrase:"
            )
    if len(decoded) != 32:
        raise PiiProtectionError("PII encryption key must decode to 32 bytes")
    return decoded


def _b64encode(value: bytes) -> str:
    """Encode binary ciphertext metadata as URL-safe base64."""
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: Any) -> bytes:
    """Decode strict URL-safe base64 metadata."""
    if not isinstance(value, str):
        raise PiiProtectionError("encrypted field metadata is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise PiiProtectionError("encrypted field metadata is invalid") from exc


def _field_names(fields: Iterable[str]) -> tuple[str, ...]:
    """Validate and de-duplicate declared top-level field names."""
    names: list[str] = []
    for field in fields:
        if not isinstance(field, str) or not field or field == ENCRYPTED_FIELDS_KEY:
            raise PiiProtectionError("PII field names must be non-empty strings")
        if field not in names:
            names.append(field)
    return tuple(names)


@dataclass(frozen=True)
class PiiFieldEncryptor:
    """Encrypt and decrypt explicitly declared event fields with AES-GCM."""

    key_name: str
    key: bytes = field(repr=False)

    @classmethod
    def from_secret(cls, key_name: str, secret: str) -> PiiFieldEncryptor:
        """Build an encryptor from a KV secret without retaining its text form."""
        if not key_name:
            raise PiiProtectionError("PII encryption key name is empty")
        return cls(key_name, _decode_secret(secret, key_name=key_name))

    def encrypt_fields(self, detail: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
        """Return a copy with declared top-level fields replaced by AES-GCM envelopes."""
        if not isinstance(detail, dict):
            raise PiiProtectionError("event detail must be an object")
        names = _field_names(fields)
        if not names:
            return dict(detail)
        if ENCRYPTED_FIELDS_KEY in detail:
            raise PiiProtectionError("reserved encrypted field metadata key")
        missing = [field for field in names if field not in detail]
        if missing:
            raise PiiProtectionError("declared PII field is missing")
        result = dict(detail)
        encrypted: dict[str, dict[str, str]] = {}
        cipher = AESGCM(self.key)
        for field in names:
            try:
                plaintext = json.dumps(
                    detail[field], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise PiiProtectionError("PII field is not JSON serializable") from exc
            nonce = os.urandom(12)
            aad = f"contextual-orchestrator:event-detail:{self.key_name}:{field}".encode()
            encrypted[field] = {
                "nonce": _b64encode(nonce),
                "ciphertext": _b64encode(cipher.encrypt(nonce, plaintext, aad)),
            }
            del result[field]
        result[ENCRYPTED_FIELDS_KEY] = {
            "version": ENCRYPTED_FIELDS_VERSION,
            "algorithm": ENCRYPTED_FIELDS_ALGORITHM,
            "key_name": self.key_name,
            "fields": encrypted,
        }
        return result

    def decrypt_fields(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Restore an encrypted event detail or return an unchanged plain detail."""
        if not isinstance(detail, dict):
            raise PiiProtectionError("event detail must be an object")
        metadata = detail.get(ENCRYPTED_FIELDS_KEY)
        if metadata is None:
            return dict(detail)
        if not isinstance(metadata, dict) or metadata.get("version") != ENCRYPTED_FIELDS_VERSION:
            raise PiiProtectionError("unsupported encrypted field version")
        if metadata.get("algorithm") != ENCRYPTED_FIELDS_ALGORITHM or metadata.get("key_name") != self.key_name:
            raise PiiProtectionError("encrypted field metadata does not match the configured key")
        encrypted = metadata.get("fields")
        if not isinstance(encrypted, dict):
            raise PiiProtectionError("encrypted field metadata is invalid")
        result = {key: value for key, value in detail.items() if key != ENCRYPTED_FIELDS_KEY}
        cipher = AESGCM(self.key)
        for field, envelope in encrypted.items():
            if not isinstance(field, str) or not isinstance(envelope, dict):
                raise PiiProtectionError("encrypted field metadata is invalid")
            nonce = _b64decode(envelope.get("nonce"))
            ciphertext = _b64decode(envelope.get("ciphertext"))
            aad = f"contextual-orchestrator:event-detail:{self.key_name}:{field}".encode()
            try:
                value = cipher.decrypt(nonce, ciphertext, aad)
                result[field] = json.loads(value.decode("utf-8"))
            except (InvalidTag, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PiiProtectionError("encrypted PII field failed authentication") from exc
        return result


def load_pii_encryptor(key_name: str = DEFAULT_PII_KEY_NAME) -> PiiFieldEncryptor:
    """Resolve the PII key from the KV credential registry and fail closed."""
    secret = get_credential(key_name)
    if not secret:
        raise PiiProtectionError(f"KV credential {key_name!r} is not configured")
    return PiiFieldEncryptor.from_secret(key_name, secret)


def is_encrypted_detail(detail: Any) -> bool:
    """Return whether an event detail carries the protected-field envelope."""
    return isinstance(detail, dict) and ENCRYPTED_FIELDS_KEY in detail
