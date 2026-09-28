"""Exercise the audit bootstrap without global runner writes or network."""
import os
from pathlib import Path
import subprocess
import tarfile

import pytest


@pytest.mark.parametrize("download_failure", [False, True])
def test_audit_bootstrap_uses_job_local_path_and_keeps_failure_fatal(tmp_path, download_failure):
    workflow = (Path(__file__).parents[1] / ".github/workflows/security.yml").read_text()
    step = workflow.split("      - name: Install cargo-audit\n", 1)[1].split("\n      - name:", 1)[0]
    script = "\n".join(line[10:] for line in step.split("        run: |\n", 1)[1].splitlines())
    assert "/usr/local/bin" not in script
    assert "GITHUB_PATH" in script
    assert "continue-on-error" not in step
    seed = tmp_path / "seed" / "cargo-audit-x86_64-unknown-linux-gnu-v0.22.2"
    seed.mkdir(parents=True)
    binary = seed / "cargo-audit"
    binary.write_text('#!/bin/sh\n[ "$1" = "--version" ] || exit 97\nprintf "cargo-audit 0.22.2\\n"\n')
    binary.chmod(0o755)
    archive = tmp_path / "seed.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(seed, arcname=seed.name)
    commands = tmp_path / "commands"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text('#!/bin/sh\n[ "${DOWNLOAD_FAILURE}" = "false" ] || exit 9\n[ "$1" = "-sSLf" ] || exit 98\n[ "$2" = "https://github.com/rustsec/rustsec/releases/download/cargo-audit%2Fv0.22.2/cargo-audit-x86_64-unknown-linux-gnu-v0.22.2.tgz" ] || exit 98\n[ "$3" = "-o" ] || exit 98\ncp "$SEED_ARCHIVE" "$4"\n')
    curl.chmod(0o755)
    runner = tmp_path / "runner temp"
    runner.mkdir()
    path_file = tmp_path / "github-path"
    path_file.write_text("")
    env = {**os.environ, "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
           "RUNNER_TEMP": str(runner), "GITHUB_PATH": str(path_file),
           "SEED_ARCHIVE": str(archive), "DOWNLOAD_FAILURE": str(download_failure).lower()}
    result = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
    if download_failure:
        assert result.returncode != 0
        assert not path_file.read_text()
    else:
        assert result.returncode == 0, result.stderr
        installed = runner / "cargo-audit-bin" / "cargo-audit"
        assert installed.read_bytes() == binary.read_bytes()
        assert path_file.read_text().splitlines() == [str(installed.parent)]
        assert "cargo-audit 0.22.2" in result.stdout
