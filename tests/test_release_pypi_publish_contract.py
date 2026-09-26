"""Contract for the release workflow's PyPI publication job.

`publish-pypi` in `.github/workflows/release.yml` uploads the exact wheel that
`verify` built twice and `publish` attached to the immutable GitHub Release.
These tests pin the properties that make that safe: it runs only after the
GitHub Release job succeeds, never rebuilds, re-verifies SHA256SUMS against the
immutable release, checks metadata with `twine check --strict`, uses a
SHA-pinned uploader with least privilege, references the PyPI secret exactly
once, and is idempotent on re-run while refusing a PyPI version that already
holds different files.

Plain text assertions plus real execution of the job's own shell/Python step
bodies against stubbed `gh` and PyPI responses, matching this repository's
workflow-contract convention (no YAML dependency).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"
_PYPI_PUBLISH_SHA = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
_PYPI_PUBLISH_VERSION = "v1.14.2"
_SECRET_NAME = "PIPY_TOKEN"
_VERSION = "0.2.0"
_WHEEL = f"contextual_orchestrator-{_VERSION}-py3-none-any.whl"

_STEP_ORDER = (
    "Download the verified release inputs produced by verify",
    "Stage exactly the verified wheel and re-verify SHA256SUMS",
    "Check distribution metadata with twine check --strict",
    "Refuse a PyPI version that already holds different files",
    "Publish the verified wheel to PyPI",
    "Explain a PyPI upload failure",
    "Verify PyPI serves exactly the verified wheel",
)


def _workflow_text() -> str:
    """Return the release workflow's raw YAML text."""
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    """Return one top-level job, bounded by the next top-level job or EOF."""
    start = workflow.index(f"\n  {job_name}:\n")
    rest = workflow[start + 1 :]
    following = re.search(r"(?m)^  [A-Za-z0-9_-]+:\n", rest[len(job_name) + 4 :])
    end = len(rest) if following is None else len(job_name) + 4 + following.start()
    return rest[:end]


def _steps(block: str) -> dict[str, str]:
    """Map each `- name:` step to its own text, in file order."""
    parts = re.split(r"(?m)^      - name: ", block)[1:]
    return {part.splitlines()[0].strip(): part for part in parts}


def _run_body(step: str) -> str:
    """Return a step's `run: |` body, dedented as the runner would see it."""
    raw = step.split("        run: |\n", 1)[1]
    lines = []
    for line in raw.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines)) + "\n"


def _pypi_job() -> str:
    return _job_block(_workflow_text(), "publish-pypi")


# --- Static structure -------------------------------------------------------


def test_job_runs_only_after_the_github_release_job_on_main() -> None:
    job = _pypi_job()
    assert "    needs: [verify, publish]\n" in job
    assert "    if: github.ref == 'refs/heads/main'\n" in job
    # No status-function override: the implicit success() keeps PyPI behind
    # a fully successful GitHub Release publication.
    assert "always()" not in job
    assert "continue-on-error" not in job
    workflow = _workflow_text()
    assert workflow.index("\n  publish:\n") < workflow.index("\n  publish-pypi:\n")


def test_job_uses_the_pypi_environment_and_least_privilege() -> None:
    job = _pypi_job()
    assert "    environment: pypi\n" in job
    assert "    permissions:\n      contents: read\n      id-token: write\n    env:\n" in job
    assert "contents: write" not in job
    assert "actions: " not in job
    assert "checks: " not in job


def test_uploader_is_pinned_to_the_reviewed_full_commit_sha() -> None:
    job = _pypi_job()
    assert (
        f"uses: pypa/gh-action-pypi-publish@{_PYPI_PUBLISH_SHA} "
        f"# pypa/gh-action-pypi-publish@{_PYPI_PUBLISH_VERSION}"
    ) in job
    for ref in re.findall(r"uses: ([^\s]+)", job):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_job_publishes_the_verified_artifact_and_never_rebuilds() -> None:
    workflow = _workflow_text()
    job = _pypi_job()
    verify = _job_block(workflow, "verify")
    assert "name: release-publish-inputs" in verify
    assert "dist/**" in verify
    assert "actions/download-artifact@" in job
    assert "name: release-publish-inputs" in job
    for forbidden in (
        "actions/checkout",
        "uv build",
        "python -m build",
        "maturin",
        "pip wheel",
        "setup.py",
        "setup-uv",
        "actions/upload-artifact",
        "gh release upload",
        "gh release edit",
    ):
        assert forbidden not in job, forbidden


def test_steps_run_in_the_safe_order() -> None:
    names = list(_steps(_pypi_job()))
    assert names == list(_STEP_ORDER)


def test_checksums_are_reverified_against_the_immutable_release_before_upload() -> None:
    stage = _steps(_pypi_job())[_STEP_ORDER[1]]
    assert '(cd "${inputs}" && sha256sum --strict -c SHA256SUMS)' in stage
    assert 'gh release download "v${RELEASE_VERSION}"' in stage
    assert "--pattern SHA256SUMS" in stage
    assert 'cmp -s "${inputs}/SHA256SUMS" "${remote_dir}/SHA256SUMS"' in stage
    assert ".immutable == true" in stage
    assert '(cd dist && sha256sum --strict -c "${RUNNER_TEMP}/SHA256SUMS")' in stage


def test_twine_check_strict_gates_every_staged_distribution() -> None:
    twine = _steps(_pypi_job())[_STEP_ORDER[2]]
    assert "twine==7.0.0" in twine
    assert "--only-binary=:all:" in twine
    assert '--constraint "${constraints}"' in twine
    assert "distributions=(dist/*.whl dist/*.tar.gz)" in twine
    assert 'twine" check --strict "${distributions[@]}"' in twine
    pins = twine.split("<<'PINS'\n", 1)[1].split("\n          PINS\n", 1)[0]
    for line in pins.splitlines():
        assert re.fullmatch(r"          [a-z0-9-]+==[0-9][0-9A-Za-z.]*", line), line
    assert "secrets." not in twine


def test_secret_is_referenced_exactly_once_on_the_upload_step() -> None:
    workflow = _workflow_text()
    assert workflow.count(_SECRET_NAME) == 1
    assert workflow.count("secrets.") == 1
    assert "PYPI_API_TOKEN" not in workflow
    upload = _steps(_pypi_job())[_STEP_ORDER[4]]
    assert f"password: ${{{{ secrets.{_SECRET_NAME} }}}}" in upload


def test_upload_is_idempotent_and_failure_is_explained() -> None:
    steps = _steps(_pypi_job())
    upload = steps[_STEP_ORDER[4]]
    assert "id: pypi_upload" in upload
    assert "packages-dir: dist/" in upload
    assert "skip-existing: true" in upload
    assert "attestations: false" in upload
    assert "verify-metadata: false" not in upload
    explain = steps[_STEP_ORDER[5]]
    assert "if: failure() && steps.pypi_upload.outcome == 'failure'" in explain
    assert "repository access list" in explain
    assert "workflow release.yml, environment pypi" in explain
    assert "exit 1" in explain


# --- Execution of the job's own step bodies ---------------------------------

_STUB_GH = """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "api" ]; then
    cat "${FAKE_RELEASE_JSON}"
    exit 0
fi
if [ "$1" = "release" ] && [ "$2" = "download" ]; then
    [ "${FAKE_DOWNLOAD_FAIL:-}" = "1" ] && exit 1
    dir=""
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "--dir" ]; then dir="$2"; fi
        shift
    done
    cp "${FAKE_REMOTE_SUMS}" "${dir}/SHA256SUMS"
    exit 0
fi
echo "unexpected gh call: $*" >&2
exit 98
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _prepare_stage(tmp_path: Path, *, scenario: str) -> tuple[Path, dict[str, str]]:
    work = tmp_path / "work"
    inputs = work / "release-publish-inputs/dist"
    inputs.mkdir(parents=True)
    wheel_bytes = b"verified wheel bytes"
    (inputs / _WHEEL).write_bytes(wheel_bytes)
    sums = f"{hashlib.sha256(wheel_bytes).hexdigest()}  {_WHEEL}\n"
    if scenario == "extra_listed":
        (inputs / "other.whl").write_bytes(b"x")
        sums += f"{hashlib.sha256(b'x').hexdigest()}  other.whl\n"
    (inputs / "SHA256SUMS").write_text(sums, encoding="utf-8")
    if scenario == "corrupt":
        (inputs / _WHEEL).write_bytes(b"tampered")
    remote_sums = tmp_path / "remote-SHA256SUMS"
    remote_sums.write_text(
        sums if scenario != "release_mismatch" else "0" * 64 + f"  {_WHEEL}\n",
        encoding="utf-8",
    )
    release = {
        "tag_name": f"v{_VERSION}",
        "draft": scenario == "draft",
        "prerelease": False,
        "immutable": scenario != "mutable",
    }
    release_json = tmp_path / "release.json"
    release_json.write_text(json.dumps(release), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "gh", _STUB_GH)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
        "RELEASE_VERSION": _VERSION,
        "RUNNER_TEMP": str(runner_temp),
        "TMPDIR": str(tmp_path),
        "FAKE_RELEASE_JSON": str(release_json),
        "FAKE_REMOTE_SUMS": str(remote_sums),
        "FAKE_DOWNLOAD_FAIL": "1" if scenario == "download_failure" else "",
    }
    return work, env


@pytest.mark.parametrize(
    "scenario,success",
    [
        ("ok", True),
        ("corrupt", False),
        ("extra_listed", False),
        ("release_mismatch", False),
        ("mutable", False),
        ("draft", False),
        ("download_failure", False),
    ],
)
def test_stage_step_admits_only_the_attested_wheel(tmp_path: Path, scenario: str, success: bool) -> None:
    work, env = _prepare_stage(tmp_path, scenario=scenario)
    script = _run_body(_steps(_pypi_job())[_STEP_ORDER[1]])
    result = subprocess.run(
        ["bash", "-c", script], cwd=work, env=env, text=True, capture_output=True, timeout=30
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    if success:
        assert sorted(p.name for p in (work / "dist").iterdir()) == [_WHEEL]
        assert (Path(env["RUNNER_TEMP"]) / "SHA256SUMS").is_file()
    else:
        assert "::error::" in result.stderr or result.returncode != 0


_FAKE_PYPI_SITECUSTOMIZE = '''
import io
import json
import os
import time
import urllib.error
import urllib.request

_responses = json.loads(open(os.environ["FAKE_PYPI_RESPONSES"], encoding="utf-8").read())
_calls = {"n": 0}


def _fake_urlopen(request, timeout=None):
    url = request if isinstance(request, str) else request.full_url
    assert url == "https://pypi.org/pypi/contextual-orchestrator/0.2.0/json", url
    index = min(_calls["n"], len(_responses) - 1)
    _calls["n"] += 1
    status, files = _responses[index]
    if status != 200:
        raise urllib.error.HTTPError(url, status, "fake", {}, io.BytesIO(b""))
    body = json.dumps({"urls": [{"filename": n, "digests": {"sha256": d}} for n, d in files.items()]})
    return io.BytesIO(body.encode())


urllib.request.urlopen = _fake_urlopen
time.sleep = lambda seconds: None
'''


def _run_pypi_check(tmp_path: Path, step_name: str, responses: list) -> subprocess.CompletedProcess[str]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    (runner_temp / "SHA256SUMS").write_text(f"{'a' * 64}  {_WHEEL}\n", encoding="utf-8")
    site = tmp_path / "fake-site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(_FAKE_PYPI_SITECUSTOMIZE, encoding="utf-8")
    responses_path = tmp_path / "responses.json"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(site),
        "RUNNER_TEMP": str(runner_temp),
        "RELEASE_VERSION": _VERSION,
        "PYPI_PROJECT": "contextual-orchestrator",
        "FAKE_PYPI_RESPONSES": str(responses_path),
    }
    script = _run_body(_steps(_pypi_job())[step_name])
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30
    )


@pytest.mark.parametrize(
    "responses,success",
    [
        ([[404, {}]], True),
        ([[200, {_WHEEL: "a" * 64}]], True),
        ([[200, {_WHEEL: "b" * 64}]], False),
        ([[200, {"contextual_orchestrator-0.2.0.tar.gz": "c" * 64}]], False),
        ([[500, {}]], False),
    ],
)
def test_pre_upload_check_refuses_foreign_files(tmp_path: Path, responses: list, success: bool) -> None:
    result = _run_pypi_check(tmp_path, _STEP_ORDER[3], responses)
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    if not success:
        assert "::error::" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "responses,success",
    [
        ([[200, {_WHEEL: "a" * 64}]], True),
        ([[404, {}], [200, {}], [200, {_WHEEL: "a" * 64}]], True),
        ([[404, {}]], False),
        ([[200, {_WHEEL: "b" * 64}]], False),
        ([[200, {_WHEEL: "a" * 64, "extra.tar.gz": "d" * 64}]], False),
        ([[503, {}]], False),
    ],
)
def test_post_upload_check_requires_exactly_the_verified_files(
    tmp_path: Path, responses: list, success: bool
) -> None:
    result = _run_pypi_check(tmp_path, _STEP_ORDER[6], responses)
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    if not success:
        assert "::error::" in result.stdout + result.stderr
