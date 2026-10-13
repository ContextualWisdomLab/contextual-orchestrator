"""Planning ADR identifiers must remain unique and match their filenames."""

from __future__ import annotations

from pathlib import Path
import re

import pytest


def test_planning_adr_identifiers_are_unique_and_match_content() -> None:
    """Reject duplicate or internally inconsistent planning ADR identifiers."""
    adr_files = sorted(
        path for path in Path("docs/planning/adrs").glob("[0-9][0-9][0-9][0-9]-*.md")
        if not re.match(r"^\d{4}-\d{2}-\d{2}-", path.name)
    )
    identifiers = [path.name[:4] for path in adr_files]

    assert len(identifiers) == len(set(identifiers)), "duplicate planning ADR identifier"
    for path, identifier in zip(adr_files, identifiers, strict=True):
        assert re.fullmatch(r"\d{4}-[a-z][a-z0-9-]*\.md", path.name), (
            f"{path} has an invalid ADR filename"
        )
        content = path.read_text(encoding="utf-8")
        frontmatter = content.split("---", 2)[1] if content.startswith("---") else ""
        frontmatter_ids = re.findall(r'^id: "(\d{4})"$', frontmatter, re.MULTILINE)
        heading_ids = re.findall(r"^# ADR (\d{4})(?::|\b)", content, re.MULTILINE)
        assert len(frontmatter_ids) <= 1, f"{path} has duplicate front matter IDs"
        assert len(heading_ids) <= 1, f"{path} has duplicate ADR headings"
        declared_ids = set(frontmatter_ids + heading_ids)
        assert declared_ids, f"{path} has no ADR identifier"
        assert declared_ids == {identifier}


def test_planning_adr_duplicate_is_detected_with_uppercase_filename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A malformed name must not conceal a duplicate ADR identifier."""
    root = tmp_path / "docs/planning/adrs"
    root.mkdir(parents=True)
    (root / "0136-OpenCode.md").touch()
    (root / "0136-opencode-go.md").touch()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(AssertionError, match="duplicate planning ADR identifier"):
        test_planning_adr_identifiers_are_unique_and_match_content()
