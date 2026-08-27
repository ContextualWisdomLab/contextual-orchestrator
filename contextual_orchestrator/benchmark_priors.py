"""Static prior information injected from Chatbot Arena and Artificial Analysis."""
from typing import Mapping, Tuple

# Maps standard model base names or IDs to (alpha_prior, beta_prior)
# A neutral prior is (1.0, 0.0) where stability=1.0.
# A higher alpha with some beta represents a stronger evidence base.
# For example, alpha=10.0, beta=1.0 gives a 90% prior success rate with strength 11.
_BASELINE_PRIORS: Mapping[str, Tuple[float, float]] = {
    "gpt-4o": (9.0, 1.0),
    "gpt-4-turbo": (8.5, 1.5),
    "claude-3-5-sonnet": (9.5, 0.5),
    "claude-3-opus": (8.8, 1.2),
    "claude-3-sonnet": (8.0, 2.0),
    "claude-3-haiku": (7.5, 2.5),
    "gemini-1.5-pro": (8.5, 1.5),
    "gemini-1.5-flash": (8.0, 2.0),
    "llama-3-70b-instruct": (8.2, 1.8),
    "llama-3-8b-instruct": (7.0, 3.0),
    "mixtral-8x7b-instruct": (7.2, 2.8),
}

def resolve_quality_prior(member_id: str) -> Tuple[float, float]:
    """Resolve prior information (alpha, beta) for a given model identifier.
    
    This prior is grounded in LMSYS Chatbot Arena Elo and Artificial Analysis
    Quality Index. Missing models fall back to the uninformative baseline (1.0, 0.0).
    """
    for key, prior in _BASELINE_PRIORS.items():
        if key in member_id.lower():
            return prior
    return (1.0, 0.0)
