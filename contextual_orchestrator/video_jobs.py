"""Provider-affine ownership records for asynchronous video jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import logging
import threading
import time
from typing import Any
import uuid


_LOGGER = logging.getLogger(__name__)


class VideoJobContractError(RuntimeError):
    """Raised when a provider submission cannot become a trackable video job."""


@dataclass(frozen=True)
class VideoJobRecord:
    """Persist the immutable ownership tuple for one gateway video job."""

    gateway_job_id: str
    provider_job_id: str
    agent_id: str
    submitted_at: int
    owner_id: str
    agent_affinity_key: str = ""


@dataclass(frozen=True)
class VideoJobUsage:
    """Persist the first complete provider usage report separately."""

    prompt_tokens: int
    completion_tokens: int
    observed_at: int


@dataclass(frozen=True)
class VideoJobOwner:
    """Combine an ownership record with its optional measured usage."""

    gateway_job_id: str
    provider_job_id: str
    agent_id: str
    submitted_at: int
    owner_id: str = ""
    usage_measurement_status: str = "unavailable"
    provider_usage: dict[str, int] | None = None
    agent_affinity_key: str = ""


def video_agent_affinity_key(agent: Any) -> str:
    """Fingerprint the non-secret routing identity used for provider follow-ups."""
    identity = {
        "base_url": agent.base_url,
        "credential_name": agent.credential_name,
        "auth_scheme": agent.auth_scheme,
        "local_credential_key": agent.local_credential_key,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class VideoJobRegistry:
    """Store video-job ownership in the configured shared job registry."""

    def __init__(self, job_registry: Any) -> None:
        # Keep immutable ownership and mutable provider observations in separate
        # records. The old mapping remains a compatibility path for jobs
        # created before this normalized layout existed.
        self._records = job_registry.mapping(
            "video_job_records", decode=lambda raw: VideoJobRecord(**raw)
        )
        self._usages = job_registry.mapping(
            "video_job_usages", decode=lambda raw: VideoJobUsage(**raw)
        )
        self._legacy_owners = job_registry.mapping(
            "video_job_owners", decode=lambda raw: VideoJobOwner(**raw)
        )
        self._usage_lock = threading.Lock()

    def register(
        self,
        provider_result: dict[str, Any],
        agent_id: str,
        owner_id: str,
        *,
        agent_affinity_key: str = "",
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
        submitted_at = int(time.time())
        record = VideoJobRecord(
            gateway_job_id=gateway_job_id,
            provider_job_id=provider_job_id,
            agent_id=agent_id,
            submitted_at=submitted_at,
            owner_id=owner_id,
            agent_affinity_key=agent_affinity_key,
        )
        reported_usage = self._provider_usage(provider_result)
        # Core ownership is written first: a failure after provider acceptance
        # must never leave the job without a gateway-addressable owner.
        self._records[gateway_job_id] = record
        if reported_usage is not None:
            try:
                self._store_usage_if_absent(
                    gateway_job_id,
                    VideoJobUsage(
                        prompt_tokens=reported_usage["prompt_tokens"],
                        completion_tokens=reported_usage["completion_tokens"],
                        observed_at=submitted_at,
                    ),
                )
            except Exception:  # noqa: BLE001 - ownership is already durably committed
                # Returning the opaque gateway id is the recoverability boundary:
                # the caller can poll the accepted provider job and retry the
                # companion observation, while billing still receives the
                # provider response through the coordinator's independent sink.
                _LOGGER.warning(
                    "video usage persistence failed after ownership commit; "
                    "follow-up polling may retry"
                )
        response_owner = VideoJobOwner(
            gateway_job_id=record.gateway_job_id,
            provider_job_id=record.provider_job_id,
            agent_id=record.agent_id,
            submitted_at=record.submitted_at,
            owner_id=record.owner_id,
            agent_affinity_key=record.agent_affinity_key,
        )
        return self.public_response(provider_result, response_owner)

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

        def replace_provider_identity(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace(owner.provider_job_id, owner.gateway_job_id)
            if isinstance(value, list):
                return [replace_provider_identity(item) for item in value]
            if isinstance(value, dict):
                return {
                    replace_provider_identity(key): replace_provider_identity(item)
                    for key, item in value.items()
                }
            return value

        response = replace_provider_identity(provider_result)
        response["id"] = owner.gateway_job_id
        return response

    def owner(self, gateway_job_id: str, owner_id: str) -> VideoJobOwner:
        """Return a principal-owned record, hiding unknown and foreign identities alike."""
        record, legacy = self._record(gateway_job_id)
        stored_owner_id = record.owner_id
        if not owner_id or stored_owner_id != owner_id:
            raise KeyError(gateway_job_id)
        if legacy:
            assert isinstance(record, VideoJobOwner)
            return self._owner_from_legacy(record)
        assert isinstance(record, VideoJobRecord)
        return self._owner_from_record(record)

    def _record(self, gateway_job_id: str) -> tuple[VideoJobRecord | VideoJobOwner, bool]:
        """Load the normalized record, falling back to the legacy map."""
        try:
            return self._records[gateway_job_id], False
        except KeyError:
            return self._legacy_owners[gateway_job_id], True

    def _usage_document(self, gateway_job_id: str) -> dict[str, int] | None:
        """Read one normalized usage row as the public token-count shape."""
        usage = self._usages.get(gateway_job_id)
        if usage is None:
            return None
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }

    def _owner_from_record(self, record: VideoJobRecord) -> VideoJobOwner:
        """Join one normalized ownership record to its optional usage row."""
        provider_usage = self._usage_document(record.gateway_job_id)
        return VideoJobOwner(
            gateway_job_id=record.gateway_job_id,
            provider_job_id=record.provider_job_id,
            agent_id=record.agent_id,
            submitted_at=record.submitted_at,
            owner_id=record.owner_id,
            usage_measurement_status=(
                "measured" if provider_usage is not None else "unavailable"
            ),
            provider_usage=provider_usage,
            agent_affinity_key=record.agent_affinity_key,
        )

    def _owner_from_legacy(self, owner: VideoJobOwner) -> VideoJobOwner:
        """Join a retained legacy owner to the shared first-write usage row."""
        if owner.provider_usage is not None:
            return owner
        provider_usage = self._usage_document(owner.gateway_job_id)
        if provider_usage is None:
            return owner
        return replace(
            owner,
            usage_measurement_status="measured",
            provider_usage=provider_usage,
        )

    def observe_provider_result(
        self, owner: VideoJobOwner, provider_result: dict[str, Any]
    ) -> VideoJobOwner:
        """Persist provider-reported counts while retaining honest unknown state."""
        usage = self._provider_usage(provider_result)
        record, legacy = self._record(owner.gateway_job_id)
        if legacy:
            assert isinstance(record, VideoJobOwner)
            current = self._owner_from_legacy(record)
            if usage is not None and current.provider_usage is None:
                # Legacy ownership remains readable in its historical mapping,
                # while observations use the normalized HSETNX-backed mapping.
                # This gives old jobs the same cross-replica first-write-wins
                # contract as newly normalized jobs without rewriting their row.
                self._store_usage_if_absent(
                    owner.gateway_job_id,
                    VideoJobUsage(
                        prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        observed_at=int(time.time()),
                    ),
                )
            return self._owner_from_legacy(record)
        assert isinstance(record, VideoJobRecord)
        if usage is not None and owner.provider_usage is None:
            self._store_usage_if_absent(
                owner.gateway_job_id,
                VideoJobUsage(
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    observed_at=int(time.time()),
                ),
            )
        return self._owner_from_record(record)

    def _store_usage_if_absent(self, gateway_job_id: str, usage: VideoJobUsage) -> None:
        """Keep the first complete report when replicas observe stale owners."""
        setter = getattr(self._usages, "set_if_absent", None)
        if callable(setter):
            setter(gateway_job_id, usage)
            return
        # ponytail: plain dict fallback has no compare-and-set; this process-local
        # lock serializes its threaded request path. Valkey uses hsetnx above.
        with self._usage_lock:
            if self._usages.get(gateway_job_id) is None:
                self._usages[gateway_job_id] = usage

    @staticmethod
    def _provider_usage(document: dict[str, Any]) -> dict[str, int] | None:
        """Return only concrete provider counts; absent counts remain unavailable."""
        usage = document.get("usage")
        if not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion = usage.get("completion_tokens", usage.get("output_tokens"))
        if (
            type(prompt) is not int
            or prompt < 0
            or type(completion) is not int
            or completion < 0
        ):
            return None
        return {"prompt_tokens": prompt, "completion_tokens": completion}
