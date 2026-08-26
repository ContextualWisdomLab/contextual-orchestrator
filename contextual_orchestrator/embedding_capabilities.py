"""Authority-backed, model-specific embedding request capabilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModelCapability:
    """Provider-published request limits for one exact embedding model."""

    provider_name: str
    model_name: str
    max_inputs: int
    max_tokens_per_input: int
    max_total_tokens: int
    tokenizer: str
    authority_url: str


OPENAI_TEXT_EMBEDDING_3_LARGE = EmbeddingModelCapability(
    provider_name="openai",
    model_name="text-embedding-3-large",
    max_inputs=2048,
    max_tokens_per_input=8192,
    max_total_tokens=300_000,
    tokenizer="cl100k_base",
    authority_url=(
        "https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create"
    ),
)


def embedding_model_capability(
    provider_name: str, model_name: str
) -> EmbeddingModelCapability | None:
    """Return a capability only for an exact authority-backed provider/model pair."""
    if (
        provider_name.casefold() == OPENAI_TEXT_EMBEDDING_3_LARGE.provider_name
        and model_name == OPENAI_TEXT_EMBEDDING_3_LARGE.model_name
    ):
        return OPENAI_TEXT_EMBEDDING_3_LARGE
    return None
