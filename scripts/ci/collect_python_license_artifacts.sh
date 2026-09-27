#!/usr/bin/env bash
# Download the inventory's Python scopes without installing or building them.
set -euo pipefail
shopt -s nullglob
artifact_dir="${1:?artifact directory required}"
export_dir="$(mktemp -d)"
trap 'rm -rf "$export_dir"' EXIT
python -m scripts.ci.dependency_inventory --repository-root . \
  --output /dev/null --check-sources-only
uv export --locked --offline --all-groups --all-extras --no-emit-project \
  --output-file "$export_dir/requirements.txt" >/dev/null
python - "$export_dir" "$export_dir/requirements.txt" requirements.lock requirements*.txt fuzz/requirements*.txt <<'PY'
import re
import sys
from pathlib import Path
from scripts.ci.dependency_inventory import external_source_findings

for index, name in enumerate(sys.argv[2:]):
    path = Path(name)
    raw = path.read_bytes()
    findings = external_source_findings(path, raw)
    if findings:
        raise SystemExit("Unreviewed requirement sources: " + "; ".join(findings))
    # Licensing includes packages that this interpreter would never install.
    # Preserve pins and hashes; remove markers only in temporary evidence inputs.
    lines = []
    for line in raw.decode().splitlines():
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*==", line) and ";" in line:
            continuation = " \\" if line.rstrip().endswith("\\") else ""
            line = line.split(";", 1)[0].rstrip() + continuation
        lines.append(line)
    (Path(sys.argv[1]) / f"scope-{index:03d}.txt").write_text("\n".join(lines) + "\n")
PY
for requirements in "$export_dir"/scope-*.txt; do
  python -m pip download --require-hashes -r "$requirements" \
    --no-deps --only-binary=:all: --dest "$artifact_dir"
done
