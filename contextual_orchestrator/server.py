from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import uuid
from urllib.parse import urlparse

from .admin import ADMIN_HTML, ADMIN_TRANSLATIONS
from .api_contract import OPENAPI_SPEC
from .orchestrator import TaskOrchestrator, chat_completion_response


def serve(orchestrator: TaskOrchestrator, host: str = "127.0.0.1", port: int = 8000) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
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
                agents = orchestrator.admin_state()["agents"]
                self._send({"items": agents, "total_count": len(agents)})
                return
            if path == "/api/v1/orchestration_policies/default_policy":
                self._send(orchestrator.admin_state()["policy"])
                return
            if path.startswith("/api/v1/locale_bundles/"):
                locale_code = path.rsplit("/", 1)[-1]
                bundle = ADMIN_TRANSLATIONS.get(locale_code)
                self._send({"locale_code": locale_code, "messages": bundle} if bundle else {"error": "not found"}, 200 if bundle else 404)
                return
            self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                size = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(size).decode("utf-8"))
                if path == "/v1/chat/completions":
                    result = orchestrator.complete(body.get("messages", []), mode=body.get("orchestration", "auto"))
                    self._send(chat_completion_response(result, model=body.get("model", "contextual-orchestrator")))
                    return
                if path == "/admin/simulate":
                    prompt = body.get("prompt", "")
                    result = orchestrator.complete([{"role": "user", "content": prompt}], mode=body.get("mode", "auto"))
                    self._send(result)
                    return
                if path == "/api/v1/workflow_runs":
                    result = orchestrator.complete(
                        [{"role": "user", "content": body.get("prompt_text", "")}],
                        mode=body.get("run_mode", "auto"),
                    )
                    result["workflow_run_id"] = f"run_{uuid.uuid4().hex}"
                    self._send(result, 201)
                    return
                self._send({"error": "not found"}, 404)
            except Exception as exc:  # ponytail: tiny server, swap for ASGI if production hardening matters.
                self._send({"error": str(exc)}, 500)

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
