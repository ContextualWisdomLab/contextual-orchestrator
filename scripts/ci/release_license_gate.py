"""Fail-closed licence gate for the canonical release, read from the CycloneDX SBOM.

The release workflow already downloads the mandatory `cyclonedx-sbom.json` for
the exact commit being released. That SBOM enumerates every component that ends
up in the distributed artifact -- direct, transitive, build and optional alike
-- so it is the honest input for a licence decision: a check driven by
`pyproject.toml` alone would miss transitive components, and one driven by the
locally installed environment would miss whatever that environment happens not
to install.

Two outcomes block a release, and neither is waivable here:

* a copyleft licence in the GPL family (GPL, LGPL, AGPL, in any SPDX spelling);
* a component whose licence is absent, empty or literally unknown.

A dual-licensed component passes only when its expression really does offer a
permissive alternative (`Apache-2.0 OR GPL-2.0-only` passes and records
`Apache-2.0` as the taken option; `Apache-2.0 AND GPL-2.0-only` does not, since
`AND` imposes both). Being unused at runtime, optional or test-only is never an
exemption: if it is in the artifact's SBOM, it is in scope.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# SPDX identifiers and the older free-text spellings that mean the same family.
_COPYLEFT_PATTERN = re.compile(
    r"(?:^|[^A-Za-z])(?:A?GPL|LGPL|GPL)(?:[-_ ]|$)"
    r"|GNU\s+(?:Affero\s+|Lesser\s+)?General\s+Public",
    re.IGNORECASE,
)
_UNKNOWN_VALUES = frozenset({"", "unknown", "none", "null", "noassertion", "other", "proprietary"})


def _license_terms(component: dict[str, Any]) -> list[str]:
    """Collect every licence string CycloneDX offers for one component."""
    terms: list[str] = []
    for entry in component.get("licenses") or []:
        if not isinstance(entry, dict):
            continue
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            terms.append(expression.strip())
        license_object = entry.get("license")
        if isinstance(license_object, dict):
            for key in ("id", "name"):
                value = license_object.get(key)
                if isinstance(value, str) and value.strip():
                    terms.append(value.strip())
    return terms


def _permissive_choice(expression: str) -> str | None:
    """Return one non-copyleft operand of an SPDX ``OR`` expression, if any.

    ``AND`` imposes every operand at once, so an expression containing a
    top-level ``AND`` never yields a choice here even when one operand is
    permissive. Operators are matched case-sensitively, as SPDX defines them,
    so a name such as ``GPL-2.0-or-later`` is one operand rather than two.
    """
    # SPDX operators are upper-case standalone tokens. Matching them
    # case-insensitively would split "GPL-2.0-or-later" on its own name and
    # invent a permissive operand that the licence never offered.
    cleaned = expression.replace("(", " ").replace(")", " ")
    if re.search(r"\sAND\s", cleaned):
        return None
    operands = [part.strip() for part in re.split(r"\sOR\s", cleaned)]
    if len(operands) < 2:
        return None
    for operand in operands:
        if operand and not _COPYLEFT_PATTERN.search(operand):
            return operand
    return None


def classify_sbom_components(sbom: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Split every SBOM component into permitted, copyleft and unknown groups."""
    permitted: list[dict[str, str]] = []
    copyleft: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []
    for component in sbom.get("components") or []:
        if not isinstance(component, dict):
            continue
        name = str(component.get("name") or "<unnamed component>")
        version = str(component.get("version") or "")
        terms = _license_terms(component)
        usable = [term for term in terms if term.strip().lower() not in _UNKNOWN_VALUES]
        row = {"name": name, "version": version, "license": "; ".join(usable)}
        if not usable:
            unknown.append(row)
            continue
        copyleft_terms = [term for term in usable if _COPYLEFT_PATTERN.search(term)]
        if not copyleft_terms:
            permitted.append(row)
            continue
        choice = next(
            (taken for term in copyleft_terms for taken in (_permissive_choice(term),) if taken),
            None,
        )
        if choice is not None:
            permitted.append({**row, "license": f"{row['license']} (permissive option taken: {choice})"})
            continue
        copyleft.append(row)
    return {"permitted": permitted, "copyleft": copyleft, "unknown": unknown}


def _render(groups: dict[str, list[dict[str, str]]]) -> str:
    lines = [
        f"permitted={len(groups['permitted'])} "
        f"copyleft={len(groups['copyleft'])} unknown={len(groups['unknown'])}"
    ]
    for label in ("copyleft", "unknown"):
        for row in groups[label]:
            lines.append(f"{label.upper()} {row['name']}=={row['version']} license={row['license'] or '<none>'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sbom", required=True, help="path to cyclonedx-sbom.json for the exact commit")
    arguments = parser.parse_args(argv)
    try:
        with open(arguments.sbom, encoding="utf-8") as handle:
            sbom = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"::error::Release licence gate could not read the CycloneDX SBOM at {arguments.sbom}: {error}", file=sys.stderr)
        return 1
    if not isinstance(sbom, dict) or not sbom.get("components"):
        print(
            "::error::CycloneDX SBOM lists no components; an empty component set is not evidence that the "
            "artifact is licence-clean. Refusing to release.",
            file=sys.stderr,
        )
        return 1
    groups = classify_sbom_components(sbom)
    print(_render(groups))
    if groups["copyleft"] or groups["unknown"]:
        print(
            "::error::Release licence gate failed: "
            f"{len(groups['copyleft'])} GPL-family and {len(groups['unknown'])} unknown-licence component(s) "
            "are present in the artifact SBOM. Replace them with permissively licensed alternatives; being "
            "optional or unexecuted is not an exemption, and this gate is never waived to publish.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
