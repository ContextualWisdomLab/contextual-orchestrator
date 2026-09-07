"""Check the emitted group-name pattern with HTML's UnicodeSets semantics."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.admin import ADMIN_HTML  # noqa: E402


def test_group_pattern_compiles_and_preserves_name_rules() -> None:
    """Compile the actual HTML pattern and retain its prior accepted language."""
    match = re.search(r'<input id="modelGroupName"[^>]*pattern="([^"]+)"', ADMIN_HTML)
    assert match is not None
    cases = {
        "audit_group": True,
        "audit-group": True,
        "Audit_Group2": True,
        "a_b-c": True,
        "1_2": True,
        "": False,
        "audit": False,
        "audit__group": False,
        "audit--group": False,
        "_audit_group": False,
        "audit_group_": False,
        "audit/group": False,
        "audit group": False,
        "audit.group": False,
        "감사_그룹": False,
        "audit_group\n": False,
    }
    script = "\n".join([
        'import assert from "node:assert/strict";',
        f"const pattern = new RegExp({json.dumps(match.group(1))}, 'v');",
        f"const cases = {json.dumps(cases)};",
        "for (const [value, expected] of Object.entries(cases)) {",
        "  const found = pattern.exec(value);",
        "  assert.equal(found !== null && found[0] === value, expected, value);",
        "}",
    ])
    result = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module"],
        input=script, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
