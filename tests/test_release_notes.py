"""Tests for the canonical-release CHANGELOG/version extraction helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PYPROJECT = """[project]
name = "contextual-orchestrator"
version = "0.2.0"
description = "x"
"""

_CHANGELOG = """# Changelog

## [0.2.0] - Unreleased

### Added

- New thing.

### Fixed

- Old bug.

## [0.1.0] - Unreleased

### Added

- First thing.
"""


def test_read_declared_version_extracts_the_project_version() -> None:
    """The declared version comes from `[project]`'s `version = "..."` line only."""
    module = _module()
    assert module.read_declared_version(_PYPROJECT) == "0.2.0"


def test_read_declared_version_rejects_a_missing_version_field() -> None:
    """A pyproject with no version field must fail closed, not guess."""
    module = _module()
    with pytest.raises(ValueError, match="version"):
        module.read_declared_version("[project]\nname = \"x\"\n")


def test_read_declared_version_rejects_a_missing_project_table() -> None:
    """A pyproject with no `[project]` table at all must fail closed too."""
    module = _module()
    with pytest.raises(ValueError, match=r"\[project\]"):
        module.read_declared_version('[tool.other]\nversion = "9.9.9"\n')


def test_read_declared_version_ignores_a_same_named_key_in_an_earlier_table() -> None:
    """A `version` key under an unrelated table must never be mistaken for
    `[project]`'s real version, even when it textually precedes it."""
    module = _module()
    pyproject = (
        '[tool.some_tool]\n'
        'version = "9.9.9"\n'
        '\n'
        '[project]\n'
        'name = "contextual-orchestrator"\n'
        'version = "0.2.0"\n'
        'description = "x"\n'
    )
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_ignores_a_same_named_key_in_a_later_table() -> None:
    """A `version` key in a table declared after `[project]` must not leak in
    either, once the `[project]` table's own body has ended."""
    module = _module()
    pyproject = (
        '[project]\n'
        'name = "x"\n'
        'version = "0.2.0"\n'
        '\n'
        '[tool.other]\n'
        'version = "7.7.7"\n'
    )
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_tolerates_a_trailing_comment_on_the_project_header() -> None:
    """`[project] # comment` is valid TOML; a regex anchored on `^\\[project\\]\\s*$`
    would reject it as "no [project] table" (CodeRabbit finding: TOML parsed
    with regex instead of a real parser)."""
    module = _module()
    pyproject = '[project] # the project table\nname = "x"\nversion = "0.2.0"\n'
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_accepts_a_single_quoted_version() -> None:
    """TOML allows single-quoted (literal) strings too, not just double
    quotes -- a regex anchored on `"([^"]+)"` would miss this."""
    module = _module()
    pyproject = "[project]\nname = 'x'\nversion = '0.2.0'\n"
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_tolerates_a_trailing_comment_on_the_version_line() -> None:
    """`version = "0.2.0"  # released` is valid TOML; a regex requiring
    `\\s*$` right after the closing quote would reject it."""
    module = _module()
    pyproject = '[project]\nname = "x"\nversion = "0.2.0"  # released\n'
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_is_not_confused_by_a_multiline_string_containing_a_bracket_line() -> None:
    """A multiline string value whose body has a line starting with `[` must
    never be mistaken for the next table's header -- a regex scanning for
    `^\\[` to find the `[project]` table's own boundary would truncate the
    table body before `version` and wrongly report it missing."""
    module = _module()
    pyproject = (
        "[project]\n"
        'name = "x"\n'
        'description = """\n'
        "Some text.\n"
        "[not a real table]\n"
        "More text.\n"
        '"""\n'
        'version = "0.2.0"\n'
    )
    assert module.read_declared_version(pyproject) == "0.2.0"


def test_read_declared_version_rejects_invalid_toml() -> None:
    """Text that is not valid TOML at all must fail closed with a clear
    message, not raise an unrelated parser exception."""
    module = _module()
    with pytest.raises(ValueError, match="not valid TOML"):
        module.read_declared_version("[project\nversion = \n")


def test_extract_changelog_section_returns_only_the_matching_version_body() -> None:
    """Only the body between the matching heading and the next heading is returned."""
    module = _module()
    section = module.extract_changelog_section(_CHANGELOG, "0.2.0")
    assert "New thing." in section
    assert "Old bug." in section
    assert "First thing." not in section
    assert "## [0.1.0]" not in section


def test_extract_changelog_section_matches_a_dated_heading_too() -> None:
    """A heading with a real date, not just 'Unreleased', still matches."""
    module = _module()
    dated = _CHANGELOG.replace("## [0.2.0] - Unreleased", "## [0.2.0] - 2026-09-02")
    section = module.extract_changelog_section(dated, "0.2.0")
    assert "New thing." in section


def test_extract_changelog_section_rejects_a_missing_version() -> None:
    """A version with no CHANGELOG section must fail closed, not publish empty notes."""
    module = _module()
    with pytest.raises(ValueError, match=r"0\.9\.9"):
        module.extract_changelog_section(_CHANGELOG, "0.9.9")


def test_extract_changelog_section_rejects_an_empty_section() -> None:
    """A heading with no content beneath it must fail closed."""
    module = _module()
    empty = "## [0.3.0] - Unreleased\n\n## [0.2.0] - Unreleased\n\nbody\n"
    with pytest.raises(ValueError, match="empty"):
        module.extract_changelog_section(empty, "0.3.0")


def test_render_release_notes_includes_provenance_and_section_body() -> None:
    """The rendered body cites the exact commit and repository alongside notes."""
    module = _module()
    body = module.render_release_notes(
        version="0.2.0",
        section_body="- New thing.",
        repository="ContextualWisdomLab/contextual-orchestrator",
        commit_sha="a" * 40,
    )
    assert "0.2.0" in body
    assert "a" * 40 in body
    assert "ContextualWisdomLab/contextual-orchestrator" in body
    assert "- New thing." in body


def test_main_writes_rendered_notes_to_the_requested_output_path(tmp_path: Path) -> None:
    """The CLI wires pyproject/changelog extraction into one written notes file."""
    module = _module()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(_PYPROJECT, encoding="utf-8")
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(_CHANGELOG, encoding="utf-8")
    output_path = tmp_path / "notes.md"

    exit_code = module.main(
        [
            "--pyproject",
            str(pyproject_path),
            "--changelog",
            str(changelog_path),
            "--version",
            "0.2.0",
            "--repository",
            "ContextualWisdomLab/contextual-orchestrator",
            "--commit-sha",
            "b" * 40,
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    written = output_path.read_text(encoding="utf-8")
    assert "New thing." in written
    assert "b" * 40 in written


def test_main_fails_closed_when_version_input_does_not_match_pyproject(tmp_path: Path) -> None:
    """The CLI refuses to render notes for a version pyproject.toml does not declare."""
    module = _module()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(_PYPROJECT, encoding="utf-8")
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(_CHANGELOG, encoding="utf-8")

    exit_code = module.main(
        [
            "--pyproject",
            str(pyproject_path),
            "--changelog",
            str(changelog_path),
            "--version",
            "9.9.9",
            "--repository",
            "ContextualWisdomLab/contextual-orchestrator",
            "--commit-sha",
            "c" * 40,
            "--output",
            str(tmp_path / "notes.md"),
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "notes.md").exists()


def test_main_prints_to_stdout_when_no_output_path_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting --output prints the rendered notes for a caller to capture."""
    module = _module()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(_PYPROJECT, encoding="utf-8")
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(_CHANGELOG, encoding="utf-8")

    exit_code = module.main(
        [
            "--pyproject",
            str(pyproject_path),
            "--changelog",
            str(changelog_path),
            "--version",
            "0.2.0",
            "--repository",
            "ContextualWisdomLab/contextual-orchestrator",
            "--commit-sha",
            "d" * 40,
        ]
    )

    assert exit_code == 0
    assert "New thing." in capsys.readouterr().out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
