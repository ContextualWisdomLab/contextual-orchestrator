"""Issue #1347 acceptance: the real CVE-2024-1234 record never authorizes a lodash finding.

The fixture is the unmodified MITRE CVE Services response for CVE-2024-1234,
retrieved 2026-10-06 from https://cveawg.mitre.org/api/cve/CVE-2024-1234
(SHA-256 1b338b63b95b269a83580872eb1e57ec8bc27b2b4f0b01fbcf20c37a2b03c6de).
The record describes a WordPress plugin, not lodash. These tests characterize
existing behavior; they are not a repair RED.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from contextual_orchestrator import vulnerability_claim as claims

_FIXTURE = Path(__file__).parent / "fixtures" / "advisories" / "CVE-2024-1234.mitre.json"
_FIXTURE_SHA256 = "1b338b63b95b269a83580872eb1e57ec8bc27b2b4f0b01fbcf20c37a2b03c6de"


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(claims, "get_credential", lambda _: str(tmp_path))
    return tmp_path


def _real_record() -> dict:
    raw = _FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _FIXTURE_SHA256
    payload = json.loads(raw)
    assert payload["containers"]["cna"]["affected"][0]["product"] == "Exclusive Addons for Elementor"
    return payload


def test_original_python_rust_repository_never_fetches_or_allows_lodash_finding(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported repository had no JavaScript manifests or lockfiles."""
    (snapshot / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["numpy>=2"]\n')
    (snapshot / "Cargo.toml").write_text('[dependencies]\nserde="1"\n')
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _: pytest.fail("must not fetch"))
    verdict = claims.assess_vulnerability_claim("CVE-2024-1234", "lodash", "npm")
    assert verdict.status == claims.CLAIM_UNVERIFIED
    assert verdict.repository_package_present is None
    assert not verdict.finding_allowed and not verdict.versions_checked


@pytest.mark.parametrize("frozen", [False, True])
def test_real_record_never_allows_lodash_finding_even_when_lodash_is_present(
    snapshot: Path, monkeypatch: pytest.MonkeyPatch, frozen: bool,
) -> None:
    (snapshot / "package.json").write_text('{"dependencies":{"lodash":"4.17.20"}}')
    payload = _real_record()
    monkeypatch.setattr(claims, "_fetch_official_record", lambda _: payload)
    evidence = claims.capture_repository_package_evidence() if frozen else None
    verdict = claims.assess_vulnerability_claim(
        "CVE-2024-1234", "lodash", "npm", repository_evidence=evidence,
    )
    assert verdict.status == claims.CLAIM_UNVERIFIED
    assert not verdict.finding_allowed and not verdict.versions_checked
    assert verdict.affected_installed_versions == ()
