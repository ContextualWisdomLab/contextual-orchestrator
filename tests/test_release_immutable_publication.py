"""Execute the real publisher against a stateful GitHub immutability boundary.

Only the remote CLI is replaced. The workflow's own shell, ordering, failure
propagation, uploads and byte comparison execute without publication authority.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TAG = "v0.2.0"
_SBOM = '{"bomFormat":"CycloneDX","version":1}\n'
_START = "Create the GitHub Release"
_RESUME = "Validate the existing release lifecycle"

_GH = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

state_path = Path(os.environ["FAKE_RELEASE_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state["calls"].append(args)

def save():
    state_path.write_text(json.dumps(state))

def fail(message):
    save()
    print(message, file=sys.stderr)
    raise SystemExit(1)

def output(value):
    if "--jq" in args:
        result = subprocess.run(
            ["jq", "-r", args[args.index("--jq") + 1]],
            input=json.dumps(value), text=True, capture_output=True,
        )
        if result.returncode:
            fail(result.stderr)
        print(result.stdout, end="")
    else:
        print(json.dumps(value))

if args[:2] == ["release", "create"]:
    if state["release"] is not None:
        fail("release already exists")
    draft = "--draft" in args
    state["release"] = {
        "tag_name": args[2], "draft": draft, "prerelease": False,
        "immutable": not draft and state["locking"], "assets": [],
    }
elif args[:2] == ["release", "view"]:
    release = state["release"]
    if release is None:
        fail("HTTP 404")
    output({"assets": release["assets"], "isDraft": release["draft"]})
elif args[:2] == ["release", "upload"]:
    release = state["release"]
    if release["immutable"]:
        fail("Cannot upload assets to an immutable release")
    if state.get("upload_failure"):
        fail("upload interrupted")
    data = Path(args[3]).read_text()
    state["asset_bytes"] = data
    release["assets"] = [{"name": "cyclonedx-sbom.json", "size": len(data)}]
elif args[:2] == ["release", "download"]:
    if state.get("download_failure"):
        fail("download interrupted")
    directory = Path(args[args.index("--dir") + 1])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cyclonedx-sbom.json").write_text(state["asset_bytes"])
elif args[:2] == ["release", "edit"]:
    if not state["release"]["draft"]:
        fail("unexpected edit of published release")
    if state.get("publish_failure"):
        fail("publication interrupted")
    state["release"]["draft"] = False
    state["release"]["immutable"] = state["locking"]
elif args[:2] in (["release", "verify"], ["release", "verify-asset"]):
    if state.get("attestation_failure"):
        fail("invalid release attestation")
    if not state["release"]["immutable"]:
        fail("release not immutable")
    if args[1] == "verify-asset" and Path(args[3]).read_text() != state["asset_bytes"]:
        fail("attestation asset mismatch")
elif args and args[0] == "api":
    if state.get("metadata_failure"):
        fail("HTTP 503")
    if state["release"] is None:
        fail("HTTP 404")
    output(state["release"])
else:
    fail("unexpected gh command: " + repr(args))
save()
'''


def _steps() -> list[tuple[str, str, str]]:
    """Extract bounded publish steps without adding a YAML dependency."""
    text = (_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    publish = text.split("\n  publish:\n", 1)[1]
    result = []
    for block in re.split(r"(?m)^      - name: ", publish)[1:]:
        name = block.splitlines()[0]
        if "\n        run: |\n" not in block:
            continue
        metadata, raw_script = block.split("\n        run: |\n", 1)
        script = "\n".join(
            line[10:] for line in raw_script.splitlines() if line.startswith("          ")
        )
        result.append((name, metadata, script))
    return result


def _existing(*, draft: bool, immutable: bool, asset: str | None = _SBOM) -> dict:
    """Construct a remote lifecycle state, not a successful mock verdict."""
    return {
        "tag_name": _TAG,
        "draft": draft,
        "prerelease": False,
        "immutable": immutable,
        "assets": [] if asset is None else [
            {"name": "cyclonedx-sbom.json", "size": len(asset)}
        ],
    }


def _run(tmp_path: Path, **changes: object) -> tuple[subprocess.CompletedProcess, dict]:
    """Run publication shell steps in order and retain all remote effects."""
    state = {"release": None, "locking": True, "asset_bytes": _SBOM, "calls": []}
    state.update(changes)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable} -S\n" + _GH.split("\n", 1)[1])
    gh.chmod(0o700)
    (tmp_path / "sbom-download").mkdir()
    (tmp_path / "sbom-download/cyclonedx-sbom.json").write_text(_SBOM)
    (tmp_path / "release-notes.md").write_text("Release 0.2.0\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_RELEASE_STATE": str(state_path),
        "GITHUB_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
        "RELEASE_VERSION": "0.2.0",
        "RELEASE_RESUME": "false" if state["release"] is None else "true",
        "TMPDIR": str(tmp_path),
    }
    active = False
    result = subprocess.CompletedProcess([], 0, "", "")
    for name, metadata, script in _steps():
        active = active or name in {_START, _RESUME}
        if not active:
            continue
        if "if: env.RELEASE_RESUME != 'true'" in metadata and state["release"] is not None:
            continue
        if "if: env.RELEASE_RESUME == 'true'" in metadata and state["release"] is None:
            continue
        result = subprocess.run(
            ["bash", "-c", script], cwd=tmp_path, env=env,
            text=True, capture_output=True, timeout=20,
        )
        if result.returncode:
            break
    return result, json.loads(state_path.read_text())


def _calls(state: dict, command: str) -> list:
    """Select actual remote effects from the subprocess journal."""
    return [call for call in state["calls"] if call[:2] == ["release", command]]


def test_fresh_immutable_publication_attaches_before_locking(tmp_path: Path) -> None:
    """The original public-create-then-upload sequence fails at immutable upload."""
    result, state = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    assert state["release"]["immutable"] is True
    assert state["release"]["draft"] is False
    commands = [call[:2] for call in state["calls"]]
    assert commands.index(["release", "upload"]) < commands.index(["release", "edit"])
    assert _calls(state, "verify") and _calls(state, "verify-asset")


def test_mutable_publication_cannot_report_success(tmp_path: Path) -> None:
    """A release object and tag alone are not immutable evidence."""
    result, _ = _run(tmp_path, locking=False)
    assert result.returncode != 0


@pytest.mark.parametrize("asset", [None, _SBOM])
def test_draft_resume_finishes_without_recreating(tmp_path: Path, asset: str | None) -> None:
    """Resume both interrupted upload and interrupted finalization."""
    result, state = _run(tmp_path, release=_existing(draft=True, immutable=False, asset=asset))
    assert result.returncode == 0, result.stderr + result.stdout
    assert not _calls(state, "create")
    assert state["release"]["immutable"] is True
    assert bool(_calls(state, "upload")) is (asset is None)


def test_public_immutable_resume_is_read_only(tmp_path: Path) -> None:
    """Repeat completion verifies attestation without editing existing artifacts."""
    result, state = _run(tmp_path, release=_existing(draft=False, immutable=True))
    assert result.returncode == 0, result.stderr + result.stdout
    assert not any(_calls(state, name) for name in ("create", "upload", "edit"))
    assert _calls(state, "verify") and _calls(state, "verify-asset")


@pytest.mark.parametrize("immutable", [False, True])
def test_incomplete_public_release_is_not_repaired_by_upload(tmp_path: Path, immutable: bool) -> None:
    """Do not mutate a public release, even if its settings would allow it."""
    result, state = _run(
        tmp_path, release=_existing(draft=False, immutable=immutable, asset=None),
    )
    assert result.returncode != 0
    assert not any(_calls(state, name) for name in ("create", "upload", "edit"))


@pytest.mark.parametrize("draft,immutable", [(True, False), (False, True)])
def test_different_existing_asset_fails_without_overwrite(tmp_path: Path, draft: bool, immutable: bool) -> None:
    """Same asset name must not substitute different bytes."""
    result, state = _run(
        tmp_path, release=_existing(draft=draft, immutable=immutable), asset_bytes="different",
    )
    assert result.returncode != 0
    assert not _calls(state, "upload") and not _calls(state, "edit")


@pytest.mark.parametrize("failure", ["upload_failure", "download_failure", "publish_failure"])
def test_failure_leaves_recoverable_draft(tmp_path: Path, failure: str) -> None:
    """An incomplete publisher must not expose an asset-incomplete public release."""
    result, state = _run(tmp_path, **{failure: True})
    assert result.returncode != 0
    assert state["release"]["draft"] is True


@pytest.mark.parametrize("field,value", [
    ("tag_name", "v9.9.9"), ("prerelease", True), ("draft", "true"), ("immutable", None),
])
def test_ambiguous_resume_metadata_fails_without_mutation(tmp_path: Path, field: str, value: object) -> None:
    """Wrong tags and untyped lifecycle fields cannot authorize release writes."""
    release = _existing(draft=True, immutable=False)
    release[field] = value
    result, state = _run(tmp_path, release=release)
    assert result.returncode != 0
    assert not any(_calls(state, name) for name in ("create", "upload", "edit"))


def test_metadata_outage_is_not_absence(tmp_path: Path) -> None:
    """A release metadata outage cannot authorize a new create or upload."""
    result, state = _run(
        tmp_path, release=_existing(draft=True, immutable=False, asset=None), metadata_failure=True,
    )
    assert result.returncode != 0
    assert not any(_calls(state, name) for name in ("create", "upload", "edit"))


def test_bad_attestation_cannot_report_success(tmp_path: Path) -> None:
    """Lock metadata alone is not cryptographic verification."""
    result, state = _run(
        tmp_path, release=_existing(draft=False, immutable=True), attestation_failure=True,
    )
    assert result.returncode != 0
    assert not any(_calls(state, name) for name in ("create", "upload", "edit"))
