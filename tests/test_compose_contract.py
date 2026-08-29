"""Deployment contract for the canonical root Compose path."""

from pathlib import Path


def test_compose_uses_postgres_kv_and_secret_bootstrap() -> None:
    compose = Path("compose.yaml").read_text()
    assert "credential_bootstrap:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "CONTEXTUAL_ORCHESTRATOR_KV_BACKEND: postgres" in compose
    assert "postgresql://contextual_orchestrator@postgres/contextual_orchestrator" in compose
    assert "PGPASSWORD: ${CONTEXTUAL_ORCHESTRATOR_POSTGRES_PASSWORD" in compose
    assert "postgresql://contextual_orchestrator:${CONTEXTUAL_ORCHESTRATOR_POSTGRES_PASSWORD}" not in compose
    assert "--name CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN --value-stdin < /run/secrets/admin_token" in compose
    assert "--name CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN --value-stdin < /run/secrets/inference_token" in compose
    assert "--production" in compose
    assert "--auth-token-key" not in compose
    assert "server_token" not in compose
    assert "OPENAI_API_KEY" not in compose
    assert '127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT:-8000}:8000' in compose


def test_gateway_image_installs_postgres_driver_and_ignores_secrets() -> None:
    dockerfile = Path("Dockerfile").read_text()
    assert "COPY pyproject.toml requirements.lock README.md LICENSE ./" in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    assert "--production" in dockerfile
    assert "--admin-token-key CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" in dockerfile
    assert "--inference-token-key CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN" in dockerfile
    assert "--auth-token-key" not in dockerfile
    assert ".secrets" in Path(".dockerignore").read_text().splitlines()
