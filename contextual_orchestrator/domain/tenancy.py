"""Tenant identity and LiteLLM-style virtual keys with spend budgets.

A *tenant* is the trusted owner that usage and budgets are attributed to. A
*virtual key* is a gateway-issued secret that maps to exactly one tenant and
may carry its own budget (LiteLLM ``max_budget`` / ``budget_duration`` /
``soft_budget``). A tenant may carry a shared budget that every one of its
keys draws on. Only a SHA-256 digest of a key is ever stored; the plaintext
secret is shown once at issuance.

Tenant identity never comes from client-declared request attribution
(``attribution.account`` and friends are descriptive labels). It comes from a
presented virtual key, or from the trusted embedding application, or falls
back to :data:`DEFAULT_TENANT_ID` for single-tenant deployments.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Any

from .budget import BudgetScope, SpendLimit
from .money import Money

#: Tenant used when neither a virtual key nor a trusted caller supplies one.
DEFAULT_TENANT_ID = "default"

#: Minimum plaintext length so a stored unsalted digest cannot be brute forced.
MIN_VIRTUAL_KEY_LENGTH = 32

_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_KEY_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_tenant_id(value: object) -> str:
    """Return a validated tenant id (1-128 chars of ``[A-Za-z0-9._:/@-]``)."""
    if not isinstance(value, str) or not _TENANT_ID.match(value):
        raise ValueError(
            "tenant_id must be 1-128 characters of letters, digits, '.', '_', ':', '/', '@' or '-'"
        )
    return value


def hash_virtual_key(secret: str) -> str:
    """Return the storable digest (``sha256:<hex>``) of a virtual key secret.

    Keys are high-entropy random secrets (at least
    :data:`MIN_VIRTUAL_KEY_LENGTH` characters), so an unsalted SHA-256 digest
    is a lookup handle, not a password hash.
    """
    if not isinstance(secret, str) or len(secret) < MIN_VIRTUAL_KEY_LENGTH:
        raise ValueError(
            f"virtual key must be a string of at least {MIN_VIRTUAL_KEY_LENGTH} characters"
        )
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def key_hash_matches(secret: str, key_hash: str) -> bool:
    """Constant-time comparison of a presented secret against a stored digest."""
    try:
        candidate = hash_virtual_key(secret)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, key_hash)


def key_id_for_hash(key_hash: str) -> str:
    """Derive the public, non-secret key id (``vk_`` + 16 hex chars of the digest)."""
    if not isinstance(key_hash, str) or not _KEY_HASH.match(key_hash):
        raise ValueError("key_hash must look like sha256:<64 hex chars>")
    return "vk_" + key_hash.removeprefix("sha256:")[:16]


def _optional_money(value: Money | None, name: str) -> None:
    if value is not None and not isinstance(value, Money):
        raise ValueError(f"{name} must be Money or None")


@dataclass(frozen=True)
class VirtualKey:
    """A stored virtual key definition (digest only, never the secret)."""

    key_hash: str
    tenant_id: str
    max_budget: Money | None = None
    budget_duration_seconds: int | None = None
    soft_budget: Money | None = None
    created_at: int = 0
    key_alias: str | None = None
    disabled: bool = False

    def __post_init__(self) -> None:
        """Validate identity, budgets, and the digest shape."""
        key_id_for_hash(self.key_hash)
        validate_tenant_id(self.tenant_id)
        _optional_money(self.max_budget, "max_budget")
        _optional_money(self.soft_budget, "soft_budget")
        if self.key_alias is not None and (
            not isinstance(self.key_alias, str) or len(self.key_alias) > 128
        ):
            raise ValueError("key_alias must be a string of at most 128 characters")
        if not isinstance(self.disabled, bool):
            raise ValueError("disabled must be a boolean")
        if type(self.created_at) is not int or self.created_at < 0:
            raise ValueError("created_at must be a non-negative integer epoch")

    @property
    def key_id(self) -> str:
        """Public identifier safe for logs, usage rows, and error details."""
        return key_id_for_hash(self.key_hash)

    def spend_limit(self) -> SpendLimit:
        """This key's budget as a :class:`SpendLimit` (no cap when ``max_budget`` is unset)."""
        return SpendLimit(
            scope=BudgetScope.VIRTUAL_KEY,
            scope_id=self.key_id,
            max_cost=self.max_budget,
            soft_max_cost=self.soft_budget,
            budget_duration_seconds=self.budget_duration_seconds,
            anchor_epoch=self.created_at,
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe representation for durable storage (no plaintext secret)."""
        return {
            "key_hash": self.key_hash,
            "key_id": self.key_id,
            "tenant_id": self.tenant_id,
            "max_budget": _money_dict(self.max_budget),
            "budget_duration_seconds": self.budget_duration_seconds,
            "soft_budget": _money_dict(self.soft_budget),
            "created_at": self.created_at,
            "key_alias": self.key_alias,
            "disabled": self.disabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VirtualKey":
        """Rebuild a key definition from :meth:`as_dict` output."""
        return cls(
            key_hash=data["key_hash"],
            tenant_id=data["tenant_id"],
            max_budget=_money_from_dict(data.get("max_budget")),
            budget_duration_seconds=data.get("budget_duration_seconds"),
            soft_budget=_money_from_dict(data.get("soft_budget")),
            created_at=data.get("created_at", 0),
            key_alias=data.get("key_alias"),
            disabled=bool(data.get("disabled", False)),
        )


@dataclass(frozen=True)
class TenantBudget:
    """A shared budget for every call attributed to one tenant."""

    tenant_id: str
    max_budget: Money | None = None
    budget_duration_seconds: int | None = None
    soft_budget: Money | None = None
    created_at: int = 0

    def __post_init__(self) -> None:
        """Validate identity and budgets."""
        validate_tenant_id(self.tenant_id)
        _optional_money(self.max_budget, "max_budget")
        _optional_money(self.soft_budget, "soft_budget")
        if type(self.created_at) is not int or self.created_at < 0:
            raise ValueError("created_at must be a non-negative integer epoch")

    def spend_limit(self) -> SpendLimit:
        """This tenant's budget as a :class:`SpendLimit`."""
        return SpendLimit(
            scope=BudgetScope.TENANT,
            scope_id=self.tenant_id,
            max_cost=self.max_budget,
            soft_max_cost=self.soft_budget,
            budget_duration_seconds=self.budget_duration_seconds,
            anchor_epoch=self.created_at,
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe representation for durable storage."""
        return {
            "tenant_id": self.tenant_id,
            "max_budget": _money_dict(self.max_budget),
            "budget_duration_seconds": self.budget_duration_seconds,
            "soft_budget": _money_dict(self.soft_budget),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantBudget":
        """Rebuild a tenant budget from :meth:`as_dict` output."""
        return cls(
            tenant_id=data["tenant_id"],
            max_budget=_money_from_dict(data.get("max_budget")),
            budget_duration_seconds=data.get("budget_duration_seconds"),
            soft_budget=_money_from_dict(data.get("soft_budget")),
            created_at=data.get("created_at", 0),
        )


def _money_dict(value: Money | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {"amount": str(value.amount), "currency": value.currency}


def _money_from_dict(value: Any) -> Money | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("stored money must be an object")
    return Money(value["amount"], value.get("currency", "USD"))


__all__ = [
    "DEFAULT_TENANT_ID",
    "MIN_VIRTUAL_KEY_LENGTH",
    "TenantBudget",
    "VirtualKey",
    "hash_virtual_key",
    "key_hash_matches",
    "key_id_for_hash",
    "validate_tenant_id",
]
