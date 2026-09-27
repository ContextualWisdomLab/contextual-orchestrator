"""Deployment contract for the canonical root Compose path."""

from pathlib import Path
import shutil
import tomllib


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
    assert "uv pip install --python 3.12 --require-hashes" in dockerfile
    assert "COPY --from=dependency-builder /build/deps/" in dockerfile
    assert "maturin build --locked --release" in dockerfile
    assert "--production" in dockerfile
    assert "--admin-token-key CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN" in dockerfile
    assert "--inference-token-key CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN" in dockerfile
    assert "--auth-token-key" not in dockerfile
    assert ".secrets" in Path(".dockerignore").read_text().splitlines()


def test_gateway_build_copies_complete_rust_workspace(tmp_path) -> None:
    """Every workspace manifest and its licence must exist in the build stage."""
    for line in Path("Dockerfile").read_text().splitlines():
        fields = line.split()
        if not fields or fields[0] != "COPY" or not fields[-1].startswith("/build/rust/"):
            continue
        destination = tmp_path / fields[-1].removeprefix("/build/")
        destination.mkdir(parents=True, exist_ok=True)
        for source in fields[1:-1]:
            path = Path(source)
            if path.is_dir():
                shutil.copytree(path, destination, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("target"))
            else:
                shutil.copyfile(path, destination / path.name)
    workspace = tomllib.loads((tmp_path / "rust/Cargo.toml").read_text())
    for member in workspace["workspace"]["members"]:
        root = tmp_path / "rust" / member
        manifest = tomllib.loads((root / "Cargo.toml").read_text())
        assert (root / manifest["package"]["license-file"]).read_bytes() == Path("LICENSE").read_bytes()
