"""Fail closed when a release SBOM differs from the pinned runtime closure."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)(?:\s+\\)?$")


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line[0].isspace():
            if line.strip().startswith(("#", "--hash=sha256:")):
                continue
            raise ValueError(f"unsupported requirement continuation: {line}")
        match = _PIN.fullmatch(line)
        if match is None:
            raise ValueError(f"unsupported or unpinned requirement: {line}")
        name, version = _name(match[1]), match[2]
        if name in pins:
            raise ValueError(f"duplicate pinned requirement: {name}")
        pins[name] = version
    if not pins:
        raise ValueError("runtime lock contains no pinned packages")
    return pins


def verify(lock: Path, project: Path, sbom: Path) -> None:
    expected = _pins(lock)
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))["project"]
    document = json.loads(sbom.read_text(encoding="utf-8"))
    if document.get("bomFormat") != "CycloneDX":
        raise ValueError("release SBOM is not CycloneDX")
    root = document.get("metadata", {}).get("component", {})
    if not isinstance(root, dict) or (
        _name(str(root.get("name", ""))) != _name(metadata["name"])
        or root.get("version") != metadata["version"]
    ):
        raise ValueError("release SBOM root does not match the project")
    components = document.get("components")
    if not isinstance(components, list):
        raise ValueError("release SBOM has no component list")
    actual: dict[str, str] = {}
    refs: set[str] = set()
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("name"), str):
            raise ValueError("release SBOM has a malformed component")
        name, version = _name(component["name"]), component.get("version")
        ref = component.get("bom-ref")
        if (
            name in actual
            or not isinstance(version, str)
            or not isinstance(ref, str)
            or not ref
            or ref in refs
        ):
            raise ValueError(f"release SBOM has duplicate or invalid component: {name}")
        actual[name] = version
        refs.add(ref)
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        wrong = sorted(
            name for name in expected.keys() & actual.keys()
            if expected[name] != actual[name]
        )
        raise ValueError(
            f"release SBOM differs from runtime lock: "
            f"missing={missing}, extra={extra}, wrong_version={wrong}"
        )
    root_ref = root.get("bom-ref")
    dependencies = document.get("dependencies")
    if not isinstance(root_ref, str) or not root_ref or not isinstance(dependencies, list):
        raise ValueError("release SBOM has no rooted dependency graph")
    graph: dict[str, list[str]] = {}
    for entry in dependencies:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("ref"), str)
            or not isinstance(entry.get("dependsOn", []), list)
        ):
            raise ValueError("release SBOM has a malformed dependency entry")
        ref, children = entry["ref"], entry.get("dependsOn", [])
        if ref in graph or any(not isinstance(child, str) for child in children):
            raise ValueError("release SBOM has a duplicate or invalid dependency entry")
        graph[ref] = children
    if set(graph) != refs | {root_ref} or not graph[root_ref]:
        raise ValueError("release SBOM dependency graph is incomplete")
    if any(set(children) - refs for children in graph.values()):
        raise ValueError("release SBOM dependency graph references unknown components")
    reached = {root_ref}
    pending = [root_ref]
    while pending:
        for child in graph[pending.pop()]:
            if child not in reached:
                reached.add(child)
                pending.append(child)
    if reached != refs | {root_ref}:
        raise ValueError("release SBOM has components outside the rooted dependency graph")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise ValueError("expected lock, pyproject, and SBOM paths")
        verify(*(Path(value) for value in sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f"runtime SBOM verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
