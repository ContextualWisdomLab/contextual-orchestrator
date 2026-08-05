"""Tests for the fallback policy command-line adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from contextual_orchestrator.model_fallback import (
    FallbackManifestError,
    main,
)
from tests.fallback_test_support import manifest_document


class _ExplodingEnvironment(dict[str, str]):
    """Environment mapping that proves the policy process never reads secrets."""

    def get(self, key: str, default: Any = None) -> Any:
        """Fail if fallback planning attempts to inspect any environment value."""
        raise AssertionError(f"fallback policy read environment value {key!r}")


def write_manifest(path: Path) -> None:
    """Write the shared valid manifest fixture as UTF-8 JSON."""
    path.write_text(json.dumps(manifest_document()), encoding="utf-8")


def test_cli_emits_free_first_json_from_declared_credential_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A trusted caller declares available names without exposing secret values."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    monkeypatch.setattr(os, "environ", _ExplodingEnvironment())

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--repository-visibility",
            "public",
            "--available-credential",
            "FREE_API_KEY",
            "--available-credential",
            "PAID_API_KEY",
            "--required-capability",
            "structured_output",
            "--format",
            "json",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["candidate_id"] for item in payload["candidates"]] == [
        "free-primary",
        "paid-primary",
    ]


def test_cli_emits_models_and_respects_deny_paid(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Shell consumers receive validated model identifiers."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--available-credential",
            "FREE_API_KEY",
            "--available-credential",
            "PAID_API_KEY",
            "--deny-paid",
            "--format",
            "models",
        ]
    ) == 0
    assert capsys.readouterr().out == "nvidia/free\n"


def test_cli_treats_undeclared_credentials_as_unavailable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A credential absent from the trusted name set is unavailable."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)

    assert main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--agent",
            "noema",
            "--available-credential",
            "PAID_API_KEY",
            "--format",
            "ids",
        ]
    ) == 0
    assert capsys.readouterr().out == "paid-primary\n"


def test_cli_rejects_removed_environment_selector(
    tmp_path: Path,
) -> None:
    """The policy-only CLI must not accept a secret-bearing environment selector."""
    manifest_path = tmp_path / "policy.json"
    write_manifest(manifest_path)
    with pytest.raises(SystemExit):
        main(
            [
                "plan",
                "--manifest",
                str(manifest_path),
                "--agent",
                "noema",
                "--credential-env",
                "FREE_API_KEY",
            ]
        )


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
    """Declarative credential names use strict identifier syntax."""
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
                "--available-credential",
                "bad-key",
            ]
        )
