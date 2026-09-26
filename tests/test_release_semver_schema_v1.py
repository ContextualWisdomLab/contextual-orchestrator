"""Contract tests for the versioned release SemVer observation schemas (v1).

These schemas are docs/data only: there is no transport and no version
decision in this slice (docs/planning/adrs/0137-release-semver-observation-schema.md).
Every test runs on repository files and fixtures; nothing calls a model and
nothing resolves a schema over the network.
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
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

ROOT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT_DIR / "contextual_orchestrator"
FAMILY_DIR = PACKAGE_DIR / "schemas" / "release_semver"
MANIFEST_PATH = FAMILY_DIR / "MANIFEST.json"
FIXTURES_DIR = ROOT_DIR / "tests" / "fixtures"
CONFORMANCE_PATH = FIXTURES_DIR / "release_semver_v1_conformance.json"
GITHUB_2260_DIR = FIXTURES_DIR / "github_2260_noema_semver"
GITHUB_2260_COMMIT = "dccacc77cd7be310d443b126ea98aec19216c816"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ID_PREFIX = "https://github.com/ContextualWisdomLab/contextual-orchestrator/schemas/release_semver/"

# Immutability guard. v1 is frozen once released: editing or deleting any of
# these files must fail here. A schema change is a new ``v2/`` directory with
# its own MANIFEST entries, never an edit to these bytes or to this table.
PINNED_V1_SHA256 = {
    "v1/evidence.schema.json": "9c6768602e4322ac0320d60e484fdfc56b26de3ce0c461e98a2911cc26f71736",
    "v1/observation.schema.json": "836ff74c10427f7023fc416ee0f843040a992160b9615f31411c03ee8f728146",
    "v1/receipt_envelope.schema.json": "5b14f3c9fcb8773f32db07360ac9b7fdaa4cda23f2b6df2a01ec7d7e382f35cb",
}

# The .github#2260 evidence-pack member names (tests/fixtures/noema_semver at
# dccacc77) and its API-finding lists (release-tag.yml ``api_keys``).
GITHUB_2260_PACK_MEMBERS = frozenset(
    {
        "previous_version",
        "changelog_fragments",
        "removed_public_symbols",
        "renamed_public_symbols",
        "required_arg_promotions",
        "deprecated_alias_only",
        "commit_titles",
        "pr_titles",
        "api_surface_inspected",
    }
)
GITHUB_2260_API_FINDING_LISTS = (
    "removed_public_symbols",
    "renamed_public_symbols",
    "required_arg_promotions",
)

FORBIDDEN_PROPERTY_NAMES = frozenset(
    {"release_version", "next_version", "outcome", "decision"}
)
FORBIDDEN_OBSERVATION_PROPERTY_NAMES = FORBIDDEN_PROPERTY_NAMES | frozenset(
    {"confidence", "probability", "score", "bump", "reason"}
)
REASON_CODES_BY_CLASS = {
    "major": {
        "removed_public_symbol",
        "renamed_public_symbol",
        "required_arg_promotion",
        "other_breaking_change",
    },
    "minor": {"deprecated_alias_only", "feature_addition"},
    "patch": {"fix_only", "docs_or_internal_only"},
    "abstain": {"insufficient_evidence", "conflicting_evidence"},
}
GITATTRIBUTES_LINES = (
    "contextual_orchestrator/schemas/** -text",
    "tests/fixtures/release_semver_v1_conformance.json -text",
    "tests/fixtures/github_2260_noema_semver/** -text",
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


def _refuse_retrieval(uri: str) -> Resource:
    """Registry retrieval hook: schemas are never fetched from their $id."""
    raise NoSuchResource(ref=uri)


def _local_registry(documents: dict[str, dict[str, Any]]) -> Registry:
    """Build a registry from packaged files only; unknown URIs never hit the network."""
    return Registry(retrieve=_refuse_retrieval).with_resources(
        (
            document["$id"],
            Resource.from_contents(document, default_specification=DRAFT202012),
        )
        for document in documents.values()
    )


def _validator(name: str) -> Draft202012Validator:
    """Build a Draft 2020-12 validator that resolves sibling schemas locally."""
    documents = _schema_documents()
    return Draft202012Validator(documents[name], registry=_local_registry(documents))


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


def _canonical_sha256(document: Any) -> str:
    """SHA-256 of the documented canonical JSON form (RFC 8785 for number-free JSON)."""
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    """Return the Git blob id of ``data`` (proves byte identity with upstream)."""
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _github_2260_provenance() -> dict[str, Any]:
    """Load the provenance record for the copied .github#2260 fixtures."""
    return json.loads((GITHUB_2260_DIR / "PROVENANCE.json").read_text(encoding="utf-8"))


def _github_2260_files(role: str) -> list[str]:
    """Return copied .github#2260 fixture names with the given role."""
    files = _github_2260_provenance()["files"]
    return sorted(name for name, entry in files.items() if entry["role"] == role)


def _hash_pinned_files() -> list[Path]:
    """Every file whose exact bytes the manifest, pins, or provenance depend on."""
    return sorted(
        [
            *FAMILY_DIR.rglob("*.json"),
            CONFORMANCE_PATH,
            *GITHUB_2260_DIR.glob("*.json"),
        ]
    )


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
    """Every object schema with declared properties rejects unknown members."""

    def walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and isinstance(
                node.get("properties"), dict
            ):
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


def test_hash_pinned_files_contain_no_carriage_returns() -> None:
    """Schemas and fixtures are LF-only, so their digests are platform independent."""
    for path in _hash_pinned_files():
        assert b"\r" not in path.read_bytes(), path.relative_to(ROOT_DIR)


def test_gitattributes_disables_eol_conversion_for_hash_pinned_files() -> None:
    """autocrlf clones and Windows-built wheels keep the manifest-pinned bytes."""
    lines = (ROOT_DIR / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for expected in GITATTRIBUTES_LINES:
        assert expected in lines
    patterns = [line.split()[0] for line in GITATTRIBUTES_LINES]
    for path in _hash_pinned_files():
        relative = path.relative_to(ROOT_DIR).as_posix()
        assert any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns), (
            relative
        )


def test_no_schema_declares_a_version_or_decision_field() -> None:
    """The client never produces a version or decision, so no schema declares one."""
    for name, document in _schema_documents().items():
        names = set(_property_names(document))
        assert not names & FORBIDDEN_PROPERTY_NAMES, name


def test_observation_has_no_self_reported_authority_field() -> None:
    """A model self-report (confidence, score, bump, free text) is not representable."""
    names = set(_property_names(_schema_documents()["observation"]))
    assert not names & FORBIDDEN_OBSERVATION_PROPERTY_NAMES


def test_reason_codes_are_a_closed_enum_partitioned_by_class() -> None:
    """reason_code is a small enum and every code belongs to exactly one class."""
    observation = _schema_documents()["observation"]
    enum = observation["properties"]["reason_code"]["enum"]
    assert "type" not in observation["properties"]["reason_code"]
    assert len(enum) == len(set(enum)) == 10
    partition = set().union(*REASON_CODES_BY_CLASS.values())
    assert set(enum) == partition
    validator = _validator("observation")
    base = _valid_document("observation")
    for observed_class, codes in REASON_CODES_BY_CLASS.items():
        for code in enum:
            document = dict(base, observed_class=observed_class, reason_code=code)
            if code in codes:
                continue
            assert list(validator.iter_errors(document)), (observed_class, code)


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


def test_github_2260_fixture_copies_are_byte_identical_to_upstream() -> None:
    """The copied .github#2260 fixtures match their pinned upstream Git blobs."""
    provenance = _github_2260_provenance()
    assert provenance["source_commit"] == GITHUB_2260_COMMIT
    on_disk = {path.name for path in GITHUB_2260_DIR.glob("*.json")} - {
        "PROVENANCE.json"
    }
    assert on_disk == set(provenance["files"])
    for name, entry in provenance["files"].items():
        data = (GITHUB_2260_DIR / name).read_bytes()
        assert _git_blob_sha1(data) == entry["git_blob_sha1"], name


@pytest.mark.parametrize("name", _github_2260_files("evidence_pack"))
def test_github_2260_evidence_packs_validate(name: str) -> None:
    """The owner's #2260 evidence fixtures are valid v1 evidence packs, unchanged."""
    document = json.loads((GITHUB_2260_DIR / name).read_text(encoding="utf-8"))
    assert set(document) == GITHUB_2260_PACK_MEMBERS
    errors = list(_validator("evidence").iter_errors(document))
    assert errors == [], [error.message for error in errors]


def test_evidence_schema_members_are_exactly_the_github_2260_pack() -> None:
    """The v1 pack adds no members of its own; identifiers live in the envelope."""
    evidence = _schema_documents()["evidence"]
    assert set(evidence["properties"]) == GITHUB_2260_PACK_MEMBERS
    assert set(evidence["required"]) == GITHUB_2260_PACK_MEMBERS
    for member in GITHUB_2260_PACK_MEMBERS - {
        "previous_version",
        "api_surface_inspected",
    }:
        document = _valid_document("evidence")
        document[member] = [{"ref": "x:y", "text": "z"}]
        assert list(_validator("evidence").iter_errors(document)), member


def test_github_2260_api_surface_rule_is_mirrored() -> None:
    """Not inspected requires a removed/renamed/required-arg finding, as in #2260."""
    validator = _validator("evidence")
    document = _valid_document("evidence")
    document["api_surface_inspected"] = False
    assert list(validator.iter_errors(document))
    document["deprecated_alias_only"] = ["contextual_orchestrator.old_alias"]
    assert list(validator.iter_errors(document))
    for member in GITHUB_2260_API_FINDING_LISTS:
        with_finding = dict(document, **{member: ["contextual_orchestrator.symbol"]})
        assert list(validator.iter_errors(with_finding)) == [], member


@pytest.mark.parametrize("name", _github_2260_files("recorded_verdict"))
def test_github_2260_recorded_verdicts_are_not_observations(name: str) -> None:
    """#2260's non-production {bump, confidence} verdict shape is rejected as-is."""
    recorded = json.loads((GITHUB_2260_DIR / name).read_text(encoding="utf-8"))
    validator = _validator("observation")
    assert list(validator.iter_errors(recorded))
    assert list(validator.iter_errors(recorded["verdict"]))
    smuggled = dict(
        _valid_document("observation"), confidence=recorded["verdict"]["confidence"]
    )
    assert list(validator.iter_errors(smuggled))


@pytest.mark.parametrize("name", _github_2260_files("recorded_verdict"))
def test_github_2260_evidence_ref_format_is_accepted(name: str) -> None:
    """Refs in #2260's recorded fixtures (changelog:, api:...:) use the v1 ref format."""
    evidence_ref = _schema_documents()["observation"]["$defs"]["evidence_ref"]
    validator = Draft202012Validator(evidence_ref)
    recorded = json.loads((GITHUB_2260_DIR / name).read_text(encoding="utf-8"))
    for ref in recorded["verdict"]["evidence_refs"]:
        assert validator.is_valid(ref), ref


def test_fixture_documents_echo_the_canonical_evidence_digest() -> None:
    """Fixture digests follow the documented canonical form of the evidence pack."""
    fixture = _conformance()
    digest = _canonical_sha256(_valid_document("evidence"))
    assert fixture["canonical_evidence_sha256"] == digest
    assert _valid_document("observation")["evidence_sha256"] == digest
    envelope = _valid_document("receipt_envelope")
    assert envelope["evidence_sha256"] == digest
    assert all(
        item["observation"]["evidence_sha256"] == digest
        for item in envelope["observations"]
    )
    receipt = envelope["fast_mlsirm_receipt"]
    assert receipt["sha256"] == _canonical_sha256(receipt["document"])


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


def test_envelope_has_no_decision_of_its_own() -> None:
    """The receipt document is the only decision authority; the envelope carries none."""
    envelope = _schema_documents()["receipt_envelope"]
    assert "outcome" not in envelope["properties"]
    receipt = envelope["properties"]["fast_mlsirm_receipt"]
    assert receipt["properties"]["document"] == {"type": "object", "minProperties": 1}


@pytest.mark.parametrize("digit", "0123456789abcdef")
def test_degenerate_digests_and_commits_are_rejected(digit: str) -> None:
    """Every repeated-digit SHA-256 and commit id is rejected wherever one appears."""
    validator = _validator("receipt_envelope")
    envelope = _valid_document("receipt_envelope")
    for path, width in (
        (("fast_mlsirm_receipt", "sha256"), 64),
        (("evidence_sha256",), 64),
        (("schema_sha256", "evidence"), 64),
        (("schema_sha256", "observation"), 64),
        (("evidence_source_commit",), 40),
        (("producer", "source_commit"), 40),
    ):
        document = copy.deepcopy(envelope)
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = digit * width
        assert list(validator.iter_errors(document)), path


def test_served_route_is_fixed_to_the_free_pool() -> None:
    """Every observation's gateway-reported route must be orchestrator/free."""
    envelope = _schema_documents()["receipt_envelope"]
    served_route = envelope["properties"]["observations"]["items"]["properties"][
        "served_route"
    ]
    assert served_route["properties"]["route"] == {"const": "orchestrator/free"}
    assert "route" in served_route["required"]
    assert envelope["properties"]["model_pool"]["const"] == "orchestrator/free"


def test_refs_resolve_from_the_local_registry_only() -> None:
    """$ref resolution uses packaged files; a registry without them cannot resolve."""
    envelope_schema = _schema_documents()["receipt_envelope"]
    envelope = _valid_document("receipt_envelope")
    assert list(_validator("receipt_envelope").iter_errors(envelope)) == []
    isolated = Draft202012Validator(
        envelope_schema,
        registry=Registry(retrieve=_refuse_retrieval).with_resource(
            envelope_schema["$id"],
            Resource.from_contents(envelope_schema, default_specification=DRAFT202012),
        ),
    )
    with pytest.raises(Unresolvable):
        list(isolated.iter_errors(envelope))
    for document in _schema_documents().values():
        assert "local registry" in document["$comment"]


@pytest.mark.parametrize(
    ("schema", "mutate"),
    [
        (
            "evidence",
            lambda d: d.__setitem__("commit_titles", [d["commit_titles"][0]] * 513),
        ),
        (
            "evidence",
            lambda d: d.__setitem__("pr_titles", [d["pr_titles"][0]] * 257),
        ),
        (
            "evidence",
            lambda d: d.__setitem__(
                "changelog_fragments", [d["changelog_fragments"][0]] * 257
            ),
        ),
        (
            "evidence",
            lambda d: d["commit_titles"].__setitem__(0, "x" * 2001),
        ),
        (
            "observation",
            lambda d: d.__setitem__(
                "evidence_refs", [f"commit:{i:040x}" for i in range(65)]
            ),
        ),
        (
            "observation",
            lambda d: d.__setitem__("evidence_refs", ["changelog:" + "a" * 2039]),
        ),
        ("observation", lambda d: d.__setitem__("assignment_ref", "r" * 129)),
        (
            "receipt_envelope",
            lambda d: d.__setitem__(
                "observations",
                [
                    dict(
                        d["observations"][0],
                        served_route=dict(
                            d["observations"][0]["served_route"], agent_id=f"agent_{i}"
                        ),
                    )
                    for i in range(33)
                ],
            ),
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
