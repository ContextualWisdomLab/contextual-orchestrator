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

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
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
    # An absolute interpreter: a `#!/usr/bin/env python` shebang would pick
    # this very stub off PATH and recurse.
    script = f"""#!{sys.executable}
import json, pathlib, subprocess, sys
log = pathlib.Path({str(log)!r})
argv = sys.argv[1:]
with log.open("a") as handle:
    handle.write(" ".join(argv) + "\\n")
if argv[:2] == ["-m", "pip"] and argv[2] == "download":
    # A download that produces the fixture wheel already on disk: nothing
    # leaves the machine, and the bytes are the ones the test planted.
    pathlib.Path("license-artifacts").mkdir(exist_ok=True)
    sys.exit(0)
import os
real_env = {{**os.environ, "PYTHONPATH": {str(REPOSITORY_ROOT)!r}}}
if argv[:2] == ["-m", "scripts.ci.dependency_inventory"] and "--check-sources-only" in argv:
    sys.exit(subprocess.run([{sys.executable!r}, *argv], env=real_env).returncode)
if argv[:2] == ["-m", "scripts.ci.dependency_inventory"]:
    output = argv[argv.index("--output") + 1]
    pathlib.Path(output).write_text({inventory_json!r}, encoding="utf-8")
    sys.exit(0)
if argv[:2] == ["-m", "scripts.ci.release_license_gate"]:
    sys.exit(subprocess.run([{sys.executable!r}, *argv], env=real_env).returncode)
if argv[:2] == ["-m", "pip"] and argv[2] == "install":
    # Offline installs may only use the adjudicated directory, and every wheel
    # in it must carry an approved hash; anything else is a failed install.
    approved_file = pathlib.Path("approved-hashes.json")
    if "--no-index" in argv and approved_file.exists():
        approved = set(json.loads(approved_file.read_text()))
        import hashlib as _h
        for wheel in sorted(pathlib.Path("license-artifacts").glob("*.whl")):
            digest = _h.sha256(wheel.read_bytes()).hexdigest()
            with log.open("a") as handle:
                handle.write("INSTALLED " + wheel.name + " " + digest + chr(10))
            if digest not in approved:
                with log.open("a") as handle:
                    handle.write("REJECTED unapproved bytes" + chr(10))
                sys.exit(1)
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


def _permitted_inventory() -> dict:
    """One package whose bundled licence text evidences its declaration."""
    inventory = _held_inventory()
    inventory["ecosystems"][0]["packages"] = [{
        "name": "permitted_library", "version": "1.0", "licenses": ["MIT"],
        "license_files": [{"name": "LICENSE", "sha256": "c" * 64,
                           "text": "MIT License\n\nPermission is hereby granted, free of charge"}],
    }]
    return inventory


def test_an_adjudicated_pass_installs_the_wheels_it_read(tmp_path) -> None:
    """The allowed flow reaches the install, offline, from the same directory."""
    log = tmp_path / "invocations.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub_python(stubs, log, _permitted_inventory())
    script = "\n".join([
        "set -euo pipefail",
        _step_script("Enumerate every declared dependency scope from the lockfiles"),
        _step_script("Install audit and project dependencies"),
    ])
    environment = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "GITHUB_SHA": "0" * 40}

    completed = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=environment,
                               capture_output=True, text=True)

    invocations = log.read_text(encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    install_lines = [line for line in invocations.splitlines() if line.startswith("-m pip install")]
    shipped = [line for line in install_lines if "requirements.lock" in line]
    assert shipped, install_lines
    assert all("--no-index" in line and "--find-links license-artifacts" in line for line in shipped)
    assert invocations.count("-m pip download") == 1, "the adjudicated wheels are fetched once"


def test_an_external_source_stops_the_job_before_any_download(tmp_path) -> None:
    """A direct URL or VCS requirement is refused before pip fetches anything."""
    log = tmp_path / "invocations.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub_python(stubs, log, _permitted_inventory())
    (tmp_path / "requirements.lock").write_text(
        "vcs-library @ git+https://example.invalid/pkg.git@deadbeef\n", encoding="utf-8")
    (tmp_path / "fuzz").mkdir()
    script = "\n".join([
        "set -euo pipefail",
        _step_script("Enumerate every declared dependency scope from the lockfiles"),
    ])
    environment = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "GITHUB_SHA": "0" * 40}

    # The source check runs in the working directory, so the real module sees
    # this fixture's lockfile rather than the repository's.
    completed = subprocess.run(
        ["bash", "-c", script.replace("python -m scripts.ci.dependency_inventory --repository-root . \\\n  --output /dev/null --check-sources-only",
                                      "python -m scripts.ci.dependency_inventory --repository-root . --output /dev/null --check-sources-only")],
        cwd=tmp_path, env=environment, capture_output=True, text=True)

    invocations = log.read_text(encoding="utf-8") if log.exists() else ""
    assert completed.returncode != 0, completed.stdout
    assert "--check-sources-only" in invocations, "the source check must actually run"
    assert "-m pip download" not in invocations, invocations


def _synthetic_wheel(directory: Path, name: str, version: str, licence_text: str) -> tuple[Path, str]:
    """A real wheel on disk, so the install can be bound to its actual bytes."""
    directory.mkdir(exist_ok=True)
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA",
                         f"Name: {name}\nVersion: {version}\nLicense-Expression: MIT\n")
        archive.writestr(f"{name}-{version}.dist-info/licenses/LICENSE", licence_text)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_only_the_adjudicated_bytes_are_installed(tmp_path) -> None:
    """The install is bound to the exact wheel that was judged, not to a name."""
    log = tmp_path / "invocations.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    wheel, digest = _synthetic_wheel(tmp_path / "license-artifacts", "example_library", "1.0",
                                     "MIT License\n\nPermission is hereby granted, free of charge")
    (tmp_path / "approved-hashes.json").write_text(json.dumps([digest]), encoding="utf-8")
    inventory = _held_inventory()
    inventory["ecosystems"][0]["packages"] = [{
        "name": "example_library", "version": "1.0", "licenses": ["MIT"],
        "license_files": [{"name": "LICENSE", "sha256": "d" * 64,
                           "text": "MIT License\n\nPermission is hereby granted, free of charge"}],
    }]
    _stub_python(stubs, log, inventory)
    script = "\n".join(["set -euo pipefail",
                        _step_script("Enumerate every declared dependency scope from the lockfiles"),
                        _step_script("Install audit and project dependencies")])
    environment = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "GITHUB_SHA": "0" * 40}

    passing = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=environment,
                             capture_output=True, text=True)
    assert passing.returncode == 0, passing.stderr
    assert f"INSTALLED {wheel.name} {digest}" in log.read_text(encoding="utf-8")

    # Swap the wheel for different bytes after adjudication: the install refuses.
    log.write_text("", encoding="utf-8")
    _synthetic_wheel(tmp_path / "license-artifacts", "example_library", "1.0",
                     "MIT License\n\nPermission is hereby granted, free of charge -- altered copy")
    swapped = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=environment,
                             capture_output=True, text=True)

    assert swapped.returncode != 0
    assert "REJECTED unapproved bytes" in log.read_text(encoding="utf-8")
