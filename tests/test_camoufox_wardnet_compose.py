"""Static deployment contract for the sealed Camoufox/Wardnet profile."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

COMPOSE = Path(__file__).parents[1] / "compose.camoufox-wardnet.yaml"


def test_camoufox_browser_has_only_internal_networks_and_wardnet_dns() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    browser = text.split("  camofox-browser:", 1)[1].split("  camofox-mcp:", 1)[0]
    assert "dns: [172.30.0.2]" in browser
    assert "camoufox_control: {}" in browser
    assert "camoufox_egress: {}" in browser
    assert "default:" not in browser
    assert "ports:" not in browser
    assert text.count("internal: true") == 2


def test_artifacts_are_immutable_and_boundaries_are_separately_authenticated() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "wardnet.git#233c831bb26fc57b6c4be3435f54306f56fd37a8" in text
    assert text.count("rust:1.88-bookworm@sha256:af306cfa") == 2
    assert "cargo build --locked --release" in text
    assert (
        "camofox-browser@sha256:"
        "afaaf9795af8793f3e6353e9e5dd5b03713b6ffed6e80c1b0a179575322bcff0" in text
    )
    assert (
        "camofox-mcp@sha256:"
        "52791742410fe9a4661afabe9326b6276feaa579616d3d45e76faa7da2f4130b" in text
    )
    assert "EGRESS_DNS_BIND_ADDR: 0.0.0.0:53" in text
    assert "NET_BIND_SERVICE" in text
    assert "WARDNET_EGRESS_PROXY_TOKEN" in text
    assert "CAMOFOX_HTTP_API_KEY" in text
    assert "CAMOFOX_AUTH_MODE: required" in text
    assert "platform: linux/amd64" in text


def test_rendered_compose_keeps_browser_off_the_default_network() -> None:
    """Ask Compose itself to merge and normalize the security boundary."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    environment = {
        **os.environ,
        "CONTEXTUAL_ORCHESTRATOR_POSTGRES_PASSWORD": "test-only",
        "CONTEXTUAL_ORCHESTRATOR_KV_PASSPHRASE": "test-only",
        "WARDNET_ADMIN_TOKEN": "test-only",
        "WARDNET_EGRESS_PROXY_TOKEN": "test-only",
        "WARDNET_CONTROL_PLANE_DATABASE_URL": "postgresql://test.invalid/db?sslmode=require",
        "CAMOFOX_API_KEY": "test-only",
        "CAMOFOX_MCP_TOKEN": "test-only",
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.camoufox-wardnet.yaml",
            "config",
            "--format",
            "json",
        ],
        cwd=COMPOSE.parent,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    rendered = json.loads(result.stdout)
    browser = rendered["services"]["camofox-browser"]
    wardnet = rendered["services"]["wardnet"]
    assert set(browser["networks"]) == {"camoufox_control", "camoufox_egress"}
    assert browser["dns"] == ["172.30.0.2"]
    assert browser["platform"] == "linux/amd64"
    assert wardnet["environment"]["CONTROL_PLANE_DATABASE_URL"].endswith(
        "?sslmode=require"
    )
    assert rendered["networks"]["camoufox_egress"]["internal"] is True


def test_deployment_docs_do_not_treat_dev_postgres_or_doh_as_proven() -> None:
    """Keep the documented runtime boundary no stronger than current evidence."""
    text = (COMPOSE.parent / "docs" / "kv-credentials.md").read_text(encoding="utf-8")
    assert "plaintext development PostgreSQL service" in text
    assert "cannot satisfy this prerequisite" in text
    assert "does not assert that the browser refuses all DoH requests" in text
