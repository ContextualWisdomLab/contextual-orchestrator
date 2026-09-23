"""A licence hold must stop the job before anything is installed.

Checking that the gate command appears before the install command proves only
text order. This runs the workflow's own step scripts with stubbed executables
and asserts that when the gate rejects, the install command is never invoked --
the property the ordering is there to produce.

Nothing is downloaded or installed: the stub `python` answers `pip download`
and `pip install` by logging, and hands the licence gate to the real
interpreter so the rejection is the real one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "security.yml"


def _step_script(step_name: str) -> str:
    """The `run:` body of one named step, dedented."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"      - name: {step_name}")
    body = text[text.index("run: |", start) + len("run: |"):]
    lines: list[str] = []
    for line in body.splitlines()[1:]:
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line[10:])
    return "\n".join(lines)


def _stub_python(directory: Path, log: Path, inventory_payload: dict) -> None:
    """A `python` that logs pip calls and runs the real licence gate."""
    inventory_json = json.dumps(inventory_payload)
    script = f"""#!/usr/bin/env {sys.executable.rsplit("/", 1)[-1]}
import json, pathlib, subprocess, sys
log = pathlib.Path({str(log)!r})
argv = sys.argv[1:]
with log.open("a") as handle:
    handle.write(" ".join(argv) + "\\n")
if argv[:2] == ["-m", "pip"] and argv[2] == "download":
    pathlib.Path("license-artifacts").mkdir(exist_ok=True)
    sys.exit(0)
if argv[:2] == ["-m", "scripts.ci.dependency_inventory"]:
    output = argv[argv.index("--output") + 1]
    pathlib.Path(output).write_text({inventory_json!r}, encoding="utf-8")
    sys.exit(0)
if argv[:2] == ["-m", "scripts.ci.release_license_gate"]:
    sys.exit(subprocess.run([{sys.executable!r}, *argv], cwd={str(REPOSITORY_ROOT)!r}).returncode)
if argv[:2] == ["-m", "pip"] and argv[2] == "install":
    sys.exit(0)
sys.exit(0)
"""
    path = directory / "python"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _held_inventory() -> dict:
    """One package whose declaration has no licence text: a hold."""
    return {
        "schema": "contextual-orchestrator/dependency-inventory/v1",
        "source_sha": "0" * 40,
        "ecosystems": [{
            "ecosystem": "python",
            "lockfile": "requirements.lock",
            "provenance": [{"path": "requirements.lock", "read_sha256": "a" * 64,
                            "blob_id": "b" * 40, "committed_blob_id": "b" * 40, "matches_commit": True}],
            "packages": [{"name": "declared_only_library", "version": "1.0",
                          "licenses": ["MIT"], "license_files": []}],
        }],
    }


def test_a_licence_hold_prevents_the_install_step(tmp_path) -> None:
    log = tmp_path / "invocations.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub_python(stubs, log, _held_inventory())
    script = "\n".join([
        "set -euo pipefail",
        _step_script("Enumerate every declared dependency scope from the lockfiles"),
        _step_script("Install audit and project dependencies"),
    ])
    environment = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "GITHUB_SHA": "0" * 40}

    completed = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=environment,
                               capture_output=True, text=True)

    invocations = log.read_text(encoding="utf-8") if log.exists() else ""
    assert completed.returncode != 0, "a held licence must fail the job"
    assert "release_license_gate" in invocations, "the gate must actually be invoked"
    assert not re.search(r"^-m pip install", invocations, re.MULTILINE), invocations
