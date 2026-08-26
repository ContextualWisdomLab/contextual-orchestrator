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
    owner_id: str = ""
    usage_measurement_status: str = "unavailable"
    provider_usage: dict[str, int] | None = None


class VideoJobRegistry:
    """Store video-job ownership in the configured shared job registry."""

    def __init__(self, job_registry: Any) -> None:
        self._owners = job_registry.mapping(
            "video_job_owners", decode=lambda raw: VideoJobOwner(**raw)
        )

    def register(
        self, provider_result: dict[str, Any], agent_id: str, owner_id: str
    ) -> dict[str, Any]:
        """Persist ownership and replace the provider id with an opaque gateway id."""
        provider_job_id = provider_result.get("id")
        if not isinstance(provider_job_id, str) or not provider_job_id.strip():
            raise VideoJobContractError(
                "video provider response must contain a non-empty id"
            )
        if not isinstance(owner_id, str) or not owner_id:
            raise VideoJobContractError("video job owner is unavailable")
        gateway_job_id = f"videojob_{uuid.uuid4().hex}"
        reported_usage = self._provider_usage(provider_result)
        self._owners[gateway_job_id] = VideoJobOwner(
            gateway_job_id=gateway_job_id,
            provider_job_id=provider_job_id,
            agent_id=agent_id,
            submitted_at=int(time.time()),
            owner_id=owner_id,
            usage_measurement_status=(
                "measured" if reported_usage is not None else "unavailable"
            ),
            provider_usage=reported_usage,
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

        reported_id = provider_result.get("id")
        if isinstance(reported_id, str) and reported_id != owner.provider_job_id:
            raise VideoJobContractError("video provider returned a different job id")

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

    def owner(self, gateway_job_id: str, owner_id: str) -> VideoJobOwner:
        """Return a principal-owned record, hiding unknown and foreign identities alike."""
        owner = self._owners[gateway_job_id]
        if not owner_id or owner.owner_id != owner_id:
            raise KeyError(gateway_job_id)
        return owner

    def observe_provider_result(
        self, owner: VideoJobOwner, provider_result: dict[str, Any]
    ) -> VideoJobOwner:
        """Persist provider-reported counts while retaining honest unknown state."""
        usage = self._provider_usage(provider_result)
        if usage is None or owner.provider_usage is not None:
            return owner
        updated = VideoJobOwner(
            gateway_job_id=owner.gateway_job_id,
            provider_job_id=owner.provider_job_id,
            agent_id=owner.agent_id,
            submitted_at=owner.submitted_at,
            owner_id=owner.owner_id,
            usage_measurement_status="measured",
            provider_usage=usage,
        )
        self._owners[owner.gateway_job_id] = updated
        return updated

    @staticmethod
    def _provider_usage(document: dict[str, Any]) -> dict[str, int] | None:
        """Return only concrete provider counts; absent counts remain unavailable."""
        usage = document.get("usage")
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if (type(prompt) is not int or prompt < 0 or
                type(completion) is not int or completion < 0):
            return None
        return {"prompt_tokens": prompt, "completion_tokens": completion}
