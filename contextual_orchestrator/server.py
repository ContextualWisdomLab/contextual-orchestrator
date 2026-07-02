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
from .orchestrator import TaskOrchestrator, chat_completion_response, redact_value


ALLOWED_CHAT_KEYS = {"model", "messages", "orchestration", "orchestration_mode", "mode", "include_orchestration_trace"}
ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant", "tool"}
ALLOWED_MODES = {"auto", "route", "conduct"}
ALLOWED_SIMULATE_KEYS = {"prompt", "mode", "include_orchestration_trace"}
ALLOWED_WORKFLOW_KEYS = {"prompt_text", "run_mode", "include_orchestration_trace"}
ALLOWED_EVALUATION_KEYS = {"prompts", "prompt_text", "run_mode", "include_orchestration_trace"}
ALLOWED_AGENT_PATCH_KEYS = {"status", "priority", "tags", "provider_exclusions"}


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
        if host in {"0.0.0.0", "::", ""} and not self.allow_public_bind:
            raise ValueError("public bind requires --allow-public-bind")

    def authorize(self, headers: Any, scope: str, client_address: str) -> None:
        """Validate bearer token for admin or inference scope."""
        if not (self.auth_token or self.admin_token or self.inference_token):
            if client_address in {"127.0.0.1", "::1", "localhost"}:
                return
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
            auth_mode = "loopback_no_auth"
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
        if role not in ALLOWED_MESSAGE_ROLES or not isinstance(content, str):
            raise RequestError(400, "invalid_message", "message role or content is invalid")
        validated.append({"role": role, "content": content})
    return validated


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
) -> ThreadingHTTPServer:
    """Build, but do not start, the orchestration HTTP server."""
    security = security or SecurityConfig()
    security.check_bind(host)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if path == "/openapi.json":
                    self._send(OPENAPI_SPEC)
                    return
                self._authorize("admin")
                if path in ("/", "/admin"):
                    self._send_text(ADMIN_HTML, "text/html; charset=utf-8")
                    return
                if path == "/admin/state":
                    self._send(_response_payload(orchestrator.admin_state(), security.expose_trace_by_default))
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

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urllib.parse.urlparse(self.path).path
                scope = "admin" if path == "/admin/simulate" else "inference"
                self._authorize(scope)
                body = self._read_json()

                if path == "/v1/chat/completions":
                    _reject_unknown_keys(body, ALLOWED_CHAT_KEYS)
                    messages = _validate_messages(body.get("messages"))
                    mode = _validate_mode(body.get("orchestration") or body.get("orchestration_mode") or body.get("mode") or "auto")
                    include_trace = bool(body.get("include_orchestration_trace", security.expose_trace_by_default))
                    started_at = time.perf_counter()
                    result = self._run(lambda: orchestrator.run(messages, mode=mode, workflow_run_id=f"run_{uuid.uuid4().hex}"))
                    orchestrator.record_analytics_event(
                        "chat_completion_requested",
                        {
                            "endpoint_path": "/v1/chat/completions",
                            "actor_scope": "inference",
                            "status_code": 200,
                            "run_mode": result["mode"],
                            "workflow_run_id": result["workflow_run_id"],
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        },
                    )
                    self._send(chat_completion_response(result, model=str(body.get("model", "contextual-orchestrator")), include_trace=include_trace))
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
) -> None:
    """Serve the admin console and resource-oriented orchestration API."""
    server = build_server(orchestrator, host=host, port=port, security=security)
    print(f"listening on http://{host}:{port}")
    server.serve_forever()
