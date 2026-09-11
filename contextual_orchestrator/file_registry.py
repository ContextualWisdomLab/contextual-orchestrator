"""Principal-owned provider affinity for OpenAI-compatible Files resources."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any
import uuid


class FileContractError(RuntimeError):
    """Raised when a provider response cannot become a gateway file resource."""


class FileProviderUnavailableError(FileContractError):
    """Raised when owned files have no shared provider replica."""


@dataclass(frozen=True)
class FileOwner:
    """Bind one opaque gateway file id to its provider-side resource.

    ``document`` and ``replicas`` are retained as the durable ``file_owners``
    record keys so already-persisted registry rows continue to decode. New
    package-owned code uses the semantic accessors below instead of spreading
    those historical generic persistence names beyond this adapter boundary.
    """

    gateway_file_id: str
    provider_file_id: str
    agent_id: str
    owner_id: str
    agent_affinity_key: str
    document: dict[str, Any]
    replicas: dict[str, dict[str, str]] | None = None

    @property
    def provider_document(self) -> dict[str, Any]:
        """Return the durable provider response document for this owned file."""
        return self.document

    @property
    def provider_replicas(self) -> dict[str, dict[str, str]] | None:
        """Return durable provider replica bindings for this owned file."""
        return self.replicas


def file_agent_affinity_key(model_agent: Any) -> str:
    """Fingerprint the non-secret provider account used by file follow-ups."""
    provider_account_identity = {
        "base_url": model_agent.base_url,
        "credential_name": model_agent.credential_name,
        "auth_scheme": model_agent.auth_scheme,
        "local_credential_key": model_agent.local_credential_key,
    }
    encoded_provider_identity = json.dumps(
        provider_account_identity, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded_provider_identity).hexdigest()


class FileRegistry:
    """Persist provider file identities without exposing them to callers."""

    def __init__(self, job_registry: Any) -> None:
        self._file_owners = job_registry.mapping(
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
        file_owner = FileOwner(
            gateway_file_id=gateway_file_id,
            provider_file_id=provider_file_id,
            agent_id=agent_id,
            owner_id=owner_id,
            agent_affinity_key=agent_affinity_key,
            document=dict(provider_result),
            replicas={},
        )
        provider_replicas = file_owner.provider_replicas
        assert provider_replicas is not None
        for replica_result, replica_agent_id, affinity_key in provider_results:
            replica_id = replica_result.get("id")
            if not isinstance(replica_id, str) or not replica_id.strip():
                raise FileContractError("file provider response must contain a non-empty id")
            provider_replicas[replica_agent_id] = {
                "provider_file_id": replica_id,
                "agent_affinity_key": affinity_key,
            }
        self._file_owners[gateway_file_id] = file_owner
        return self.public_response(provider_result, file_owner)

    @staticmethod
    def public_response(
        provider_document: dict[str, Any], file_owner: FileOwner
    ) -> dict[str, Any]:
        """Return a provider document with only the gateway identity exposed."""
        public_document = dict(provider_document)
        reported_id = public_document.get("id")
        if reported_id not in (None, file_owner.provider_file_id):
            raise FileContractError("file provider returned a different file id")
        public_document["id"] = file_owner.gateway_file_id
        return public_document

    def owner(self, gateway_file_id: str, owner_id: str) -> FileOwner:
        """Resolve a principal-owned file while hiding foreign ids as not found."""
        file_owner = self._file_owners[gateway_file_id]
        if not owner_id or file_owner.owner_id != owner_id:
            raise KeyError(gateway_file_id)
        return file_owner

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        """List only files owned by the authenticated principal."""
        return [
            self.public_response(file_owner.provider_document, file_owner)
            for file_owner in self._file_owners.values()
            if file_owner.owner_id == owner_id
        ]

    def delete(self, gateway_file_id: str, owner_id: str) -> FileOwner:
        """Remove and return a principal-owned binding after provider deletion."""
        file_owner = self.owner(gateway_file_id, owner_id)
        del self._file_owners[gateway_file_id]
        return file_owner

    def retain_replicas(
        self,
        gateway_file_id: str,
        owner_id: str,
        provider_replicas: dict[str, dict[str, str]],
    ) -> None:
        """Persist replicas still requiring deletion after a partial attempt."""
        file_owner = self.owner(gateway_file_id, owner_id)
        self._file_owners[gateway_file_id] = replace(
            file_owner, replicas=dict(provider_replicas)
        )

    def bind_request(
        self, request_document: dict[str, Any], owner_id: str
    ) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
        """Validate file ownership and return provider-specific replica ids."""
        file_bindings: dict[str, dict[str, str]] = {}

        def rewrite_request_value(request_value: Any) -> Any:
            if isinstance(request_value, list):
                return [rewrite_request_value(request_item) for request_item in request_value]
            if not isinstance(request_value, dict):
                return request_value
            rewritten_mapping: dict[str, Any] = {}
            for field_name, request_item in request_value.items():
                if (
                    field_name == "file_id"
                    and isinstance(request_item, str)
                    and request_item.startswith("file_")
                ):
                    try:
                        file_owner = self.owner(request_item, owner_id)
                    except KeyError as exc:
                        raise FileContractError("referenced file was not found") from exc
                    provider_replicas = file_owner.provider_replicas or {
                        file_owner.agent_id: {
                            "provider_file_id": file_owner.provider_file_id,
                            "agent_affinity_key": file_owner.agent_affinity_key,
                        }
                    }
                    file_bindings[request_item] = provider_replicas
                    rewritten_mapping[field_name] = request_item
                else:
                    rewritten_mapping[field_name] = rewrite_request_value(request_item)
            return rewritten_mapping

        rewritten_document = rewrite_request_value(request_document)
        if file_bindings:
            common_agents = set.intersection(
                *(
                    set(provider_replicas)
                    for provider_replicas in file_bindings.values()
                )
            )
            if not common_agents:
                raise FileProviderUnavailableError(
                    "referenced files have no common provider replica"
                )
        return rewritten_document, file_bindings
