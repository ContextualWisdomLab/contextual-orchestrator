"""Classify model identifiers that cannot serve ordinary chat-agent roles.

Provider catalogs mix chat, embedding, reranking, transcription, moderation,
image, realtime, and speech-only models. This negative classifier rejects only
families that clearly advertise a non-chat endpoint; it never infers reasoning,
coding, vision, or verification support from a model name.
"""

from __future__ import annotations

import re

_MODEL_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TRANSPORT_INCOMPATIBLE_EXACT_TOKENS = frozenset(
    {
        "bge",
        "clip",
        "dall",
        "e5",
        "embed",
        "embedding",
        "embeddings",
        "gte",
        "image",
        "images",
        "moderation",
        "realtime",
        "rerank",
        "reranker",
        "siglip",
        "sora",
        "speech",
        "transcribe",
        "transcription",
        "tts",
        "whisper",
    }
)
_TRANSPORT_INCOMPATIBLE_PREFIXES = ("embed", "moderat", "rerank", "transcrib")


def _model_tokens(model_id: str) -> tuple[str, ...]:
    """Normalize one provider model identifier into lowercase tokens."""
    if not isinstance(model_id, str):
        return ()
    return tuple(_MODEL_TOKEN_RE.findall(model_id.casefold()))


def _is_transport_compatible_tokens(tokens: tuple[str, ...]) -> bool:
    """Reject already-tokenized identifiers for endpoint-only model families."""
    if not tokens:
        return False
    return not any(
        token in _TRANSPORT_INCOMPATIBLE_EXACT_TOKENS
        or token.startswith(_TRANSPORT_INCOMPATIBLE_PREFIXES)
        for token in tokens
    )


def is_chat_compatible_model_id(model_id: str) -> bool:
    """Return whether an identifier can use the ordinary chat transport."""
    return _is_transport_compatible_tokens(_model_tokens(model_id))


def is_general_chat_agent_model_id(model_id: str) -> bool:
    """Return whether a chat model may enter ordinary review-agent roles."""
    tokens = _model_tokens(model_id)
    if not _is_transport_compatible_tokens(tokens):
        return False
    return not any(
        token == "safety"
        or token == "guard"
        or token == "shieldgemma"
        or token.startswith("nemoguard")
        for token in tokens
    )
