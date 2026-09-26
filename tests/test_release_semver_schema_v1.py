"""Contract tests for the versioned release SemVer observation schemas (v1).

These schemas are docs/data only: there is no transport and no version
decision in this slice (docs/planning/adrs/0137-release-semver-observation-schema.md).
Every test runs on repository files and fixtures; nothing calls a model.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT_DIR / "contextual_orchestrator"
FAMILY_DIR = PACKAGE_DIR / "schemas" / "release_semver"
MANIFEST_PATH = FAMILY_DIR / "MANIFEST.json"
CONFORMANCE_PATH = (
    ROOT_DIR / "tests" / "fixtures" / "release_semver_v1_conformance.json"
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ID_PREFIX = "https://github.com/ContextualWisdomLab/contextual-orchestrator/schemas/release_semver/"

# Immutability guard. v1 is frozen once released: editing or deleting any of
# these files must fail here. A schema change is a new ``v2/`` directory with
# its own MANIFEST entries, never an edit to these bytes or to this table.
PINNED_V1_SHA256 = {
    "v1/evidence.schema.json": "1006bf906ce023dc61f6d7c007576f39155d3636e7c599aeebabe10ca6582164",
    "v1/observation.schema.json": "1d0ee9ae64d135a299e28a84c81f1dc15010375b369f763ad695c8a05679c34d",
    "v1/receipt_envelope.schema.json": "62010e31397d8e0c85bcea33dd6fa23ff54f3ef7e53250a89d6c944148753966",
}

FORBIDDEN_PROPERTY_NAMES = frozenset({"release_version"})
FORBIDDEN_OBSERVATION_PROPERTY_NAMES = frozenset(
    {"confidence", "probability", "score", "release_version", "next_version", "bump"}
)


def _manifest() -> dict[str, Any]:
    """Load the schema-family manifest."""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _schema_documents() -> dict[str, dict[str, Any]]:
    """Return every manifest-listed schema keyed by its short name."""
    documents = {}
    for entry in _manifest()["schemas"].values():
        path = FAMILY_DIR / entry["path"]
        documents[path.name.removesuffix(".schema.json")] = json.loads(
            path.read_text(encoding="utf-8")
        )
    return documents


def _validator(name: str) -> Draft202012Validator:
    """Build a Draft 2020-12 validator that resolves sibling schemas by $id."""
    documents = _schema_documents()
    registry = Registry().with_resources(
        (
            document["$id"],
            Resource.from_contents(document, default_specification=DRAFT202012),
        )
        for document in documents.values()
    )
    return Draft202012Validator(documents[name], registry=registry)


def _conformance() -> dict[str, Any]:
    """Load the fixture-only conformance document."""
    return json.loads(CONFORMANCE_PATH.read_text(encoding="utf-8"))


def _apply(
    document: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a copy of ``document`` with fixture set/remove operations applied."""
    result = copy.deepcopy(document)
    for operation in operations:
        *parents, leaf = operation["path"]
        target: Any = result
        for key in parents:
            target = target[key]
        if operation["op"] == "remove":
            del target[leaf]
        elif operation["op"] == "set":
            target[leaf] = copy.deepcopy(operation["value"])
        else:
            raise AssertionError(f"unknown fixture operation {operation['op']!r}")
    return result


def _conformance_cases() -> list[dict[str, Any]]:
    """Expand fixtures into ``{name, schema, valid, document}`` cases."""
    conformance = _conformance()
    cases = []
    for schema, base in conformance["base_documents"].items():
        cases.append(
            {
                "name": base["name"],
                "schema": schema,
                "valid": True,
                "document": base["document"],
            }
        )
    for case in conformance["cases"]:
        base = conformance["base_documents"][case["schema"]]["document"]
        cases.append(
            {
                "name": case["name"],
                "schema": case["schema"],
                "valid": case["valid"],
                "document": _apply(base, case["ops"]),
            }
        )
    return cases


def _property_names(node: Any) -> Iterator[str]:
    """Yield every declared property name and required entry in a schema tree."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            yield from properties
        required = node.get("required")
        if isinstance(required, list):
            yield from (value for value in required if isinstance(value, str))
        for value in node.values():
            yield from _property_names(value)
    elif isinstance(node, list):
        for value in node:
            yield from _property_names(value)


def _valid_document(schema: str) -> dict[str, Any]:
    """Return a deep copy of the valid base fixture document for one schema."""
    return copy.deepcopy(_conformance()["base_documents"][schema]["document"])


def test_manifest_hashes_match_schema_file_bytes() -> None:
    """Each manifest digest is the SHA-256 of the exact file bytes it names."""
    manifest = _manifest()
    assert manifest["manifest_version"] == 1
    assert manifest["family"] == "release_semver"
    assert manifest["digest_algorithm"] == "sha256"
    for schema_id, entry in manifest["schemas"].items():
        path = FAMILY_DIR / entry["path"]
        assert path.is_file(), schema_id
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], (
            schema_id
        )


def test_manifest_lists_exactly_the_schema_files_on_disk() -> None:
    """No schema file ships unlisted, and no listed file is missing."""
    on_disk = {
        path.relative_to(FAMILY_DIR).as_posix()
        for path in FAMILY_DIR.rglob("*.schema.json")
    }
    listed = {entry["path"] for entry in _manifest()["schemas"].values()}
    assert on_disk == listed


def test_every_schema_is_valid_draft_2020_12_with_manifest_id() -> None:
    """Schemas declare Draft 2020-12, pass meta-validation, and match their $id key."""
    for schema_id, entry in _manifest()["schemas"].items():
        document = json.loads((FAMILY_DIR / entry["path"]).read_text(encoding="utf-8"))
        assert document["$schema"] == DRAFT_2020_12
        Draft202012Validator.check_schema(document)
        assert document["$id"] == schema_id
        assert schema_id == ID_PREFIX + entry["path"]
        assert document["additionalProperties"] is False


def test_every_object_schema_is_closed() -> None:
    """Every object with declared properties rejects unknown members."""

    def walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            is_conditional_branch = where.endswith(("/if", "/then", "/else"))
            if isinstance(node.get("properties"), dict) and not is_conditional_branch:
                assert node.get("additionalProperties") is False, where
            for key, value in node.items():
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}/{index}")

    for name, document in _schema_documents().items():
        walk(document, name)


def test_v1_schema_files_are_immutable() -> None:
    """Fail if any released v1 schema file is edited, deleted, or re-pinned."""
    manifest_v1 = {
        entry["path"]: entry["sha256"]
        for entry in _manifest()["schemas"].values()
        if entry["path"].startswith("v1/")
    }
    assert manifest_v1 == PINNED_V1_SHA256
    for relative_path, digest in PINNED_V1_SHA256.items():
        path = FAMILY_DIR / relative_path
        assert path.is_file(), f"released schema {relative_path} was deleted"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, (
            f"released schema {relative_path} changed; add a new version instead"
        )


def test_no_schema_can_represent_a_release_version() -> None:
    """contextual-orchestrator never emits a version: no schema declares one."""
    for name, document in _schema_documents().items():
        names = set(_property_names(document))
        assert not names & FORBIDDEN_PROPERTY_NAMES, name


def test_observation_has_no_self_reported_authority_field() -> None:
    """A model self-report (confidence, score, bump, version) is not representable."""
    names = set(_property_names(_schema_documents()["observation"]))
    assert not names & FORBIDDEN_OBSERVATION_PROPERTY_NAMES


@pytest.mark.parametrize(
    "case",
    _conformance_cases(),
    ids=lambda case: case["name"],
)
def test_conformance_fixture_case(case: dict[str, Any]) -> None:
    """Each fixture document validates or fails exactly as declared."""
    errors = list(_validator(case["schema"]).iter_errors(case["document"]))
    if case["valid"]:
        assert errors == [], [error.message for error in errors]
    else:
        assert errors, "expected schema rejection"


def test_conformance_fixture_covers_each_schema_both_ways() -> None:
    """Every schema has at least one accepted and one rejected fixture."""
    seen = {(case["schema"], case["valid"]) for case in _conformance_cases()}
    for name in _schema_documents():
        assert (name, True) in seen, name
        assert (name, False) in seen, name


def test_fixture_documents_echo_the_canonical_evidence_digest() -> None:
    """Fixture digests follow the documented canonical form of the evidence pack."""
    fixture = _conformance()
    evidence = _valid_document("evidence")
    canonical = json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert fixture["canonical_evidence_sha256"] == digest
    assert _valid_document("observation")["evidence_sha256"] == digest
    envelope = _valid_document("receipt_envelope")
    assert envelope["evidence_sha256"] == digest
    assert all(
        item["observation"]["evidence_sha256"] == digest
        for item in envelope["observations"]
    )


def test_fixture_envelope_binds_the_manifest_schema_digests() -> None:
    """The valid envelope fixture names the exact evidence/observation schema digests."""
    by_name = {
        Path(entry["path"]).name: entry["sha256"]
        for entry in _manifest()["schemas"].values()
    }
    envelope = _valid_document("receipt_envelope")
    assert envelope["schema_sha256"] == {
        "evidence": by_name["evidence.schema.json"],
        "observation": by_name["observation.schema.json"],
    }


@pytest.mark.parametrize(
    ("schema", "mutate"),
    [
        (
            "evidence",
            lambda d: d.__setitem__("commit_titles", [d["commit_titles"][0]] * 513),
        ),
        ("evidence", lambda d: d.__setitem__("pr_titles", [d["pr_titles"][0]] * 257)),
        (
            "evidence",
            lambda d: d.__setitem__(
                "changelog_fragments", [d["changelog_fragments"][0]] * 257
            ),
        ),
        ("evidence", lambda d: d["commit_titles"][0].__setitem__("text", "x" * 2001)),
        (
            "evidence",
            lambda d: d["commit_titles"][0].__setitem__("ref", "commit:" + "a" * 250),
        ),
        (
            "observation",
            lambda d: d.__setitem__(
                "evidence_refs", [f"commit:{i:040x}" for i in range(65)]
            ),
        ),
        ("observation", lambda d: d.__setitem__("assignment_ref", "r" * 129)),
        (
            "receipt_envelope",
            lambda d: d.__setitem__("observations", [d["observations"][0]] * 33),
        ),
        (
            "receipt_envelope",
            lambda d: d["fast_mlsirm_receipt"].__setitem__(
                "schema_id", "urn:" + "x" * 509
            ),
        ),
    ],
)
def test_size_bounds_are_enforced(schema: str, mutate: Any) -> None:
    """Arrays, strings, and identifiers are bounded so documents stay small."""
    document = _valid_document(schema)
    assert list(_validator(schema).iter_errors(document)) == []
    mutate(document)
    assert list(_validator(schema).iter_errors(document))


def test_package_data_ships_every_schema_family_file() -> None:
    """The wheel's package-data globs cover the manifest and every schema file."""
    config = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["contextual_orchestrator"]
    shipped = [MANIFEST_PATH, *FAMILY_DIR.rglob("*.schema.json")]
    for path in shipped:
        relative = path.relative_to(PACKAGE_DIR).as_posix()
        assert any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns), (
            relative
        )
