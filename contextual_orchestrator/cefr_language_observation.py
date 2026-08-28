"""Provider-neutral CEFR criterion observations with a fail-closed gateway boundary.

This module deliberately does not calculate a CEFR level, score, placement, or
psychometric result.  It accepts opaque references owned by the released
assessment contract, asks one independently blinded rater at a time for a
criterion observation, and returns only bounded observation evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Protocol

from .orchestrator import (
    CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1,
    ModelAgent,
    ModelClient,
    TaskOrchestrator,
)


CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1 = "cwl_cefr_language_assessment/v1"
FAST_MLSIRM_SCORING_SCHEMA_VERSION = "1.0"
MAX_CEFR_REFERENCE_COUNT = 64
MAX_CEFR_RATERS = 32
MAX_CEFR_SETTINGS_BYTES = 8_192
MAX_CEFR_RESPONSE_BYTES = 32_000

_REVIEW_SIGNALS = frozenset(
    {
        "critical_criterion",
        "out_of_distribution",
        "uncertain",
        "unsupported_evidence",
        "human_requested",
    }
)
_OBSERVATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criterion_ref", "category_anchor_ref", "evidence_reference_ids", "status", "uncertainty", "review_signals", "reason_code"],
    "properties": {
        "criterion_ref": {"type": "string"},
        "category_anchor_ref": {"type": ["string", "null"]},
        "evidence_reference_ids": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": MAX_CEFR_REFERENCE_COUNT,
        },
        "status": {"enum": ["observed", "abstained"]},
        "uncertainty": {"enum": ["low", "medium", "high"]},
        "review_signals": {
            "type": "array",
            "items": {"enum": sorted(_REVIEW_SIGNALS)},
            "maxItems": len(_REVIEW_SIGNALS),
        },
        "reason_code": {"type": ["string", "null"]},
    },
}


class CefrObservationError(ValueError):
    """Raised when a CEFR observation cannot cross a governed boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reference(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise CefrObservationError("invalid_reference", f"{field} must be a bounded non-empty string")
    return value.strip()


def _references(values: Sequence[str], field: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not values or len(values) > MAX_CEFR_REFERENCE_COUNT:
        raise CefrObservationError("invalid_references", f"{field} must contain 1..{MAX_CEFR_REFERENCE_COUNT} references")
    normalized = tuple(sorted(_reference(value, field) for value in values))
    if len(set(normalized)) != len(normalized):
        raise CefrObservationError("duplicate_reference", f"{field} must not contain duplicates")
    return normalized


def _freeze_json(value: Any) -> Any:
    """Return a recursively immutable copy of JSON-compatible data."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return a mutable JSON-compatible copy of an immutable snapshot."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class CefrRaterAssignment:
    """One independently blinded rater assignment, without candidate identity."""

    assignment_ref: str
    rater_family: str
    rater_version: str
    model_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignment_ref", _reference(self.assignment_ref, "assignment_ref"))
        object.__setattr__(self, "rater_family", _reference(self.rater_family, "rater_family"))
        object.__setattr__(self, "rater_version", _reference(self.rater_version, "rater_version"))
        if self.model_name is not None:
            object.__setattr__(self, "model_name", _reference(self.model_name, "model_name"))


@dataclass(frozen=True)
class CefrLanguageObservationRequest:
    """Opaque-reference request for one criterion across independent raters."""

    task_ref: str
    rubric_ref: str
    criterion_ref: str
    category_anchor_refs: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]
    rater_assignments: tuple[CefrRaterAssignment, ...]
    prompt_revision: str
    replay_id: str
    workflow_settings: Mapping[str, Any]
    response_format: str = "json_schema"
    api_surface: str = "chat.completions"
    contract_id: str = CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1
    fast_mlsirm_contract_version: str = FAST_MLSIRM_SCORING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.contract_id != CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1:
            raise CefrObservationError("contract_incompatible", "unsupported CEFR assessment contract")
        if self.fast_mlsirm_contract_version != FAST_MLSIRM_SCORING_SCHEMA_VERSION:
            raise CefrObservationError("contract_incompatible", "unsupported fast-mlsirm scoring contract")
        for name in ("task_ref", "rubric_ref", "criterion_ref", "prompt_revision", "replay_id"):
            object.__setattr__(self, name, _reference(getattr(self, name), name))
        object.__setattr__(self, "category_anchor_refs", _references(self.category_anchor_refs, "category_anchor_refs"))
        object.__setattr__(self, "evidence_reference_ids", _references(self.evidence_reference_ids, "evidence_reference_ids"))
        assignments = tuple(self.rater_assignments)
        if not assignments or len(assignments) > MAX_CEFR_RATERS or any(type(value) is not CefrRaterAssignment for value in assignments):
            raise CefrObservationError("invalid_rater_assignments", f"rater_assignments must contain 1..{MAX_CEFR_RATERS} exact assignments")
        if len({value.assignment_ref for value in assignments}) != len(assignments):
            raise CefrObservationError("duplicate_rater_assignment", "rater assignments must be unique")
        object.__setattr__(self, "rater_assignments", tuple(sorted(assignments, key=lambda value: value.assignment_ref)))
        if self.response_format not in {"json_object", "json_schema"}:
            raise CefrObservationError("unsupported_response_format", "response_format must be json_object or json_schema")
        if self.api_surface not in {"chat.completions", "responses"}:
            raise CefrObservationError("unsupported_api_surface", "api_surface must be chat.completions or responses")
        if not isinstance(self.workflow_settings, Mapping):
            raise CefrObservationError("invalid_workflow_settings", "workflow_settings must be an object")
        try:
            encoded_text = json.dumps(
                dict(self.workflow_settings),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            settings = json.loads(encoded_text)
            encoded = encoded_text.encode()
        except (TypeError, ValueError, RecursionError, OverflowError) as exc:
            raise CefrObservationError("invalid_workflow_settings", "workflow_settings must be JSON-compatible") from exc
        if len(encoded) > MAX_CEFR_SETTINGS_BYTES:
            raise CefrObservationError("resource_limit", "workflow_settings exceeds the bounded size")
        object.__setattr__(self, "workflow_settings", _freeze_json(settings))

    @property
    def replay_identity(self) -> str:
        """Return a deterministic identity without embedding source evidence."""
        payload = self.to_contract_payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def to_contract_payload(self) -> dict[str, Any]:
        """Return the opaque request envelope delegated to the released adapter."""
        return {
            "contract_id": self.contract_id,
            "fast_mlsirm_contract_version": self.fast_mlsirm_contract_version,
            "task_ref": self.task_ref,
            "rubric_ref": self.rubric_ref,
            "criterion_ref": self.criterion_ref,
            "category_anchor_refs": list(self.category_anchor_refs),
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "rater_assignment_refs": [value.assignment_ref for value in self.rater_assignments],
            "prompt_revision": self.prompt_revision,
            "replay_id": self.replay_id,
            "workflow_settings": _thaw_json(self.workflow_settings),
        }


class CefrContractAdapter(Protocol):
    """Adapter owned by the released CEFR and fast-mlsirm contracts."""

    contract_id: str
    fast_mlsirm_contract_version: str

    def validate_request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate the exact consumer request contract."""

    def validate_observation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate one criterion observation for downstream scoring."""


class StructuredObservationGateway(Protocol):
    """Existing contextual-orchestrator structured-call boundary."""

    contextual_orchestrator_contract: str

    def complete_structured(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        *,
        api_surface: str,
        model_name: str | None = None,
    ) -> Mapping[str, Any]:
        """Return bounded provider metadata and an unparsed answer."""


@dataclass(frozen=True)
class TaskOrchestratorCefrGateway:
    """Use the existing KV-backed, discovered provider gateway for raters."""

    orchestrator: TaskOrchestrator

    @property
    def contextual_orchestrator_contract(self) -> str:
        """Expose the required gateway contract version."""
        return CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1

    def complete_structured(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
        *,
        api_surface: str,
        model_name: str | None = None,
    ) -> Mapping[str, Any]:
        """Select one structured-capable agent and call it through the gateway."""
        if model_name is None:
            agent = self.orchestrator._select_agent("", "judge", required_tags=("response_format",))
        else:
            agent = self.orchestrator._requested_agent(model_name)
            if agent is None:
                agent = self.orchestrator._select_agent("", "judge", required_tags=("response_format",))
        if agent.disabled or not {"response_format", "capability:response_format"}.intersection(agent.tags):
            raise CefrObservationError("capability_mismatch", "selected rater does not declare structured-output support")
        if api_surface == "chat.completions":
            payload: dict[str, Any] = {
                "model": agent.model,
                "messages": messages,
                "response_format": response_format,
                "stream": False,
                "temperature": self.orchestrator.client.temperature,
                "max_tokens": self.orchestrator.client.max_output_tokens,
            }
            endpoint = "chat/completions"
        elif api_surface == "responses":
            payload = {
                "model": agent.model,
                "input": messages,
                "text": {"format": _responses_format(response_format)},
                "stream": False,
                "temperature": self.orchestrator.client.temperature,
                "max_output_tokens": self.orchestrator.client.max_output_tokens,
            }
            endpoint = "responses"
        else:
            raise CefrObservationError("unsupported_api_surface", "unsupported API surface")
        profile = self.orchestrator._role_effort_profile("judge")
        if profile is not None:
            payload = self.orchestrator.client.apply_effort_profile(agent, payload, profile)
        response = self.orchestrator.client.proxy_send(agent, endpoint, payload)
        answer = _response_text(agent, response, api_surface)
        usage = _safe_usage(response.get("usage")) if isinstance(response, Mapping) else None
        return {
            "answer": answer,
            "served_agent_id": agent.id,
            "model": agent.model,
            "provider": agent.provider_name or "unreported",
            "provider_version": response.get("provider_version") if isinstance(response.get("provider_version"), str) else None,
            "usage": usage,
        }


def _responses_format(response_format: Mapping[str, Any]) -> dict[str, Any]:
    if response_format.get("type") == "json_object":
        return {"type": "json_object"}
    schema = response_format.get("json_schema")
    if not isinstance(schema, Mapping):
        raise CefrObservationError("unsupported_response_format", "json_schema format is incomplete")
    return {"type": "json_schema", **{key: schema[key] for key in ("name", "schema", "strict") if key in schema}}


def _response_text(agent: ModelAgent, response: Mapping[str, Any], api_surface: str) -> str:
    if api_surface == "chat.completions":
        return ModelClient._response_content(agent, dict(response))
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    raise CefrObservationError("provider_error", "Responses provider omitted output text")


def _safe_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
        token_count = value.get(key)
        if type(token_count) is int and token_count >= 0:
            safe[key] = token_count
    return safe or None


def _response_format(kind: str) -> dict[str, Any]:
    if kind == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "cefr_criterion_observation",
            "strict": True,
            "schema": _OBSERVATION_SCHEMA,
        },
    }


def _messages(request: CefrLanguageObservationRequest, assignment: CefrRaterAssignment) -> list[dict[str, Any]]:
    """Build a prompt containing only opaque references and one rater assignment."""
    envelope = {
        "task_ref": request.task_ref,
        "rubric_ref": request.rubric_ref,
        "criterion_ref": request.criterion_ref,
        "category_anchor_refs": request.category_anchor_refs,
        "evidence_reference_ids": request.evidence_reference_ids,
        "rater_assignment_ref": assignment.assignment_ref,
        "rater_family": assignment.rater_family,
        "rater_version": assignment.rater_version,
        "prompt_revision": request.prompt_revision,
    }
    return [
        {
            "role": "system",
            "content": (
                "Return only one criterion-level observation using the requested JSON shape. "
                "Use authorized evidence references; never emit a CEFR level, score, placement, "
                "certification, or psychometric result. This rater is blind to candidate identity "
                "and to all other raters."
            ),
        },
        {"role": "user", "content": json.dumps(envelope, sort_keys=True, separators=(",", ":"))},
    ]


def _parse_json(answer: Any) -> dict[str, Any]:
    if not isinstance(answer, str) or len(answer.encode()) > MAX_CEFR_RESPONSE_BYTES:
        raise CefrObservationError("malformed_json", "rater response is missing or too large")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CefrObservationError("malformed_json", "rater response contains duplicate keys")
            result[key] = value
        return result

    try:
        parsed = json.loads(answer, object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, RecursionError, TypeError):
        raise CefrObservationError("malformed_json", "rater response is not valid JSON") from None
    if not isinstance(parsed, dict) or set(parsed) != set(_OBSERVATION_SCHEMA["properties"]):
        raise CefrObservationError("malformed_json", "rater response has an unsupported shape")
    return parsed


def _normalize_observation(value: Mapping[str, Any], request: CefrLanguageObservationRequest) -> dict[str, Any]:
    allowed = set(_OBSERVATION_SCHEMA["properties"])
    if set(value) != allowed:
        raise CefrObservationError("malformed_json", "criterion observation contains unsupported fields")
    if value.get("criterion_ref") != request.criterion_ref:
        raise CefrObservationError("unsupported_evidence", "criterion reference does not match the request")
    category = value.get("category_anchor_ref")
    if category is not None and (not isinstance(category, str) or category not in request.category_anchor_refs):
        raise CefrObservationError("unsupported_evidence", "category anchor is not declared by the request")
    evidence = value.get("evidence_reference_ids")
    if not isinstance(evidence, list) or any(type(item) is not str for item in evidence):
        raise CefrObservationError("unsupported_evidence", "evidence references are malformed")
    evidence_ids = tuple(evidence)
    if len(set(evidence_ids)) != len(evidence_ids) or not set(evidence_ids).issubset(request.evidence_reference_ids):
        raise CefrObservationError("unsupported_evidence", "evidence references are not declared by the request")
    status = value.get("status")
    uncertainty = value.get("uncertainty")
    signals = value.get("review_signals")
    reason = value.get("reason_code")
    if status not in {"observed", "abstained"} or uncertainty not in {"low", "medium", "high"}:
        raise CefrObservationError("malformed_json", "observation status or uncertainty is invalid")
    if not isinstance(signals, list) or len(set(signals)) != len(signals) or not set(signals).issubset(_REVIEW_SIGNALS):
        raise CefrObservationError("malformed_json", "review signals are invalid")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise CefrObservationError("malformed_json", "reason_code must be null or non-empty")
    if status == "observed" and (category is None or not evidence_ids or reason is not None):
        raise CefrObservationError("unsupported_evidence", "observed output requires one category and evidence")
    if status == "abstained" and (category is not None or evidence_ids or reason is None):
        raise CefrObservationError("unsupported_evidence", "abstained output cannot retain a rating or evidence")
    return {
        "criterion_ref": request.criterion_ref,
        "category_anchor_ref": category,
        "evidence_reference_ids": list(evidence_ids),
        "status": status,
        "uncertainty": uncertainty,
        "review_signals": sorted(signals),
        "reason_code": None if reason is None else reason.strip(),
    }


def _failure_code(error: BaseException) -> str:
    if isinstance(error, CefrObservationError):
        return error.code
    name = type(error).__name__.casefold()
    if "timeout" in name:
        return "timeout"
    if "capab" in name or "unsupported" in name:
        return "capability_mismatch"
    if "json" in name:
        return "malformed_json"
    return "provider_error"


def _observe_one(
    request: CefrLanguageObservationRequest,
    assignment: CefrRaterAssignment,
    gateway: StructuredObservationGateway,
    adapter: CefrContractAdapter,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": f"cefr_observation_{hashlib.sha256((request.replay_identity + assignment.assignment_ref).encode()).hexdigest()[:32]}",
        "assignment_ref": assignment.assignment_ref,
        "rater_family": assignment.rater_family,
        "rater_version": assignment.rater_version,
        "prompt_revision": request.prompt_revision,
        "workflow_settings": _thaw_json(request.workflow_settings),
        "model": None,
        "provider": None,
        "provider_version": None,
        "usage": None,
        "served_agent_id": None,
        "rater_provenance": None,
        "criterion_observation": None,
        "parse_state": "not_attempted",
        "verifier_state": "not_run",
        "failure_code": None,
    }
    try:
        response = gateway.complete_structured(
            _messages(request, assignment),
            _response_format(request.response_format),
            api_surface=request.api_surface,
            model_name=assignment.model_name,
        )
        if not isinstance(response, Mapping):
            raise CefrObservationError("provider_error", "gateway returned a non-object result")
        for key in ("model", "provider", "provider_version"):
            if isinstance(response.get(key), str):
                base[key] = response[key]
        served_agent_id = response.get("served_agent_id")
        if type(served_agent_id) is not str or not served_agent_id.strip():
            raise CefrObservationError("provider_error", "gateway omitted the served agent identity")
        base["served_agent_id"] = served_agent_id.strip()
        if assignment.model_name is not None and response.get("model") != assignment.model_name:
            raise CefrObservationError("rater_assignment_mismatch", "gateway served a different model than assigned")
        base["rater_provenance"] = {
            "assignment_ref": assignment.assignment_ref,
            "rater_family": assignment.rater_family,
            "rater_version": assignment.rater_version,
            "served_agent_id": base["served_agent_id"],
            "model": base["model"],
            "provider": base["provider"],
            "provider_version": base["provider_version"],
        }
        base["usage"] = _safe_usage(response.get("usage"))
        base["parse_state"] = "received"
        parsed = _parse_json(response.get("answer"))
        base["parse_state"] = "accepted"
        observation = _normalize_observation(parsed, request)
        adapter.validate_observation(
            {
                "contract_id": request.contract_id,
                "fast_mlsirm_contract_version": request.fast_mlsirm_contract_version,
                "request_replay_identity": request.replay_identity,
                "rater_provenance": base["rater_provenance"],
                "observation": observation,
            }
        )
        base["criterion_observation"] = observation
        base["verifier_state"] = "accepted"
    except Exception as error:  # noqa: BLE001 - return only stable failure evidence
        base["failure_code"] = _failure_code(error)
        if base["parse_state"] == "received":
            base["parse_state"] = "rejected"
        base["verifier_state"] = "rejected"
    return base


def _validate_contract(adapter: CefrContractAdapter, request: CefrLanguageObservationRequest) -> None:
    if (
        adapter is None
        or getattr(adapter, "contract_id", None) != CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1
        or getattr(adapter, "fast_mlsirm_contract_version", None) != FAST_MLSIRM_SCORING_SCHEMA_VERSION
        or not callable(getattr(adapter, "validate_request", None))
        or not callable(getattr(adapter, "validate_observation", None))
    ):
        raise CefrObservationError("missing_contract", "released CEFR and fast-mlsirm contracts are required")
    try:
        validated = adapter.validate_request(request.to_contract_payload())
    except CefrObservationError:
        raise
    except Exception as error:  # noqa: BLE001 - contract errors must be stable
        raise CefrObservationError("contract_incompatible", "consumer contract rejected the request") from error
    if not isinstance(validated, Mapping):
        raise CefrObservationError("contract_incompatible", "consumer contract returned no validated request")


def observe_language_response_criteria(
    request: CefrLanguageObservationRequest,
    gateway: StructuredObservationGateway,
    contract_adapter: CefrContractAdapter,
    *,
    max_concurrency: int = 1,
) -> dict[str, Any]:
    """Run independently blinded criterion raters and return no final score.

    The caller supplies the released contract adapter.  Without it the function
    fails closed, which prevents this gateway from silently becoming a duplicate
    CEFR or fast-mlsirm schema.  Each provider call receives one assignment and
    opaque references only; other rater outputs and candidate identity are never
    included in a prompt.
    """
    if type(request) is not CefrLanguageObservationRequest:
        raise CefrObservationError("invalid_request", "request must be an exact CefrLanguageObservationRequest")
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= MAX_CEFR_RATERS:
        raise CefrObservationError("resource_limit", "max_concurrency must be an integer in 1..32")
    if getattr(gateway, "contextual_orchestrator_contract", None) != CONTEXTUAL_ORCHESTRATOR_CONTRACT_V1:
        raise CefrObservationError("missing_gateway_contract", "contextual-orchestrator contract is required")
    _validate_contract(contract_adapter, request)
    if max_concurrency == 1:
        observations = [_observe_one(request, assignment, gateway, contract_adapter) for assignment in request.rater_assignments]
    else:
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            observations = list(executor.map(lambda assignment: _observe_one(request, assignment, gateway, contract_adapter), request.rater_assignments))
    observations.sort(key=lambda value: value["assignment_ref"])
    review_reasons = {
        value["failure_code"]
        for value in observations
        if value["failure_code"] is not None
    }
    for value in observations:
        observation = value["criterion_observation"]
        if observation is None:
            review_reasons.add("incomplete_observation_panel")
            continue
        if observation["status"] == "abstained":
            review_reasons.add("incomplete_observation_panel")
        review_reasons.update(observation["review_signals"])
        if observation["uncertainty"] == "high":
            review_reasons.add("uncertain")
    observed_categories = [
        value["criterion_observation"]["category_anchor_ref"]
        for value in observations
        if value["criterion_observation"] is not None
        and value["criterion_observation"]["status"] == "observed"
    ]
    disagreement_count = sum(
        left != right
        for index, left in enumerate(observed_categories)
        for right in observed_categories[index + 1 :]
    )
    if disagreement_count:
        review_reasons.add("disagreement")
    observed_count = sum(
        value["criterion_observation"] is not None
        and value["criterion_observation"]["status"] == "observed"
        for value in observations
    )
    incomplete_count = len(observations) - observed_count
    return {
        "contract_id": request.contract_id,
        "fast_mlsirm_contract_version": request.fast_mlsirm_contract_version,
        "criterion_ref": request.criterion_ref,
        "request_replay_identity": request.replay_identity,
        "panel_size": len(observations),
        "observed_count": observed_count,
        "incomplete_count": incomplete_count,
        "disagreement_count": disagreement_count,
        "observations": observations,
        "human_review": {
            "required": bool(review_reasons),
            "reason_codes": sorted(review_reasons),
        },
    }


__all__ = [
    "CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1",
    "FAST_MLSIRM_SCORING_SCHEMA_VERSION",
    "CefrContractAdapter",
    "CefrLanguageObservationRequest",
    "CefrObservationError",
    "CefrRaterAssignment",
    "StructuredObservationGateway",
    "TaskOrchestratorCefrGateway",
    "observe_language_response_criteria",
]
