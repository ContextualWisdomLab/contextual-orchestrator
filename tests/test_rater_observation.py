"""Contracts for criterion-bound governed rater observations."""

from __future__ import annotations

import hashlib
import json
from collections import UserDict
from copy import deepcopy
from typing import Any, Callable

import pytest

from contextual_orchestrator.evaluation_criterion_binding import (
    MAX_CRITERION_BINDING_CATEGORIES,
    MAX_CRITERION_BINDING_REFERENCES,
    MAX_CRITERION_BINDING_REFERENCE_LENGTH,
    CategoryExecutionBinding,
    CriterionExecutionBinding,
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)
from contextual_orchestrator.rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    MAX_RATER_EVIDENCE_REFERENCES,
    MAX_RATER_OBSERVATIONS,
    MAX_RATER_REFERENCE_LENGTH,
    MAX_RATER_REVIEW_SIGNALS,
    CriterionObservation,
    RaterConfigurationIdentity,
    RaterInvocation,
    RaterObservationError,
)


def _digest(payload: dict[str, Any]) -> str:
    """Return the canonical criterion-set digest independently of production."""
    content = deepcopy(payload)
    content.pop("criterion_set_sha256", None)
    return hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _category(seed: str, order: int) -> dict[str, object]:
    """Return one category definition receipt."""
    return {
        "definition_ref": f"{seed}_definition",
        "definition_sha256": seed[0] * 64,
        "order_index": order,
    }


def _criterion(seed: str) -> dict[str, Any]:
    """Return one substantive criterion receipt."""
    return {
        "criterion_revision_ref": f"{seed}_revision_1",
        "definition_ref": f"{seed}_definition",
        "definition_sha256": "1" * 64,
        "admissible_evidence_rule_ref": f"{seed}_evidence_rule",
        "admissible_evidence_rule_sha256": "2" * 64,
        "exclusion_rule_ref": f"{seed}_exclusion_rule",
        "exclusion_rule_sha256": "3" * 64,
        "response_semantics_ref": f"{seed}_response_semantics",
        "response_semantics_sha256": "4" * 64,
        "abstention_rule_ref": f"{seed}_abstention_rule",
        "abstention_rule_sha256": "5" * 64,
        "not_observable_rule_ref": f"{seed}_not_observable_rule",
        "not_observable_rule_sha256": "6" * 64,
        "categories": {
            f"{seed}_not_supported": _category("a_category", 0),
            f"{seed}_supported": _category("b_category", 1),
        },
    }


def _criterion_set() -> dict[str, Any]:
    """Return a complete non-empty criterion set with a content digest."""
    payload: dict[str, Any] = {
        "criterion_set_snapshot_ref": "criterion_set_snapshot_1",
        "criterion_set_sha256": "",
        "blueprint_revision_ref": "evaluation_blueprint_revision_1",
        "rubric_revision_ref": "rubric_revision_1",
        "intended_use_ref": "intended_use_1",
        "construct_ref": "construct_1",
        "population_scope_ref": "population_scope_1",
        "language_scope_ref": "language_scope_1",
        "domain_scope_ref": "domain_scope_1",
        "criteria": {
            "criterion_evidence_support": _criterion(
                "criterion_evidence_support"
            ),
            "criterion_safety": _criterion("criterion_safety"),
        },
    }
    payload["criterion_set_sha256"] = _digest(payload)
    return payload


def _configuration() -> dict[str, str]:
    """Return one exact rater configuration."""
    return {
        "rater_family_ref": "rater-family",
        "provider_ref": "provider",
        "implementation_revision_ref": "implementation-v1",
        "instruction_revision_ref": "instruction-v1",
        "response_schema_revision_ref": "schema-v1",
        "workflow_mode_ref": "independent-blind",
        "modality_channel_ref": "text",
    }


def _observed(
    category: str = "criterion_evidence_support_supported",
) -> dict[str, Any]:
    """Return one observed criterion payload."""
    return {
        "status": "observed",
        "category_anchor_ref": category,
        "evidence_reference_ids": ["evidence-1"],
        "uncertainty": "low",
        "review_signal_refs": [],
        "reason_ref": None,
    }


def _abstained() -> dict[str, Any]:
    """Return one explicit abstention payload."""
    return {
        "status": "abstained",
        "category_anchor_ref": None,
        "evidence_reference_ids": [],
        "uncertainty": "high",
        "review_signal_refs": ["review-1"],
        "reason_ref": "insufficient-evidence",
    }


def _invocation() -> dict[str, Any]:
    """Return one complete criterion-bound invocation."""
    return {
        "contract_id": GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
        "invocation_ref": "invocation-1",
        "configuration": _configuration(),
        "evaluation_run_snapshot_ref": "run-snapshot-1",
        "item_instance_ref": "item-instance-1",
        "task_revision_ref": "task-v1",
        "rubric_revision_ref": "rubric_revision_1",
        "criterion_set": _criterion_set(),
        "response_evidence_ref": "response-evidence-1",
        "observations": {
            "criterion_evidence_support": _observed(),
            "criterion_safety": _abstained(),
        },
    }


def _trusted() -> CriterionSetExecutionBinding:
    """Return the independently admitted criterion set for parser calls."""
    return CriterionSetExecutionBinding.from_mapping(_criterion_set())


def _parse(payload: Any) -> RaterInvocation:
    """Parse provider output under the test's independent trusted policy."""
    return RaterInvocation.from_mapping(payload, expected_criterion_set=_trusted())


def _parse_json(payload: str) -> RaterInvocation:
    """Parse raw provider JSON under the independent trusted policy."""
    return RaterInvocation.from_json(payload, expected_criterion_set=_trusted())


def _code(callable_: Callable[[], Any]) -> str:
    """Return a stable domain error code from one failing call."""
    with pytest.raises(
        (RaterObservationError, EvaluationCriterionBindingError)
    ) as error:
        callable_()
    return error.value.code


def _redigest(payload: dict[str, Any]) -> None:
    """Update the digest after an intentional, otherwise valid policy change."""
    payload["criterion_set_sha256"] = _digest(payload)


def test_criterion_set_round_trip_carries_all_substantive_meaning() -> None:
    """Definitions, rules, scope, category order, and digest survive admission."""
    payload = _criterion_set()
    payload["criteria"] = dict(reversed(tuple(payload["criteria"].items())))
    binding = CriterionSetExecutionBinding.from_mapping(payload)
    assert binding.criterion_refs == (
        "criterion_evidence_support",
        "criterion_safety",
    )
    criterion = binding.criterion("criterion_evidence_support")
    assert criterion.definition_ref == "criterion_evidence_support_definition"
    assert criterion.admissible_evidence_rule_ref.endswith("_evidence_rule")
    assert criterion.exclusion_rule_ref.endswith("_exclusion_rule")
    assert criterion.response_semantics_ref.endswith("_response_semantics")
    assert criterion.abstention_rule_ref.endswith("_abstention_rule")
    assert criterion.not_observable_rule_ref.endswith("_not_observable_rule")
    assert criterion.category_refs == (
        "criterion_evidence_support_not_supported",
        "criterion_evidence_support_supported",
    )
    assert binding.criterion_set_sha256 == _digest(payload)
    assert binding.to_payload() == _criterion_set()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("construct_ref", None, "invalid_reference"),
        ("construct_ref", " construct", "invalid_reference"),
        ("criterion_set_sha256", "bad", "invalid_sha256"),
        ("criterion_set_sha256", object(), "invalid_sha256"),
    ],
)
def test_criterion_set_rejects_invalid_top_level_values(
    field: str, value: object, code: str
) -> None:
    """Top-level references and digests fail closed before domain admission."""
    payload = _criterion_set()
    payload[field] = value
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(payload)) == code


def test_criterion_set_rejects_missing_unknown_wrong_container_and_empty() -> None:
    """The criterion-set object is exact, complete, bounded, and non-empty."""
    missing = _criterion_set()
    del missing["construct_ref"]
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(missing)) == (
        "missing_field"
    )

    unknown = _criterion_set()
    unknown["score"] = 1
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(unknown)) == (
        "unknown_field"
    )

    for invalid in ([], UserDict(_criterion_set())):
        assert _code(
            lambda invalid=invalid: CriterionSetExecutionBinding.from_mapping(invalid)
        ) == "invalid_object"

    non_string = _criterion_set()
    non_string["criteria"] = {1: _criterion("criterion")}
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(non_string)) == (
        "invalid_object_key"
    )

    empty = _criterion_set()
    empty["criteria"] = {}
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(empty)) == (
        "invalid_criterion_set"
    )

    oversized = _criterion_set()
    oversized["criteria"] = {
        f"criterion_{index}": _criterion(f"criterion_{index}")
        for index in range(MAX_CRITERION_BINDING_REFERENCES + 1)
    }
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(oversized)) == (
        "invalid_criterion_set"
    )


def test_criterion_set_digest_covers_scope_rules_categories_and_order() -> None:
    """Any substantive mutation invalidates the old criterion-set digest."""
    mutations = (
        lambda payload: payload.__setitem__("domain_scope_ref", "domain_scope_2"),
        lambda payload: payload["criteria"]["criterion_safety"].__setitem__(
            "definition_ref", "changed_definition"
        ),
        lambda payload: payload["criteria"]["criterion_safety"].__setitem__(
            "admissible_evidence_rule_sha256", "9" * 64
        ),
        lambda payload: payload["criteria"]["criterion_safety"]["categories"][
            "criterion_safety_supported"
        ].__setitem__("definition_ref", "changed_category"),
        lambda payload: (
            payload["criteria"]["criterion_safety"]["categories"][
                "criterion_safety_not_supported"
            ].__setitem__("order_index", 1),
            payload["criteria"]["criterion_safety"]["categories"][
                "criterion_safety_supported"
            ].__setitem__("order_index", 0),
        ),
    )
    for mutate in mutations:
        payload = _criterion_set()
        mutate(payload)
        assert _code(lambda: CriterionSetExecutionBinding.from_mapping(payload)) == (
            "criterion_set_digest_mismatch"
        )


def test_criterion_category_validation_is_exact_ordered_and_bounded() -> None:
    """Categories require complete content identity and contiguous unique order."""
    one = _criterion("criterion")
    one["categories"] = {"only": _category("a_category", 0)}
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(one, criterion_ref="criterion")
    ) == "invalid_category_set"

    too_many = _criterion("criterion")
    too_many["categories"] = {
        f"category_{index}": _category("a_category", index)
        for index in range(MAX_CRITERION_BINDING_CATEGORIES + 1)
    }
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            too_many, criterion_ref="criterion"
        )
    ) == "invalid_category_set"

    duplicate = _criterion("criterion")
    duplicate["categories"]["criterion_supported"]["order_index"] = 0
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            duplicate, criterion_ref="criterion"
        )
    ) == "duplicate_order_index"

    gap = _criterion("criterion")
    gap["categories"]["criterion_supported"]["order_index"] = 2
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(gap, criterion_ref="criterion")
    ) == "non_contiguous_order_index"

    missing = _category("a_category", 0)
    del missing["definition_ref"]
    assert _code(
        lambda: CategoryExecutionBinding.from_mapping(
            missing, category_ref="category"
        )
    ) == "missing_field"

    unknown = _category("a_category", 0)
    unknown["score"] = 0
    assert _code(
        lambda: CategoryExecutionBinding.from_mapping(
            unknown, category_ref="category"
        )
    ) == "unknown_field"

    for invalid_order in (True, -1):
        invalid = _category("a_category", 0)
        invalid["order_index"] = invalid_order
        assert _code(
            lambda invalid=invalid: CategoryExecutionBinding.from_mapping(
                invalid, category_ref="category"
            )
        ) == "invalid_order_index"


def test_criterion_validation_rejects_missing_unknown_and_bad_values() -> None:
    """Criterion rules cannot be omitted, extended, or weakly typed."""
    missing = _criterion("criterion")
    del missing["exclusion_rule_ref"]
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            missing, criterion_ref="criterion"
        )
    ) == "missing_field"

    unknown = _criterion("criterion")
    unknown["gold"] = True
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            unknown, criterion_ref="criterion"
        )
    ) == "unknown_field"

    bad_ref = _criterion("criterion")
    bad_ref["definition_ref"] = "\u0085"
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            bad_ref, criterion_ref="criterion"
        )
    ) == "invalid_reference"

    bad_digest = _criterion("criterion")
    bad_digest["definition_sha256"] = "A" * 64
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            bad_digest, criterion_ref="criterion"
        )
    ) == "invalid_sha256"

    bad_categories = _criterion("criterion")
    bad_categories["categories"] = UserDict(bad_categories["categories"])
    assert _code(
        lambda: CriterionExecutionBinding.from_mapping(
            bad_categories, criterion_ref="criterion"
        )
    ) == "invalid_object"


def test_duplicate_criterion_revisions_and_lookup_fail_closed() -> None:
    """Set members have unique revisions and lookup does not normalize aliases."""
    payload = _criterion_set()
    payload["criteria"]["criterion_safety"]["criterion_revision_ref"] = (
        payload["criteria"]["criterion_evidence_support"][
            "criterion_revision_ref"
        ]
    )
    _redigest(payload)
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(payload)) == (
        "duplicate_criterion_revision"
    )

    binding = _trusted()
    assert _code(lambda: binding.criterion("missing")) == "criterion_not_registered"
    assert _code(lambda: binding.criterion(" missing")) == "invalid_reference"


def test_reference_length_boundaries_are_exact() -> None:
    """Criterion and rater reference limits reject overlong opaque identities."""
    payload = _criterion_set()
    payload["construct_ref"] = "x" * MAX_CRITERION_BINDING_REFERENCE_LENGTH
    _redigest(payload)
    assert CriterionSetExecutionBinding.from_mapping(payload).construct_ref == (
        "x" * MAX_CRITERION_BINDING_REFERENCE_LENGTH
    )

    payload["construct_ref"] += "x"
    _redigest(payload)
    assert _code(lambda: CriterionSetExecutionBinding.from_mapping(payload)) == (
        "invalid_reference"
    )

    observation = _observed()
    observation["criterion_ref"] = "x" * MAX_RATER_REFERENCE_LENGTH
    assert CriterionObservation.from_mapping(observation).criterion_ref == (
        "x" * MAX_RATER_REFERENCE_LENGTH
    )
    observation["criterion_ref"] += "x"
    assert _code(lambda: CriterionObservation.from_mapping(observation)) == (
        "invalid_reference"
    )


def test_binding_constructors_are_sealed_and_integrity_is_replayed() -> None:
    """Direct construction and later object-level tampering cannot bypass admission."""
    with pytest.raises(ValueError):
        CategoryExecutionBinding("c", "d", "a" * 64, 0)

    binding = _trusted()
    criterion = binding.criteria[0]
    with pytest.raises(ValueError):
        CriterionExecutionBinding(
            criterion_ref=criterion.criterion_ref,
            criterion_revision_ref=criterion.criterion_revision_ref,
            definition_ref=criterion.definition_ref,
            definition_sha256=criterion.definition_sha256,
            admissible_evidence_rule_ref=criterion.admissible_evidence_rule_ref,
            admissible_evidence_rule_sha256=(
                criterion.admissible_evidence_rule_sha256
            ),
            exclusion_rule_ref=criterion.exclusion_rule_ref,
            exclusion_rule_sha256=criterion.exclusion_rule_sha256,
            response_semantics_ref=criterion.response_semantics_ref,
            response_semantics_sha256=criterion.response_semantics_sha256,
            abstention_rule_ref=criterion.abstention_rule_ref,
            abstention_rule_sha256=criterion.abstention_rule_sha256,
            not_observable_rule_ref=criterion.not_observable_rule_ref,
            not_observable_rule_sha256=criterion.not_observable_rule_sha256,
            categories=criterion.categories,
        )
    with pytest.raises(ValueError):
        CriterionSetExecutionBinding(
            criterion_set_snapshot_ref=binding.criterion_set_snapshot_ref,
            criterion_set_sha256=binding.criterion_set_sha256,
            blueprint_revision_ref=binding.blueprint_revision_ref,
            rubric_revision_ref=binding.rubric_revision_ref,
            intended_use_ref=binding.intended_use_ref,
            construct_ref=binding.construct_ref,
            population_scope_ref=binding.population_scope_ref,
            language_scope_ref=binding.language_scope_ref,
            domain_scope_ref=binding.domain_scope_ref,
            criteria=binding.criteria,
        )

    category_tampered = _trusted()
    object.__setattr__(
        category_tampered.criteria[0].categories[0], "definition_ref", "mutated"
    )
    assert _code(category_tampered.to_payload) == "criterion_set_integrity_mismatch"

    criterion_tampered = _trusted()
    object.__setattr__(criterion_tampered.criteria[0], "categories", [])
    assert _code(criterion_tampered.to_payload) == "criterion_set_integrity_mismatch"

    set_tampered = _trusted()
    object.__setattr__(set_tampered, "criteria", [])
    assert _code(set_tampered.to_payload) == "criterion_set_integrity_mismatch"


def test_configuration_is_closed_complete_and_round_trips() -> None:
    """Only an exact provider-neutral rater configuration crosses the boundary."""
    config = RaterConfigurationIdentity.from_mapping(_configuration())
    assert config.to_payload() == _configuration()

    unknown = _configuration()
    unknown["temperature"] = "0.2"
    assert _code(lambda: RaterConfigurationIdentity.from_mapping(unknown)) == (
        "unknown_field"
    )

    missing = _configuration()
    del missing["provider_ref"]
    assert _code(lambda: RaterConfigurationIdentity.from_mapping(missing)) == (
        "missing_field"
    )

    assert _code(lambda: RaterConfigurationIdentity.from_mapping(UserDict())) == (
        "invalid_object"
    )


def test_observed_and_abstained_states_are_mutually_exclusive() -> None:
    """Observed evidence and explicit abstention have distinct state contracts."""
    observed = CriterionObservation.from_mapping(
        _observed(), criterion_ref="criterion"
    )
    assert observed.to_payload() == _observed()
    abstained = CriterionObservation.from_mapping(
        _abstained(), criterion_ref="criterion"
    )
    assert abstained.to_payload() == _abstained()

    invalid_cases = (
        ({**_observed(), "status": "unknown"}, "invalid_status"),
        ({**_observed(), "uncertainty": "certain"}, "invalid_uncertainty"),
        ({**_observed(), "evidence_reference_ids": []}, "invalid_references"),
        ({**_observed(), "reason_ref": "reason"}, "invalid_observed_state"),
        (
            {**_abstained(), "category_anchor_ref": "category"},
            "invalid_abstention_state",
        ),
        (
            {**_abstained(), "evidence_reference_ids": ["evidence"]},
            "invalid_abstention_state",
        ),
        ({**_abstained(), "reason_ref": None}, "invalid_reference"),
    )
    for payload, code in invalid_cases:
        assert _code(
            lambda payload=payload: CriterionObservation.from_mapping(
                payload, criterion_ref="criterion"
            )
        ) == code


def test_observation_fields_and_reference_collections_fail_closed() -> None:
    """Observation fields are exact and bounded against aliases and duplication."""
    missing = _observed()
    del missing["uncertainty"]
    assert _code(
        lambda: CriterionObservation.from_mapping(missing, criterion_ref="criterion")
    ) == "missing_field"

    unknown = _observed()
    unknown["final_score"] = 1
    assert _code(
        lambda: CriterionObservation.from_mapping(unknown, criterion_ref="criterion")
    ) == "decision_leakage"

    ordinary_unknown = _observed()
    ordinary_unknown["explanation"] = "x"
    assert _code(
        lambda: CriterionObservation.from_mapping(
            ordinary_unknown, criterion_ref="criterion"
        )
    ) == "unknown_field"

    for field, maximum, factory in (
        ("evidence_reference_ids", MAX_RATER_EVIDENCE_REFERENCES, _observed),
        ("review_signal_refs", MAX_RATER_REVIEW_SIGNALS, _abstained),
    ):
        wrong = factory()
        wrong[field] = "not-an-array"
        assert _code(
            lambda wrong=wrong: CriterionObservation.from_mapping(
                wrong, criterion_ref="criterion"
            )
        ) == "invalid_references"

        duplicate = factory()
        duplicate[field] = ["same", "same"]
        assert _code(
            lambda duplicate=duplicate: CriterionObservation.from_mapping(
                duplicate, criterion_ref="criterion"
            )
        ) == "duplicate_reference"

        oversized = factory()
        oversized[field] = [f"ref-{index}" for index in range(maximum + 1)]
        assert _code(
            lambda oversized=oversized: CriterionObservation.from_mapping(
                oversized, criterion_ref="criterion"
            )
        ) == "invalid_references"

    copied = ["evidence"]
    observation = CriterionObservation(
        criterion_ref="criterion",
        status="observed",
        category_anchor_ref="category",
        evidence_reference_ids=copied,
        uncertainty="medium",
        review_signal_refs=[],
        reason_ref=None,
    )
    copied.append("mutated")
    assert observation.evidence_reference_ids == ("evidence",)


def test_invocation_requires_independent_policy_and_rejects_substitution() -> None:
    """Matching malicious criteria and observations cannot replace owner policy."""
    payload = _invocation()
    assert _code(lambda: RaterInvocation.from_mapping(payload)) == (
        "trusted_criterion_set_required"
    )
    assert _code(
        lambda: RaterInvocation.from_mapping(
            payload, expected_criterion_set=object()
        )
    ) == "invalid_expected_criterion_set"

    substituted = _invocation()
    substituted["criterion_set"]["construct_ref"] = "foreign_construct"
    substituted["criterion_set"]["criteria"] = {
        "foreign_criterion": _criterion("foreign_criterion")
    }
    substituted["criterion_set"]["criterion_set_snapshot_ref"] = "foreign_set"
    _redigest(substituted["criterion_set"])
    substituted["observations"] = {
        "foreign_criterion": _observed("foreign_criterion_supported")
    }
    assert _code(lambda: _parse(substituted)) == "criterion_set_substitution"


def test_invocation_round_trip_uses_trusted_object_and_deterministic_order() -> None:
    """The provider echo is checked, then replaced with the trusted domain value."""
    payload = _invocation()
    payload["observations"] = dict(reversed(tuple(payload["observations"].items())))
    trusted = _trusted()
    invocation = RaterInvocation.from_mapping(
        payload, expected_criterion_set=trusted
    )
    assert invocation.criterion_set is trusted
    assert tuple(item.criterion_ref for item in invocation.observations) == (
        "criterion_evidence_support",
        "criterion_safety",
    )
    expected = _invocation()
    assert invocation.to_payload() == expected

    caller = _invocation()
    invocation = _parse(caller)
    caller["observations"]["criterion_evidence_support"][
        "evidence_reference_ids"
    ].append("mutated")
    caller["criterion_set"]["criteria"]["criterion_safety"][
        "definition_ref"
    ] = "mutated"
    assert invocation.to_payload() == expected


def test_invocation_mapping_boundary_is_closed_complete_and_bounded() -> None:
    """Invocation envelopes, observations, and decision authority fail closed."""
    assert _code(lambda: _parse(UserDict(_invocation()))) == "invalid_object"

    non_string = _invocation()
    non_string[1] = "value"
    assert _code(lambda: _parse(non_string)) == "invalid_object_key"

    missing = _invocation()
    del missing["task_revision_ref"]
    assert _code(lambda: _parse(missing)) == "missing_field"

    decision = _invocation()
    decision["score"] = 1
    assert _code(lambda: _parse(decision)) == "decision_leakage"

    unknown = _invocation()
    unknown["provider_latency"] = 1
    assert _code(lambda: _parse(unknown)) == "unknown_field"

    wrong = _invocation()
    wrong["observations"] = []
    assert _code(lambda: _parse(wrong)) == "invalid_object"

    empty = _invocation()
    empty["observations"] = {}
    assert _code(lambda: _parse(empty)) == "invalid_observations"

    oversized = _invocation()
    oversized["observations"] = {
        f"criterion-{index}": _observed()
        for index in range(MAX_RATER_OBSERVATIONS + 1)
    }
    assert _code(lambda: _parse(oversized)) == "invalid_observations"


def test_invocation_rejects_contract_configuration_references_and_rubric() -> None:
    """The aggregate validates its own exact contract and run/item identities."""
    contract = _invocation()
    contract["contract_id"] = "wrong/v1"
    assert _code(lambda: _parse(contract)) == "contract_incompatible"

    configuration = _invocation()
    configuration["configuration"] = []
    assert _code(lambda: _parse(configuration)) == "invalid_object"

    reference = _invocation()
    reference["item_instance_ref"] = " item"
    assert _code(lambda: _parse(reference)) == "invalid_reference"

    rubric = _invocation()
    rubric["rubric_revision_ref"] = "rubric_revision_2"
    assert _code(lambda: _parse(rubric)) == "criterion_set_rubric_mismatch"


def test_invocation_rejects_coverage_duplicate_types_and_foreign_categories() -> None:
    """Every trusted criterion has one typed observation in its admitted category."""
    missing = _invocation()
    missing["observations"].pop("criterion_safety")
    assert _code(lambda: _parse(missing)) == "criterion_coverage_mismatch"

    extra = _invocation()
    extra["observations"]["criterion_extra"] = _abstained()
    assert _code(lambda: _parse(extra)) == "criterion_coverage_mismatch"

    category = _invocation()
    category["observations"]["criterion_evidence_support"] = _observed(
        "criterion_safety_supported"
    )
    assert _code(lambda: _parse(category)) == "category_not_admitted"

    config = RaterConfigurationIdentity.from_mapping(_configuration())
    binding = _trusted()
    observed = CriterionObservation.from_mapping(
        _observed(), criterion_ref="criterion_evidence_support"
    )
    duplicate = (observed, observed)
    assert _code(
        lambda: RaterInvocation(
            invocation_ref="invocation",
            configuration=config,
            evaluation_run_snapshot_ref="run",
            item_instance_ref="item",
            task_revision_ref="task",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=binding,
            response_evidence_ref="response",
            observations=duplicate,
        )
    ) == "duplicate_criterion"

    invalid_constructor_cases = (
        ({"configuration": object()}, "invalid_configuration"),
        ({"criterion_set": object()}, "invalid_criterion_set"),
        ({"observations": []}, "invalid_observations"),
        ({"observations": (object(),)}, "invalid_observation"),
    )
    base = {
        "invocation_ref": "invocation",
        "configuration": config,
        "evaluation_run_snapshot_ref": "run",
        "item_instance_ref": "item",
        "task_revision_ref": "task",
        "rubric_revision_ref": "rubric_revision_1",
        "criterion_set": binding,
        "response_evidence_ref": "response",
        "observations": (observed,),
    }
    for change, code in invalid_constructor_cases:
        arguments = {**base, **change}
        assert _code(lambda arguments=arguments: RaterInvocation(**arguments)) == code


def test_raw_json_rejects_duplicates_depth_and_invalid_values() -> None:
    """Provider JSON cannot exploit duplicate members or parser ambiguity."""
    payload = _invocation()
    assert _parse_json(json.dumps(payload)).to_payload() == payload

    duplicate = '{"contract_id":"a","contract_id":"b"}'
    assert _code(lambda: _parse_json(duplicate)) == "duplicate_object_member"

    nested = "[" * 65 + "0" + "]" * 65
    assert _code(lambda: _parse_json(nested)) == "invalid_json"
    assert _code(lambda: _parse_json("{")) == "invalid_json"
    assert _code(
        lambda: RaterInvocation.from_json(
            object(), expected_criterion_set=_trusted()
        )
    ) == "invalid_json"
    assert _code(lambda: RaterInvocation.from_json("{}")) == (
        "trusted_criterion_set_required"
    )


def test_tampered_trusted_policy_is_rejected_before_provider_data() -> None:
    """Later mutation of the independently trusted object invalidates admission."""
    trusted = _trusted()
    object.__setattr__(trusted.criteria[0], "definition_ref", "mutated")
    assert _code(
        lambda: RaterInvocation.from_mapping(
            _invocation(), expected_criterion_set=trusted
        )
    ) == "criterion_set_integrity_mismatch"

    invocation = _parse(_invocation())
    object.__setattr__(invocation.criterion_set, "construct_ref", "mutated")
    assert _code(invocation.to_payload) == "criterion_set_integrity_mismatch"


def test_nested_value_objects_expose_verified_payloads() -> None:
    """Public child payload methods verify their own integrity before export."""
    binding = _trusted()
    criterion = binding.criteria[0]
    category = criterion.categories[0]
    assert category.to_payload()["order_index"] == 0
    assert criterion.to_payload()["categories"]

    object.__setattr__(category, "definition_ref", object())
    assert _code(category.to_payload) == "category_binding_integrity_mismatch"


def test_rater_reference_controls_are_rejected() -> None:
    """Rater-side references reject C0, C1, and surrogate controls."""
    for value in ("line\nbreak", "control\u0085", "\ud800"):
        payload = _observed()
        payload["criterion_ref"] = value
        assert _code(
            lambda payload=payload: CriterionObservation.from_mapping(payload)
        ) == "invalid_reference"


def test_invalid_echoed_criterion_set_translates_binding_errors() -> None:
    """Malformed provider policy echoes remain rater-boundary domain errors."""
    payload = _invocation()
    payload["criterion_set"]["criterion_set_sha256"] = "0" * 64
    assert _code(lambda: _parse(payload)) == "criterion_set_digest_mismatch"


def test_direct_invocation_replays_tampered_criterion_integrity() -> None:
    """Direct aggregate construction cannot accept a later-mutated set object."""
    trusted = _trusted()
    object.__setattr__(trusted.criteria[0], "definition_ref", "mutated")
    observed = CriterionObservation.from_mapping(
        _observed(), criterion_ref="criterion_evidence_support"
    )
    config = RaterConfigurationIdentity.from_mapping(_configuration())
    assert _code(
        lambda: RaterInvocation(
            invocation_ref="invocation",
            configuration=config,
            evaluation_run_snapshot_ref="run",
            item_instance_ref="item",
            task_revision_ref="task",
            rubric_revision_ref="rubric_revision_1",
            criterion_set=trusted,
            response_evidence_ref="response",
            observations=(observed,),
        )
    ) == "criterion_set_integrity_mismatch"


def test_json_depth_scanner_handles_escaped_string_delimiters() -> None:
    """Escaped quotes and slashes inside JSON strings do not affect depth."""
    payload = _invocation()
    payload["response_evidence_ref"] = 'evidence-\\"quoted'
    encoded = json.dumps(payload)
    assert _parse_json(encoded).response_evidence_ref == 'evidence-\\"quoted'
