"""Render one GitHub Release body from `pyproject.toml` and `CHANGELOG.md`.

This helper backs `.github/workflows/release.yml`. It never guesses a
version and never publishes empty notes: a missing `version` field, a
requested version absent from `CHANGELOG.md`, or a heading with no content
underneath all fail closed instead of producing a placeholder release body.
It has no network access and no GitHub credential; the workflow itself owns
tag/Release creation via the `gh` CLI.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

_HEADING_PATTERN = re.compile(r"(?m)^## \[(?P<version>[^\]]+)\][^\n]*$")


def read_declared_version(pyproject_text: str) -> str:
    """Return the `[project]` table's `version` declared in *pyproject_text*.

    Parses *pyproject_text* as real TOML (stdlib `tomllib`, available since
    this repository's CI/workflow toolchain is pinned to Python 3.12) rather
    than scanning for a `version = "..."` line with a regex. A regex cannot
    correctly distinguish a `[project]` table header followed by a trailing
    comment, a single-quoted or comment-suffixed version value, or a
    multiline string value that happens to contain a line starting with
    `[`, from a genuine table boundary or version field -- a real parser
    handles all of those the same way a TOML-consuming tool would. Raises
    ``ValueError`` when *pyproject_text* is not valid TOML, there is no
    `[project]` table, or it has no string `version` field, rather than
    guessing a version from a tag, a changelog heading, or any other
    inferred source.
    """
    try:
        document = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"pyproject.toml is not valid TOML: {exc}") from exc
    project_table = document.get("project")
    if not isinstance(project_table, dict):
        raise ValueError("pyproject.toml has no [project] table")
    version = project_table.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml [project] table has no version field")
    return version


def extract_changelog_section(changelog_text: str, version: str) -> str:
    """Return the body of `CHANGELOG.md`'s `## [version]` section.

    Matches a heading regardless of what follows the version in brackets
    (``- Unreleased`` or a real date), and returns everything up to the next
    ``## [`` heading or end of file. Raises ``ValueError`` when *version* has
    no matching heading, or when the matched section has no content.
    """
    headings = list(_HEADING_PATTERN.finditer(changelog_text))
    for index, heading in enumerate(headings):
        if heading.group("version") != version:
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog_text)
        section = changelog_text[start:end].strip("\n")
        if not section.strip():
            raise ValueError(f"CHANGELOG.md section for {version} is empty")
        return section
    raise ValueError(f"CHANGELOG.md has no section for {version}")


def render_release_notes(*, version: str, section_body: str, repository: str, commit_sha: str) -> str:
    """Compose the final GitHub Release body from provenance and the section."""
    return (
        f"Release `v{version}` of `{repository}`, built from commit "
        f"`{commit_sha}`.\n\n{section_body}\n"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for rendering one release's notes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", required=True, help="path to pyproject.toml")
    parser.add_argument("--changelog", required=True, help="path to CHANGELOG.md")
    parser.add_argument("--version", required=True, help="version being released, e.g. 0.2.0")
    parser.add_argument("--repository", required=True, help="owner/name GitHub repository")
    parser.add_argument("--commit-sha", required=True, help="exact commit SHA being released")
    parser.add_argument("--output", help="write rendered notes here instead of stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Render one release's notes and fail closed on any mismatch or gap."""
    args = _parse_args(argv)
    try:
        pyproject_text = Path(args.pyproject).read_text(encoding="utf-8")
        declared_version = read_declared_version(pyproject_text)
        if declared_version != args.version:
            raise ValueError(
                f"pyproject.toml declares version {declared_version!r}, "
                f"but --version was {args.version!r}"
            )
        changelog_text = Path(args.changelog).read_text(encoding="utf-8")
        section_body = extract_changelog_section(changelog_text, args.version)
        notes = render_release_notes(
            version=args.version,
            section_body=section_body,
            repository=args.repository,
            commit_sha=args.commit_sha,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.output:
        Path(args.output).write_text(notes, encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
