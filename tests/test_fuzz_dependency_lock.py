from __future__ import annotations

import re
import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_METADATA_PATH = REPOSITORY_ROOT / "pyproject.toml"
FUZZ_LOCK_PATH = REPOSITORY_ROOT / "fuzz" / "requirements-atheris.txt"
MARKER_PATTERN = re.compile(
    r"^atheris==(?P<release>\d+\.\d+\.\d+)\s*;\s*"
    r"(?P<field>python_version|python_full_version)\s*"
    r"(?P<operator><|>=)\s*['\"](?P<boundary>\d+\.\d+)['\"]$"
)
HASH_PATTERN = re.compile(r"--hash=sha256:(?P<digest>[0-9a-f]{64})")


@dataclass(frozen=True)
class InterpreterRequirement:
    """One interpreter-gated Atheris release parsed from project or lock data."""

    release: str
    field: str
    operator: str
    boundary: tuple[int, int]
    hashes: frozenset[str] = frozenset()

    def matches(self, python_version: tuple[int, int]) -> bool:
        """Return whether the requirement applies to one Python major/minor pair."""

        if self.operator == "<":
            return python_version < self.boundary
        if self.operator == ">=":
            return python_version >= self.boundary
        raise AssertionError(f"Unsupported marker operator: {self.operator}")


def _version_pair(value: str) -> tuple[int, int]:
    """Parse a dotted major/minor version into a comparable integer pair."""

    major, minor = value.split(".", 1)
    return int(major), int(minor)


def _parse_requirement(requirement: str) -> InterpreterRequirement:
    """Parse the deliberately narrow Atheris marker grammar used by this lock."""

    match = MARKER_PATTERN.fullmatch(requirement.strip())
    assert match is not None, f"Unexpected Atheris requirement: {requirement!r}"
    return InterpreterRequirement(
        release=match.group("release"),
        field=match.group("field"),
        operator=match.group("operator"),
        boundary=_version_pair(match.group("boundary")),
    )


def _project_requirements() -> tuple[InterpreterRequirement, ...]:
    """Load all Atheris requirements declared by the project's fuzz extra."""

    metadata = tomllib.loads(PROJECT_METADATA_PATH.read_text(encoding="utf-8"))
    fuzz_extra = metadata["project"]["optional-dependencies"]["fuzz"]
    return tuple(
        _parse_requirement(requirement)
        for requirement in fuzz_extra
        if requirement.startswith("atheris==")
    )


def _lock_requirements() -> tuple[InterpreterRequirement, ...]:
    """Load interpreter markers and SHA-256 evidence from the universal lock."""

    lines = FUZZ_LOCK_PATH.read_text(encoding="utf-8").splitlines()
    requirements: list[InterpreterRequirement] = []
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        if not line.startswith("atheris=="):
            line_index += 1
            continue

        assert line.rstrip().endswith("\\"), (
            f"Atheris lock header must continue to hashes: {line!r}"
        )
        parsed = _parse_requirement(line.rstrip()[:-1].rstrip())
        line_index += 1
        hashes: set[str] = set()
        while line_index < len(lines) and lines[line_index].startswith((" ", "\t")):
            hash_match = HASH_PATTERN.search(lines[line_index])
            if hash_match is not None:
                hashes.add(hash_match.group("digest"))
            line_index += 1
        requirements.append(
            InterpreterRequirement(
                release=parsed.release,
                field=parsed.field,
                operator=parsed.operator,
                boundary=parsed.boundary,
                hashes=frozenset(hashes),
            )
        )
    return tuple(requirements)


def _selected_release(
    requirements: tuple[InterpreterRequirement, ...],
    python_version: tuple[int, int],
) -> str:
    """Require exactly one applicable release for a representative interpreter."""

    selected = [
        requirement.release
        for requirement in requirements
        if requirement.matches(python_version)
    ]
    assert len(selected) == 1, (
        f"Expected exactly one Atheris release for Python {python_version}, "
        f"selected {selected}"
    )
    return selected[0]


def test_fuzz_extra_selects_one_published_release_per_supported_interpreter() -> None:
    """Project metadata must partition supported interpreters without gaps or overlap."""

    requirements = _project_requirements()
    assert {
        (entry.release, entry.field, entry.operator, entry.boundary)
        for entry in requirements
    } == {
        ("3.0.0", "python_version", "<", (3, 13)),
        ("3.1.0", "python_version", ">=", (3, 13)),
    }
    assert _selected_release(requirements, (3, 11)) == "3.0.0"
    assert _selected_release(requirements, (3, 13)) == "3.1.0"
    assert _selected_release(requirements, (3, 14)) == "3.1.0"


def test_universal_lock_matches_markers_and_published_hashes() -> None:
    """The universal lock must mirror project markers and hash every selected wheel."""

    requirements = _lock_requirements()
    assert {
        (entry.release, entry.field, entry.operator, entry.boundary)
        for entry in requirements
    } == {
        ("3.0.0", "python_full_version", "<", (3, 13)),
        ("3.1.0", "python_full_version", ">=", (3, 13)),
    }
    assert _selected_release(requirements, (3, 11)) == "3.0.0"
    assert _selected_release(requirements, (3, 13)) == "3.1.0"
    assert _selected_release(requirements, (3, 14)) == "3.1.0"

    hashes_by_release = {entry.release: entry.hashes for entry in requirements}
    assert hashes_by_release["3.0.0"] == {
        "1f0929c7bc3040f3fe4102e557718734190cf2d7718bbb8e3ce6d3eb56ef5bb3",
        "510e502c57b6dc615fb174066407af620d4c7f73cf08a782c86e7761bf12c4eb",
        "8a5c8a781467c187da40fd29139784193e2647058831f837f675d0bb8cbd8746",
        "a402cdca8a650d1371050b1f9552eb4cdc488d2db64950d603c4560318365eac",
    }
    assert hashes_by_release["3.1.0"] == {
        "315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011",
        "ec5e11f21a4c197fe91f7aea2b2de88e623c73a21fc07b105ac6329a1588457b",
        "f8a9f51ce8369026e8eb7b7174835e8c4c85a1a6db5d9add36c15100779d2a39",
    }
