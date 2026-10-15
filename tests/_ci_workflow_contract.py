"""Read immutable central workflow fixtures without network access or execution."""

import hashlib
import json
import re
from pathlib import Path


def execution_contract(root: Path, workflow_path: str) -> str:
    """Return local execution or the verified, publication-gated supplier fixture."""
    caller = (root / workflow_path).read_text(encoding="utf-8")
    uses = re.findall(r"(?m)^\s+uses:\s+(\S+)", caller)
    central = [value for value in uses if "/.github/workflows/" in value]
    if not central:
        if "runs-on:" not in caller:
            raise AssertionError("Workflow has no local or central execution contract")
        return caller
    if len(central) != 1 or len(uses) != 1 or "runs-on:" in caller or "steps:" in caller:
        raise AssertionError("Expected one thin reusable-workflow caller")
    reference = central[0]
    match = re.fullmatch(
        r"ContextualWisdomLab/\.github/\.github/workflows/([a-z0-9-]+\.yml)@([0-9a-f]{40})",
        reference,
    )
    if match is None:
        raise AssertionError("Central workflow must use its fixed repository and immutable commit")
    name, commit = match.groups()
    directory = root / "tests/fixtures/central_workflows"
    manifest = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
    if manifest.get("reference") != reference:
        raise AssertionError("Caller pin does not match verified fixture provenance")
    if manifest.get("protected_publication_commit") != commit:
        raise AssertionError("Supplier is not verified as protected-published; activation remains blocked")
    raw = (directory / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise AssertionError("Central workflow fixture digest mismatch")
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw, usedforsecurity=False).hexdigest()
    if blob != manifest.get("git_blob_sha"):
        raise AssertionError("Central workflow fixture Git identity mismatch")
    return raw.decode("utf-8")
