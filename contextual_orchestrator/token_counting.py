"""Authoritative raw-text token counting for accounting boundaries.

Provider-reported chat usage is authoritative. Local counters handle raw text
only; they never reconstruct provider chat framing, tool schemas, or
multimodal serialization. Exact full model identifiers select the packaged
Rust tokenizer. Unknown identifiers and missing native code are explicitly
unavailable rather than estimated.
"""

from __future__ import annotations

import importlib
import operator
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Protocol

#: Sentinel ``CountingProvenance.framing_source`` value for a registry entry
#: whose structure is recorded but whose official source text could not be
#: read (e.g. no network access at authoring time). ``describe_messages``
#: treats this exactly like a missing entry: it fails closed rather than
#: guessing framing constants.
FRAMING_SOURCE_UNVERIFIED = "unverified"

_CL100K_EMBEDDING_MODELS = frozenset(
    {
        "text-embedding-ada-002",
        "text-embedding-3-small",
        "text-embedding-3-large",
    }
)
_CL100K_MODELS = _CL100K_EMBEDDING_MODELS | frozenset(
    {
        "gpt-4",
        "gpt-3.5-turbo",
        "gpt-3.5",
        "gpt-35-turbo",
        "davinci-002",
        "babbage-002",
    }
)
_O200K_MODELS = frozenset({"o1", "o3", "o4-mini", "gpt-5", "gpt-4.1", "gpt-4o"})


@dataclass(frozen=True)
class CountingProvenance:
    """One provider/model family's citable, scoped chat-framing contract.

    Every field must trace to an official, citable document. ``framing_scope``
    is exactly the set of model identifiers the source states the framing
    constants apply to -- never a broader family name the source itself hedges
    as an estimate. ``supported_fields`` are the per-message keys the framing
    algorithm accounts for; any other key (including tool calls or non-text
    content parts) makes a count unreconstructible. ``unsupported_fields`` is
    documentation of the known request-level and per-message shapes this
    contract explicitly does not cover (tools, multimodal parts, prior
    responses/conversations, instructions) -- callers surface these as named,
    explicit unavailability rather than silently ignoring them.
    """

    tokenizer: str
    framing_source: str
    framing_source_url: str
    framing_read_date: str
    framing_scope: frozenset[str]
    supported_fields: frozenset[str]
    unsupported_fields: frozenset[str]
    tokens_per_message: int
    tokens_per_name: int
    reply_priming_tokens: int


@dataclass(frozen=True)
class MessageCountResult:
    """An exact chat-message token count bound to its counting provenance."""

    token_count: int
    model: str
    tokenizer: str
    framing_source: str
    framing_source_url: str
    count_source: str = "provenance_exact"


# OpenAI Cookbook, "How to count tokens with tiktoken":
# https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken
# (redirects to https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken)
# Read 2026-09-14. The document's ``num_tokens_from_messages`` function scopes
# ``tokens_per_message = 3`` / ``tokens_per_name = 1`` to exactly this set of
# dated model identifiers via an explicit membership check, and adds
# ``+= 3`` once per response for reply priming. The same document also offers
# family-prefix fallbacks (e.g. bare "gpt-4o") with an explicit hedge --
# "Consider the counts from the function below an estimate, not a timeless
# guarantee" -- so those broader aliases are deliberately excluded from
# ``framing_scope``: only the exact dated identifiers the source itself
# treats as authoritative are registered here.
_OPENAI_COOKBOOK_SOURCE = "OpenAI Cookbook: How to count tokens with tiktoken"
_OPENAI_COOKBOOK_URL = (
    "https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken"
)
_OPENAI_COOKBOOK_READ_DATE = "2026-09-14"
_OPENAI_COOKBOOK_SCOPE = frozenset(
    {
        "gpt-3.5-turbo-0125",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        "gpt-4o-mini-2024-07-18",
        "gpt-4o-2024-08-06",
    }
)
# Fields the cookbook's framing loop actually walks over per message
# (``role``, ``content``, ``name``); anything else (tool calls, function
# calls, non-text content parts) is not accounted for by this formula.
_OPENAI_COOKBOOK_SUPPORTED_FIELDS = frozenset({"role", "content", "name"})
# Known request/message shapes this contract does not cover. Documentation
# only -- ``describe_messages`` fails closed on any field outside
# ``supported_fields``, not only these named ones.
_OPENAI_COOKBOOK_UNSUPPORTED_FIELDS = frozenset(
    {
        "tools",
        "tool_choice",
        "tool_calls",
        "function_call",
        "content_parts",
        "images",
        "audio",
        "instructions",
        "response_id",
        "previous_response_id",
        "conversation_id",
    }
)
_CL100K_COOKBOOK_MODELS = frozenset(
    {
        "gpt-3.5-turbo-0125",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
    }
)
_O200K_COOKBOOK_MODELS = frozenset({"gpt-4o-mini-2024-07-18", "gpt-4o-2024-08-06"})


def _openai_cookbook_entry(tokenizer: str) -> CountingProvenance:
    """Build one verified OpenAI Cookbook registry row for ``tokenizer``."""
    return CountingProvenance(
        tokenizer=tokenizer,
        framing_source=_OPENAI_COOKBOOK_SOURCE,
        framing_source_url=_OPENAI_COOKBOOK_URL,
        framing_read_date=_OPENAI_COOKBOOK_READ_DATE,
        framing_scope=_OPENAI_COOKBOOK_SCOPE,
        supported_fields=_OPENAI_COOKBOOK_SUPPORTED_FIELDS,
        unsupported_fields=_OPENAI_COOKBOOK_UNSUPPORTED_FIELDS,
        tokens_per_message=3,
        tokens_per_name=1,
        reply_priming_tokens=3,
    )


#: Counting-provenance registry keyed by exact model identifier. Only
#: identifiers with an official, citable, currently-verified source are
#: registered; every other identifier (including broader family aliases the
#: source itself hedges as inexact) is deliberately absent so counting fails
#: closed for it.
COUNTING_PROVENANCE_REGISTRY: dict[str, CountingProvenance] = {
    **{model: _openai_cookbook_entry("cl100k") for model in _CL100K_COOKBOOK_MODELS},
    **{model: _openai_cookbook_entry("o200k") for model in _O200K_COOKBOOK_MODELS},
}


class TokenCountingStrategy(Protocol):
    """Contract for an authoritative raw-text token counter."""

    def count_text(self, text: str, model: str) -> int:
        """Return the exact token count for ``text`` under ``model``."""
        ...


class TokenCountUnavailable(RuntimeError):
    """An authoritative tokenizer or provider count is unavailable."""


def _validated_count(value: Any) -> int:
    """Normalize a tokenizer count and reject invalid numeric evidence."""
    if isinstance(value, bool):
        raise TokenCountUnavailable("the tokenizer returned an invalid count")
    try:
        count = operator.index(value)
    except TypeError as exc:
        raise TokenCountUnavailable("the tokenizer returned an invalid count") from exc
    if count < 0:
        raise TokenCountUnavailable("the tokenizer returned an invalid count")
    return count


class PgTiktokenAdapter:
    """Adapter delegating raw-text counts to ``pg_llm_batch.TokenCounter``."""

    def __init__(self, pg_counter: Any) -> None:
        self._counter = pg_counter

    def count_text(self, text: str, model: str = "") -> int:
        """Count raw text through the configured PostgreSQL tokenizer."""
        try:
            return _validated_count(self._counter.count_tokens(text, model))
        except TokenCountUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - external tokenizer boundary.
            raise TokenCountUnavailable("the PostgreSQL tokenizer is unavailable") from exc

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Reject chat prompts whose provider framing is unreconstructible."""
        raise TokenCountUnavailable("provider chat framing is unavailable")


class NativeExactTokenCounter:
    """Dispatch exact raw-text counts for explicitly mapped model identifiers."""

    def __init__(self, native_module: Any) -> None:
        self._native_module = native_module

    def count_text(self, text: str, model: str = "") -> int:
        """Count raw text for a declared model or fail closed."""
        if model in _CL100K_MODELS:
            function_name = "count_cl100k"
        elif model in _O200K_MODELS:
            function_name = "count_o200k"
        else:
            raise TokenCountUnavailable(
                f"no authoritative tokenizer is declared for {model!r}"
            )
        try:
            function = getattr(self._native_module, function_name)
            return _validated_count(function(text))
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native tokenizer is unavailable") from exc

    def describe_messages(
        self,
        messages: list[Mapping[str, Any]],
        model: str = "",
        *,
        tools: Any = None,
    ) -> MessageCountResult:
        """Return a provenance-bound exact chat count, or fail closed by named field.

        Succeeds only when ``model`` has a verified ``COUNTING_PROVENANCE_REGISTRY``
        entry and every message uses only that entry's ``supported_fields`` with
        plain-string values. Any tool payload, non-text content part, or other
        unsupported field raises :class:`TokenCountUnavailable` naming the field
        rather than silently under-counting it.
        """
        entry = COUNTING_PROVENANCE_REGISTRY.get(model)
        if entry is None or entry.framing_source == FRAMING_SOURCE_UNVERIFIED:
            raise TokenCountUnavailable(
                f"provider chat framing is unavailable: {model!r} is outside "
                "the verified counting-provenance scope"
            )
        if tools:
            raise TokenCountUnavailable(
                "provider chat framing is unavailable: field 'tools' is unsupported"
            )
        if not isinstance(messages, list):
            raise TokenCountUnavailable(
                "provider chat framing is unavailable: messages must be a list"
            )
        total = 0
        for message in messages:
            if not isinstance(message, Mapping):
                raise TokenCountUnavailable(
                    "provider chat framing is unavailable: message is not a mapping"
                )
            total += entry.tokens_per_message
            for key, value in message.items():
                if key not in entry.supported_fields:
                    raise TokenCountUnavailable(
                        f"provider chat framing is unavailable: field {key!r} is unsupported"
                    )
                if not isinstance(value, str):
                    raise TokenCountUnavailable(
                        f"provider chat framing is unavailable: field {key!r} is not plain text"
                    )
                total += self._encode_length(entry.tokenizer, value)
                if key == "name":
                    total += entry.tokens_per_name
        total += entry.reply_priming_tokens
        return MessageCountResult(
            token_count=total,
            model=model,
            tokenizer=entry.tokenizer,
            framing_source=entry.framing_source,
            framing_source_url=entry.framing_source_url,
        )

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Return the exact provenance-bound chat token count, or fail closed."""
        return self.describe_messages(messages, model).token_count

    def _encode_length(self, tokenizer: str, text: str) -> int:
        """Encode ``text`` with the declared native tokenizer function."""
        if tokenizer == "cl100k":
            function_name = "count_cl100k"
        elif tokenizer == "o200k":
            function_name = "count_o200k"
        else:  # pragma: no cover - registry entries only declare known tokenizers
            raise TokenCountUnavailable(f"no native encoder is declared for {tokenizer!r}")
        try:
            function = getattr(self._native_module, function_name)
            return _validated_count(function(text))
        except TokenCountUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native tokenizer is unavailable") from exc

    def pack_text(self, text: str, model: str, max_tokens: int) -> list[tuple[str, int]]:
        """Split one declared cl100k input at exact native token boundaries."""
        if model not in _CL100K_EMBEDDING_MODELS:
            raise TokenCountUnavailable(f"no authoritative tokenizer is declared for {model!r}")
        try:
            parts, _shards = self._native_module.pack_cl100k(
                [text], max_tokens, 1, max_tokens
            )
            return [(part.text, _validated_count(part.token_count)) for part in parts]
        except Exception as exc:  # noqa: BLE001 - optional native boundary.
            raise TokenCountUnavailable("the native cl100k packer is unavailable") from exc


# Compatibility name retained for embedding callers; behavior remains exact.
NativeCl100kTokenCounter = NativeExactTokenCounter


class UnavailableTokenCounter:
    """Represent absence of an authoritative tokenizer."""

    def count_text(self, text: str, model: str = "") -> int:
        """Fail closed instead of fabricating a raw-text token count."""
        raise TokenCountUnavailable(f"no authoritative tokenizer is available for {model!r}")

    def count_messages(self, messages: list[dict], model: str = "") -> int:
        """Fail closed instead of fabricating a chat prompt count."""
        raise TokenCountUnavailable("provider chat framing is unavailable")


UnavailableEmbeddingTokenCounter = UnavailableTokenCounter


def _native_token_counter() -> NativeExactTokenCounter | None:
    """Load the optional extension without making startup depend on it."""
    try:
        module = importlib.import_module("contextual_orchestrator._token_packer")
    except Exception:  # noqa: BLE001 - incompatible wheel equals absence.
        return None
    functions = ("count_cl100k", "count_o200k", "pack_cl100k")
    if not all(callable(getattr(module, name, None)) for name in functions):
        return None
    return NativeExactTokenCounter(module)


def _build_counter(postgres_dsn: Optional[str], config: Any) -> Any:
    """Build the configured authoritative counter or unavailable seam."""
    if postgres_dsn:
        try:  # pragma: no cover - needs Postgres + pg_tiktoken extension
            from pg_llm_batch import TokenCounter as PgTokenCounter  # type: ignore

            return PgTiktokenAdapter(PgTokenCounter(postgres_dsn, config=config))
        except Exception:  # pragma: no cover - optional authoritative boundary
            pass
    return _native_token_counter() or UnavailableTokenCounter()


def build_embedding_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> PgTiktokenAdapter | NativeExactTokenCounter | UnavailableTokenCounter:
    """Return an authoritative embedding counter or explicit unavailable seam."""
    return _build_counter(postgres_dsn, config)


def build_token_counter(
    postgres_dsn: Optional[str] = None,
    *,
    config: Any = None,
) -> PgTiktokenAdapter | NativeExactTokenCounter | UnavailableTokenCounter:
    """Return an authoritative raw-text counter or explicit unavailable seam."""
    return _build_counter(postgres_dsn, config)


def describe_message_count(
    counter: Any,
    messages: list[Mapping[str, Any]],
    model: str,
    *,
    tools: Any = None,
) -> MessageCountResult:
    """Return ``counter``'s provenance-bound exact chat count, or fail closed.

    The least-invasive seam for callers that want counting provenance
    (``tokenizer``, ``framing_source``, ``count_source``) alongside the
    integer count without depending on a specific counter implementation:
    any counter exposing ``describe_messages`` (currently
    :class:`NativeExactTokenCounter`) is supported; others are explicitly
    unavailable.
    """
    describe = getattr(counter, "describe_messages", None)
    if describe is None:
        raise TokenCountUnavailable("provider chat framing is unavailable")
    return describe(messages, model, tools=tools)
