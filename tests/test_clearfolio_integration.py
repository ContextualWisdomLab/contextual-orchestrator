"""Clearfolio document-viewer integration for the admin console.

The admin console can point at a Clearfolio deployment (Java viewer platform:
upload -> async convert -> PDF preview) as its document viewer. Configuration only:
--clearfolio-url; default None keeps the console unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.admin import ADMIN_HTML, ADMIN_TRANSLATIONS  # noqa: E402
from contextual_orchestrator.server import SecurityConfig, build_server  # noqa: E402


def _orch() -> TaskOrchestrator:
    return TaskOrchestrator([ModelAgent("general_agent", "mock-model", tags=("reasoning",))])


def _get_state(server, token: str) -> dict:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/admin/state",
        headers={"authorization": f"Bearer {token}", "connection": "close"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()


def test_state_carries_viewer_config_when_set() -> None:
    server = build_server(_orch(), port=0, security=SecurityConfig(auth_token="t_viewer"),
                          clearfolio_url="https://clearfolio.example.com/")
    state = _get_state(server, "t_viewer")
    assert state["document_viewer"] == {"provider": "clearfolio", "url": "https://clearfolio.example.com"}  # trailing / stripped


def test_state_viewer_null_by_default() -> None:
    server = build_server(_orch(), port=0, security=SecurityConfig(auth_token="t_viewer"))
    state = _get_state(server, "t_viewer")
    assert state["document_viewer"] is None


def test_invalid_viewer_url_rejected() -> None:
    raised = False
    try:
        build_server(_orch(), port=0, security=SecurityConfig(auth_token="t_viewer"), clearfolio_url="ftp://nope")
    except ValueError:
        raised = True
    assert raised


def test_admin_html_has_viewer_card_and_render() -> None:
    assert 'id="docViewerStatus"' in ADMIN_HTML
    assert 'id="docViewerActions"' in ADMIN_HTML
    assert 'id="docViewerOpenDoc"' in ADMIN_HTML
    assert "function renderDocumentViewer()" in ADMIN_HTML
    assert "state.document_viewer" in ADMIN_HTML
    assert "/viewer/" in ADMIN_HTML  # deep-link to Clearfolio's canonical viewer route


def test_viewer_i18n_keys_both_locales() -> None:
    for locale in ("en", "ko"):
        for key in ("doc_viewer_title", "doc_viewer_desc", "doc_viewer_unset", "doc_viewer_open", "doc_viewer_open_doc"):
            assert key in ADMIN_TRANSLATIONS[locale], f"{key} missing in {locale}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
