"""OpenAI embeddings encoding_format, dimensions, and user validation on batch path."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import (  # noqa: E402
    RequestError,
    SecurityConfig,
    _validate_embeddings_dimensions,
    _validate_embeddings_encoding_format,
    _validate_embeddings_user,
    build_server,
)

_TEST_AUTH_TOKEN = "emb_enc_token"  # noqa: S105


def build() -> TaskOrchestrator:
    return TaskOrchestrator(
        [ModelAgent("general_agent", "mock-generalist", tags=("reasoning", "writing"))]
    )


def test_validate_encoding_format_dimensions_user() -> None:
    assert _validate_embeddings_encoding_format({}) is None
    assert _validate_embeddings_encoding_format({"encoding_format": "float"}) == "float"
    assert _validate_embeddings_encoding_format({"encoding_format": "base64"}) == "base64"
    try:
        _validate_embeddings_encoding_format({"encoding_format": "json"})
        raise AssertionError("bad format")
    except RequestError as exc:
        assert exc.code == "invalid_encoding_format"
    assert _validate_embeddings_dimensions({"dimensions": 256}) == 256
    try:
        _validate_embeddings_dimensions({"dimensions": 0})
        raise AssertionError("zero")
    except RequestError as exc:
        assert exc.code == "invalid_dimensions"
    try:
        _validate_embeddings_dimensions({"dimensions": True})
        raise AssertionError("bool")
    except RequestError as exc:
        assert exc.code == "invalid_dimensions"
    assert _validate_embeddings_user({"user": "acct_1"}) == "acct_1"
    try:
        _validate_embeddings_user({"user": ""})
        raise AssertionError("empty user")
    except RequestError as exc:
        assert exc.code == "invalid_user"


def test_http_encoding_format_accepted() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/batch/embeddings",
            data=json.dumps(
                {
                    "input": ["hello"],
                    "model": "mock-embed",
                    "encoding_format": "float",
                    "dimensions": 8,
                    "user": "buyer-1",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status in {200, 202}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_bad_encoding_format_rejected() -> None:
    server = build_server(build(), port=0, security=SecurityConfig(auth_token=_TEST_AUTH_TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/batch/embeddings",
            data=json.dumps(
                {
                    "input": ["hello"],
                    "encoding_format": "hex",
                }
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {_TEST_AUTH_TOKEN}",
                "connection": "close",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"]["code"] == "invalid_encoding_format"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    test_validate_encoding_format_dimensions_user()
    test_http_encoding_format_accepted()
    test_http_bad_encoding_format_rejected()
    print("ok")
