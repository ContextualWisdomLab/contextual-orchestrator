"""Provider-affine ownership records for asynchronous video jobs."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any


class VideoJobContractError(RuntimeError):
    """Raised when a provider submission cannot become a trackable video job."""


@dataclass(frozen=True)
class VideoJobOwner:
    """Bind one gateway video job to the exact provider agent that accepted it."""

    gateway_job_id: str
    provider_job_id: str
    agent_id: str
    submitted_at: int


class VideoJobRegistry:
    """Store video-job ownership in the configured shared job registry."""

    def __init__(self, job_registry: Any) -> None:
        self._owners = job_registry.mapping(
            "video_job_owners", decode=lambda raw: VideoJobOwner(**raw)
        )

    def register(self, provider_result: dict[str, Any], agent_id: str) -> dict[str, Any]:
        """Persist ownership and replace the provider id with an opaque gateway id."""
        provider_job_id = provider_result.get("id")
        if not isinstance(provider_job_id, str) or not provider_job_id.strip():
            raise VideoJobContractError(
                "video provider response must contain a non-empty id"
            )
        gateway_job_id = f"videojob_{uuid.uuid4().hex}"
        self._owners[gateway_job_id] = VideoJobOwner(
            gateway_job_id=gateway_job_id,
            provider_job_id=provider_job_id,
            agent_id=agent_id,
            submitted_at=int(time.time()),
        )
        return self.public_response(provider_result, self._owners[gateway_job_id])

    @staticmethod
    def public_response(
        provider_result: dict[str, Any], owner: VideoJobOwner
    ) -> dict[str, Any]:
        """Replace every occurrence of the provider job id in a JSON document.

        Providers may repeat their job identifier in nested metadata or URLs.
        The gateway ownership identifier is the only job identity exposed to
        clients, so exact occurrences are replaced recursively before a
        provider document crosses the public boundary.
        """

        def replace(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace(owner.provider_job_id, owner.gateway_job_id)
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {replace(key): replace(item) for key, item in value.items()}
            return value

        response = replace(provider_result)
        response["id"] = owner.gateway_job_id
        return response

    def owner(self, gateway_job_id: str) -> VideoJobOwner:
        """Return the recorded provider owner or raise ``KeyError`` when unknown."""
        return self._owners[gateway_job_id]
