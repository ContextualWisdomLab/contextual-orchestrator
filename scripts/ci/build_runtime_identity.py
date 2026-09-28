"""Write the release identity embedded in the exact-commit wheel."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from contextual_orchestrator.runtime_identity import current_schema_sha256


def main(source_sha: str, version: str) -> None:
    root = Path(__file__).resolve().parents[2]
    actual_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    actual_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if source_sha != actual_sha or version != actual_version:
        raise SystemExit("release identity must match the checked out source and package version")
    if subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root, check=False).returncode != 0:
        raise SystemExit("release identity requires unmodified tracked source")
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "contextual_orchestrator"],
        cwd=root,
        text=True,
    ).splitlines()
    if any(
        path.endswith((".py", ".json", ".pyc", ".pyd"))
        or (path.endswith(".so") and not Path(path).name.startswith("_decision_receipt."))
        for path in untracked
    ):
        raise SystemExit("release identity requires no untracked package source")
    manifest = {
        "version": version,
        "release_tag": f"v{version}",
        "source_sha": source_sha,
        "schema_sha256": current_schema_sha256(),
    }
    path = root / "contextual_orchestrator" / "_release_identity.json"
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_runtime_identity SOURCE_SHA VERSION")
    main(sys.argv[1], sys.argv[2])
