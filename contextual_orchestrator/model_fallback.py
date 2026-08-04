"""Public API for deterministic, transport-neutral model fallbacks.

The policy validates trusted candidate metadata and returns a stable plan with
all eligible free candidates before every paid fallback. It never performs a
network request and never stores credential values, so existing workflow
transports and reviewer identities remain under the caller's control.
"""

from __future__ import annotations

from ._fallback_cli import main
from ._fallback_manifest import load_fallback_manifest
from ._fallback_plan import build_fallback_plan
from ._fallback_types import (
    CandidateValidationError,
    CostTier,
    FallbackCandidate,
    FallbackContext,
    FallbackManifestError,
    FallbackPlan,
    NoEligibleCandidateError,
    SkippedCandidate,
)

__all__ = [
    "CandidateValidationError",
    "CostTier",
    "FallbackCandidate",
    "FallbackContext",
    "FallbackManifestError",
    "FallbackPlan",
    "NoEligibleCandidateError",
    "SkippedCandidate",
    "build_fallback_plan",
    "load_fallback_manifest",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
