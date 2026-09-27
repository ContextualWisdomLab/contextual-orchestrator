"""Fail-closed licence gate for the canonical release, read from the CycloneDX SBOM.

The release workflow already downloads the mandatory `cyclonedx-sbom.json` for
the exact commit being released. That SBOM is the input here: it names the
components that actually ship, including transitive ones a `pyproject.toml`
reading would miss.

Three outcomes block a release, none of them waivable:

* a copyleft licence in the GPL family (GPL, LGPL, AGPL, in SPDX or free-text
  spelling, including forms like ``GPLv3`` that carry no separator);
* a licence that cannot be adjudicated -- absent, empty, a placeholder such as
  ``NOASSERTION``, or a ``LicenseRef-`` pointer to a text this gate has not
  reviewed. Undecidable is refused, never read as permission;
* an SBOM that does not demonstrably cover the dependency scopes this
  repository declares, because a partial SBOM says nothing about the scopes it
  never collected.

Composite licence semantics follow SPDX rather than convenience. Separate
``licenses[]`` entries are conjunctive, so every entry must pass on its own. A
single expression passes only when its operands really offer a permissive
choice: ``Apache-2.0 OR GPL-2.0-only`` passes and records the option taken,
``Apache-2.0 AND GPL-2.0-only`` does not because ``AND`` imposes both, and
``GPL-3.0-only OR UNKNOWN`` does not either, because an undecidable operand
cannot be the permissive one. SPDX operators are matched case-sensitively, so
``GPL-2.0-or-later`` stays a single operand.

Being optional, unexecuted or test-only is never an exemption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote

if __package__:
    from .dependency_inventory import InventoryError, _npm_packages
else:
    from dependency_inventory import InventoryError, _npm_packages

# GPL/LGPL/AGPL in any spelling, including ``GPLv3``. No trailing separator is
# required: free-text spellings run the version straight onto the family name.
_COPYLEFT_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:A?GPL|LGPL)"
    r"|GNU\s+(?:Affero\s+|Lesser\s+)?General\s+Public",
    re.IGNORECASE,
)
_UNDECIDABLE_VALUES = frozenset({"", "unknown", "none", "null", "noassertion", "other", "proprietary"})
_UNDECIDABLE_PREFIXES = ("licenseref-", "documentref-")
# Closed declaration vocabulary: recognized identifiers and legacy metadata
# spellings only. Recognition never replaces actual instrument evidence.
_KNOWN_NON_GPL_DECLARATIONS = frozenset(
    " ".join(value.replace("(", " ").replace(")", " ").split()).casefold() for value in (
        "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC",
        "Apache-2.0", "Apache-2.0 WITH LLVM-exception", "MPL-2.0", "PSF-2.0",
        "Zlib", "CC0-1.0", "CC-BY-4.0", "Unlicense", "BlueOak-1.0.0", "Unicode-3.0",
        "MIT License", "MIT No Attribution", "MIT No Attribution License (MIT-0)",
        "BSD License", "BSD 3-Clause License", "3-Clause BSD License",
        "Apache 2.0", "Apache License, Version 2.0", "Apache Software License",
        "Mozilla Public License 2.0 (MPL 2.0)", "PSFL", "Python Software Foundation License",
        "Apache-2.0/MIT", "MIT/Apache-2.0",
    )
)
_NAME_SEPARATORS = re.compile(r"[-_.]+")
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


class SbomSchemaError(Exception):
    """The SBOM could not be read as a component inventory."""


def _is_undecidable(term: str) -> bool:
    lowered = term.strip().lower()
    return lowered in _UNDECIDABLE_VALUES or lowered.startswith(_UNDECIDABLE_PREFIXES)


def _license_terms(component: dict[str, Any]) -> list[str]:
    """Return one string per ``licenses[]`` entry; entries are conjunctive."""
    licenses = component.get("licenses")
    if licenses is None:
        return []
    if not isinstance(licenses, list):
        raise SbomSchemaError(f"component {component.get('name')!r} has a non-list licenses field")
    terms: list[str] = []
    for entry in licenses:
        if not isinstance(entry, dict):
            raise SbomSchemaError(f"component {component.get('name')!r} has a malformed licenses entry")
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            terms.append(expression.strip())
            continue
        license_object = entry.get("license")
        if isinstance(license_object, dict):
            value = license_object.get("id") or license_object.get("name")
            terms.append(value.strip() if isinstance(value, str) else "")
            continue
        terms.append("")
    return terms


def classify_license_term(term: str) -> tuple[str, str]:
    """Classify one ``licenses[]`` entry as permitted, copyleft or undecidable.

    The second element carries the reason; for a permitted dual licence it is
    the permissive operand actually relied upon.
    """
    if _is_undecidable(term):
        return "undecidable", term.strip() or "<none>"
    cleaned = term.replace("(", " ").replace(")", " ")
    # A non-GPL spelling is not permission: refuse every unrecognized operand,
    # including unknown alternatives next to an otherwise valid OR choice.
    declarations = re.split(r"\s+(?:AND|OR)\s+", cleaned)
    if any(not _COPYLEFT_PATTERN.search(operand)
           and " ".join(operand.split()).casefold() not in _KNOWN_NON_GPL_DECLARATIONS
           for operand in declarations):
        return "undecidable", term
    if re.search(r"\sAND\s", cleaned):
        operands = [part.strip() for part in re.split(r"\sAND\s", cleaned) if part.strip()]
        if any(_is_undecidable(operand) for operand in operands):
            return "undecidable", term
        if any(_COPYLEFT_PATTERN.search(operand) for operand in operands):
            return "copyleft", term
        return "permitted", term
    operands = [part.strip() for part in re.split(r"\sOR\s", cleaned) if part.strip()]
    if len(operands) > 1:
        if any(_is_undecidable(operand) for operand in operands):
            return "undecidable", term
        choice = next((operand for operand in operands if not _COPYLEFT_PATTERN.search(operand)), None)
        return ("permitted", choice) if choice is not None else ("copyleft", term)
    return ("copyleft", term) if _COPYLEFT_PATTERN.search(term) else ("permitted", term)


def _walk_components(container: Any, path: str) -> list[dict[str, Any]]:
    """Flatten the component tree; a nested dependency ships just as much."""
    components = container.get("components")
    if components is None:
        return []
    if not isinstance(components, list):
        raise SbomSchemaError(f"{path} has a non-list components field")
    flattened: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise SbomSchemaError(f"{path}.components[{index}] is not an object")
        flattened.append(component)
        flattened.extend(_walk_components(component, f"{path}.components[{index}]"))
    return flattened


def classify_sbom_components(sbom: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Split every component, nested ones included, into the three groups."""
    permitted: list[dict[str, str]] = []
    copyleft: list[dict[str, str]] = []
    undecidable: list[dict[str, str]] = []
    for component in _walk_components(sbom, "sbom"):
        name = str(component.get("name") or "<unnamed component>")
        version = str(component.get("version") or "")
        terms = _license_terms(component)
        if not terms:
            undecidable.append({"name": name, "version": version, "license": "<none declared>"})
            continue
        verdicts = [classify_license_term(term) for term in terms]
        row = {"name": name, "version": version, "license": "; ".join(terms)}
        if any(verdict == "undecidable" for verdict, _ in verdicts):
            undecidable.append(row)
        elif any(verdict == "copyleft" for verdict, _ in verdicts):
            copyleft.append(row)
        else:
            permitted.append({**row, "license": "; ".join(reason for _, reason in verdicts)})
    return {"permitted": permitted, "copyleft": copyleft, "undecidable": undecidable}


def _normalize(name: str) -> str:
    return _NAME_SEPARATORS.sub("-", name.strip().lower())


def _declared_requirements(pyproject: dict[str, Any]) -> set[str]:
    """Every distribution this project declares, across all scopes."""
    project = pyproject.get("project") or {}
    sources: list[Any] = [project.get("dependencies") or []]
    sources.extend((project.get("optional-dependencies") or {}).values())
    sources.extend((pyproject.get("dependency-groups") or {}).values())
    declared: set[str] = set()
    for requirements in sources:
        for requirement in requirements or []:
            if not isinstance(requirement, str):
                continue
            match = _REQUIREMENT_NAME.match(requirement)
            if match:
                declared.add(_normalize(match.group(0)))
    return declared


def _lock_packages_from_toml(path: Path, key: str) -> set[tuple[str, str]]:
    """Read ``[[package]]`` name/version pairs from a Cargo or uv lockfile."""
    with open(path, "rb") as handle:
        document = tomllib.load(handle)
    entries = document.get(key) or []
    return {
        (_normalize(str(entry.get("name", ""))), str(entry.get("version", "")))
        for entry in entries
        if isinstance(entry, dict) and entry.get("name")
    }


def _lock_packages_from_npm(path: Path) -> set[tuple[str, str]]:
    """Read installed package name/version pairs from an npm lockfile."""
    return {(_normalize(package["name"]), package["version"])
            for package in _npm_packages(path, path.read_bytes())}


def _parse_purl(purl: str, purl_prefix: str) -> tuple[str, str]:
    """Read the name and version the purl itself asserts, ignoring the fields."""
    remainder = purl[len(purl_prefix):].split("?", 1)[0].split("#", 1)[0]
    name, separator, version = remainder.rpartition("@")
    if not separator:  # no version segment at all
        name, version = remainder, ""
    return _normalize(unquote(name)), unquote(version)


def _sbom_packages(components: list[dict[str, Any]], purl_prefix: str) -> tuple[set[tuple[str, str]], list[str]]:
    """Return one ecosystem's purl-asserted pairs, plus any identity mismatches.

    Coverage is decided from the purl, since that is the package coordinate.
    A purl that disagrees with its own component's ``name``/``version`` fields
    makes the component's identity unreliable, so the disagreement is reported
    rather than quietly resolved in favour of whichever side matches the lock.
    """
    packages: set[tuple[str, str]] = set()
    mismatches: list[str] = []
    for component in components:
        purl = str(component.get("purl") or "")
        if not purl.startswith(purl_prefix):
            continue
        purl_name, purl_version = _parse_purl(purl, purl_prefix)
        name = str(component.get("name") or "")
        if purl_prefix == "pkg:npm/" and component.get("group"):
            name = f"{component['group']}/{name}"
        field_name = _normalize(name)
        field_version = str(component.get("version") or "")
        packages.add((purl_name, purl_version))
        if (purl_name, purl_version) != (field_name, field_version):
            mismatches.append(f"{field_name}=={field_version} carries purl {purl}")
    return packages, mismatches


def _missing_report(ecosystem: str, lock: Path, missing: set[tuple[str, str]], expected: int) -> str:
    sample = ", ".join(f"{name}=={version}" for name, version in sorted(missing)[:10])
    suffix = ", ..." if len(missing) > 10 else ""
    return (
        f"{ecosystem}: {len(missing)} of {expected} package(s) resolved in {lock} are absent from the "
        f"SBOM ({sample}{suffix})"
    )


def classify_inventory_licenses(inventory: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Adjudicate the inventory's own entries, which the SBOM never covers.

    The inventory carries licence terms read from distribution metadata that the
    job already had on disk, so the classes outside the shipped artefact are
    judged by the same rules rather than exempted. An entry with no resolved
    terms is undecidable, which blocks: unknown is never read as permission.
    """
    copyleft: list[dict[str, str]] = []
    undecidable: list[dict[str, str]] = []
    permitted: list[dict[str, str]] = []
    for entry in inventory.get("ecosystems") or []:
        ecosystem = str(entry.get("ecosystem") or "")
        for package in entry.get("packages") or []:
            terms = [str(term) for term in package.get("licenses") or [] if str(term).strip()]
            row = {
                "name": f"{ecosystem}:{package.get('name')}",
                "version": str(package.get("version") or ""),
                "license": "; ".join(terms) or str(package.get("license_source") or "<none resolved>"),
            }
            if not terms:
                undecidable.append(row)
                continue
            verdicts = [classify_license_term(term) for term in terms]
            if any(verdict == "copyleft" for verdict, _ in verdicts):
                copyleft.append(row)
            elif any(verdict == "undecidable" for verdict, _ in verdicts):
                undecidable.append(row)
            elif package.get("bundled_archives"):
                undecidable.append({**row, "license": f"{row['license']} (nested archive scope unresolved)"})
            elif "license_files" in package and not package.get("license_files"):
                # A declaration with no licence text in the artefact is the
                # publisher's word without the instrument behind it. Permitted
                # terms do not settle it; it is held like any other unknown.
                undecidable.append({**row, "license": f"{row['license']} (declaration only, no text)"})
            elif not _declaration_matches_text(terms, package.get("license_files") or []):
                # The filename proves a file exists; only its text shows whether
                # the declared licence is the one actually granted.
                undecidable.append({**row, "license": f"{row['license']} (text does not evidence the declaration)"})
            else:
                permitted.append(row)
    return {"permitted": permitted, "copyleft": copyleft, "undecidable": undecidable}




# Wording that withholds a right a permissive licence grants. Any of these
# makes the text something other than the permissive licence it claims.
_RESTRICTION_PATTERN = re.compile(
    r"non[- ]?commercial|not for commercial|commercial use (?:is )?(?:prohibited|forbidden)"
    r"|submit[- ]restricted|evaluation (?:use )?only|internal use only|may not (?:be )?redistribut"
    r"|no redistribution|research (?:use )?only|written (?:consent|permission) (?:is )?required",
    re.IGNORECASE,
)

_LICENCE_FAMILY_TOKENS = {
    "MIT": ("permission is hereby granted",),
    "BSD": ("redistribution and use in source and binary forms",),
    "APACHE": ("apache license",),
    "MPL": ("mozilla public license",),
    "ISC": ("permission to use, copy, modify",),
    "0BSD": ("permission to use, copy, modify",),
    "PSF": ("python software foundation",),
    "ZLIB": ("altered source versions",),
    "CC0": ("cc0 1.0 universal",),
    "UNLICENSE": ("free and unencumbered software released into the public domain",),
}


# Complete SPDX instruments from license-list-data@31ba1a50e5397e00a304dbadc76531740e89ee48.
# Primary-source variants are recorded in the instrument-set runbook.
# Only whitespace is normalized. No package, filename or keyword exemption.
# The LLVM title's three/four leading dashes are the two verified archive forms.
_CANONICAL_TEXT_HASHES = {
    "Apache-2.0 WITH LLVM-exception": frozenset({
        "63bdd4702a2eaf44fc39da5567c649ee9a2da804b6434982b034ac37004eb459",
        "f42a00ac54d036890559853a40f95622ab3e63d52173f5714284134b2af11e3c",
    }),
    "CC-BY-4.0": frozenset({
        "1f5a529dc95849305307f0d6861169d8cae9e99807e4abcec68ef9ad19235652",
        "25a40a30d753162c4026b87a389b9534c72436327abcd083f90da00ead6d6869",
    }),
    "PSF-2.0": frozenset({"350fbb5f093f61337b130b56e5a7119129c68975bebc1e7dd247d0206313d0e1"}),
    "MPL-2.0": frozenset({"e8ba82e63ba908724aaee6043943c5a2629b9ebf1af581ea0eea19a713123685"}),
    "BlueOak-1.0.0": frozenset({
        "61c644f13191f65c6ff4e58322c5d92ca44702c37ef0e1bc36f08af1021835a7",
        "d1d8b7a22428eba7e46e7e373d014141266ead51a00c9291a4792278110a8997",  # Complete equivalent Markdown rendering; see instrument-set record.
    }),
}


# Complete reviewed permissive instrument sets and their selection notices.
# See docs/doctoring/dual_license_instrument_set.md; no filename/package trust.
_REVIEWED_INSTRUMENT_SETS = {
    "Unlicense OR MIT": frozenset({
        "7e7a2c785f3db52a3daf64a62b76b09b940355e4fe1b7f7092f473b7663416b1",
        "952115fb93510335fd97e1e479516553fa0c4da1b49acddf9cd5d18392a3e1cf",
        "2069c208cba553e43cd0b730df8a0c10bf1b1101b96f661e2f1307c73b9722e3",
    }),
    'Apache-2.0 OR BSD-3-Clause': frozenset({
        'c9a79affdaaa650e90a55607fef88e5c5e4f0547a78ccfe8014e1693ef839120',
        'a0b9af0d1614b5e8f3004aaf2092bf005b64398ef067ca868d81a8beeb6cb0b5',
        'c268cc09d949fefffa9309d0d6c0b44674a873823ad419680e623919478e4619',
    }),
    'Apache-2.0 OR BSD-2-Clause': frozenset({
        '4456c8e282202cfddd8665522fd320e8b7f64d8a1f7d9abfd7802080576cf117',
        '59d8f0ba87ad9a2f1a431123c8d16646e5b89ba53653e818f16d136d77263c99',
        '13c6a3608faee72d1b3a7aad6d1c8036408ed82d9a28a7cf0ef87d6acc4f91c9',
    }),
    ('Apache Software License', 'MIT License', 'MIT OR Apache-2.0'): frozenset({
        '5e776b61ef48708fd6760085a01c9acddc107b6a071f745b5969d1d5a97899d1',
        '0ffddef9e48f8a09aed5caf2d44f7ba1c1be2d9b8e0a6f693b1635b2d5566645',
        'dcdd5bec314a2c06621a42d529b6c1e6705301c076bb641fff909129fbca8897',
    }),
}


# Exact complete grant plus attribution; single-instrument grants keep their path.
_REVIEWED_ATTRIBUTION_SETS = frozenset({
    (("MIT", "MIT License"), frozenset({
        "e6690babf4bc31029ccffd0fe1f35c698007d81008ff576274435aae1102d232",
        "8c319ea357316cadb17350ef988afaefa44f9b635acb78d757a4048fd00ce2e2",
    })),
    (("Apache Software License", "Apache-2.0"), frozenset({
        "0ffddef9e48f8a09aed5caf2d44f7ba1c1be2d9b8e0a6f693b1635b2d5566645",
        "b70d362542e47e70df8e7ae570c48dee966450e73d06bdf236edf9446165e5e3",
    })),
})


def _declaration_matches_text(terms: list[str], license_files: list[Any]) -> bool:
    """Whether the bundled licence text evidences a declared, non-copyleft term.

    Complete pinned SPDX instruments are matched before keyword checks, since
    their compatibility clauses may mention GPL without selecting that license.
    Every file in a canonical-only declaration must match a complete instrument;
    changed or additional terms cannot use that path. Mixed legacy declarations
    retain the prior conservative matcher. Missing text is always refused.
    """
    texts = [
        str(entry.get("text") or "")
        for entry in license_files
        if isinstance(entry, dict) and str(entry.get("text") or "").strip()
    ]
    if not texts or len(texts) != len(license_files):
        # A record with an empty or non-dict licence entry is incomplete.
        return False
    reviewed_key = terms[0] if len(terms) == 1 else tuple(sorted(terms))
    actual = frozenset(hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
                       for text in texts)
    if len(texts) == len(actual) and (reviewed_key, actual) in _REVIEWED_ATTRIBUTION_SETS:
        return True
    if reviewed_key in _REVIEWED_INSTRUMENT_SETS:
        required = _REVIEWED_INSTRUMENT_SETS[reviewed_key]
        return len(texts) == len(required) and actual == required
    evidenced = False
    canonical_terms = set(terms) & _CANONICAL_TEXT_HASHES.keys()
    if canonical_terms != set(terms):
        canonical_terms = set()  # Mixed legacy declarations retain the prior conservative path.
    matched_canonical_terms: set[str] = set()
    for text in texts:
        digest = hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
        matches = {term for term in canonical_terms if digest in _CANONICAL_TEXT_HASHES[term]}
        if matches:
            matched_canonical_terms.update(matches)
            evidenced = True
            continue
        if canonical_terms:
            return False  # Every instrument must match, including additional files.
        # Every bundled text has to be acceptable: a permissive LICENSE next to
        # a separate GPL one is a package under both, not under the first.
        if _COPYLEFT_PATTERN.search(text) or _RESTRICTION_PATTERN.search(text):
            return False
        lowered = " ".join(text.split()).lower()
        evidenced = False
        for term in terms:
            if term in canonical_terms:
                continue  # These declarations require the complete pinned instrument.
            upper = term.upper()
            for family, tokens in _LICENCE_FAMILY_TOKENS.items():
                if family in upper and any(token in lowered for token in tokens):
                    evidenced = True
        if not evidenced:
            return False
    return matched_canonical_terms == canonical_terms


def _inventory_expectations(inventory: dict[str, Any]) -> dict[str, set[tuple[str, str]]]:
    """Expected name/version pairs per ecosystem, as the inventory recorded them."""
    expectations: dict[str, set[tuple[str, str]]] = {}
    for entry in inventory.get("ecosystems") or []:
        ecosystem = str(entry.get("ecosystem") or "")
        expectations[ecosystem] = {
            (_normalize(str(package.get("name") or "")), str(package.get("version") or ""))
            for package in entry.get("packages") or []
        }
    return expectations


_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def inventory_binding_findings(inventory: dict[str, Any], expected_sha: str | None) -> list[str]:
    """Refuse an inventory that does not evidence the tree being released.

    Scope of this check, stated plainly: the only supported producer is
    `scripts/ci/dependency_inventory.py` run in the same job, on the same
    checkout, immediately before this gate -- which is what
    `.github/workflows/release.yml` does, and the only caller there is. These
    checks reject a malformed, unbound or self-contradicting document from that
    trusted producer; they are **not** independent verification of an inventory
    obtained from anywhere else. Verifying a foreign inventory would mean
    re-reading each lockfile at the released commit and re-deriving its blob id
    here, which this does not do.
    """
    findings: list[str] = []
    if str(inventory.get("schema") or "") != "contextual-orchestrator/dependency-inventory/v1":
        findings.append(f"inventory: unrecognised schema {inventory.get('schema')!r}")
    source_sha = str(inventory.get("source_sha") or "")
    if not _HEX40.match(source_sha):
        findings.append("inventory: source_sha is missing or not a commit id, so it binds to nothing")
    elif expected_sha and source_sha != expected_sha:
        findings.append(
            f"inventory: source_sha {source_sha[:12]} does not match the released commit "
            f"{expected_sha[:12]}"
        )
    ecosystems = inventory.get("ecosystems")
    if not isinstance(ecosystems, list) or not ecosystems:
        findings.append("inventory: no ecosystems recorded")
        return findings
    for entry in ecosystems:
        if not isinstance(entry, dict):
            findings.append("inventory: an ecosystem entry is not an object")
            continue
        ecosystem = entry.get("ecosystem")
        if entry.get("error"):
            findings.append(f"inventory {ecosystem}: {entry['error']}")
        provenance_entries = entry.get("provenance")
        if not isinstance(provenance_entries, list) or not provenance_entries:
            # Absent provenance is not a passing scope; it is an unevidenced one.
            findings.append(f"inventory {ecosystem}: no provenance recorded for its sources")
            continue
        for provenance in provenance_entries:
            if not isinstance(provenance, dict):
                findings.append(f"inventory {ecosystem}: a provenance entry is not an object")
                continue
            path = provenance.get("path") or "<unnamed source>"
            if provenance.get("error"):
                findings.append(f"inventory {ecosystem}: {path}: {provenance['error']}")
                continue
            blob_id = str(provenance.get("blob_id") or "")
            committed = str(provenance.get("committed_blob_id") or "")
            if not _HEX64.match(str(provenance.get("read_sha256") or "")):
                findings.append(f"inventory {ecosystem}: {path} has no usable read_sha256")
            if not _HEX40.match(blob_id) or not _HEX40.match(committed):
                findings.append(f"inventory {ecosystem}: {path} has no usable blob ids")
            elif blob_id != committed:
                # Recompute the verdict rather than trusting the recorded one.
                findings.append(
                    f"inventory {ecosystem}: {path} blob {blob_id[:12]} differs from the committed "
                    f"{committed[:12]}"
                )
            if provenance.get("matches_commit") is not True:
                findings.append(f"inventory {ecosystem}: {path} is not marked as matching its commit")
    return findings


def scope_coverage_findings(
    sbom: dict[str, Any],
    pyproject_path: str | None,
    repository_root: str | None,
    inventory: dict[str, Any] | None = None,
) -> list[str]:
    """Prove the SBOM covers each ecosystem's whole resolved dependency set.

    Existence of one component per ecosystem proves nothing, so every finding
    here is a set comparison against that ecosystem's own lockfile, which is
    the resolved transitive closure. A manifest with no readable lockfile is a
    finding too: an unprovable scope is not a covered one.
    """
    findings: list[str] = []
    components = _walk_components(sbom, "sbom")
    present_names = {_normalize(str(component.get("name") or "")) for component in components}
    project_name = ""
    if pyproject_path:
        with open(pyproject_path, "rb") as handle:
            pyproject = tomllib.load(handle)
        project_name = _normalize(str((pyproject.get("project") or {}).get("name") or ""))
        missing_declared = sorted(_declared_requirements(pyproject) - present_names)
        if missing_declared:
            findings.append(
                "declared Python distributions absent from the SBOM "
                f"({len(missing_declared)}): {', '.join(missing_declared)}"
            )
    if not repository_root:
        return findings
    root = Path(repository_root)
    ecosystems: tuple[tuple[str, Path, tuple[Path, ...], str, str], ...] = (
        ("python", root / "pyproject.toml", (root / "uv.lock",), "pkg:pypi/", "package"),
        ("cargo", root / "rust" / "Cargo.toml", (root / "rust" / "Cargo.lock",), "pkg:cargo/", "package"),
        ("npm", root / "package.json", (root / "package-lock.json",), "pkg:npm/", ""),
    )
    for ecosystem, manifest, lock_candidates, purl_prefix, toml_key in ecosystems:
        if not manifest.exists():
            continue
        lock = next((candidate for candidate in lock_candidates if candidate.exists()), None)
        if lock is None:
            findings.append(
                f"{manifest} ships with the artifact but no lockfile "
                f"({', '.join(str(candidate) for candidate in lock_candidates)}) is available, so its "
                "resolved dependency set cannot be proven"
            )
            continue
        try:
            inventory_expected = (_inventory_expectations(inventory) if inventory else {}).get(ecosystem)
            expected = (
                inventory_expected
                if inventory_expected is not None
                else (
                    _lock_packages_from_npm(lock) if ecosystem == "npm"
                    else _lock_packages_from_toml(lock, toml_key)
                )
            )
        except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
            findings.append(f"{ecosystem}: lockfile {lock} could not be read ({error})")
            continue
        expected = {pair for pair in expected if pair[0] and pair[0] != project_name}
        present, mismatches = _sbom_packages(components, purl_prefix)
        if mismatches:
            findings.append(
                f"{ecosystem}: {len(mismatches)} component(s) whose purl identity contradicts their own "
                f"name/version fields ({'; '.join(sorted(mismatches)[:5])})"
            )
        if not expected:
            # A shipped manifest whose lockfile resolves nothing proves nothing
            # either: the structure parsed, but it carries no dependency set to
            # compare against, which is silence rather than a clean bill.
            findings.append(
                f"{ecosystem}: {lock} resolves no packages for shipped manifest {manifest}, so its "
                "dependency set is unprovable rather than empty"
            )
            continue
        missing = {pair for pair in expected if pair not in present}
        if missing:
            findings.append(_missing_report(ecosystem, lock, missing, len(expected)))
    return findings


def _render(groups: dict[str, list[dict[str, str]]], coverage: list[str]) -> str:
    lines = [
        f"permitted={len(groups['permitted'])} copyleft={len(groups['copyleft'])} "
        f"undecidable={len(groups['undecidable'])} coverage_findings={len(coverage)}"
    ]
    for label in ("copyleft", "undecidable"):
        for row in groups[label]:
            lines.append(f"{label.upper()} {row['name']}=={row['version']} license={row['license']}")
    lines.extend(f"COVERAGE {finding}" for finding in coverage)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed release licence and SBOM-coverage gate.")
    parser.add_argument("--sbom", help="path to cyclonedx-sbom.json for the exact commit")
    parser.add_argument(
        "--mode", choices=("preinstall", "release"), default="release",
        help=(
            "preinstall: adjudicate the inventory alone, before the environment an SBOM would "
            "describe exists, and before anything is installed. release: the full gate -- SBOM "
            "licences, inventory licences, binding and scope coverage together."
        ),
    )
    parser.add_argument("--pyproject", help="pyproject.toml whose declared scopes the SBOM must cover")
    parser.add_argument("--repository-root", help="repository root, to check non-Python manifests")
    parser.add_argument("--inventory", help="dependency inventory whose scopes the SBOM must cover")
    parser.add_argument("--source-sha", help="the released commit the inventory must describe")
    arguments = parser.parse_args(argv)
    if not arguments.sbom:
        if arguments.mode == "release":
            print("::error::--sbom is required in release mode; refusing to release.", file=sys.stderr)
            return 1
        sbom = {"components": []}
    else:
      try:
        with open(arguments.sbom, encoding="utf-8") as handle:
            sbom = json.load(handle)
      except (OSError, json.JSONDecodeError) as error:
        print(f"::error::Release licence gate could not read the CycloneDX SBOM at {arguments.sbom}: {error}",
              file=sys.stderr)
        return 1
    if not isinstance(sbom, dict):
        print("::error::CycloneDX SBOM is not a JSON object; refusing to release.", file=sys.stderr)
        return 1
    inventory: dict[str, Any] | None = None
    if arguments.inventory:
        try:
            with open(arguments.inventory, encoding="utf-8") as handle:
                inventory = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            print(f"::error::Release licence gate could not read the dependency inventory: {error}",
                  file=sys.stderr)
            return 1
    try:
        groups = classify_sbom_components(sbom)
        coverage = (
            scope_coverage_findings(sbom, arguments.pyproject, arguments.repository_root, inventory)
            if arguments.mode == "release"
            # Before install there is no environment SBOM to compare against,
            # so coverage is the release gate's question, not this one's.
            else []
        )
        if inventory is not None:
            coverage = inventory_binding_findings(inventory, arguments.source_sha) + coverage
            if arguments.mode == "release":
                coverage += ["prebuild project source is not final wheel licence evidence"
                             for entry in inventory.get("ecosystems", [])
                             for package in entry.get("packages", [])
                             if package.get("license_evidence") == "prebuild-source"]
            inventory_groups = classify_inventory_licenses(inventory)
            groups = {
                key: groups[key] + inventory_groups[key]
                for key in ("permitted", "copyleft", "undecidable")
            }
    except SbomSchemaError as error:
        print(f"::error::CycloneDX SBOM is malformed and cannot be adjudicated ({error}); refusing to release.",
              file=sys.stderr)
        return 1
    except (InventoryError, OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"::error::Release licence gate could not read the declared dependency scopes ({error}).",
              file=sys.stderr)
        return 1
    if not any(groups.values()):
        print(
            "::error::CycloneDX SBOM lists no components; an empty component set is not evidence that the "
            "artifact is licence-clean. Refusing to release.",
            file=sys.stderr,
        )
        return 1
    print(_render(groups, coverage))
    if groups["copyleft"] or groups["undecidable"] or coverage:
        print(
            "::error::Release licence gate failed: "
            f"{len(groups['copyleft'])} GPL-family, {len(groups['undecidable'])} undecidable-licence "
            f"component(s) and {len(coverage)} dependency-scope coverage gap(s). Replace copyleft components "
            "with permissively licensed alternatives and extend SBOM collection until every declared scope is "
            "covered; optional or unexecuted scope is not an exemption, an undecidable licence is never read "
            "as permission, and this gate is not waived to publish.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
