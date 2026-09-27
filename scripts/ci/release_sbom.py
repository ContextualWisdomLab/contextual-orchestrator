"""Bind a complete CycloneDX component inventory to exact release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote


def bind_inventory(bom: dict, inventory: dict, source_sha: str) -> dict:
    """Refuse omitted declared packages before adding source and licence evidence."""
    if inventory.get("source_sha") != source_sha or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("inventory source identity mismatch")
    if bom.get("bomFormat") != "CycloneDX":
        raise ValueError("expected CycloneDX SBOM")
    identities: dict[tuple[str, str, str], list[dict]] = {}
    for component in bom.get("components", []):
        purl = component.get("purl", "")
        if not purl.startswith("pkg:"):
            continue
        ecosystem, _, package = purl[4:].partition("/")
        name, separator, version = package.partition("?")[0].rpartition("@")
        if not separator:
            raise ValueError("unversioned component identity")
        name = unquote(name)
        declared_name = "/".join(filter(None, (component.get("group"), component.get("name"))))
        if ecosystem == "pypi":
            declared_name = re.sub(r"[-_.]+", "-", declared_name).lower()
        normalized_name = re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "pypi" else name
        if declared_name != normalized_name or component.get("version") != unquote(version):
            raise ValueError("component metadata disagrees with its package URL")
        if ecosystem == "pypi":
            name = re.sub(r"[-_.]+", "-", name).lower()
        identities.setdefault((ecosystem, name, unquote(version)), []).append(component)
    if not inventory.get("ecosystems"):
        raise ValueError("empty dependency inventory")
    for scope in inventory["ecosystems"]:
        ecosystem = {"python": "pypi", "cargo": "cargo", "npm": "npm"}[scope["ecosystem"]]
        if not scope.get("packages"):
            raise ValueError("empty dependency scope")
        for package in scope["packages"]:
            name = package["name"]
            if ecosystem == "pypi":
                name = re.sub(r"[-_.]+", "-", name).lower()
            matches = identities.get((ecosystem, name, package["version"]), [])
            if not matches:
                raise ValueError(f"SBOM omits {ecosystem}:{name}@{package['version']}")
            for component in matches:
                # Publisher declarations remain declarations; the separate gate adjudicates them.
                if package.get("licenses") and not component.get("licenses"):
                    component["licenses"] = [{"license": {"name": term}} for term in package["licenses"]]
    bom.setdefault("metadata", {}).setdefault("properties", []).extend([
        {"name": "contextual-orchestrator:source-sha", "value": source_sha},
        {"name": "contextual-orchestrator:inventory-sha256", "value": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()},
    ])
    return bom


def main() -> None:
    """Validate complete component coverage and write the bound release SBOM."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sbom", "inventory", "source-sha", "output"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    result = bind_inventory(json.loads(Path(args.sbom).read_text()),
                            json.loads(Path(args.inventory).read_text()), args.source_sha)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
