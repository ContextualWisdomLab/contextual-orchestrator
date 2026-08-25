"""Deployment contract for the canonical root Compose path."""

from pathlib import Path


def test_compose_uses_postgres_kv_and_secret_bootstrap() -> None:
    compose = Path("compose.yaml").read_text()
    assert "credential_bootstrap:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "CONTEXTUAL_ORCHESTRATOR_KV_BACKEND: postgres" in compose
    assert "--value-stdin < /run/secrets/server_token" in compose
    assert "OPENAI_API_KEY" not in compose
    assert '127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT:-8000}:8000' in compose


def test_gateway_image_installs_postgres_driver_and_ignores_secrets() -> None:
    assert 'pip install --no-cache-dir ".[db]"' in Path("Dockerfile").read_text()
    assert ".secrets" in Path(".dockerignore").read_text().splitlines()
