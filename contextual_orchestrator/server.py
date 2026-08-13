"""HTTP server exposing chat, admin, governance, and evaluation endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
import urllib.parse
from typing import Any
import uuid

from .admin import ADMIN_HTML, ADMIN_TRANSLATIONS
from .api_contract import OPENAPI_SPEC
from .cost_ledger import ATTRIBUTION_DIMENSIONS, dimension_catalog
from .cost_router import CostRoutingCoordinator
from .batch_routing import BatchRequest
from .orchestrator import (
    BudgetExceededError,
    TaskOrchestrator,
    chat_completion_chunks,
    chat_completion_response,
    text_completion_response,
    redact_value,
    sse_stream_body,
)

# OpenAI request params forwarded verbatim to the provider on passthrough.
OPENAI_PASSTHROUGH_PARAM_KEYS = {
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "n", "stop",
    "seed", "presence_penalty", "frequency_penalty", "logit_bias", "logprobs",
    "top_logprobs", "user", "metadata", "parallel_tool_calls", "reasoning_effort",
    "response_format", "tools", "tool_choice", "functions", "function_call",
    "modalities", "prediction", "store", "service_tier", "stream_options",
}
# Provider features the multi-agent verifier cannot merge -> single-agent passthrough.
PASSTHROUGH_TRIGGER_KEYS = {"response_format", "tools", "tool_choice", "functions", "function_call"}
ALLOWED_CHAT_KEYS = {
    "model", "messages", "orchestration", "orchestration_mode", "mode",
    "include_orchestration_trace", "stream", "attribution", "routing",
} | OPENAI_PASSTHROUGH_PARAM_KEYS
# Responses API body keys (`input` replaces `messages`).
ALLOWED_RESPONSES_KEYS = {
    "model", "input", "instructions", "stream", "metadata", "reasoning",
} | OPENAI_PASSTHROUGH_PARAM_KEYS
ALLOWED_BATCH_KEYS = {"requests", "attribution", "routing", "model"}
ALLOWED_EMBEDDINGS_BATCH_KEYS = {"model", "input", "inputs", "endpoint", "metadata", "attribution"}
ALLOWED_COMPLETIONS_KEYS = {
    "model", "prompt", "stream", "stream_options", "echo", "suffix", "best_of",
    "logprobs", "n", "max_tokens", "temperature", "top_p", "stop", "user", "seed",
    "presence_penalty", "frequency_penalty", "logit_bias", "service_tier",
} | {"attribution", "routing"}
ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant", "tool"}
ALLOWED_MODES = {"auto", "route", "conduct"}
ALLOWED_SIMULATE_KEYS = {"prompt", "mode", "include_orchestration_trace"}
ALLOWED_WORKFLOW_KEYS = {"prompt_text", "run_mode", "include_orchestration_trace"}
ALLOWED_EVALUATION_KEYS = {"prompts", "prompt_text", "run_mode", "include_orchestration_trace"}
ALLOWED_AGENT_PATCH_KEYS = {"status", "priority", "tags", "provider_exclusions"}
ALLOWED_AGENT_CREATE_KEYS = {
    "id",
    "model",
    "base_url",
    "api_key_env",
    "credential_key",
    "tags",
    "priority",
    "disabled",
    "provider_name",
    "provider_exclusions",
}


class RequestError(Exception):
    """HTTP-safe request failure."""

    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass
class SecurityConfig:
    """Runtime safety controls for the stdlib HTTP server."""

    auth_token: str = ""
    admin_token: str = ""
    inference_token: str = ""
    allow_public_bind: bool = False
    expose_trace_by_default: bool = False
    max_body_bytes: int = 64 * 1024
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    max_concurrent_runs: int = 8
    _rate_buckets: dict[str, tuple[int, float]] = field(default_factory=dict, init=False, repr=False)
    _rate_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _run_semaphore: threading.BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (self.admin_token or self.inference_token) and not (self.admin_token and self.inference_token):
            raise ValueError("split token mode requires both admin_token and inference_token")
        self._run_semaphore = threading.BoundedSemaphore(self.max_concurrent_runs)

    def check_bind(self, host: str) -> None:
        """Require explicit opt-in before binding the API to public interfaces."""
        if host in {"0.0.0.0", "::", ""} and not self.allow_public_bind:  # nosec B104 - comparison rejects public bind unless explicitly opted in.
            raise ValueError("public bind requires --allow-public-bind")

    def authorize(self, headers: Any, scope: str, client_address: str) -> None:
        """Validate bearer token for admin or inference scope."""
        if not (self.auth_token or self.admin_token or self.inference_token):
            raise RequestError(401, "unauthorized", "bearer token is required")
        raw = headers.get("authorization", "")
        if not raw.lower().startswith("bearer "):
            raise RequestError(401, "unauthorized", "bearer token is required")
        token = raw.split(" ", 1)[1].strip()
        expected = self.auth_token or (self.admin_token if scope == "admin" else self.inference_token)
        if not expected or not secrets.compare_digest(token, expected):
            raise RequestError(401, "unauthorized", "bearer token is invalid for this scope")

    def check_rate_limit(self, key: str) -> None:
        """Apply a simple per-client fixed-window request budget."""
        now = time.monotonic()
        with self._rate_lock:
            count, reset_at = self._rate_buckets.get(key, (0, now + self.rate_limit_window_seconds))
            if now >= reset_at:
                count, reset_at = 0, now + self.rate_limit_window_seconds
            if count >= self.rate_limit_requests:
                raise RequestError(429, "rate_limit_exceeded", "request rate limit exceeded")
            self._rate_buckets[key] = (count + 1, reset_at)

    def acquire_run_slot(self) -> None:
        """Reserve a run slot, rejecting quickly when the process is saturated."""
        if not self._run_semaphore.acquire(blocking=False):
            raise RequestError(503, "concurrency_limit_exceeded", "too many concurrent orchestration runs")

    def release_run_slot(self) -> None:
        """Release a run slot acquired by acquire_run_slot."""
        self._run_semaphore.release()

    def readiness_profile(self) -> dict[str, Any]:
        """Return a secret-free security profile for sales-readiness evidence."""
        if self.admin_token and self.inference_token:
            auth_mode = "split_token"
        elif self.auth_token:
            auth_mode = "single_token"
        else:
            auth_mode = "auth_not_configured"
        return {
            "auth_mode": auth_mode,
            "allow_public_bind": self.allow_public_bind,
            "expose_trace_by_default": self.expose_trace_by_default,
            "rate_limit_requests": self.rate_limit_requests,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
            "max_concurrent_runs": self.max_concurrent_runs,
        }


def _error_payload(error_code: str, error_message: str, error_detail: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = error_detail or {}
    return {
        "error": {"code": error_code, "message": error_message, "detail": detail},
        "error_code": error_code,
        "error_message": error_message,
        "error_detail": detail,
    }


def _coerce_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RequestError(400, "invalid_json", "request body must be a JSON object")
    return value



def _validate_completion_prompt(prompt: Any) -> list[dict[str, str]]:
    """Legacy Completions ``prompt`` → single user message list.

    Accepts a non-empty string or an array of strings (at most 128 items). OpenAI
    also allows arrays of token IDs (integers); this gateway rejects token-id
    prompts fail-closed with ``invalid_prompt`` so SDKs get a clear migration
    path to string prompts.
    """
    if isinstance(prompt, str):
        if not prompt.strip():
            raise RequestError(400, "invalid_prompt", "prompt must be a non-empty string or array")
        if len(prompt) > 32_000:
            raise RequestError(400, "invalid_prompt", "prompt must be at most 32000 characters")
        return [{"role": "user", "content": prompt}]
    if isinstance(prompt, list):
        if not prompt:
            raise RequestError(400, "invalid_prompt", "prompt must be a non-empty string or array")
        if len(prompt) > 128:
            raise RequestError(
                400,
                "invalid_prompt",
                "prompt array must contain at most 128 items",
            )
        # Token-id form: list of ints, or list of list of ints (batch of token sequences).
        if all(isinstance(item, int) and not isinstance(item, bool) for item in prompt):
            raise RequestError(
                400,
                "invalid_prompt",
                "token-id prompts are not supported; pass a string or array of strings",
            )
        if all(isinstance(item, list) for item in prompt):
            raise RequestError(
                400,
                "invalid_prompt",
                "token-id prompts are not supported; pass a string or array of strings",
            )
        parts: list[str] = []
        for item in prompt:
            if not isinstance(item, str):
                raise RequestError(400, "invalid_prompt", "prompt array items must be strings")
            if not item.strip():
                raise RequestError(
                    400,
                    "invalid_prompt",
                    "prompt array items must be non-empty strings",
                )
            parts.append(item)
        joined = "\n".join(parts)
        if not joined.strip():
            raise RequestError(400, "invalid_prompt", "prompt must be a non-empty string or array")
        if len(joined) > 32_000:
            raise RequestError(400, "invalid_prompt", "prompt must be at most 32000 characters")
        return [{"role": "user", "content": joined}]
    raise RequestError(400, "invalid_prompt", "prompt must be a non-empty string or array")


def _validate_completions_stream(body: dict[str, Any]) -> bool | None:
    """Legacy Completions ``stream`` — strict boolean; ``true`` is not supported here.

    OpenAI Completions accepts streaming, but this gateway rejects ``stream=true``
    with a clear redirect to chat completions. Non-boolean values fail closed.
    """
    if "stream" not in body:
        return None
    stream = body.get("stream")
    if not isinstance(stream, bool):
        raise RequestError(400, "invalid_stream", "stream must be a boolean")
    if stream is True:
        raise RequestError(
            400,
            "invalid_stream",
            "stream is not supported on /v1/completions; use /v1/chat/completions",
        )
    return stream


def _validate_completions_echo(body: dict[str, Any]) -> bool | None:
    """Legacy Completions ``echo`` — strict boolean; ``true`` is not supported.

    OpenAI can prepend the prompt to the completion when ``echo`` is true. This
    gateway does not implement that behaviour, so ``echo=true`` fails closed with
    a clear ``invalid_echo`` error. ``false`` and omit remain valid.
    """
    if "echo" not in body:
        return None
    echo = body.get("echo")
    if not isinstance(echo, bool):
        raise RequestError(400, "invalid_echo", "echo must be a boolean")
    if echo is True:
        raise RequestError(
            400,
            "invalid_echo",
            "echo=true is not supported on /v1/completions",
        )
    return echo














def _validate_completions_logit_bias(body: dict[str, Any]) -> dict[str, float] | None:
    """Legacy Completions ``logit_bias`` — empty object is a no-op; non-empty fails closed.

    OpenAI uses logit_bias to bias token sampling. This gateway does not apply
    token biases on the Completions route. An empty object is an honest no-op
    (SDK clients often send ``{}``). Any non-empty map is type-checked then
    rejected so clients never believe sampling bias was applied.
    """
    if "logit_bias" not in body:
        return None
    bias = body.get("logit_bias")
    if not isinstance(bias, dict):
        raise RequestError(400, "invalid_logit_bias", "logit_bias must be an object of token biases")
    # Empty object: no tokens to bias — treat as omit (honest no-op).
    if len(bias) == 0:
        return {}
    if len(bias) > 300:
        raise RequestError(400, "invalid_logit_bias", "logit_bias must contain at most 300 entries")
    for key, value in bias.items():
        token = str(key)
        if not token.isdigit():
            raise RequestError(400, "invalid_logit_bias", "logit_bias keys must be digit token ids")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RequestError(400, "invalid_logit_bias", "logit_bias values must be numbers in [-100, 100]")
        number = float(value)
        if number < -100 or number > 100:
            raise RequestError(400, "invalid_logit_bias", "logit_bias values must be numbers in [-100, 100]")
    raise RequestError(
        400,
        "invalid_logit_bias",
        "logit_bias is not supported on /v1/completions",
    )



def _validate_service_tier(body: dict[str, Any], *, endpoint_path: str) -> str | None:
    """OpenAI ``service_tier`` — accept omit/auto/default as no-ops; reject others.

    OpenAI uses service_tier for capacity priority (auto/default/flex/priority).
    This gateway has no tiered capacity plane, so only auto/default (or omit)
    are honest no-ops. Other values fail closed so clients cannot silently
    believe flex/priority processing was applied.
    """
    if "service_tier" not in body:
        return None
    service_tier = body.get("service_tier")
    if not isinstance(service_tier, str):
        raise RequestError(400, "invalid_service_tier", "service_tier must be a string")
    if service_tier not in ("auto", "default"):
        raise RequestError(
            400,
            "invalid_service_tier",
            f"service_tier values other than auto or default are not supported on {endpoint_path}",
        )
    return service_tier


def _validate_chat_modalities(body: dict[str, Any]) -> list[str] | None:
    """Chat Completions ``modalities`` — omit or ``[\"text\"]`` only.

    OpenAI selects output types (text/audio) via modalities. This gateway is
    text-only; non-text modalities fail closed so clients cannot silently
    believe audio (or other) output was applied.
    """
    if "modalities" not in body:
        return None
    modalities = body.get("modalities")
    if not isinstance(modalities, list) or not modalities:
        raise RequestError(
            400,
            "invalid_modalities",
            "modalities must be a non-empty array of strings",
        )
    if any(not isinstance(item, str) for item in modalities):
        raise RequestError(
            400,
            "invalid_modalities",
            "modalities must be a non-empty array of strings",
        )
    if modalities != ["text"]:
        raise RequestError(
            400,
            "invalid_modalities",
            'only modalities ["text"] is supported on /v1/chat/completions',
        )
    return modalities


def _validate_completions_user(body: dict[str, Any]) -> str | None:
    """Legacy Completions ``user`` — optional string end-user id, max 64 characters."""
    if "user" not in body:
        return None
    user = body.get("user")
    if not isinstance(user, str):
        raise RequestError(400, "invalid_user", "user must be a string of at most 64 characters")
    if not user.strip():
        raise RequestError(400, "invalid_user", "user must be a non-empty string of at most 64 characters")
    if len(user) > 64:
        raise RequestError(400, "invalid_user", "user must be a string of at most 64 characters")
    return user

def _validate_completions_n(body: dict[str, Any]) -> int | None:
    """Legacy Completions ``n`` — positive integer; only ``n=1`` is supported.

    OpenAI can return multiple completions when ``n > 1``. This gateway always
    returns a single choice, so ``n > 1`` fails closed. ``n=1`` and omit remain
    valid. Cap 128 is retained for clear range errors before the support check.
    """
    if "n" not in body:
        return None
    n = body.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise RequestError(400, "invalid_n", "n must be a positive integer")
    if n > 128:
        raise RequestError(400, "invalid_n", "n must be at most 128")
    if n > 1:
        raise RequestError(
            400,
            "invalid_n",
            "n greater than 1 is not supported on /v1/completions",
        )
    return n

def _validate_completions_stop(body: dict[str, Any]) -> str | list[str] | None:
    """Legacy Completions ``stop`` — type-checked then rejected (not applied).

    OpenAI uses stop sequences to cut generation early. This gateway validates
    shape (string or ≤4 non-empty strings, each ≤256 chars) but does not apply
    stop sequences on the Completions path, so any provided ``stop`` fails closed.
    """
    if "stop" not in body:
        return None
    stop = body.get("stop")
    if isinstance(stop, str):
        if not stop:
            raise RequestError(400, "invalid_stop", "stop sequences must be non-empty strings")
        if len(stop) > 256:
            raise RequestError(400, "invalid_stop", "each stop sequence must be at most 256 characters")
    elif isinstance(stop, list):
        if not stop or len(stop) > 4:
            raise RequestError(400, "invalid_stop", "stop must be a string or array of up to 4 non-empty strings")
        for item in stop:
            if not isinstance(item, str) or not item:
                raise RequestError(400, "invalid_stop", "stop sequences must be non-empty strings")
            if len(item) > 256:
                raise RequestError(400, "invalid_stop", "each stop sequence must be at most 256 characters")
    else:
        raise RequestError(400, "invalid_stop", "stop must be a string or array of up to 4 non-empty strings")
    raise RequestError(
        400,
        "invalid_stop",
        "stop sequences are not supported on /v1/completions",
    )



def _validate_completions_seed(body: dict[str, Any]) -> int | None:
    """Legacy Completions ``seed`` — type-checked then rejected (not applied).

    OpenAI uses seed for best-effort deterministic sampling. This gateway validates
    signed int64 integers but does not apply seed on the Completions route path,
    so any provided ``seed`` fails closed. Omit remains valid.
    """
    if "seed" not in body:
        return None
    seed = body.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RequestError(400, "invalid_seed", "seed must be an integer")
    if seed < -(2**63) or seed > (2**63 - 1):
        raise RequestError(400, "invalid_seed", "seed must fit in a signed 64-bit integer")
    raise RequestError(
        400,
        "invalid_seed",
        "seed is not supported on /v1/completions",
    )



def _validate_completions_frequency_penalty(body: dict[str, Any]) -> float | None:
    """Legacy Completions ``frequency_penalty`` — number in [-2, 2]."""
    if "frequency_penalty" not in body:
        return None
    value = body.get("frequency_penalty")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(400, "invalid_frequency_penalty", "frequency_penalty must be a number in [-2, 2]")
    number = float(value)
    if number < -2 or number > 2:
        raise RequestError(400, "invalid_frequency_penalty", "frequency_penalty must be a number in [-2, 2]")
    return number

def _validate_completions_presence_penalty(body: dict[str, Any]) -> float | None:
    """Legacy Completions ``presence_penalty`` — number in [-2, 2]."""
    if "presence_penalty" not in body:
        return None
    value = body.get("presence_penalty")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(400, "invalid_presence_penalty", "presence_penalty must be a number in [-2, 2]")
    number = float(value)
    if number < -2 or number > 2:
        raise RequestError(400, "invalid_presence_penalty", "presence_penalty must be a number in [-2, 2]")
    return number

def _validate_completions_temperature(body: dict[str, Any]) -> float | None:
    """Legacy Completions ``temperature`` — number in [0, 2]."""
    if "temperature" not in body:
        return None
    temperature = body.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise RequestError(400, "invalid_temperature", "temperature must be a number in [0, 2]")
    value = float(temperature)
    if value < 0 or value > 2:
        raise RequestError(400, "invalid_temperature", "temperature must be a number in [0, 2]")
    return value

def _validate_completions_top_p(body: dict[str, Any]) -> float | None:
    """Legacy Completions ``top_p`` — number in (0, 1] (OpenAI nucleus sampling)."""
    if "top_p" not in body:
        return None
    top_p = body.get("top_p")
    if isinstance(top_p, bool) or not isinstance(top_p, (int, float)):
        raise RequestError(400, "invalid_top_p", "top_p must be a number in (0, 1]")
    value = float(top_p)
    if value <= 0 or value > 1:
        raise RequestError(400, "invalid_top_p", "top_p must be a number in (0, 1]")
    return value

def _validate_completions_model(body: dict[str, Any]) -> str:
    """Legacy Completions ``model`` — required non-empty string (OpenAI parity)."""
    if "model" not in body:
        raise RequestError(400, "invalid_model", "model is required")
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise RequestError(400, "invalid_model", "model must be a non-empty string")
    if len(model) > 256:
        raise RequestError(400, "invalid_model", "model must be at most 256 characters")
    return model

def _validate_completions_max_tokens(body: dict[str, Any]) -> int | None:
    """Legacy Completions ``max_tokens`` — positive integer capped at 1_048_576."""
    if "max_tokens" not in body:
        return None
    max_tokens = body.get("max_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise RequestError(400, "invalid_max_tokens", "max_tokens must be a positive integer")
    if max_tokens > 1_048_576:
        raise RequestError(
            400,
            "invalid_max_tokens",
            "max_tokens must be at most 1048576",
        )
    return max_tokens

def _validate_chat_max_completion_tokens(body: dict[str, Any]) -> int | None:
    """Chat Completions ``max_completion_tokens`` — positive integer capped at 1_048_576.

    OpenAI prefers this over legacy ``max_tokens`` for chat. When both are set,
    ``max_completion_tokens`` wins so clients get a single honest budget.
    """
    if "max_completion_tokens" not in body:
        return None
    max_completion_tokens = body.get("max_completion_tokens")
    if (
        isinstance(max_completion_tokens, bool)
        or not isinstance(max_completion_tokens, int)
        or max_completion_tokens < 1
    ):
        raise RequestError(
            400,
            "invalid_max_completion_tokens",
            "max_completion_tokens must be a positive integer",
        )
    if max_completion_tokens > 1_048_576:
        raise RequestError(
            400,
            "invalid_max_completion_tokens",
            "max_completion_tokens must be at most 1048576",
        )
    return max_completion_tokens


def _validate_completions_logprobs(body: dict[str, Any]) -> int | bool | None:
    """Legacy Completions ``logprobs`` — only ``false``/omit; token logprobs unsupported.

    OpenAI accepts ``false`` or an integer 0–5 for top logprob counts. This gateway
    always returns ``logprobs: null`` on text completions, so integer logprobs
    (including 0–5) and boolean ``true`` fail closed. ``false`` and omit remain valid.
    """
    if "logprobs" not in body:
        return None
    logprobs = body.get("logprobs")
    if logprobs is False:
        return False
    if isinstance(logprobs, bool):  # True
        raise RequestError(
            400,
            "invalid_logprobs",
            "logprobs must be false; token logprobs are not supported on /v1/completions",
        )
    if isinstance(logprobs, int) and not isinstance(logprobs, bool):
        raise RequestError(
            400,
            "invalid_logprobs",
            "token logprobs are not supported on /v1/completions; pass false or omit",
        )
    raise RequestError(
        400,
        "invalid_logprobs",
        "logprobs must be false; token logprobs are not supported on /v1/completions",
    )

def _validate_completions_suffix(body: dict[str, Any]) -> str | None:
    """Legacy Completions ``suffix`` — optional string; non-empty is not supported.

    OpenAI appends ``suffix`` after the model completion. This gateway does not
    implement that insertion, so a non-empty suffix fails closed. Empty string
    and omit remain valid. Non-string values and oversized strings still fail.
    """
    if "suffix" not in body:
        return None
    suffix = body.get("suffix")
    if not isinstance(suffix, str):
        raise RequestError(400, "invalid_suffix", "suffix must be a string")
    if len(suffix) > 8_000:
        raise RequestError(400, "invalid_suffix", "suffix must be at most 8000 characters")
    if suffix:
        raise RequestError(
            400,
            "invalid_suffix",
            "non-empty suffix is not supported on /v1/completions",
        )
    return suffix


def _validate_completions_best_of(body: dict[str, Any]) -> int | None:
    """Legacy Completions ``best_of`` — positive integer, ``best_of >= n``, max 1.

    OpenAI generates ``best_of`` candidates server-side and returns the top ``n``.
    This gateway runs a single completion path, so ``best_of > 1`` fails closed
    rather than silently returning one unranked candidate. ``best_of=1`` (and
    omit) remain valid. Boolean ``True``/``False`` are rejected.
    """
    if "best_of" not in body:
        return None
    best_of = body.get("best_of")
    if isinstance(best_of, bool) or not isinstance(best_of, int) or best_of < 1:
        raise RequestError(400, "invalid_best_of", "best_of must be a positive integer")
    if best_of > 128:
        raise RequestError(400, "invalid_best_of", "best_of must be at most 128")
    if best_of > 1:
        raise RequestError(
            400,
            "invalid_best_of",
            "best_of greater than 1 is not supported on /v1/completions",
        )
    n = body.get("n", 1)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise RequestError(400, "invalid_n", "n must be a positive integer")
    if best_of < n:
        raise RequestError(
            400,
            "invalid_best_of",
            "best_of must be greater than or equal to n",
        )
    return best_of


def _validate_completions_stream_options(body: dict[str, Any]) -> dict[str, Any] | None:
    """Legacy Completions ``stream_options`` — object with boolean flags; requires stream=true.

    Mirrors OpenAI chat Completions: ``stream_options`` is only valid when streaming.
    This gateway rejects Completions streaming, so a well-formed ``stream_options``
    still fails closed once ``stream`` is checked (or here if ``stream`` is not true).
    """
    if "stream_options" not in body:
        return None
    opts = body.get("stream_options")
    if not isinstance(opts, dict):
        raise RequestError(400, "invalid_stream_options", "stream_options must be an object")
    if body.get("stream") is not True:
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options requires stream=true",
        )
    allowed = {"include_usage", "include_obfuscation"}
    unknown = sorted(set(opts) - allowed)
    if unknown:
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options contains unsupported fields",
            {"fields": unknown},
        )
    if "include_usage" in opts and not isinstance(opts["include_usage"], bool):
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options.include_usage must be a boolean",
        )
    if "include_obfuscation" in opts and not isinstance(opts["include_obfuscation"], bool):
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options.include_obfuscation must be a boolean",
        )
    return opts




def _validate_chat_stream_options(body: dict[str, Any], stream: bool) -> dict[str, Any] | None:
    """Chat Completions ``stream_options`` — requires stream=true; include_usage unsupported.

    Shape matches OpenAI (include_usage / include_obfuscation booleans). This
    gateway's SSE route path does not emit a final usage chunk and does not
    apply stream obfuscation, so include_usage/include_obfuscation=true fail closed.
    """
    if "stream_options" not in body:
        return None
    opts = body.get("stream_options")
    if not isinstance(opts, dict):
        raise RequestError(400, "invalid_stream_options", "stream_options must be an object")
    if stream is not True:
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options requires stream=true on /v1/chat/completions",
        )
    allowed = {"include_usage", "include_obfuscation"}
    unknown = sorted(set(opts) - allowed)
    if unknown:
        raise RequestError(
            400,
            "invalid_stream_options",
            "stream_options contains unsupported fields",
            {"fields": unknown},
        )
    if "include_usage" in opts:
        if not isinstance(opts["include_usage"], bool):
            raise RequestError(
                400,
                "invalid_stream_options",
                "stream_options.include_usage must be a boolean",
            )
        if opts["include_usage"] is True:
            raise RequestError(
                400,
                "invalid_stream_options",
                "stream_options.include_usage=true is not supported on /v1/chat/completions",
            )
    if "include_obfuscation" in opts:
        if not isinstance(opts["include_obfuscation"], bool):
            raise RequestError(
                400,
                "invalid_stream_options",
                "stream_options.include_obfuscation must be a boolean",
            )
        if opts["include_obfuscation"] is True:
            # SSE obfuscation is not applied by this gateway; fail closed.
            raise RequestError(
                400,
                "invalid_stream_options",
                "stream_options.include_obfuscation=true is not supported on /v1/chat/completions",
            )
    return opts


def _reject_unknown_keys(body: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise RequestError(400, "unknown_fields", "request contains unsupported fields", {"fields": unknown})


def _validate_mode(mode: Any) -> str:
    if not isinstance(mode, str) or mode not in ALLOWED_MODES:
        raise RequestError(400, "invalid_mode", "mode must be auto, route, or conduct")
    return mode


def _validate_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise RequestError(400, "invalid_message", "messages must be a non-empty array")
    validated: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise RequestError(400, "invalid_message", "each message must be an object")
        role = message.get("role")
        content = message.get("content")
        if isinstance(role, str) and role == "developer":
            # Newer OpenAI clients send developer in place of system; this gateway
            # does not apply a separate developer plane — fail closed with migration.
            raise RequestError(
                400,
                "invalid_message_role",
                "developer role is not supported on /v1/chat/completions; use system instead",
            )
        if isinstance(content, list):
            # OpenAI multimodal content parts (text/image_url/input_audio/...) are not
            # applied by this text-only gateway. Fail closed so SDKs cannot silently
            # believe vision/audio parts were processed as plain text.
            raise RequestError(
                400,
                "invalid_message_content",
                "multipart content arrays are not supported on /v1/chat/completions; "
                "pass a string content",
            )
        if not isinstance(role, str) or role not in ALLOWED_MESSAGE_ROLES or not isinstance(content, str):
            raise RequestError(400, "invalid_message", "message role or content is invalid")
        # User/system turns drive the prompt — empty content is never applied and
        # would only create silent no-op turns. Assistant/tool may still use empty
        # content when tool_calls or tool results carry the payload.
        if role in {"user", "system"} and not content.strip():
            raise RequestError(
                400,
                "invalid_message_content",
                "user and system message content must be a non-empty string",
            )
        entry: dict[str, str] = {"role": role, "content": content}
        if role == "tool":
            # OpenAI tool messages bind results to a prior tool_call via tool_call_id.
            tool_call_id = message.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                raise RequestError(
                    400,
                    "invalid_message",
                    "tool messages require a non-empty tool_call_id string",
                )
            if len(tool_call_id) > 128:
                raise RequestError(
                    400,
                    "invalid_message",
                    "tool_call_id must be at most 128 characters",
                )
            entry["tool_call_id"] = tool_call_id
        if "name" in message:
            # OpenAI optional participant name on system/user/assistant (not tool).
            msg_name = message.get("name")
            if role == "tool":
                raise RequestError(
                    400,
                    "invalid_message_name",
                    "name is not valid on tool role messages",
                )
            if not isinstance(msg_name, str) or not msg_name.strip():
                raise RequestError(
                    400,
                    "invalid_message_name",
                    "message name must be a non-empty string",
                )
            if len(msg_name) > 64:
                raise RequestError(
                    400,
                    "invalid_message_name",
                    "message name must be at most 64 characters",
                )
            # OpenAI participant names are alphanumeric plus underscore/hyphen.
            if not all(ch.isalnum() or ch in "_-" for ch in msg_name):
                raise RequestError(
                    400,
                    "invalid_message_name",
                    "message name must match [a-zA-Z0-9_-]",
                )
            entry["name"] = msg_name
        validated.append(entry)
    return validated


def _validate_chat_tool_message_ids(body: dict[str, Any]) -> None:
    """Fail closed on role=tool messages missing a usable tool_call_id.

    Runs before tools passthrough so multi-turn tool results are shape-checked
    even when the body is proxied verbatim to a single provider agent.
    """
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "tool":
            continue
        tool_call_id = message.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise RequestError(
                400,
                "invalid_message",
                "tool messages require a non-empty tool_call_id string",
            )
        if len(tool_call_id) > 128:
            raise RequestError(
                400,
                "invalid_message",
                "tool_call_id must be at most 128 characters",
            )


def _validate_chat_assistant_tool_calls(body: dict[str, Any]) -> None:
    """OpenAI assistant ``tool_calls`` array shape on chat messages.

    Each entry must be a function tool call with non-empty ``id``,
    ``function.name``, and string ``function.arguments`` (JSON text).
    Validated before passthrough so multi-turn tool histories fail closed.
    """
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        if "tool_calls" not in message:
            continue
        if message.get("role") != "assistant":
            raise RequestError(
                400,
                "invalid_message",
                "tool_calls is only valid on assistant messages",
            )
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            raise RequestError(
                400,
                "invalid_message",
                "tool_calls must be a non-empty array",
            )
        if len(tool_calls) > 128:
            raise RequestError(
                400,
                "invalid_message",
                "tool_calls must contain at most 128 entries",
            )
        for call in tool_calls:
            if not isinstance(call, dict):
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls entry must be an object",
                )
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls entry requires a non-empty id string",
                )
            if len(call_id) > 128:
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls id must be at most 128 characters",
                )
            if call.get("type") != "function":
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls entry type must be function",
                )
            function = call.get("function")
            if not isinstance(function, dict):
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls entry requires a function object",
                )
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls function.name must be a non-empty string",
                )
            if len(name) > 64:
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls function.name must be at most 64 characters",
                )
            if not all(ch.isalnum() or ch in "_-" for ch in name):
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls function.name must match [a-zA-Z0-9_-]",
                )
            arguments = function.get("arguments")
            if not isinstance(arguments, str):
                raise RequestError(
                    400,
                    "invalid_message",
                    "each tool_calls function.arguments must be a string",
                )


def _validate_attribution(attribution: Any) -> dict[str, Any] | None:
    if attribution is None:
        return None
    if not isinstance(attribution, dict):
        raise RequestError(400, "invalid_attribution", "attribution must be an object")
    allowed = set(ATTRIBUTION_DIMENSIONS) | {"provider"}
    unknown = sorted(set(attribution) - allowed)
    if unknown:
        raise RequestError(400, "invalid_attribution", "attribution contains unsupported dimensions", {"fields": unknown})
    return {key: str(value) for key, value in attribution.items()}


def _validate_routing(routing: Any) -> dict[str, Any] | None:
    """OpenAI-adjacent routing hints for sync vs batch channel selection.

    Fail closed on shape so callers cannot smuggle non-boolean latency flags or
    free-form priority values that RoutingPolicy would silently misread via
    loose coercion (``bool(x)`` / ``str(x)``).
    """
    if routing is None:
        return None
    if not isinstance(routing, dict):
        raise RequestError(400, "invalid_routing", "routing must be an object")
    unknown = sorted(set(routing) - {"channel", "latency_tolerant", "priority"})
    if unknown:
        raise RequestError(400, "invalid_routing", "routing contains unsupported keys", {"fields": unknown})
    channel = routing.get("channel")
    if channel is not None and channel not in {"sync", "batch"}:
        raise RequestError(400, "invalid_routing", "routing.channel must be sync or batch")
    if "latency_tolerant" in routing:
        latency_tolerant = routing.get("latency_tolerant")
        if not isinstance(latency_tolerant, bool):
            raise RequestError(
                400,
                "invalid_routing",
                "routing.latency_tolerant must be a boolean",
            )
    if "priority" in routing:
        priority = routing.get("priority")
        if not isinstance(priority, str) or priority not in {"interactive", "normal", "bulk"}:
            raise RequestError(
                400,
                "invalid_routing",
                "routing.priority must be one of interactive, normal, bulk",
            )
    return routing


def _validate_batch_requests(body: dict[str, Any], expose_trace: bool) -> list[BatchRequest]:
    raw_requests = body.get("requests")
    if not isinstance(raw_requests, list) or not raw_requests:
        raise RequestError(400, "invalid_request", "requests must be a non-empty array")
    default_attribution = _validate_attribution(body.get("attribution")) or {}
    default_model = str(body.get("model", "contextual-orchestrator"))
    batch: list[BatchRequest] = []
    for item in raw_requests:
        if not isinstance(item, dict):
            raise RequestError(400, "invalid_request", "each batch request must be an object")
        messages = _validate_messages(item.get("messages"))
        attribution = _validate_attribution(item.get("attribution"))
        merged = {**default_attribution, **(attribution or {})}
        mode = _validate_mode(item.get("mode", "auto"))
        batch.append(BatchRequest(
            messages=messages,
            model=str(item.get("model", default_model)),
            attribution=merged,
            mode=mode,
        ))
    return batch


def _validate_embeddings_inputs(body: dict[str, Any]) -> list[str]:
    """Validate the embeddings batch inputs (accepts ``inputs`` or ``input``)."""
    raw = body.get("inputs")
    if raw is None:
        raw = body.get("input")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise RequestError(400, "invalid_request", "input/inputs must be a non-empty array of strings")
    inputs: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise RequestError(400, "invalid_request", "each embedding input must be a string")
        inputs.append(item)
    return inputs



def _validate_chat_store(body: dict[str, Any]) -> bool | None:
    """Chat Completions ``store`` — strict boolean; ``true`` is not supported.

    OpenAI can persist completions when ``store=true``. This gateway does not
    implement that persistence surface, so ``store=true`` fails closed.
    ``store=false`` and omit remain valid (explicit no-store is honest).
    """
    if "store" not in body:
        return None
    store = body.get("store")
    if not isinstance(store, bool):
        raise RequestError(400, "invalid_store", "store must be a boolean")
    if store is True:
        raise RequestError(
            400,
            "invalid_store",
            "store=true is not supported on /v1/chat/completions",
        )
    return store


def _validate_chat_response_format(body: dict[str, Any]) -> dict[str, Any] | None:
    """OpenAI chat ``response_format`` — object with type text/json_object/json_schema.

    Shape is validated before passthrough so malformed payloads fail closed
    rather than reaching a provider with an unusable format object.

    OpenAI type-only forms are strict: ``text`` and ``json_object`` accept only
    the ``type`` key. ``json_schema`` accepts only ``type`` and ``json_schema``.
    Extra sibling keys fail closed so clients cannot smuggle unsupported fields
    into a provider-shaped object that this gateway never interpreted.
    """
    if "response_format" not in body:
        return None
    fmt = body.get("response_format")
    if not isinstance(fmt, dict):
        raise RequestError(
            400,
            "invalid_response_format",
            "response_format must be an object",
        )
    fmt_type = fmt.get("type")
    if fmt_type not in ("text", "json_object", "json_schema"):
        raise RequestError(
            400,
            "invalid_response_format",
            "response_format.type must be one of text, json_object, json_schema",
        )
    if fmt_type in ("text", "json_object"):
        # OpenAI: {"type": "json_object"} / {"type": "text"} — no siblings.
        unknown = sorted(set(fmt) - {"type"})
        if unknown:
            raise RequestError(
                400,
                "invalid_response_format",
                f"response_format with type {fmt_type} accepts only the type field",
                {"fields": unknown},
            )
        return fmt
    if fmt_type == "json_schema":
        unknown = sorted(set(fmt) - {"type", "json_schema"})
        if unknown:
            raise RequestError(
                400,
                "invalid_response_format",
                "response_format with type json_schema accepts only type and json_schema",
                {"fields": unknown},
            )
        schema = fmt.get("json_schema")
        if not isinstance(schema, dict):
            raise RequestError(
                400,
                "invalid_response_format",
                "response_format.json_schema must be an object when type is json_schema",
            )
        name = schema.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RequestError(
                400,
                "invalid_response_format",
                "response_format.json_schema.name must be a non-empty string",
            )
        # OpenAI requires json_schema.schema as the actual JSON Schema object.
        # Fail closed when missing or non-object so clients cannot silently
        # believe structured-output enforcement applied without a schema body.
        schema_body = schema.get("schema")
        if not isinstance(schema_body, dict):
            raise RequestError(
                400,
                "invalid_response_format",
                "response_format.json_schema.schema must be an object",
            )
        if "strict" in schema and not isinstance(schema.get("strict"), bool):
            raise RequestError(
                400,
                "invalid_response_format",
                "response_format.json_schema.strict must be a boolean when provided",
            )
    return fmt



def _validate_chat_tools(body: dict[str, Any]) -> list[dict[str, Any]] | None:
    """OpenAI chat ``tools`` — non-empty array of function tool objects.

    Each entry must be an object with ``type`` == ``function`` and a
    ``function`` object that has a non-empty ``name``. Shape-only validation
    before passthrough; provider schema depth is not re-checked here.
    """
    if "tools" not in body:
        return None
    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        raise RequestError(
            400,
            "invalid_tools",
            "tools must be a non-empty array",
        )
    if len(tools) > 128:
        raise RequestError(
            400,
            "invalid_tools",
            "tools must contain at most 128 entries",
        )
    validated: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            raise RequestError(400, "invalid_tools", "each tool must be an object")
        # OpenAI tool objects are type + function only; extra siblings fail closed
        # so clients cannot smuggle uninterpreted fields through passthrough.
        unknown_tool = sorted(set(item) - {"type", "function"})
        if unknown_tool:
            raise RequestError(
                400,
                "invalid_tools",
                "each tool accepts only type and function fields",
                {"fields": unknown_tool},
            )
        if item.get("type") != "function":
            raise RequestError(
                400,
                "invalid_tools",
                "each tool type must be function",
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function must be an object",
            )
        unknown_fn = sorted(set(function) - {"name", "description", "parameters", "strict"})
        if unknown_fn:
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function accepts only name, description, parameters, and strict",
                {"fields": unknown_fn},
            )
        if "strict" in function and not isinstance(function.get("strict"), bool):
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function.strict must be a boolean when provided",
            )
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function.name must be a non-empty string",
            )
        # OpenAI function names: [a-zA-Z0-9_-]{1,64}
        if len(name) > 64:
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function.name must be at most 64 characters",
            )
        if not all(ch.isalnum() or ch in "_-" for ch in name):
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function.name must match [a-zA-Z0-9_-]",
            )
        # OpenAI function tools require parameters as a JSON Schema object when present.
        if "parameters" in function:
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                raise RequestError(
                    400,
                    "invalid_tools",
                    "each tool.function.parameters must be an object",
                )
        if "description" in function and not isinstance(function.get("description"), str):
            raise RequestError(
                400,
                "invalid_tools",
                "each tool.function.description must be a string when provided",
            )
        validated.append(item)
    return validated


def _validate_chat_tool_choice(body: dict[str, Any]) -> str | dict[str, Any] | None:
    """OpenAI chat ``tool_choice`` — none/auto/required or named function object.

    When ``type`` is ``function``, ``function.name`` must match a tools entry
    so clients cannot force a tool the request did not declare.
    """
    if "tool_choice" not in body:
        return None
    choice = body.get("tool_choice")
    if isinstance(choice, str):
        if choice not in ("none", "auto", "required"):
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice string must be one of none, auto, required",
            )
        return choice
    if isinstance(choice, dict):
        # OpenAI named tool_choice is {type, function}; extra siblings fail closed.
        unknown = sorted(set(choice) - {"type", "function"})
        if unknown:
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice object accepts only type and function fields",
                {"fields": unknown},
            )
        if choice.get("type") != "function":
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice object type must be function",
            )
        function = choice.get("function")
        if not isinstance(function, dict):
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice.function must be an object with a name",
            )
        unknown_fn = sorted(set(function) - {"name"})
        if unknown_fn:
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice.function accepts only name",
                {"fields": unknown_fn},
            )
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice.function.name must be a non-empty string",
            )
        tools = body.get("tools")
        tool_names: set[str] = set()
        if isinstance(tools, list):
            for item in tools:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function")
                if isinstance(fn, dict):
                    tool_name = fn.get("name")
                    if isinstance(tool_name, str):
                        tool_names.add(tool_name)
        if name not in tool_names:
            raise RequestError(
                400,
                "invalid_tool_choice",
                "tool_choice.function.name must match a tools entry",
            )
        return choice
    raise RequestError(
        400,
        "invalid_tool_choice",
        "tool_choice must be a string or object",
    )


def _embeddings_attribution(body: dict[str, Any]) -> dict[str, Any]:
    """Build ledger attribution from the explicit ``attribution`` field merged
    with any attribution dimensions carried inside ``metadata``.

    naruon sends full cost attribution (service, team, group, company, plus the
    provider alias) inside ``metadata`` alongside observability-only keys
    (source, organization_id, user_id). Only recognised dimension keys feed the
    ledger; the rest are ignored here but still accepted.
    """
    attribution = _validate_attribution(body.get("attribution")) or {}
    metadata = body.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise RequestError(400, "invalid_request", "metadata must be an object")
    known = set(ATTRIBUTION_DIMENSIONS) | {"provider"}
    merged: dict[str, Any] = {}
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if key in known and value not in (None, ""):
                merged[key] = str(value)
    # An explicit attribution field wins over metadata-derived dimensions.
    merged.update(attribution)
    return merged


def _strip_trace(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_strip_trace(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _strip_trace(value) for key, value in payload.items() if key != "trace"}
    return payload


def _response_payload(payload: dict[str, Any], include_trace: bool) -> dict[str, Any]:
    safe_payload = redact_value(payload)
    if include_trace:
        return safe_payload
    return _strip_trace(safe_payload)


def build_server(
    orchestrator: TaskOrchestrator,
    host: str = "127.0.0.1",
    port: int = 8000,
    security: SecurityConfig | None = None,
    clearfolio_url: str | None = None,
    coordinator: CostRoutingCoordinator | None = None,
) -> ThreadingHTTPServer:
    """Build, but do not start, the orchestration HTTP server.

    ``coordinator`` is the cost-review + routing hub. When omitted a default
    one is built around ``orchestrator`` with an in-memory KV config store, so
    every completion is priced, recorded, and sync/batch routed.
    """
    security = security or SecurityConfig()
    security.check_bind(host)
    coordinator = coordinator or CostRoutingCoordinator(orchestrator)
    if clearfolio_url is not None:
        parsed_viewer = urllib.parse.urlparse(clearfolio_url)
        if parsed_viewer.scheme not in {"http", "https"} or not parsed_viewer.netloc:
            raise ValueError("clearfolio_url must be an http(s) URL")
        clearfolio_url = clearfolio_url.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if path == "/openapi.json":
                    self._send(OPENAPI_SPEC)
                    return
                if path == "/healthz":
                    # Unauthenticated liveness probe for containers/orchestrators.
                    self._send({
                        "status": "ok",
                        "service": "contextual-orchestrator",
                        "agent_count": len(orchestrator.agents),
                        "batch_backend": coordinator.batch_backend.name,
                        "embedding_batch_backend": coordinator.embedding_batch_backend.name,
                        "usage_record_count": len(coordinator.ledger.records()),
                    })
                    return
                if path.startswith("/v1/batch/embeddings/"):
                    # Embeddings batch polling is an inference-scope surface, so
                    # it is authorized here before the admin gate below.
                    self._authorize("inference")
                    batch_id = path[len("/v1/batch/embeddings/"):]
                    try:
                        self._send(coordinator.embeddings_batch_document(batch_id))
                    except KeyError:
                        self._send_error(404, "embeddings_batch_not_found", f"embeddings batch {batch_id} not found")
                    return
                self._authorize("admin")
                if path == "/api/v1/cost_attribution_dimensions":
                    self._send({"items": dimension_catalog(), "total_count": len(ATTRIBUTION_DIMENSIONS)})
                    return
                if path == "/api/v1/cost_reports/rollup":
                    dimension = (query.get("dimension") or ["model_name"])[0]
                    start = self._parse_optional_int(query, "start")
                    end = self._parse_optional_int(query, "end")
                    try:
                        self._send(coordinator.cost_report(dimension, start, end))
                    except ValueError as exc:
                        self._send_error(400, "invalid_dimension", str(exc))
                    return
                if path == "/api/v1/llm_usage_records":
                    start = self._parse_optional_int(query, "start")
                    end = self._parse_optional_int(query, "end")
                    records = coordinator.ledger.records(start, end)
                    page_number, page_size = self._parse_paging(query, default_size=50, max_size=500)
                    window = records[(page_number - 1) * page_size : page_number * page_size]
                    self._send({
                        "items": window,
                        "total_count": len(records),
                        "page_number": page_number,
                        "page_size": page_size,
                    })
                    return
                if path.startswith("/api/v1/batch_routing_jobs/"):
                    job_id = path.rsplit("/", 1)[-1]
                    try:
                        self._send(coordinator.poll_batch(job_id))
                    except KeyError:
                        self._send_error(404, "batch_job_not_found", f"batch job {job_id} not found")
                    return
                if path in ("/", "/admin"):
                    self._send_text(ADMIN_HTML, "text/html; charset=utf-8")
                    return
                if path == "/admin/state":
                    state = orchestrator.admin_state()
                    state["document_viewer"] = (
                        {"provider": "clearfolio", "url": clearfolio_url} if clearfolio_url else None
                    )
                    self._send(_response_payload(state, security.expose_trace_by_default))
                    return
                if path == "/api/v1/agent_pools":
                    page_number, page_size = self._parse_paging(query, default_size=20, max_size=100)
                    items = orchestrator.list_agents(page_number=page_number, page_size=page_size)
                    self._send({
                        "items": items,
                        "total_count": len(orchestrator.agents),
                        "page_number": page_number,
                        "page_size": page_size,
                    })
                    return
                if path == "/api/v1/orchestration_policies/default_policy":
                    self._send(orchestrator.admin_state()["policy"])
                    return
                if path == "/api/v1/analytics_snapshots/latest":
                    self._send(orchestrator.analytics_snapshot(locale_bundles=ADMIN_TRANSLATIONS))
                    return
                if path == "/api/v1/spend_analytics/latest":
                    self._send(orchestrator.spend_analytics())
                    return
                if path == "/api/v1/sales_readiness/latest":
                    self._send(orchestrator.sales_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_readiness/latest":
                    self._send(orchestrator.commercial_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/buyer_evidence_manifests/latest":
                    self._send(orchestrator.buyer_evidence_manifest_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/buyer_handoff_bundles/latest":
                    self._send(orchestrator.buyer_handoff_bundle_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/saleability_decisions/latest":
                    self._send(orchestrator.saleability_decision_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_evidence_exports/latest":
                    self._send(orchestrator.commercial_evidence_export_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_acceptance_checks/latest":
                    self._send(orchestrator.commercial_acceptance_check_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_release_candidates/latest":
                    self._send(orchestrator.commercial_release_candidate_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_gap_registers/latest":
                    self._send(orchestrator.commercial_gap_register_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_procurement_readiness/latest":
                    self._send(orchestrator.commercial_procurement_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_contract_readiness/latest":
                    self._send(orchestrator.commercial_contract_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_onboarding_readiness/latest":
                    self._send(orchestrator.commercial_onboarding_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_operations_readiness/latest":
                    self._send(orchestrator.commercial_operations_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_security_attestations/latest":
                    self._send(orchestrator.commercial_security_attestation_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_value_readiness/latest":
                    self._send(orchestrator.commercial_value_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_close_readiness/latest":
                    self._send(orchestrator.commercial_close_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_go_to_market_readiness/latest":
                    self._send(orchestrator.commercial_go_to_market_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_launch_readiness/latest":
                    self._send(orchestrator.commercial_launch_readiness_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_completion_scorecards/latest":
                    self._send(orchestrator.commercial_completion_scorecard_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_buyer_acceptance_workflows/latest":
                    self._send(orchestrator.commercial_buyer_acceptance_workflow_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_demo_scenarios/latest":
                    self._send(orchestrator.commercial_demo_scenario_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_proposal_packets/latest":
                    self._send(orchestrator.commercial_proposal_packet_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_purchase_approval_packets/latest":
                    self._send(orchestrator.commercial_purchase_approval_packet_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_due_diligence_rooms/latest":
                    self._send(orchestrator.commercial_due_diligence_room_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/commercial_investment_committee_memos/latest":
                    self._send(orchestrator.commercial_investment_committee_memo_report(
                        locale_bundles=ADMIN_TRANSLATIONS,
                        security_profile=security.readiness_profile(),
                    ))
                    return
                if path == "/api/v1/workflow_runs":
                    page_number, page_size = self._parse_paging(query, default_size=20, max_size=200)
                    self._send(_response_payload({
                        "items": orchestrator.list_recent_runs(page_number=page_number, page_size=page_size),
                        "total_count": len(getattr(orchestrator, "_workflow_runs", {})),
                        "page_number": page_number,
                        "page_size": page_size,
                    }, security.expose_trace_by_default))
                    return
                if path.startswith("/api/v1/workflow_runs/"):
                    workflow_run_id = path.rsplit("/", 1)[-1]
                    try:
                        self._send(_response_payload(orchestrator.get_workflow_run(workflow_run_id), security.expose_trace_by_default))
                        return
                    except KeyError:
                        self._send_error(404, "workflow_run_not_found", f"workflow_run {workflow_run_id} not found")
                        return
                if path.startswith("/api/v1/access_reports/"):
                    workflow_run_id = path.rsplit("/", 1)[-1]
                    try:
                        orchestrator.record_analytics_event(
                            "access_report_viewed",
                            {
                                "endpoint_path": "/api/v1/access_reports/{workflow_run_id}",
                                "workflow_run_id": workflow_run_id,
                                "actor_scope": "admin",
                                "status_code": 200,
                            },
                        )
                        self._send(_response_payload(orchestrator.get_access_report(workflow_run_id), security.expose_trace_by_default))
                        return
                    except KeyError:
                        self._send_error(404, "workflow_run_not_found", f"workflow_run {workflow_run_id} not found")
                        return
                if path.startswith("/api/v1/evaluation_runs/"):
                    evaluation_run_id = path.rsplit("/", 1)[-1]
                    runs = getattr(orchestrator, "_evaluation_runs", {})
                    if evaluation_run_id in runs:
                        self._send(_response_payload(runs[evaluation_run_id], security.expose_trace_by_default))
                        return
                    self._send_error(404, "evaluation_run_not_found", f"evaluation_run {evaluation_run_id} not found")
                    return
                if path.startswith("/api/v1/agent_pools/"):
                    segments = [part for part in path.split("/") if part]
                    if len(segments) == 6 and segments[:3] == ["api", "v1", "agent_pools"] and segments[4] == "worker_agents":
                        agent_pool_id = segments[3]
                        worker_agent_id = segments[-1]
                        try:
                            payload = orchestrator._agent_to_admin_payload(orchestrator._agent(worker_agent_id))
                            payload["agent_pool_id"] = agent_pool_id
                            self._send(payload)
                            return
                        except KeyError:
                            self._send_error(404, "agent_not_found", f"agent {worker_agent_id} not found")
                            return
                    raise RequestError(
                        400,
                        "bad_path",
                        "agent path must be /api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}",
                    )
                if path.startswith("/api/v1/locale_bundles/"):
                    locale_code = path.rsplit("/", 1)[-1]
                    bundle = ADMIN_TRANSLATIONS.get(locale_code)
                    if not bundle:
                        self._send_error(404, "locale_not_found", f"locale {locale_code} not found")
                        return
                    orchestrator.record_analytics_event(
                        "locale_bundle_loaded",
                        {
                            "endpoint_path": "/api/v1/locale_bundles/{locale_code}",
                            "locale_code": locale_code,
                            "actor_scope": "admin",
                            "status_code": 200,
                        },
                    )
                    self._send({"locale_code": locale_code, "messages": bundle})
                    return
                self._send_error(404, "route_not_found", "not found")
            except RequestError as exc:
                self._send_error(exc.status, exc.code, exc.message, exc.detail)
            except (TypeError, ValueError) as exc:
                self._send_error(400, "invalid_request", str(exc))
            except Exception:
                self._send_error(500, "internal_error", "internal server error")

        def do_PATCH(self) -> None:  # noqa: N802
            try:
                self._authorize("admin")
                path = urllib.parse.urlparse(self.path).path
                if path.startswith("/api/v1/agent_pools/") and "/worker_agents/" in path:
                    segments = [part for part in path.split("/") if part]
                    if len(segments) != 6 or segments[:3] != ["api", "v1", "agent_pools"] or segments[4] != "worker_agents":
                        raise RequestError(400, "bad_path", "agent patch path missing worker agent")
                    body = self._read_json()
                    _reject_unknown_keys(body, ALLOWED_AGENT_PATCH_KEYS)
                    updated = orchestrator.patch_agent(segments[3], segments[-1], body)
                    self._send(updated, 200)
                    return
                self._send_error(404, "route_not_found", "not found")
            except RequestError as exc:
                self._send_error(exc.status, exc.code, exc.message, exc.detail)
            except (ValueError, TypeError) as exc:
                self._send_error(400, "invalid_request", str(exc))
            except KeyError as exc:
                self._send_error(404, "resource_not_found", str(exc))
            except Exception:
                self._send_error(500, "internal_error", "internal server error")

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                self._authorize("admin")
                path = urllib.parse.urlparse(self.path).path
                if path.startswith("/api/v1/agent_pools/") and "/worker_agents/" in path:
                    segments = [part for part in path.split("/") if part]
                    if len(segments) != 6 or segments[:3] != ["api", "v1", "agent_pools"] or segments[4] != "worker_agents":
                        raise RequestError(400, "bad_path", "agent delete path missing worker agent")
                    self._send(orchestrator.remove_agent(segments[3], segments[-1]), 200)
                    return
                self._send_error(404, "route_not_found", "not found")
            except RequestError as exc:
                self._send_error(exc.status, exc.code, exc.message, exc.detail)
            except (ValueError, TypeError) as exc:
                self._send_error(400, "invalid_request", str(exc))
            except KeyError as exc:
                self._send_error(404, "resource_not_found", str(exc))
            except Exception:
                self._send_error(500, "internal_error", "internal server error")

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urllib.parse.urlparse(self.path).path
                scope = "admin" if path == "/admin/simulate" or path.startswith("/api/v1/agent_pools/") else "inference"
                self._authorize(scope)
                body = self._read_json()

                if path.startswith("/api/v1/agent_pools/") and path.endswith("/worker_agents"):
                    segments = [part for part in path.split("/") if part]
                    if len(segments) != 5 or segments[:3] != ["api", "v1", "agent_pools"]:
                        raise RequestError(400, "bad_path", "agent create path must be /api/v1/agent_pools/{pool}/worker_agents")
                    _reject_unknown_keys(body, ALLOWED_AGENT_CREATE_KEYS)
                    self._send(orchestrator.add_agent(segments[3], body), 201)
                    return

                if path == "/v1/completions":
                    # Legacy OpenAI Completions: prompt → route → text_completion.
                    _reject_unknown_keys(body, ALLOWED_COMPLETIONS_KEYS)
                    _validate_completions_stream(body)
                    _validate_completions_stream_options(body)
                    _validate_completions_best_of(body)
                    _validate_completions_echo(body)
                    _validate_completions_suffix(body)
                    _validate_completions_logprobs(body)
                    max_tokens = _validate_completions_max_tokens(body)
                    model_name = _validate_completions_model(body)
                    top_p = _validate_completions_top_p(body)
                    temperature = _validate_completions_temperature(body)
                    presence_penalty = _validate_completions_presence_penalty(body)
                    frequency_penalty = _validate_completions_frequency_penalty(body)
                    _validate_completions_seed(body)
                    _validate_completions_stop(body)
                    _validate_completions_n(body)
                    end_user_id = _validate_completions_user(body)
                    _validate_completions_logit_bias(body)
                    _validate_service_tier(body, endpoint_path="/v1/completions")
                    if "prompt" not in body:
                        raise RequestError(400, "invalid_prompt", "prompt is required")
                    messages = _validate_completion_prompt(body.get("prompt"))
                    attribution = _validate_attribution(body.get("attribution"))
                    attribution = dict(attribution or {})
                    # OpenAI ``user`` → cost-ledger account when attribution.account is unset.
                    if end_user_id is not None and not attribution.get("account"):
                        attribution["account"] = end_user_id
                    # Request model id → model_name dimension when unset (cost rollups).
                    if model_name and not attribution.get("model_name"):
                        attribution["model_name"] = model_name
                    # Endpoint product surface → service dimension when unset.
                    if not attribution.get("service"):
                        attribution["service"] = "completions_api"
                    routing = _validate_routing(body.get("routing"))
                    started_at = time.perf_counter()
                    # Apply request sampling knobs to the provider client for this call.
                    model_client = orchestrator.client
                    previous_max_tokens = model_client.max_output_tokens
                    previous_temperature = model_client.default_temperature
                    previous_top_p = model_client.default_top_p
                    previous_presence = model_client.default_presence_penalty
                    previous_frequency = model_client.default_frequency_penalty
                    if max_tokens is not None:
                        model_client.max_output_tokens = max_tokens
                    if temperature is not None:
                        model_client.default_temperature = temperature
                    if top_p is not None:
                        model_client.default_top_p = top_p
                    if presence_penalty is not None:
                        model_client.default_presence_penalty = presence_penalty
                    if frequency_penalty is not None:
                        model_client.default_frequency_penalty = frequency_penalty
                    try:
                        result = self._run(lambda: coordinator.complete(
                            messages,
                            mode="route",
                            attribution=attribution,
                            hints=routing,
                            model_name=model_name,
                            workflow_run_id=f"run_{uuid.uuid4().hex}",
                        ))
                    finally:
                        model_client.max_output_tokens = previous_max_tokens
                        model_client.default_temperature = previous_temperature
                        model_client.default_top_p = previous_top_p
                        model_client.default_presence_penalty = previous_presence
                        model_client.default_frequency_penalty = previous_frequency
                    # Batch-channel Completions return a job handle (202), not a
                    # text_completion body — match chat Completions honesty so
                    # clients never receive a 500 on a valid batch routing hint.
                    if isinstance(result, dict) and result.get("channel") == "batch":
                        orchestrator.record_analytics_event(
                            "text_completion_batched",
                            {
                                "endpoint_path": "/v1/completions",
                                "actor_scope": "inference",
                                "status_code": 202,
                                "batch_job_id": result.get("job_id"),
                                "batch_backend": result.get("backend"),
                                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            },
                        )
                        self._send(result, 202)
                        return
                    orchestrator.record_analytics_event(
                        "text_completion_requested",
                        {
                            "endpoint_path": "/v1/completions",
                            "actor_scope": "inference",
                            "status_code": 200,
                            "run_mode": "route",
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        },
                    )
                    self._send(text_completion_response(
                        result, model=model_name, usage=result.get("usage"),
                    ))
                    return
                if path == "/v1/chat/completions":
                    _reject_unknown_keys(body, ALLOWED_CHAT_KEYS)
                    if "functions" in body or "function_call" in body:
                        # OpenAI deprecated functions/function_call in favor of tools/tool_choice.
                        # Fail closed with a migration message rather than silent passthrough of
                        # a deprecated surface clients may still send from old SDKs.
                        raise RequestError(
                            400,
                            "invalid_functions",
                            "functions and function_call are not supported on /v1/chat/completions; "
                            "use tools and tool_choice instead",
                        )
                    if "tool_choice" in body and "tools" not in body:
                        # tool_choice alone is invalid without tools definitions.
                        raise RequestError(
                            400,
                            "invalid_tool_choice",
                            "tool_choice requires tools on /v1/chat/completions",
                        )
                    # Shape-check tool results before passthrough or orchestration.
                    _validate_chat_tool_message_ids(body)
                    _validate_chat_assistant_tool_calls(body)
                    if "response_format" in body:
                        _validate_chat_response_format(body)
                    if "tools" in body:
                        _validate_chat_tools(body)
                    if "tool_choice" in body:
                        _validate_chat_tool_choice(body)
                    if "parallel_tool_calls" in body:
                        # Always type-check. With tools, true/false both valid for
                        # provider passthrough; without tools, true fails closed.
                        ptc = body.get("parallel_tool_calls")
                        if not isinstance(ptc, bool):
                            raise RequestError(
                                400,
                                "invalid_parallel_tool_calls",
                                "parallel_tool_calls must be a boolean",
                            )
                        if ptc is True and "tools" not in body:
                            raise RequestError(
                                400,
                                "invalid_parallel_tool_calls",
                                "parallel_tool_calls=true requires tools on /v1/chat/completions",
                            )
                    if PASSTHROUGH_TRIGGER_KEYS & set(body):
                        # response_format / tools cannot be merged across agents;
                        # proxy the full request to one agent and return it verbatim.
                        started_at = time.perf_counter()
                        proxied = self._run(
                            lambda: orchestrator.proxy_completion(body, endpoint="chat/completions")
                        )
                        orchestrator.record_analytics_event(
                            "chat_completion_passthrough",
                            {
                                "endpoint_path": "/v1/chat/completions",
                                "actor_scope": "inference",
                                "status_code": 200,
                                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            },
                        )
                        self._send(proxied)
                        return
                    messages = _validate_messages(body.get("messages"))
                    mode = _validate_mode(body.get("orchestration") or body.get("orchestration_mode") or body.get("mode") or "auto")
                    if "include_orchestration_trace" in body:
                        include_trace_raw = body.get("include_orchestration_trace")
                        if not isinstance(include_trace_raw, bool):
                            raise RequestError(
                                400,
                                "invalid_include_orchestration_trace",
                                "include_orchestration_trace must be a boolean",
                            )
                        include_trace = include_trace_raw
                    else:
                        include_trace = bool(security.expose_trace_by_default)
                    stream = body.get("stream", False)
                    if not isinstance(stream, bool):
                        raise RequestError(400, "invalid_request", "stream must be a boolean")
                    if "stream_options" in body:
                        _validate_chat_stream_options(body, stream)
                    attribution = _validate_attribution(body.get("attribution"))
                    routing = _validate_routing(body.get("routing"))
                    model_name = str(body.get("model", "contextual-orchestrator"))
                    attribution = dict(attribution or {})
                    # OpenAI chat ``user`` → account when unset.
                    # Same fail-closed rules as Completions: present key must be a
                    # non-empty string ≤64 chars (null/empty/non-string rejected).
                    end_user_id = _validate_completions_user(body)
                    if end_user_id is not None and not attribution.get("account"):
                        attribution["account"] = end_user_id
                    if model_name and not attribution.get("model_name"):
                        attribution["model_name"] = model_name
                    if not attribution.get("service"):
                        attribution["service"] = "chat_completions_api"
                    temperature = None
                    top_p = None
                    max_tokens = None
                    presence_penalty = None
                    frequency_penalty = None
                    if "temperature" in body:
                        temperature = _validate_completions_temperature(body)
                    if "top_p" in body:
                        top_p = _validate_completions_top_p(body)
                    # OpenAI: max_completion_tokens takes precedence over max_tokens.
                    if "max_completion_tokens" in body:
                        max_tokens = _validate_chat_max_completion_tokens(body)
                    elif "max_tokens" in body:
                        max_tokens = _validate_completions_max_tokens(body)
                    if "presence_penalty" in body:
                        presence_penalty = _validate_completions_presence_penalty(body)
                    if "frequency_penalty" in body:
                        frequency_penalty = _validate_completions_frequency_penalty(body)
                    if "seed" in body:
                        # Type-check then fail closed: chat route does not apply seed.
                        _validate_completions_seed(body)
                        raise RequestError(
                            400,
                            "invalid_seed",
                            "seed is not supported on /v1/chat/completions",
                        )
                    if "logit_bias" in body:
                        # Empty {} is an honest no-op (shared Completions helper).
                        # Non-empty maps fail closed with a chat-path message.
                        try:
                            _validate_completions_logit_bias(body)
                        except RequestError as exc:
                            if (
                                exc.code == "invalid_logit_bias"
                                and "not supported" in exc.message
                            ):
                                raise RequestError(
                                    400,
                                    "invalid_logit_bias",
                                    "logit_bias is not supported on /v1/chat/completions",
                                ) from exc
                            raise
                    if "stop" in body:
                        try:
                            _validate_completions_stop(body)
                        except RequestError as exc:
                            # Completions helper fails closed with a Completions path message;
                            # re-surface for chat with the chat endpoint string.
                            if exc.code == "invalid_stop" and "not supported" in exc.message:
                                raise RequestError(
                                    400,
                                    "invalid_stop",
                                    "stop sequences are not supported on /v1/chat/completions",
                                ) from exc
                            raise
                        raise RequestError(
                            400,
                            "invalid_stop",
                            "stop sequences are not supported on /v1/chat/completions",
                        )
                    if "n" in body:
                        try:
                            _validate_completions_n(body)
                        except RequestError as exc:
                            if exc.code == "invalid_n" and "not supported" in exc.message:
                                raise RequestError(
                                    400,
                                    "invalid_n",
                                    "n greater than 1 is not supported on /v1/chat/completions",
                                ) from exc
                            raise
                    if "logprobs" in body or "top_logprobs" in body:
                        # Chat route path does not return token logprobs; fail closed.
                        if "logprobs" in body:
                            lp = body.get("logprobs")
                            if not isinstance(lp, bool):
                                raise RequestError(400, "invalid_logprobs", "logprobs must be a boolean")
                            if lp is True:
                                raise RequestError(
                                    400,
                                    "invalid_logprobs",
                                    "logprobs=true is not supported on /v1/chat/completions",
                                )
                        if "top_logprobs" in body:
                            raise RequestError(
                                400,
                                "invalid_top_logprobs",
                                "top_logprobs is not supported on /v1/chat/completions",
                            )
                    if "store" in body:
                        _validate_chat_store(body)
                    if "service_tier" in body:
                        _validate_service_tier(body, endpoint_path="/v1/chat/completions")
                    if "modalities" in body:
                        _validate_chat_modalities(body)
                    started_at = time.perf_counter()
                    model_client = orchestrator.client
                    previous_max_tokens = model_client.max_output_tokens
                    previous_temperature = model_client.default_temperature
                    previous_top_p = model_client.default_top_p
                    previous_presence = model_client.default_presence_penalty
                    previous_frequency = model_client.default_frequency_penalty
                    if max_tokens is not None:
                        model_client.max_output_tokens = max_tokens
                    if temperature is not None:
                        model_client.default_temperature = temperature
                    if top_p is not None:
                        model_client.default_top_p = top_p
                    if presence_penalty is not None:
                        model_client.default_presence_penalty = presence_penalty
                    if frequency_penalty is not None:
                        model_client.default_frequency_penalty = frequency_penalty
                    try:
                        if stream and orchestrator.would_route(messages, mode):
                            self._stream_route_completion(orchestrator, security, messages, model_name)
                            orchestrator.record_analytics_event(
                                "chat_completion_requested",
                                {
                                    "endpoint_path": "/v1/chat/completions",
                                    "actor_scope": "inference",
                                    "status_code": 200,
                                    "run_mode": "route",
                                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                                    "response_streamed": True,
                                },
                            )
                            return
                        result = self._run(lambda: coordinator.complete(
                            messages,
                            mode=mode,
                            attribution=attribution,
                            hints=routing,
                            model_name=model_name,
                            workflow_run_id=f"run_{uuid.uuid4().hex}",
                        ))
                    finally:
                        model_client.max_output_tokens = previous_max_tokens
                        model_client.default_temperature = previous_temperature
                        model_client.default_top_p = previous_top_p
                        model_client.default_presence_penalty = previous_presence
                        model_client.default_frequency_penalty = previous_frequency
                    # Latency-tolerant requests get dispatched to the batch backend.
                    if result.get("channel") == "batch":
                        orchestrator.record_analytics_event(
                            "chat_completion_batched",
                            {
                                "endpoint_path": "/v1/chat/completions",
                                "actor_scope": "inference",
                                "status_code": 202,
                                "batch_job_id": result["job_id"],
                                "batch_backend": result["backend"],
                            },
                        )
                        self._send(result, 202)
                        return
                    orchestrator.record_analytics_event(
                        "chat_completion_requested",
                        {
                            "endpoint_path": "/v1/chat/completions",
                            "actor_scope": "inference",
                            "status_code": 200,
                            "run_mode": result["mode"],
                            "workflow_run_id": result["workflow_run_id"],
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            "response_streamed": stream,
                        },
                    )
                    if stream:
                        chunks = chat_completion_chunks(result, model=model_name, include_trace=include_trace)
                        self._send_sse(sse_stream_body(chunks))
                        return
                    self._send(chat_completion_response(
                        result, model=model_name, include_trace=include_trace, usage=result.get("usage"),
                    ))
                    return
                if path == "/v1/batch/embeddings":
                    _reject_unknown_keys(body, ALLOWED_EMBEDDINGS_BATCH_KEYS)
                    inputs = _validate_embeddings_inputs(body)
                    model_name = str(body.get("model", "contextual-orchestrator"))
                    attribution = _embeddings_attribution(body)
                    submit_metadata: dict[str, Any] = {"actor_scope": "inference"}
                    endpoint_alias = body.get("endpoint")
                    if endpoint_alias:
                        submit_metadata["endpoint_alias"] = str(endpoint_alias)
                    document = self._run(lambda: coordinator.complete_embeddings_batch(
                        inputs,
                        model=model_name,
                        attribution=attribution,
                        metadata=submit_metadata,
                    ))
                    is_complete = document.get("status") == "completed"
                    orchestrator.record_analytics_event(
                        "embeddings_batch_created",
                        {
                            "endpoint_path": "/v1/batch/embeddings",
                            "actor_scope": "inference",
                            "status_code": 200 if is_complete else 202,
                            "batch_id": document.get("batch_id"),
                            "batch_backend": document.get("backend"),
                            "input_count": len(inputs),
                        },
                    )
                    self._send(document, 200 if is_complete else 202)
                    return
                if path == "/api/v1/batch_routing_jobs":
                    _reject_unknown_keys(body, ALLOWED_BATCH_KEYS)
                    batch_requests = _validate_batch_requests(body, security.expose_trace_by_default)
                    metadata = {"actor_scope": "inference"}
                    job = self._run(lambda: coordinator.submit_batch(batch_requests, metadata=metadata))
                    orchestrator.record_analytics_event(
                        "batch_routing_job_created",
                        {
                            "endpoint_path": "/api/v1/batch_routing_jobs",
                            "actor_scope": "inference",
                            "status_code": 201,
                            "batch_job_id": job.job_id,
                            "batch_backend": job.backend,
                            "request_count": job.request_count,
                        },
                    )
                    self._send({
                        "job_id": job.job_id,
                        "backend": job.backend,
                        "status": job.status,
                        "request_count": job.request_count,
                    }, 201)
                    return
                if path.startswith("/api/v1/batch_routing_jobs/") and path.endswith("/results"):
                    job_id = path[len("/api/v1/batch_routing_jobs/"):-len("/results")]
                    try:
                        retrieved = self._run(lambda: coordinator.retrieve_batch(job_id))
                    except KeyError:
                        self._send_error(404, "batch_job_not_found", f"batch job {job_id} not found")
                        return
                    self._send(_response_payload(retrieved, include_trace=True))
                    return
                if path == "/v1/responses":
                    # The Responses API has no chat-completions verifier equivalent,
                    # so every request is proxied to one agent verbatim.
                    _reject_unknown_keys(body, ALLOWED_RESPONSES_KEYS)
                    started_at = time.perf_counter()
                    proxied = self._run(
                        lambda: orchestrator.proxy_completion(body, endpoint="responses")
                    )
                    orchestrator.record_analytics_event(
                        "responses_passthrough",
                        {
                            "endpoint_path": "/v1/responses",
                            "actor_scope": "inference",
                            "status_code": 200,
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        },
                    )
                    self._send(proxied)
                    return

                if path == "/admin/simulate":
                    _reject_unknown_keys(body, ALLOWED_SIMULATE_KEYS)
                    prompt = body.get("prompt", "")
                    if not isinstance(prompt, str):
                        raise RequestError(400, "invalid_request", "prompt must be a string")
                    mode = _validate_mode(body.get("mode", "auto"))
                    include_trace = bool(body.get("include_orchestration_trace", security.expose_trace_by_default))
                    result = self._run(lambda: orchestrator.run([{"role": "user", "content": prompt}], mode=mode))
                    self._send(_response_payload(result, include_trace))
                    return
                if path == "/api/v1/workflow_runs":
                    _reject_unknown_keys(body, ALLOWED_WORKFLOW_KEYS)
                    prompt = body.get("prompt_text", "")
                    if not isinstance(prompt, str) or not prompt:
                        raise RequestError(400, "invalid_request", "prompt_text is required")
                    mode = _validate_mode(body.get("run_mode", "auto"))
                    include_trace = bool(body.get("include_orchestration_trace", security.expose_trace_by_default))
                    result = self._run(lambda: orchestrator.run([{"role": "user", "content": prompt}], mode=mode))
                    self._send(_response_payload(result, include_trace), 201)
                    return
                if path == "/api/v1/evaluation_runs":
                    _reject_unknown_keys(body, ALLOWED_EVALUATION_KEYS)
                    prompts = body.get("prompts")
                    if prompts is None and "prompt_text" in body:
                        prompts = [body["prompt_text"]]
                    if not isinstance(prompts, list) or not prompts:
                        raise RequestError(400, "invalid_request", "prompts must be a non-empty array")
                    mode = _validate_mode(body.get("run_mode", "auto"))
                    include_trace = bool(body.get("include_orchestration_trace", security.expose_trace_by_default))
                    evaluation_run = self._run(lambda: orchestrator.run_evaluation([str(item) for item in prompts], mode=mode))
                    self._send(_response_payload(evaluation_run, include_trace), 201)
                    return
                self._send_error(404, "route_not_found", "not found")
            except json.JSONDecodeError:
                self._send_error(400, "invalid_json", "request body is not valid JSON")
            except BudgetExceededError as exc:
                self._send_error(429, "budget_exceeded", str(exc), exc.detail)
            except RequestError as exc:
                self._send_error(exc.status, exc.code, exc.message, exc.detail)
            except (TypeError, ValueError) as exc:
                self._send_error(400, "invalid_request", str(exc))
            except Exception:
                self._send_error(500, "internal_error", "internal server error")

        def _authorize(self, scope: str) -> None:
            security.check_rate_limit(self.client_address[0])
            security.authorize(self.headers, scope, self.client_address[0])

        def _run(self, callback: Any) -> dict[str, Any]:
            security.acquire_run_slot()
            try:
                return callback()
            finally:
                security.release_run_slot()

        def _parse_positive_int(self, raw: str | None, field_name: str, default: int, max_value: int | None = None) -> int:
            value = default if raw is None else int(raw)
            if value < 1:
                raise ValueError(f"{field_name} must be >= 1")
            if max_value is not None and value > max_value:
                raise ValueError(f"{field_name} must be <= {max_value}")
            return value

        def _parse_paging(
            self,
            query: dict[str, list[str]],
            default_size: int = 10,
            max_size: int = 100,
        ) -> tuple[int, int]:
            page_number = self._parse_positive_int((query.get("page_number") or [None])[0], "page_number", 1)
            page_size = self._parse_positive_int((query.get("page_size") or [None])[0], "page_size", default_size, max_size)
            return page_number, page_size

        def _parse_optional_int(self, query: dict[str, list[str]], field_name: str) -> int | None:
            raw = (query.get(field_name) or [None])[0]
            if raw is None or raw == "":
                return None
            return int(raw)

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise RequestError(415, "unsupported_media_type", "content-type must be application/json")
            body_size = int(self.headers.get("content-length", "0"))
            if body_size > security.max_body_bytes:
                raise RequestError(413, "request_too_large", "request body exceeds configured limit")
            raw = self.rfile.read(body_size)
            return _coerce_json(raw) if raw else {}

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_error(
            self,
            status: int,
            code: str,
            message: str,
            detail: dict[str, Any] | None = None,
        ) -> None:
            self._send(_error_payload(code, message, {"request_id": uuid.uuid4().hex, **(detail or {})}), status)

        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(raw)

        def _send_text(self, payload: str, content_type: str, status: int = 200) -> None:
            raw = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(raw)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(raw)

        def _send_sse(self, body: str, status: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache")
            self.send_header("content-length", str(len(raw)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(raw)

        def _begin_sse(self) -> None:
            # Incremental SSE: no content-length; the connection close delimits the body.
            self.send_response(200)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self._send_security_headers()
            self.end_headers()

        def _write_sse(self, frame: str) -> None:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

        def _stream_route_completion(self, orchestrator: Any, security: Any, messages: Any, model_name: str) -> None:
            """Pipe a worker's live deltas out as OpenAI chat.completion.chunk SSE frames."""
            run_id = f"run_{uuid.uuid4().hex}"
            completion_id = f"chatcmpl-{int(time.time() * 1000)}"
            created = int(time.time())

            def frame(delta: dict[str, Any], finish: str | None = None) -> str:
                payload = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            security.acquire_run_slot()
            try:
                self._begin_sse()
                self._write_sse(frame({"role": "assistant"}))
                try:
                    for delta in orchestrator.stream_route(messages, workflow_run_id=run_id):
                        self._write_sse(frame({"content": delta}))
                    self._write_sse(frame({}, finish="stop"))
                except Exception:  # noqa: BLE001 - headers already sent; surface as a terminal error frame
                    self._write_sse(frame({}, finish="error"))
                self._write_sse("data: [DONE]\n\n")
            finally:
                security.release_run_slot()

        def _send_security_headers(self) -> None:
            self.send_header("x-content-type-options", "nosniff")
            self.send_header("referrer-policy", "no-referrer")
            self.send_header("cache-control", "no-store")
            self.send_header("x-frame-options", "DENY")

    return ThreadingHTTPServer((host, port), Handler)


def serve(
    orchestrator: TaskOrchestrator,
    host: str = "127.0.0.1",
    port: int = 8000,
    security: SecurityConfig | None = None,
    clearfolio_url: str | None = None,
) -> None:
    """Serve the admin console and resource-oriented orchestration API."""
    server = build_server(orchestrator, host=host, port=port, security=security, clearfolio_url=clearfolio_url)
    print(f"listening on http://{host}:{port}")
    server.serve_forever()
