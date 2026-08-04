"""Tests for the fallback policy command-line adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextual_orchestrator.model_fallback import (
    FallbackManifestError,
    main,
)
from tests.fallback_test_support import manifest_document


def write_manifest(path: Path) -> None:
    """Write the shared valid manifest fixture as UTF-8 JSON."""
    path.write_text(json.dumps(manifest_document()), encoding="utf-8")


def test_cli_emits_free_first_json_without_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI checks named secrets but never prints their values."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    monkeypatch.setenv("FREE_API_KEY", "free-secret-value")
    monkeypatch.setenv("PAID_API_KEY", "paid-secret-value")

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--repository-visibility",
            "public",
            "--credential-env",
            "FREE_API_KEY",
            "--credential-env",
            "PAID_API_KEY",
            "--required-capability",
            "structured_output",
            "--format",
            "json",
        ]
    ) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert [item["candidate_id"] for item in payload["candidates"]] == [
        "free-primary",
        "paid-primary",
    ]
    assert "free-secret-value" not in output
    assert "paid-secret-value" not in output


def test_cli_emits_models_and_respects_deny_paid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Shell consumers receive validated model identifiers."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    monkeypatch.setenv("FREE_API_KEY", "configured")
    monkeypatch.setenv("PAID_API_KEY", "configured")

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--credential-env",
            "FREE_API_KEY",
            "--credential-env",
            "PAID_API_KEY",
            "--deny-paid",
            "--format",
            "models",
        ]
    ) == 0
    assert capsys.readouterr().out == "nvidia/free\n"


def test_cli_treats_empty_credentials_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty secret is not a configured credential."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    monkeypatch.setenv("FREE_API_KEY", "  ")
    monkeypatch.setenv("PAID_API_KEY", "configured")

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--credential-env",
            "FREE_API_KEY",
            "--credential-env",
            "PAID_API_KEY",
            "--format",
            "ids",
        ]
    ) == 0
    assert capsys.readouterr().out == "paid-primary\n"


def test_cli_rejects_invalid_json_missing_file_and_non_object_root(
    tmp_path: Path,
) -> None:
    """File input failures are explicit instead of using defaults."""
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")
    with pytest.raises(FallbackManifestError, match="valid JSON"):
        main(["plan", "--manifest", str(invalid_path), "--agent", "noema"])
    with pytest.raises(FallbackManifestError, match="could not be read"):
        main(
            [
                "plan",
                "--manifest",
                str(tmp_path / "missing.json"),
                "--agent",
                "noema",
            ]
        )

    array_path = tmp_path / "array.json"
    array_path.write_text("[]", encoding="utf-8")
    with pytest.raises(FallbackManifestError, match="manifest must be an object"):
        main(["plan", "--manifest", str(array_path), "--agent", "noema"])


def test_cli_rejects_unsafe_credential_name(
    tmp_path: Path,
) -> None:
    """Environment selectors use strict identifier syntax."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    with pytest.raises(Exception, match="credential"):
        main(
            [
                "plan",
                "--manifest",
                str(manifest_path),
                "--agent",
                "noema",
                "--credential-env",
                "bad-key",
            ]
        )
