"""Classify chat transport compatibility and ordinary agent-role eligibility.

Provider catalogs mix endpoint-only models with models served through an
OpenAI-compatible chat transport. Transport compatibility is not the same as
fitness for an ordinary thinker, worker, verifier, or synthesizer role: audio
and policy-classification models can use chat transport, while embedding,
reranking, transcription, moderation-endpoint, image-generation, realtime, and
speech-only models cannot.
"""

from __future__ import annotations

from collections.abc import Iterable
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
_TRANSPORT_INCOMPATIBLE_PREFIXES = (
    "embed",
    "moderat",
    "rerank",
    "transcrib",
)


def is_chat_compatible_model_id(model_id: str) -> bool:
    """Return whether an identifier can use the ordinary chat transport.

    The classifier rejects only identifiers that clearly advertise an endpoint
    family incompatible with chat messages. Audio-capable and safety-classifier
    models remain transport-compatible because providers serve some of them over
    ``/chat/completions``.
    """
    tokens = _model_tokens(model_id)
    return _is_transport_compatible_tokens(tokens)


def _is_transport_compatible_tokens(tokens: tuple[str, ...]) -> bool:
    """Judge transport compatibility from already-normalized model tokens."""
    if not tokens:
        return False
    for token in tokens:
        if token in _TRANSPORT_INCOMPATIBLE_EXACT_TOKENS:
            return False
        if token.startswith(_TRANSPORT_INCOMPATIBLE_PREFIXES):
            return False
    return True


def _model_tokens(model_id: str) -> tuple[str, ...]:
    """Normalize one provider-prefixed model identifier into lowercase tokens."""
    if not isinstance(model_id, str):
        return ()
    return tuple(_MODEL_TOKEN_RE.findall(model_id.casefold()))


def is_general_chat_agent_model_id(model_id: str) -> bool:
    """Return whether a chat model may enter ordinary orchestration roles.

    Explicit guard and safety models can use chat transport but are specialized
    policy classifiers, not general answer synthesizers. This negative role gate
    does not infer reasoning, coding, vision, or verification capabilities.
    """
    tokens = _model_tokens(model_id)
    if not tokens or not _is_transport_compatible_tokens(tokens):
        return False
    return not any(
        token == "safety"
        or token == "guard"
        or token == "shieldgemma"
        or token.startswith("nemoguard")
        for token in tokens
    )


def requires_non_text_input(input_modalities: Iterable[str]) -> bool:
    """Return whether declared input-modality evidence includes non-text input.

    A model whose provider/catalog architecture evidence declares an input
    modality other than ``"text"`` (e.g. ``image``, ``audio``, ``video``) is a
    specialized multimodal deployment: a caller cannot use it for an arbitrary
    request without knowing in advance that the request must carry that extra
    modality. Absence of modality evidence is not evidence of a multimodal
    requirement, so an empty ``input_modalities`` iterable never triggers this.

    Shared by ``model_discovery._requires_non_text_input`` (reading
    ``DiscoveredModel.input_modalities`` directly) and
    ``orchestrator.TaskOrchestrator._agent_requires_non_text_input`` (reading
    an agent's persisted ``input:<modality>`` tags, with the ``input:`` prefix
    already stripped by the caller) so the "what counts as non-text" reading
    lives in exactly one place -- the two representations of the same catalog
    evidence can never drift on this question independently of each other.
    """
    return any(
        modality.strip().casefold() != "text"
        for modality in input_modalities
        if isinstance(modality, str) and modality.strip()
    )


def is_general_chat_candidate(
    model_id: str,
    *,
    capabilities: Iterable[str] = (),
    output_modalities: Iterable[str] = (),
    supports_parallel_tool_calls: bool | None = None,
) -> bool:
    """Apply explicit catalog evidence before falling back to the model name.

    A generic model identifier cannot identify a media-only endpoint. When a
    provider supplies capability or output-modality metadata, that metadata is
    therefore authoritative; absent metadata keeps the legacy name heuristic.

    General chat agents may receive multi-tool-call requests, so a model whose
    catalog or probe evidence shows it only supports one tool call at a time is
    not a general chat candidate. ``None`` means no evidence either way and
    keeps the existing eligibility decision.
    """
    if supports_parallel_tool_calls is False:
        return False
    outputs = {
        value.strip().casefold()
        for value in output_modalities
        if isinstance(value, str) and value.strip()
    }
    if outputs:
        return "text" in outputs and is_general_chat_agent_model_id(model_id)
    declared_capabilities = {
        value.strip().casefold()
        for value in capabilities
        if isinstance(value, str) and value.strip()
    }
    if declared_capabilities:
        return "chat" in declared_capabilities and is_general_chat_agent_model_id(model_id)
    return is_general_chat_agent_model_id(model_id)
