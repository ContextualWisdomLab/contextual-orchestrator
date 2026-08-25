"""Planning ADR identifiers must remain unique and match their filenames."""

from __future__ import annotations

from pathlib import Path
import re


def test_planning_adr_identifiers_are_unique_and_match_content() -> None:
    """Reject duplicate or internally inconsistent planning ADR identifiers."""
    adr_files = sorted(Path("docs/planning/adrs").glob("[0-9][0-9][0-9][0-9]-*.md"))
    identifiers = [path.name[:4] for path in adr_files]

    assert len(identifiers) == len(set(identifiers))
    for path, identifier in zip(adr_files, identifiers, strict=True):
        content = path.read_text(encoding="utf-8")
        frontmatter_id = re.search(r'^id: "(\d{4})"$', content, re.MULTILINE)
        heading_id = re.search(r"^# ADR (\d{4})(?::|\b)", content, re.MULTILINE)
        declared_ids = {
            match.group(1)
            for match in (frontmatter_id, heading_id)
            if match is not None
        }
        assert declared_ids, f"{path} has no ADR identifier"
        assert declared_ids == {identifier}
