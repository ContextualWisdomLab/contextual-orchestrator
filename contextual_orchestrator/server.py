"""HTTP server exposing chat, admin, governance, and evaluation endpoints."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import urllib.parse
from typing import Any
import uuid

from .admin import ADMIN_HTML, ADMIN_TRANSLATIONS
from .api_contract import OPENAPI_SPEC
from .orchestrator import TaskOrchestrator, chat_completion_response


def _error_payload(error_code: str, error_message: str, error_detail: dict[str, Any] | str | None = None) -> dict[str, Any]:
    return {
        "error_code": error_code,
        "error_message": error_message,
        "error_detail": error_detail if isinstance(error_detail, dict) else {},
    }


def _coerce_json(payload: bytes) -> dict[str, Any]:
    return json.loads(payload.decode("utf-8"))


def serve(orchestrator: TaskOrchestrator, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the admin console and resource-oriented orchestration API."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if path in ("/", "/admin"):
                    self._send_text(ADMIN_HTML, "text/html; charset=utf-8")
                    return
                if path == "/admin/state":
                    self._send(orchestrator.admin_state())
                    return
                if path == "/openapi.json":
                    self._send(OPENAPI_SPEC)
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
                if path == "/api/v1/workflow_runs":
                    page_number, page_size = self._parse_paging(query, default_size=20, max_size=200)
                    self._send({
                        "items": orchestrator.list_recent_runs(page_number=page_number, page_size=page_size),
                        "total_count": len(getattr(orchestrator, "_workflow_runs", {})),
                        "page_number": page_number,
                        "page_size": page_size,
                    })
                    return
                if path.startswith("/api/v1/workflow_runs/"):
                    workflow_run_id = path.rsplit("/", 1)[-1]
                    try:
                        self._send(orchestrator.get_workflow_run(workflow_run_id))
                        return
                    except KeyError:
                        self._send(_error_payload("workflow_run_not_found", f"workflow_run {workflow_run_id} not found"), 404)
                        return
                if path.startswith("/api/v1/access_reports/"):
                    workflow_run_id = path.rsplit("/", 1)[-1]
                    try:
                        self._send(orchestrator.get_access_report(workflow_run_id))
                        return
                    except KeyError:
                        self._send(_error_payload("workflow_run_not_found", f"workflow_run {workflow_run_id} not found"), 404)
                        return
                if path.startswith("/api/v1/evaluation_runs/"):
                    evaluation_run_id = path.rsplit("/", 1)[-1]
                    runs = getattr(orchestrator, "_evaluation_runs", {})
                    if evaluation_run_id in runs:
                        self._send(runs[evaluation_run_id])
                        return
                    self._send(_error_payload("evaluation_run_not_found", f"evaluation_run {evaluation_run_id} not found"), 404)
                    return
                if path.startswith("/api/v1/agent_pools/"):
                    segments = [part for part in path.split("/") if part]
                    if len(segments) == 6 and segments[0] == "api" and segments[1] == "v1" and segments[2] == "agent_pools" and segments[4] == "worker_agents":
                        agent_pool_id = segments[3]
                        worker_agent_id = segments[-1]
                        try:
                            payload = orchestrator._agent_to_admin_payload(orchestrator._agent(worker_agent_id))
                            payload["agent_pool_id"] = agent_pool_id
                            self._send(payload)
                            return
                        except KeyError:
                            self._send(_error_payload("agent_not_found", f"agent {worker_agent_id} not found"), 404)
                            return
                        except Exception:
                            self._send(_error_payload("agent_pool_not_found", f"agent_pool {agent_pool_id} not found"), 404)
                            return
                    self._send(_error_payload(
                        "bad_path",
                        "agent path must be /api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}",
                    ), 400)
                    return
                if path.startswith("/api/v1/locale_bundles/"):
                    locale_code = path.rsplit("/", 1)[-1]
                    bundle = ADMIN_TRANSLATIONS.get(locale_code)
                    if not bundle:
                        self._send(_error_payload("locale_not_found", f"locale {locale_code} not found"), 404)
                        return
                    self._send({"locale_code": locale_code, "messages": bundle})
                    return
                self._send(_error_payload("route_not_found", "not found"), 404)
            except (TypeError, ValueError) as exc:
                self._send(_error_payload("invalid_request", str(exc)), 400)

        def do_PATCH(self) -> None:  # noqa: N802
            try:
                path = urllib.parse.urlparse(self.path).path
                if path.startswith("/api/v1/agent_pools/") and "/worker_agents/" in path:
                    segments = [part for part in path.split("/") if part]
                    if len(segments) != 6 or segments[0] != "api" or segments[1] != "v1" or segments[2] != "agent_pools" or segments[4] != "worker_agents":
                        self._send(_error_payload("bad_path", "agent patch path missing worker agent"), 400)
                        return
                    agent_pool_id = segments[3]
                    worker_agent_id = segments[-1]
                    body = self._read_json()
                    updated = orchestrator.patch_agent(agent_pool_id, worker_agent_id, body)
                    self._send(updated, 200)
                    return
                self._send(_error_payload("route_not_found", "not found"), 404)
            except (ValueError, TypeError) as exc:
                self._send(_error_payload("invalid_request", str(exc)), 400)
            except KeyError as exc:
                self._send(_error_payload("resource_not_found", str(exc)), 404)
            except Exception as exc:
                self._send(_error_payload("internal_error", str(exc)), 500)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urllib.parse.urlparse(self.path).path
                size = int(self.headers.get("content-length", "0"))
                body = self._read_json(size)

                if path == "/v1/chat/completions":
                    messages = body.get("messages", [])
                    if not isinstance(messages, list):
                        self._send(_error_payload("invalid_request", "messages must be an array"), 400)
                        return
                    mode = body.get("orchestration") or body.get("orchestration_mode") or body.get("mode") or "auto"
                    result = orchestrator.run(messages, mode=mode, workflow_run_id=f"run_{uuid.uuid4().hex}")
                    self._send(chat_completion_response(result, model=body.get("model", "contextual-orchestrator")))
                    return
                if path == "/admin/simulate":
                    prompt = body.get("prompt", "")
                    result = orchestrator.run([{"role": "user", "content": prompt}], mode=body.get("mode", "auto"))
                    self._send(result)
                    return
                if path == "/api/v1/workflow_runs":
                    prompt = body.get("prompt_text", "")
                    if not isinstance(prompt, str):
                        self._send(_error_payload("invalid_request", "prompt_text is required"), 400)
                        return
                    result = orchestrator.run([{"role": "user", "content": prompt}], mode=body.get("run_mode", "auto"))
                    self._send(result, 201)
                    return
                if path == "/api/v1/evaluation_runs":
                    prompts = body.get("prompts")
                    if prompts is None and "prompt_text" in body:
                        prompts = [body["prompt_text"]]
                    if not isinstance(prompts, list) or not prompts:
                        self._send(_error_payload("invalid_request", "prompts must be a non-empty array"), 400)
                        return
                    evaluation_run = orchestrator.run_evaluation([str(item) for item in prompts], mode=body.get("run_mode", "auto"))
                    self._send(evaluation_run, 201)
                    return
                self._send(_error_payload("route_not_found", "not found"), 404)
            except json.JSONDecodeError as exc:
                self._send(_error_payload("invalid_json", str(exc)), 400)
            except (TypeError, ValueError) as exc:
                self._send(_error_payload("invalid_request", str(exc)), 400)
            except Exception as exc:
                self._send(_error_payload("internal_error", str(exc)), 500)

        def _parse_positive_int(self, raw: str | None, field_name: str, default: int, max_value: int | None = None) -> int:
            if raw is None:
                value = default
            else:
                value = int(raw)
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

        def _read_json(self, size: int | None = None) -> dict[str, Any]:
            body_size = size if size is not None else int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(body_size)
            return _coerce_json(raw) if raw else {}

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, payload: dict[str, object], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_text(self, payload: str, content_type: str, status: int = 200) -> None:
            raw = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"listening on http://{host}:{port}")
    server.serve_forever()
