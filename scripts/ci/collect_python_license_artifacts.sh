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
python - "$export_dir/requirements.txt" <<'PY'
import sys
from pathlib import Path
from scripts.ci.dependency_inventory import external_source_findings

path = Path(sys.argv[1])
findings = external_source_findings(path, path.read_bytes())
if findings:
    raise SystemExit("Unreviewed exported requirement sources: " + "; ".join(findings))
PY
for requirements in "$export_dir/requirements.txt" requirements.lock requirements*.txt fuzz/requirements*.txt; do
  python -m pip download --require-hashes -r "$requirements" \
    --no-deps --only-binary=:all: --dest "$artifact_dir"
done
