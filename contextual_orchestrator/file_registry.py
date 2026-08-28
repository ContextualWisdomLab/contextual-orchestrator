"""Principal-owned provider affinity for OpenAI-compatible Files resources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
import uuid


class FileContractError(RuntimeError):
    """Raised when a provider response cannot become a gateway file resource."""


@dataclass(frozen=True)
class FileOwner:
    """Bind one opaque gateway file id to its provider-side resource."""

    gateway_file_id: str
    provider_file_id: str
    agent_id: str
    owner_id: str
    agent_affinity_key: str
    document: dict[str, Any]
    replicas: dict[str, dict[str, str]] | None = None


def file_agent_affinity_key(agent: Any) -> str:
    """Fingerprint the non-secret provider account used by file follow-ups."""
    identity = {
        "base_url": agent.base_url,
        "credential_name": agent.credential_name,
        "auth_scheme": agent.auth_scheme,
        "local_credential_key": agent.local_credential_key,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class FileRegistry:
    """Persist provider file identities without exposing them to callers."""

    def __init__(self, job_registry: Any) -> None:
        self._owners = job_registry.mapping(
            "file_owners", decode=lambda raw: FileOwner(**raw)
        )

    def register(
        self,
        provider_result: dict[str, Any],
        agent_id: str,
        owner_id: str,
        *,
        agent_affinity_key: str,
    ) -> dict[str, Any]:
        """Persist ownership and replace the provider id with an opaque id."""
        return self.register_replicas(
            [(provider_result, agent_id, agent_affinity_key)], owner_id
        )

    def register_replicas(
        self,
        provider_results: list[tuple[dict[str, Any], str, str]],
        owner_id: str,
    ) -> dict[str, Any]:
        """Persist every accepted provider replica behind one gateway id."""
        if not provider_results:
            raise FileContractError("at least one file provider result is required")
        provider_result, agent_id, agent_affinity_key = provider_results[0]
        provider_file_id = provider_result.get("id")
        if not isinstance(provider_file_id, str) or not provider_file_id.strip():
            raise FileContractError("file provider response must contain a non-empty id")
        if not owner_id:
            raise FileContractError("file owner is unavailable")
        gateway_file_id = f"file_{uuid.uuid4().hex}"
        owner = FileOwner(
            gateway_file_id=gateway_file_id,
            provider_file_id=provider_file_id,
            agent_id=agent_id,
            owner_id=owner_id,
            agent_affinity_key=agent_affinity_key,
            document=dict(provider_result),
            replicas={},
        )
        replicas = owner.replicas
        assert replicas is not None
        for result, replica_agent_id, affinity_key in provider_results:
            replica_id = result.get("id")
            if not isinstance(replica_id, str) or not replica_id.strip():
                raise FileContractError("file provider response must contain a non-empty id")
            replicas[replica_agent_id] = {
                "provider_file_id": replica_id,
                "agent_affinity_key": affinity_key,
            }
        self._owners[gateway_file_id] = owner
        return self.public_response(provider_result, owner)

    @staticmethod
    def public_response(document: dict[str, Any], owner: FileOwner) -> dict[str, Any]:
        """Return a provider document with only the gateway identity exposed."""
        result = dict(document)
        reported_id = result.get("id")
        if reported_id not in (None, owner.provider_file_id):
            raise FileContractError("file provider returned a different file id")
        result["id"] = owner.gateway_file_id
        return result

    def owner(self, gateway_file_id: str, owner_id: str) -> FileOwner:
        """Resolve a principal-owned file while hiding foreign ids as not found."""
        owner = self._owners[gateway_file_id]
        if not owner_id or owner.owner_id != owner_id:
            raise KeyError(gateway_file_id)
        return owner

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        """List only files owned by the authenticated principal."""
        return [
            self.public_response(owner.document, owner)
            for owner in self._owners.values()
            if owner.owner_id == owner_id
        ]

    def delete(self, gateway_file_id: str, owner_id: str) -> FileOwner:
        """Remove and return a principal-owned binding after provider deletion."""
        owner = self.owner(gateway_file_id, owner_id)
        del self._owners[gateway_file_id]
        return owner

    def bind_request(
        self, document: dict[str, Any], owner_id: str
    ) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
        """Validate file ownership and return provider-specific replica ids."""
        bindings: dict[str, dict[str, str]] = {}

        def rewrite(value: Any) -> Any:
            if isinstance(value, list):
                return [rewrite(item) for item in value]
            if not isinstance(value, dict):
                return value
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key == "file_id" and isinstance(item, str) and item.startswith("file_"):
                    try:
                        owner = self.owner(item, owner_id)
                    except KeyError as exc:
                        raise FileContractError("referenced file was not found") from exc
                    replicas = owner.replicas or {
                        owner.agent_id: {
                            "provider_file_id": owner.provider_file_id,
                            "agent_affinity_key": owner.agent_affinity_key,
                        }
                    }
                    bindings[item] = replicas
                    result[key] = item
                else:
                    result[key] = rewrite(item)
            return result

        rewritten = rewrite(document)
        if bindings:
            common_agents = set.intersection(
                *(set(replicas) for replicas in bindings.values())
            )
            if not common_agents:
                raise FileContractError(
                    "referenced files have no common provider replica"
                )
        return rewritten, bindings
