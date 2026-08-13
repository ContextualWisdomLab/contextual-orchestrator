"""Static deployment contracts for the Cloud Native tenant gateway."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SECRET_NAMES = tuple(
    f"{provider_prefix}_API_KEY" for provider_prefix in ("OPENROUTER", "NVIDIA_NIM", "BYTEZ")
)
DISALLOWED_REVIEW_SECRET = "COPILOT" + "_GITHUB_TOKEN"


def test_compose_runs_two_gateways_against_one_database_without_provider_keys() -> None:
    compose = (ROOT / "deploy" / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    assert "gateway_one:" in compose
    assert "gateway_two:" in compose
    assert "tenant_postgres:" in compose
    assert compose.count("CONTEXTUAL_ORCHESTRATOR_KV_DSN") >= 3
    assert "tenant_bootstrap:" in compose

    gateway_region = compose.split("tenant_bootstrap:", 1)[0]
    for secret_name in PROVIDER_SECRET_NAMES:
        assert secret_name not in gateway_region
    bootstrap_region = compose.split("tenant_bootstrap:", 1)[1]
    for secret_name in PROVIDER_SECRET_NAMES:
        assert secret_name in bootstrap_region


def test_kubernetes_deployment_has_replicas_and_distinct_probes() -> None:
    deployment = (ROOT / "deploy" / "kubernetes" / "deployment.yaml").read_text(
        encoding="utf-8"
    )
    assert "replicas: 2" in deployment
    assert "path: /livez" in deployment
    assert "path: /readyz" in deployment
    assert "startupProbe:" in deployment
    for secret_name in PROVIDER_SECRET_NAMES:
        assert secret_name not in deployment
    assert "runAsNonRoot: true" in deployment
    assert "readOnlyRootFilesystem: true" in deployment


def test_bootstrap_job_is_the_only_kubernetes_provider_secret_consumer() -> None:
    bootstrap = (ROOT / "deploy" / "kubernetes" / "bootstrap-job.yaml").read_text(
        encoding="utf-8"
    )
    for secret_name in PROVIDER_SECRET_NAMES:
        assert f"name: {secret_name}" in bootstrap
        assert "secretKeyRef:"in bootstrap
    assert "restartPolicy: Never" in bootstrap
    assert "python scripts/bootstrap_tenant_registry.py" in bootstrap


def test_kubernetes_service_resilience_and_network_contracts_exist() -> None:
    service = (ROOT / "deploy" / "kubernetes" / "service.yaml").read_text(encoding="utf-8")
    disruption = (ROOT / "deploy" / "kubernetes" / "pod-disruption-budget.yaml").read_text(
        encoding="utf-8"
    )
    network = (ROOT / "deploy" / "kubernetes" / "network-policy.yaml").read_text(
        encoding="utf-8"
    )
    assert "kind: Service" in service
    assert "minAvailable: 1" in disruption
    assert "policyTypes:" in network
    assert "Ingress" in network and "Egress" in network


def test_live_workflow_uses_only_the_approved_provider_secret_names() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-tenant-provider-fallback.yml").read_text(
        encoding="utf-8"
     )
    assert "workflow_dispatch:" in workflow
    for secret_name in PROVIDER_SECRET_NAMES:
        assert f"secrets.{secret_name}" in workflow
    assert DISALLOWED_REVIEW_SECRET not in workflow
    assert "verify_live_provider_fallback.py" in workflow
    assert "contents: read" in workflow
