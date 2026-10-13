"""Prepare the hashed runtime lock for pip-audit's index-package input."""

from pathlib import Path
import re
import sys
import tomllib


_VCS_PIN = re.compile(
    r"fast-mlsirm @ git\+https://github\.com/ContextualWisdomLab/"
    r"fast-mlsirm\.git@(?P<revision>[0-9a-f]{40})"
)


def prepare_runtime_lock_audit(source: Path, uv_lock: Path, output: Path) -> None:
    """Check the non-PyPI VCS pin against uv.lock; keep every index requirement."""
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    direct_refs = [
        (index, line)
        for index, line in enumerate(lines)
        if line.startswith("fast-mlsirm @ ")
    ]
    match = _VCS_PIN.fullmatch(direct_refs[0][1].strip()) if len(direct_refs) == 1 else None
    if match is None:
        raise ValueError("runtime lock must contain one pinned fast-mlsirm source")
    packages = [
        package for package in tomllib.loads(uv_lock.read_text(encoding="utf-8"))["package"]
        if package["name"] == "fast-mlsirm"
    ]
    revision = match.group("revision")
    expected_source = (
        "https://github.com/ContextualWisdomLab/fast-mlsirm.git"
        f"?rev={revision}#{revision}"
    )
    if len(packages) != 1 or packages[0]["source"].get("git") != expected_source:
        raise ValueError("runtime and uv locks must pin the same fast-mlsirm source")
    del lines[direct_refs[0][0]]
    output.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare_runtime_lock_audit.py SOURCE UV_LOCK OUTPUT")
    prepare_runtime_lock_audit(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
