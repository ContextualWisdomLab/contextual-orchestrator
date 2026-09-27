"""Exercise collection and fail-closed boundaries without downloading packages."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", [None, "input", "export", "download"])
def test_all_python_scopes_are_collected_before_installation(tmp_path, failure):
    pins = ["requirements.lock", "requirements-security-ci.txt", "fuzz/requirements-property.txt"]
    for name in pins:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("safe-library==1.0 --hash=sha256:aa\n")
    if failure == "input":
        (tmp_path / pins[-1]).write_text("unsafe @ https://example.invalid/package.whl\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "downloads.jsonl"
    python = bin_dir / "python"
    python.write_text(f'''#!{sys.executable}
import json, os, subprocess, sys
if sys.argv[1:4] == ["-m", "pip", "download"]:
    with open({str(log)!r}, "a") as out:
        out.write(json.dumps(sys.argv[1:]) + "\\n")
    raise SystemExit(9 if {failure!r} == "download" else 0)
raise SystemExit(subprocess.call([{sys.executable!r}, *sys.argv[1:]]))
''')
    uv = bin_dir / "uv"
    uv.write_text(f'''#!{sys.executable}
from pathlib import Path
import sys
assert sys.argv[1:7] == ["export", "--locked", "--offline", "--all-groups", "--all-extras", "--no-emit-project"]
Path(sys.argv[-1]).write_text({("unsafe @ git+https://example.invalid/pkg.git\n" if failure == "export" else "safe-library==1.0 --hash=sha256:aa\n")!r})
''')
    for executable in (python, uv):
        executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", PYTHONPATH=str(ROOT))
    result = subprocess.run(["bash", str(ROOT / "scripts/ci/collect_python_license_artifacts.sh"),
                             str(tmp_path / "artifacts")], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert (result.returncode == 0) == (failure is None), result.stderr
    assert len(calls) == ({None: 4, "input": 0, "export": 0, "download": 1}[failure])
    if failure is None:
        assert [call[call.index("-r") + 1] for call in calls[1:]] == pins
    for call in calls:
        assert {"--require-hashes", "--no-deps", "--only-binary=:all:"} <= set(call)
