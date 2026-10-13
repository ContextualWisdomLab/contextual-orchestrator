"""Opt-in, one-request Experiential billing evidence; never pool admission."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import partial
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import urlencode
import uuid

from .credentials import get_credential
from .openrouter_canary import _write_evidence
from .orchestrator import ModelAgent, ModelClient
from .provider_errors import MAX_PROVIDER_ERROR_BODY_BYTES

API_ORIGIN = "https://api.experientiallabs.ai"
CREDENTIAL_NAME = "EXPERIENTAL_LABS_API_KEY"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")


def _identifier(value: Any, secret: str = "") -> str | None:
    """Retain provider identifiers, never credential echoes or arbitrary prose."""
    if isinstance(value, str) and _IDENTIFIER.fullmatch(value) and not (secret and secret in value):
        return value
    return None


def select_promotion(callable_models: dict, catalog: dict) -> tuple[str, str]:
    """Require exact callable identity in an active, text-capable free promotion.

    No undocumented canonical_slug mapping or provider-prefix stripping is used.
    A nonzero base tariff does not disqualify a literal free promotion.
    """
    rows = callable_models.get("data")
    models = catalog.get("models")
    promotions = catalog.get("promotions")
    if not all(isinstance(value, list) for value in (rows, models, promotions)):
        raise ValueError("model and promotion evidence is unavailable")
    callable_ids = {_identifier(row.get("id")) for row in rows if isinstance(row, dict)}
    active_ids = set()
    for row in models:
        model = row.get("model") if isinstance(row, dict) else None
        if not isinstance(model, dict) or model.get("status") != "active":
            continue
        inputs, outputs = model.get("input_modalities"), model.get("output_modalities")
        if isinstance(inputs, list) and isinstance(outputs, list) and "text" in inputs and "text" in outputs:
            active_ids.add(_identifier(model.get("slug")))
    candidates = []
    for promotion in promotions:
        if not isinstance(promotion, dict) or promotion.get("free") is not True or promotion.get("display_only") is not False:
            continue
        promotion_id, slugs = _identifier(promotion.get("id")), promotion.get("slugs")
        if promotion_id is None or not isinstance(slugs, list):
            continue
        candidates.extend((slug, promotion_id) for slug in slugs
                          if _identifier(slug) is not None and slug in callable_ids and slug in active_ids)
    if not candidates:
        raise ValueError("no callable active free promotion with verified identity")
    if len(candidates) != 1:
        raise ValueError("callable active free promotion identity is ambiguous")
    return candidates[0]


class ResponseBudgetExceeded(ValueError):
    """Operator resource admission failed; this is not evidence of zero cost."""


def _response_budget(value: Any) -> int:
    """Require an explicit operator byte budget, never invent a provider limit."""
    if type(value) is not int or value <= 0:
        raise ValueError("an explicit positive response byte budget is required")
    return value


def _native_response_budget(value: Any) -> int:
    """Admit the existing core error-read envelope before credentials or send.

    This is a transport resource requirement, not a provider price/size policy.
    HTTP error bodies remain ignored; the common ModelClient contract is unchanged.
    """
    budget = _response_budget(value)
    if budget < MAX_PROVIDER_ERROR_BODY_BYTES + 1:
        raise ValueError("native transport byte budget cannot cover core error acquisition")
    return budget


def _read_response(response: Any, budget: int) -> bytes:
    """Bound acquisition to budget plus one sentinel, rejecting partial evidence."""
    headers = getattr(response, "headers", None)
    declared = None
    if headers is not None:
        get_all = getattr(headers, "get_all", None)
        values = get_all("content-length", []) if get_all is not None else [headers.get("content-length")]
        for value in values:
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("invalid response content length")
            for token in value.split(","):
                token = token.strip(" \t")
                if not re.fullmatch(r"[0-9]+", token):
                    raise ValueError("invalid response content length")
                length = int(token)
                if declared is not None and declared != length:
                    raise ValueError("conflicting response content length")
                declared = length
    if declared is not None and declared > budget:
        raise ResponseBudgetExceeded("response exceeds operator byte budget")
    # No compatibility fallback to unbounded read(), even for adapters.
    raw = response.read(budget + 1)
    if len(raw) > budget:
        raise ResponseBudgetExceeded("response exceeds operator byte budget")
    if declared is not None and len(raw) != declared:
        raise ValueError("incomplete response body")
    return raw


def _request(
    method: str, route: str, payload: dict | None = None, *,
    response_max_bytes: int | None = None,
) -> tuple[int, dict, dict]:
    """One bounded, DNS-pinned TLS operation; no redirects, retries or fallback."""
    budget = _native_response_budget(response_max_bytes)
    if method not in {"GET", "POST"} or not route.startswith("/") or route.startswith("//"):
        raise ValueError("unsupported probe operation")
    secret = get_credential(CREDENTIAL_NAME)
    if not secret:
        raise ValueError("probe credential is unavailable")
    client = ModelClient(timeout=None, max_retries=0)
    agent = ModelAgent("billing_probe", "billing-probe", base_url=API_ORIGIN, credential_key=CREDENTIAL_NAME)
    destination = client._validate_provider(agent)
    headers = {"accept": "application/json", "content-type": "application/json"}
    # Catalog reads are public; credentials go only to the documented org-scoped API.
    if not route.startswith("/api/models"):
        headers["authorization"] = "Bearer " + secret
    request = urllib.request.Request(API_ORIGIN + route, method=method, headers=headers,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None)
    try:
        with client._open_provider(request, destination, timeout=None) as response:
            status = response.status
            response_headers = {"x-request-id": response.getheader("x-request-id")}
            raw = _read_response(response, budget)
    except urllib.error.HTTPError as error:
        status = error.code
        response_headers = {"x-request-id": error.headers.get("x-request-id")}
        try:
            error.close()
        except Exception:
            # The consumed HTTPError outcome owns ordinary cleanup failures.
            # BaseException remains caller-visible; no inference is replayed.
            pass
        return status, response_headers, {}
    body = json.loads(raw, parse_float=Decimal)
    if not isinstance(body, dict):
        raise ValueError("probe response is not an object")
    return status, response_headers, body


def _sync(path: Path) -> None:
    """Flush both evidence bytes and its directory entry before any send."""
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _persist(path: Path, evidence: dict) -> None:
    """Reuse atomic evidence publication and add the probe's durability boundary."""
    _write_evidence(path, evidence)
    _sync(path)


def _money(value: Any) -> Decimal | None:
    """Parse exact finite nonnegative USD; missing/invalid costs remain unknown."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _money_text(value: Any) -> str | None:
    """Serialize validated USD decimals losslessly, without context rounding."""
    amount = _money(value)
    return str(amount) if amount is not None else None


def _get(request: Callable, route: str) -> dict:
    status, _, body = request("GET", route)
    if type(status) is not int or not 200 <= status < 300 or not isinstance(body, dict):
        raise ValueError("probe metadata is unavailable")
    return body


def _catalog(request: Callable) -> dict:
    """Follow the provider-declared catalog pages; reject incomplete coverage."""
    body = _get(request, "/api/models")
    total, limit, offset = body.get("total"), body.get("limit"), body.get("offset")
    rows = body.get("models")
    if (type(total) is not int or total < 0 or type(limit) is not int or limit <= 0
            or offset != 0 or not isinstance(rows, list)
            or len(rows) != min(limit, total)):
        raise ValueError("catalog pagination is unavailable")
    models = list(rows)
    promotions = body.get("promotions")
    if not isinstance(promotions, list):
        raise ValueError("catalog promotions are unavailable")
    while len(models) < total:
        offset = len(models)
        body = _get(request, "/api/models?" + urlencode({"limit": limit, "offset": offset}))
        rows = body.get("models")
        if (body.get("total") != total or body.get("limit") != limit
                or body.get("offset") != offset or not isinstance(rows, list)
                or len(rows) != min(limit, total - offset)):
            raise ValueError("catalog pagination is incomplete")
        if not isinstance(body.get("promotions"), list) or body["promotions"] != promotions:
            raise ValueError("catalog promotions are inconsistent")
        models.extend(rows)
    return {"models": models, "promotions": promotions}


def _settled_charge(request: Callable, label: str, secret: str) -> Decimal | None:
    """Accept one priced, exactly attributed row only after complete pagination."""
    query = {"limit": 1000, "attribution_label": label}
    matches = []
    seen_cursors = set()
    while True:
        body = _get(request, "/api/v1/usage?" + urlencode(query))
        rows = body.get("data")
        if not isinstance(rows, list) or len(rows) > 1000 or "next_cursor" not in body:
            return None
        matches.extend(row for row in rows if isinstance(row, dict) and row.get("attribution_label") == label)
        if len(matches) > 1:
            return None
        cursor = body["next_cursor"]
        if cursor is None:
            if len(matches) != 1 or matches[0].get("pricing_known") is not True:
                return None
            if _identifier(matches[0].get("id"), secret) is None:
                return None
            return _money(matches[0].get("cost_usd"))
        if not isinstance(cursor, dict) or set(cursor) != {"cursor_ts", "cursor_id", "cursor_after"}:
            return None
        if any(not isinstance(value, (str, int, bool)) for value in cursor.values()):
            return None
        encoded = urlencode(cursor)
        if encoded in seen_cursors:
            return None
        seen_cursors.add(encoded)
        query.update(cursor)


def run_probe(
    path: Path, *, source_sha: str, run_id: str, run_attempt: str,
    request: Callable = _request, response_max_bytes: int | None = None,
) -> dict[str, Any]:
    """Reserve one attempt, send one synthetic request, then read correlated costs.

    A reservation is never expired, removed or reclaimed here. Ambiguous outcomes
    and Actions reruns cannot replay an inference. Receipts are observed once.
    """
    if run_attempt != "1":
        raise ValueError("billing probe runs only on the first attempt")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("probe provenance is invalid")
    if request is _request:
        response_max_bytes = _native_response_budget(response_max_bytes)
        request = partial(_request, response_max_bytes=response_max_bytes)
    secret = get_credential(CREDENTIAL_NAME)
    if not secret:
        raise ValueError("probe credential is unavailable")
    path = Path(path)
    evidence = {"schema_version": 2, "provider": "experiential_labs", "source_sha": source_sha,
        "run_id": run_id, "run_attempt": run_attempt, "started_at": int(time.time()),
        "attribution_label": "co-billing-" + run_id + "-" + uuid.uuid4().hex,
        "request_count": 0, "outcome": "preflight_pending",
        "response_cost_usd": None, "generation_total_cost_usd": None, "ledger_charge_usd": None,
        "cost_comparison": "unknown", "currency": "USD",
        "response_max_bytes": response_max_bytes, "response_resource_admission": "not_exceeded"}
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("billing evidence already exists; no request was replayed") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    _sync(path)
    try:
        model_id, promotion_id = select_promotion(_get(request, "/v1/models"), _catalog(request))
        if _identifier(model_id, secret) is None or _identifier(promotion_id, secret) is None:
            raise ValueError("probe model identity is invalid")
    except Exception as exc:
        if isinstance(exc, ResponseBudgetExceeded):
            evidence["response_resource_admission"] = "exceeded"
        evidence["outcome"] = "preflight_failed"
        _persist(path, evidence)
        raise ValueError("billing discovery did not establish an eligible promotion") from None
    evidence.update(model_id=model_id, promotion_id=promotion_id, request_count=1, outcome="attempt_pending")
    _persist(path, evidence)
    payload = {"model": model_id, "messages": [{"role": "user", "content": "Reply OK."}],
        "safety_identifier": evidence["attribution_label"]}
    try:
        status, headers, body = request("POST", "/v1/chat/completions", payload)
        evidence["send_outcome"] = "http_response"
    except Exception as exc:
        if isinstance(exc, ResponseBudgetExceeded):
            evidence["response_resource_admission"] = "exceeded"
        evidence["send_outcome"] = "ambiguous"
        evidence["outcome"] = "ambiguous"
        _persist(path, evidence)
        status, headers, body = None, {}, {}
    evidence["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
    evidence["request_id"] = _identifier(headers.get("x-request-id"), secret) if isinstance(headers, dict) else None
    evidence["returned_model"] = _identifier(body.get("model"), secret) if isinstance(body, dict) else None
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        evidence["response_cost_usd"] = _money_text(usage.get("cost"))
        evidence["response_tokens"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(usage.get(key)) is int and usage[key] >= 0}
    evidence["outcome"] = "ambiguous" if evidence["send_outcome"] == "ambiguous" else "charge_unknown"
    _persist(path, evidence)
    request_id = evidence["request_id"]
    if request_id:
        try:
            generation = _get(request, "/api/v1/generation?" + urlencode({"id": request_id})).get("data")
            if isinstance(generation, dict) and generation.get("id") in {request_id, "gen-" + request_id}:
                evidence["generation_total_cost_usd"] = _money_text(generation.get("total_cost"))
        except Exception as exc:
            if isinstance(exc, ResponseBudgetExceeded):
                evidence["response_resource_admission"] = "exceeded"
    try:
        evidence["ledger_charge_usd"] = _money_text(_settled_charge(request, evidence["attribution_label"], secret))
    except Exception as exc:
        if isinstance(exc, ResponseBudgetExceeded):
            evidence["response_resource_admission"] = "exceeded"
    costs = [_money(evidence[key]) for key in ("response_cost_usd", "generation_total_cost_usd", "ledger_charge_usd")]
    if all(cost is not None for cost in costs):
        evidence["cost_comparison"] = "match" if len(set(costs)) == 1 else "mismatch"
    charge = _money(evidence["ledger_charge_usd"])
    if charge is not None:
        evidence["outcome"] = "zero_charge_observed" if charge == 0 else "charge_observed"
    _persist(path, evidence)
    return evidence
