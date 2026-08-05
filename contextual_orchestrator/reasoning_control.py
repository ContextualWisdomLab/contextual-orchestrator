"""Provider-neutral, cost-aware control of model reasoning effort.

The public facade combines explicit model capability profiles, role-sensitive
compute selection, provider payload projection, bounded verifier escalation,
and measured reasoning-token evidence without retaining private model traces.
"""

from ._reasoning_payload import (
    _any_complete_path,
    _normalize_endpoint,
    _render_value,
    _rules_for,
    _set_nested_if_absent,
    apply_reasoning_payload,
    extract_reasoning_tokens,
    sum_usage_tokens,
)
from ._reasoning_policy import (
    _nearest_supported,
    ReasoningAblationCell,
    ReasoningDecision,
    ReasoningPolicy,
    adapt_reasoning_decision,
    escalate_reasoning_decision,
    select_reasoning_decision,
)
from ._reasoning_profile import (
    _parse_rules,
    CANONICAL_REASONING_LEVELS,
    PayloadRule,
    ReasoningProfile,
)

__all__ = [
    "CANONICAL_REASONING_LEVELS",
    "PayloadRule",
    "ReasoningAblationCell",
    "ReasoningDecision",
    "ReasoningPolicy",
    "ReasoningProfile",
    "adapt_reasoning_decision",
    "apply_reasoning_payload",
    "escalate_reasoning_decision",
    "extract_reasoning_tokens",
    "select_reasoning_decision",
    "sum_usage_tokens",
]
