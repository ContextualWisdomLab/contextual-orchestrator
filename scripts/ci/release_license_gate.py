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
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote

# GPL/LGPL/AGPL in any spelling, including ``GPLv3``. No trailing separator is
# required: free-text spellings run the version straight onto the family name.
_COPYLEFT_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:A?GPL|LGPL)"
    r"|GNU\s+(?:Affero\s+|Lesser\s+)?General\s+Public",
    re.IGNORECASE,
)
_UNDECIDABLE_VALUES = frozenset({"", "unknown", "none", "null", "noassertion", "other", "proprietary"})
_UNDECIDABLE_PREFIXES = ("licenseref-", "documentref-")
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
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    packages: set[tuple[str, str]] = set()
    for location, entry in (document.get("packages") or {}).items():
        if not location or not isinstance(entry, dict):
            continue  # the "" entry is the project itself, not a dependency
        name = entry.get("name") or location.split("node_modules/", 1)[-1]
        packages.add((_normalize(str(name)), str(entry.get("version", ""))))
    return packages


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
        field_name = _normalize(str(component.get("name") or ""))
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
            elif all(verdict == "undecidable" for verdict, _ in verdicts):
                undecidable.append(row)
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




_LICENCE_FAMILY_TOKENS = {
    "MIT": ("mit", "permission is hereby granted"),
    "BSD": ("bsd", "redistribution and use in source and binary forms"),
    "APACHE": ("apache",),
    "MPL": ("mozilla public license",),
    "ISC": ("isc", "permission to use, copy, modify"),
    "0BSD": ("permission to use, copy, modify",),
    "PSF": ("python software foundation",),
    "ZLIB": ("zlib", "altered source versions"),
    "CC0": ("cc0", "public domain"),
    "UNLICENSE": ("unlicense", "public domain"),
}


def _declaration_matches_text(terms: list[str], license_files: list[Any]) -> bool:
    """Whether the bundled licence text evidences a declared, non-copyleft term.

    The whole text is read, not a prefix: a permissive opening followed by a
    copyleft clause or an extra condition is exactly what a prefix check would
    miss. Text carrying GPL-family language is never evidence for a permissive
    declaration, and a text no known family matches is refused rather than
    assumed. A record that carries no text at all is refused too -- there is no
    legacy shape here that passes on a filename alone.
    """
    texts = [
        str(entry.get("text") or "")
        for entry in license_files
        if isinstance(entry, dict) and str(entry.get("text") or "").strip()
    ]
    if not texts:
        return False
    for text in texts:
        if _COPYLEFT_PATTERN.search(text):
            continue
        lowered = " ".join(text.split()).lower()
        for term in terms:
            upper = term.upper()
            for family, tokens in _LICENCE_FAMILY_TOKENS.items():
                if family in upper and any(token in lowered for token in tokens):
                    return True
    return False


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
            inventory_groups = classify_inventory_licenses(inventory)
            groups = {
                key: groups[key] + inventory_groups[key]
                for key in ("permitted", "copyleft", "undecidable")
            }
    except SbomSchemaError as error:
        print(f"::error::CycloneDX SBOM is malformed and cannot be adjudicated ({error}); refusing to release.",
              file=sys.stderr)
        return 1
    except (OSError, tomllib.TOMLDecodeError) as error:
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
