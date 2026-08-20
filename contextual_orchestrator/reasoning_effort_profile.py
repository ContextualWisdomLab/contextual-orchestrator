"""Provider-neutral reasoning-effort profiles and equal-budget ablation.

Issue #568: each TRINITY/Conductor workflow role gets an explicit
``reasoning_effort_profile``. Sampling temperature, top-p, and seed stay
independent fields. Production routing defaults stay locked until an
equal-budget ablation beats a predeclared true-θ RMSE threshold.

Buyer next action: parse a versioned profile, bind it to thinker / worker /
verifier / synthesizer / planner / judge, and compare route-versus-conduct
variants under the same token budget before asking to change defaults.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

PROFILE_VERSION = "reasoning_effort_profile.v1"
PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD = 0.55
WORKFLOW_ROLES = (
    "thinker",
    "worker",
    "verifier",
    "synthesizer",
    "planner",
    "judge",
)
REASONING_EFFORT_LEVELS = ("none", "low", "medium", "high")
ACCESS_LIST_SCOPES = ("none", "role", "workflow")
UNSUPPORTED_FALLBACKS = ("abstain", "omit", "error")
_EFFORT_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_ACCESS_RANK = {"none": 0, "role": 1, "workflow": 2}
_PROFILE_KEYS = frozenset(
    {
        "profile_version",
        "reasoning_effort",
        "max_output_tokens",
        "max_calls",
        "max_workflow_steps",
        "max_recursion_depth",
        "max_worker_fan_out",
        "access_list_scope",
        "deadline_ms",
        "cost_token_budget",
        "temperature",
        "top_p",
        "seed",
        "unsupported_provider_fallback",
    }
)


class EffortProfileError(ValueError):
    """Raised when a reasoning-effort profile is missing, unknown, or unsafe."""


def apply_request_profile(
    payload: dict[str, Any],
    profile: "ReasoningEffortProfile | None",
    *,
    supports_reasoning_effort: bool,
    default_max_output_tokens: int,
) -> dict[str, Any]:
    """Apply one validated profile to an upstream request body.

    Sampling controls remain separate from provider-native reasoning effort.
    When provider support is not proven, ``abstain`` and ``error`` fail closed;
    ``omit`` sends only the independently valid sampling and output-token
    controls. The helper never writes prompts, credentials, or private
    reasoning traces.
    """
    if profile is None:
        payload.setdefault("max_tokens", default_max_output_tokens)
        return payload
    if not isinstance(profile, ReasoningEffortProfile):
        raise EffortProfileError("effort profile must be a ReasoningEffortProfile")
    validated = parse_reasoning_effort_profile(profile.as_dict())
    if not supports_reasoning_effort and validated.unsupported_provider_fallback != "omit":
        raise EffortProfileError(
            "provider reasoning_effort support is unproven; profile requested "
            f"{validated.unsupported_provider_fallback!r}"
        )
    payload["max_tokens"] = validated.max_output_tokens
    payload["temperature"] = validated.temperature
    payload["top_p"] = validated.top_p
    if validated.seed is not None:
        payload["seed"] = validated.seed
    if supports_reasoning_effort:
        payload["reasoning_effort"] = validated.reasoning_effort
    return payload


@dataclass(frozen=True)
class ReasoningEffortProfile:
    """One versioned compute profile for a single workflow role.

    ``reasoning_effort`` is the provider-neutral thinking budget. ``temperature``,
    ``top_p``, and ``seed`` are sampling controls and must not stand in for
    effort. Buyer next action: send this object (or its dict) per role instead
    of raising temperature to "think harder".
    """

    profile_version: str = PROFILE_VERSION
    reasoning_effort: str = "medium"
    max_output_tokens: int = 256
    max_calls: int = 1
    max_workflow_steps: int = 4
    max_recursion_depth: int = 1
    max_worker_fan_out: int = 1
    access_list_scope: str = "role"
    deadline_ms: int = 120_000
    cost_token_budget: int = 1024
    temperature: float = 0.2
    top_p: float = 1.0
    seed: int | None = None
    unsupported_provider_fallback: str = "abstain"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of this profile."""
        return asdict(self)


@dataclass(frozen=True)
class EffortCatalogSnapshot:
    """Replayable hash of a role → profile catalog.

    Buyer next action: persist ``snapshot_hash`` with the evaluation run so a
    later replay can prove the same profiles were in force.
    """

    profile_version: str
    snapshot_hash: str
    role_profiles: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ThetaEstimate:
    """Deterministic θ̂ and its RMSE against known true parameters.

    Buyer next action: compare ``estimated_theta`` to the true vector you
    supplied. A lower RMSE from higher effort is evidence; a temperature-only
    change is not.
    """

    estimated_theta: tuple[float, ...]
    rmse: float
    measurement_status: str = "estimated"


def _reject_non_finite_number(value: Any, field_name: str) -> None:
    """Fail closed on NaN, infinity, or a boolean used as a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EffortProfileError(f"{field_name} must be a finite number, not {value!r}")
    if not math.isfinite(float(value)):
        raise EffortProfileError(f"{field_name} must be finite, not {value!r}")


def parse_reasoning_effort_profile(raw: Mapping[str, Any] | None) -> ReasoningEffortProfile:
    """Validate and return one profile. Unknown keys and unsafe numbers fail closed.

    Buyer next action: omit unknown knobs; send ``reasoning_effort`` as
    none/low/medium/high, never as a temperature float.
    """
    if raw is None:
        raise EffortProfileError("reasoning_effort_profile is required")
    payload = dict(raw)
    unknown = sorted(set(payload) - _PROFILE_KEYS)
    if unknown:
        raise EffortProfileError(f"unknown reasoning_effort_profile keys: {unknown}")
    defaults = ReasoningEffortProfile()
    merged: dict[str, Any] = defaults.as_dict()
    merged.update(payload)

    effort = merged["reasoning_effort"]
    if effort not in REASONING_EFFORT_LEVELS:
        raise EffortProfileError(
            "reasoning_effort must be one of none/low/medium/high; "
            "do not send a temperature or token count as effort"
        )
    for field_name in (
        "max_output_tokens",
        "max_calls",
        "max_workflow_steps",
        "max_recursion_depth",
        "max_worker_fan_out",
        "deadline_ms",
        "cost_token_budget",
        "temperature",
        "top_p",
    ):
        _reject_non_finite_number(merged[field_name], field_name)
        if field_name != "temperature" and field_name != "top_p":
            if int(merged[field_name]) != merged[field_name] or int(merged[field_name]) < 0:
                raise EffortProfileError(f"{field_name} must be a non-negative integer")
            merged[field_name] = int(merged[field_name])
        else:
            merged[field_name] = float(merged[field_name])
    if merged["seed"] is not None:
        _reject_non_finite_number(merged["seed"], "seed")
        if int(merged["seed"]) != merged["seed"]:
            raise EffortProfileError("seed must be an integer or null")
        merged["seed"] = int(merged["seed"])
    if not 0.0 <= float(merged["temperature"]) <= 2.0:
        raise EffortProfileError("temperature must be between 0 and 2")
    if not 0.0 < float(merged["top_p"]) <= 1.0:
        raise EffortProfileError("top_p must be in (0, 1]")
    if merged["access_list_scope"] not in ACCESS_LIST_SCOPES:
        raise EffortProfileError("access_list_scope must be none, role, or workflow")
    if merged["unsupported_provider_fallback"] not in UNSUPPORTED_FALLBACKS:
        raise EffortProfileError("unsupported_provider_fallback must be abstain, omit, or error")
    if merged["max_calls"] < 1 or merged["max_workflow_steps"] < 1:
        raise EffortProfileError("max_calls and max_workflow_steps must be at least 1")
    version = merged.get("profile_version")
    if version != PROFILE_VERSION:
        raise EffortProfileError(f"unsupported profile_version {version!r}")
    return ReasoningEffortProfile(
        profile_version=PROFILE_VERSION,
        reasoning_effort=str(effort),
        max_output_tokens=int(merged["max_output_tokens"]),
        max_calls=int(merged["max_calls"]),
        max_workflow_steps=int(merged["max_workflow_steps"]),
        max_recursion_depth=int(merged["max_recursion_depth"]),
        max_worker_fan_out=int(merged["max_worker_fan_out"]),
        access_list_scope=str(merged["access_list_scope"]),
        deadline_ms=int(merged["deadline_ms"]),
        cost_token_budget=int(merged["cost_token_budget"]),
        temperature=float(merged["temperature"]),
        top_p=float(merged["top_p"]),
        seed=merged["seed"],
        unsupported_provider_fallback=str(merged["unsupported_provider_fallback"]),
    )


def default_role_effort_catalog() -> dict[str, ReasoningEffortProfile]:
    """Return the issue #568 role catalog. This is evidence, not a production default.

    Thinker, planner, verifier, and judge use high effort. Worker and synthesizer
    use medium effort under the same call/depth/token budget. Buyer next action:
    run ``run_equal_budget_ablation`` before asking to install this catalog as
    the live ``OrchestrationPolicy``.
    """
    shared = {
        "max_output_tokens": 256,
        "max_calls": 1,
        "max_workflow_steps": 4,
        "max_recursion_depth": 1,
        "max_worker_fan_out": 1,
        "cost_token_budget": 1024,
        "temperature": 0.2,
        "top_p": 1.0,
        "seed": 7,
    }
    high = parse_reasoning_effort_profile({**shared, "reasoning_effort": "high"})
    medium = parse_reasoning_effort_profile({**shared, "reasoning_effort": "medium"})
    return {
        "thinker": high,
        "worker": medium,
        "verifier": high,
        "synthesizer": medium,
        "planner": high,
        "judge": high,
    }


def snapshot_role_effort_catalog(
    catalog: Mapping[str, ReasoningEffortProfile],
) -> EffortCatalogSnapshot:
    """Hash a role catalog so sync, stream, batch, route, and conduct can replay it."""
    if set(catalog) != set(WORKFLOW_ROLES):
        raise EffortProfileError(
            f"catalog must bind exactly {list(WORKFLOW_ROLES)}, got {sorted(catalog)}"
        )
    role_profiles: dict[str, dict[str, Any]] = {}
    for role in WORKFLOW_ROLES:
        profile = catalog[role]
        if not isinstance(profile, ReasoningEffortProfile):
            raise EffortProfileError(f"{role} must be a ReasoningEffortProfile")
        role_profiles[role] = parse_reasoning_effort_profile(profile.as_dict()).as_dict()
    canonical = json.dumps(
        {"profile_version": PROFILE_VERSION, "role_profiles": role_profiles},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return EffortCatalogSnapshot(
        profile_version=PROFILE_VERSION,
        snapshot_hash=digest,
        role_profiles=role_profiles,
    )


def _shrinkage_weight(
    reasoning_effort: str,
    extra_workflow_steps: float,
    extra_recursion_depth: float,
    access_list_scope: str,
) -> float:
    """Return the unused-information weight. Temperature never enters."""
    rank = _EFFORT_RANK[reasoning_effort]
    access = _ACCESS_RANK[access_list_scope]
    return 1.0 / (
        1.0
        + rank
        + 0.5 * extra_workflow_steps
        + 0.25 * extra_recursion_depth
        + 0.5 * access
    )


def _estimated_tokens_used(
    reasoning_effort: str,
    extra_workflow_steps: int,
    extra_recursion_depth: int,
    budget_tokens: int,
) -> int:
    """Return tokens consumed under a shared cap. Exceeding the cap fails closed."""
    rank = _EFFORT_RANK[reasoning_effort]
    used = 128 + 64 * rank + 48 * extra_workflow_steps + 32 * extra_recursion_depth
    if used > budget_tokens:
        raise EffortProfileError("estimated token use exceeds equal-budget cap")
    return used


def estimate_theta(
    true_theta: Iterable[float],
    *,
    reasoning_effort: str,
    extra_workflow_steps: int,
    temperature: float,
    extra_recursion_depth: int = 0,
    access_list_scope: str = "role",
) -> ThetaEstimate:
    """Return θ̂ and RMSE against known true parameters.

    ``θ̂_i = (1 − λ) θ_i`` where λ shrinks as effort, Conductor steps,
    recursion depth, and access-list scope increase. Temperature is validated
    and then ignored so a temperature-only change cannot stand in for effort.
    Buyer next action: assert RMSE uses ``θ̂ − θ``, not a rank constant.
    """
    theta: list[float] = []
    for value in true_theta:
        _reject_non_finite_number(value, "true_theta")
        theta.append(float(value))
    if not theta:
        raise EffortProfileError("true_theta must contain at least one finite value")
    if reasoning_effort not in _EFFORT_RANK:
        raise EffortProfileError(f"unknown reasoning_effort {reasoning_effort!r}")
    if access_list_scope not in _ACCESS_RANK:
        raise EffortProfileError("access_list_scope must be none, role, or workflow")
    _reject_non_finite_number(extra_workflow_steps, "extra_workflow_steps")
    _reject_non_finite_number(extra_recursion_depth, "extra_recursion_depth")
    _reject_non_finite_number(temperature, "temperature")
    if extra_workflow_steps < 0 or extra_recursion_depth < 0:
        raise EffortProfileError("workflow steps and recursion depth must be non-negative")
    shrink = _shrinkage_weight(
        reasoning_effort,
        float(extra_workflow_steps),
        float(extra_recursion_depth),
        access_list_scope,
    )
    estimated = tuple((1.0 - shrink) * value for value in theta)
    residuals = [(hat - value) ** 2 for hat, value in zip(estimated, theta)]
    rmse = math.sqrt(sum(residuals) / len(residuals))
    return ThetaEstimate(estimated_theta=estimated, rmse=rmse)


def estimate_theta_rmse(
    true_theta: Iterable[float],
    *,
    reasoning_effort: str,
    extra_workflow_steps: int,
    temperature: float,
    extra_recursion_depth: int = 0,
    access_list_scope: str = "role",
) -> float:
    """Return RMSE of a deterministic θ estimator against known true parameters.

    Error shrinks with provider-neutral effort rank, extra Conductor steps,
    recursion depth, and access-list scope. Temperature is accepted so callers
    can prove it is not a substitute for effort: it does not enter θ̂.
    Buyer next action: treat a lower RMSE from ``high`` effort as evidence,
    and a temperature-only change as non-evidence.
    """
    return estimate_theta(
        true_theta,
        reasoning_effort=reasoning_effort,
        extra_workflow_steps=extra_workflow_steps,
        extra_recursion_depth=extra_recursion_depth,
        access_list_scope=access_list_scope,
        temperature=temperature,
    ).rmse


def _ablation_arm(
    theta: tuple[float, ...],
    *,
    mode: str,
    reasoning_effort: str,
    extra_workflow_steps: int,
    extra_recursion_depth: int,
    access_list_scope: str,
    temperature: float,
    budget_tokens: int,
) -> dict[str, Any]:
    """Build one equal-budget arm with θ̂, RMSE, and measured token use."""
    estimate = estimate_theta(
        theta,
        reasoning_effort=reasoning_effort,
        extra_workflow_steps=extra_workflow_steps,
        extra_recursion_depth=extra_recursion_depth,
        access_list_scope=access_list_scope,
        temperature=temperature,
    )
    return {
        "mode": mode,
        "rmse": estimate.rmse,
        "estimated_theta": list(estimate.estimated_theta),
        "budget_tokens": budget_tokens,
        "estimated_tokens_used": _estimated_tokens_used(
            reasoning_effort,
            extra_workflow_steps,
            extra_recursion_depth,
            budget_tokens,
        ),
        "reasoning_effort": reasoning_effort,
        "access_list_scope": access_list_scope,
    }


def run_equal_budget_ablation(true_theta: Iterable[float]) -> dict[str, Any]:
    """Compare route, conduct, and one-factor variants under one token budget.

    Records estimated RMSE, θ̂, mode, and budget. Does not persist private
    chain-of-thought. Buyer next action: read ``measurement_status`` and
    ``production_default_change_allowed`` before changing live defaults.
    """
    theta = tuple(float(value) for value in true_theta)
    budget_tokens = 1024
    baseline = _ablation_arm(
        theta,
        mode="route",
        reasoning_effort="medium",
        extra_workflow_steps=0,
        extra_recursion_depth=0,
        access_list_scope="role",
        temperature=0.2,
        budget_tokens=budget_tokens,
    )
    role_differentiated = _ablation_arm(
        theta,
        mode="conduct",
        reasoning_effort="high",
        extra_workflow_steps=3,
        extra_recursion_depth=0,
        access_list_scope="role",
        temperature=0.2,
        budget_tokens=budget_tokens,
    )
    return {
        "single_model_baseline": baseline,
        "role_differentiated": role_differentiated,
        "one_factor_ablations": {
            "reasoning_effort": {
                "medium": estimate_theta_rmse(
                    theta, reasoning_effort="medium", extra_workflow_steps=0, temperature=0.2
                ),
                "high": estimate_theta_rmse(
                    theta, reasoning_effort="high", extra_workflow_steps=0, temperature=0.2
                ),
            },
            "temperature": {
                "0.2": estimate_theta_rmse(
                    theta, reasoning_effort="medium", extra_workflow_steps=0, temperature=0.2
                ),
                "1.0": estimate_theta_rmse(
                    theta, reasoning_effort="medium", extra_workflow_steps=0, temperature=1.0
                ),
            },
            "recursion_depth": {
                "1": estimate_theta_rmse(
                    theta,
                    reasoning_effort="medium",
                    extra_workflow_steps=0,
                    extra_recursion_depth=0,
                    temperature=0.2,
                ),
                "2": estimate_theta_rmse(
                    theta,
                    reasoning_effort="medium",
                    extra_workflow_steps=0,
                    extra_recursion_depth=1,
                    temperature=0.2,
                ),
            },
            "workflow_steps": {
                "1": estimate_theta_rmse(
                    theta, reasoning_effort="medium", extra_workflow_steps=0, temperature=0.2
                ),
                "4": estimate_theta_rmse(
                    theta, reasoning_effort="medium", extra_workflow_steps=3, temperature=0.2
                ),
            },
            "access_list_scope": {
                "role": estimate_theta_rmse(
                    theta,
                    reasoning_effort="high",
                    extra_workflow_steps=3,
                    access_list_scope="role",
                    temperature=0.2,
                ),
                "workflow": estimate_theta_rmse(
                    theta,
                    reasoning_effort="high",
                    extra_workflow_steps=3,
                    access_list_scope="workflow",
                    temperature=0.2,
                ),
            },
        },
        "route_versus_conduct": {
            "route": {"rmse": baseline["rmse"], "mode": "route"},
            "conduct": {"rmse": role_differentiated["rmse"], "mode": "conduct"},
        },
        "measurement_status": "estimated",
        "usage_source": "synthetic_true_theta",
        "robustness_passed": False,
    }


def production_default_change_allowed(report: Mapping[str, Any]) -> bool:
    """Return whether a live default change is allowed from this ablation.

    Buyer next action: keep current route/conduct defaults when this is false.
    A later slice may unlock only after RMSE improvement, a non-estimated
    measurement, and robustness all clear the predeclared gate.
    """
    try:
        baseline = float(report["single_model_baseline"]["rmse"])
        candidate = float(report["role_differentiated"]["rmse"])
    except (KeyError, TypeError, ValueError):
        return False
    if not math.isfinite(baseline) or not math.isfinite(candidate) or baseline <= 0:
        return False
    if report.get("measurement_status") == "estimated":
        return False
    if report.get("robustness_passed") is not True:
        return False
    improvement = (baseline - candidate) / baseline
    return improvement >= PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD
