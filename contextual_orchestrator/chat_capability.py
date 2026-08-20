"""Shared chat-capability classification and runtime fail-closed guards.

Provider model catalogs are heterogeneous: a model identifier may name a chat
model, embedding model, reranker, transcription model, image model, or another
endpoint family. The helpers in this module prevent clearly non-chat model IDs
from crossing a chat-agent boundary even when an incompatible agent was persisted
before discovery filtering was introduced.
"""

from __future__ import annotations

import re

_MODEL_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NON_CHAT_EXACT_TOKENS = frozenset(
    {
        "audio",
        "bge",
        "e5",
        "embed",
        "embedding",
        "embeddings",
        "guard",
        "gte",
        "image",
        "images",
        "moderation",
        "realtime",
        "rerank",
        "reranker",
        "safety",
        "sora",
        "speech",
        "transcribe",
        "transcription",
        "tts",
        "whisper",
    }
)
_NON_CHAT_TOKEN_PREFIXES = (
    "embed",
    "moderat",
    "rerank",
    "transcrib",
)


def is_chat_compatible_model_id(model_id: str) -> bool:
    """Return whether a model identifier is eligible for a chat-agent pool.

    The classifier intentionally rejects only identifiers that clearly advertise
    a non-chat endpoint family. Unknown identifiers remain eligible until an
    authenticated capability registry can prove more specific endpoint support.
    """
    if type(model_id) is not str:
        return False
    tokens = tuple(_MODEL_TOKEN_RE.findall(model_id.casefold()))
    if not tokens:
        return False
    for token in tokens:
        if token in _NON_CHAT_EXACT_TOKENS:
            return False
        if token.startswith(_NON_CHAT_TOKEN_PREFIXES):
            return False
    return True
