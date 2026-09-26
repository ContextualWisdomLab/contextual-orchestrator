"""ADR 0124 import boundary for the domain and application packages."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "contextual_orchestrator"

FORBIDDEN_EVERYWHERE = {
    "contextual_orchestrator.orchestrator",
    "contextual_orchestrator.server",
    "http",
    "psycopg",
    "socket",
    "sqlite3",
    "ssl",
    "urllib",
}
# The application layer may use threads; the domain may not.
FORBIDDEN_IN_DOMAIN = FORBIDDEN_EVERYWHERE | {"concurrent", "threading", "os", "subprocess"}


def _imported_modules(path: Path, package: str) -> set[str]:
    """Return absolute module names imported by one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(parts)
                modules.add(f"{base}.{node.module}" if node.module else base)
                modules.update(
                    f"{base}.{alias.name}" for alias in node.names if not node.module
                )
            elif node.module:
                modules.add(node.module)
    return modules


def _violations(subpackage: str, forbidden: set[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted((PACKAGE_ROOT / subpackage).rglob("*.py")):
        package = f"contextual_orchestrator.{subpackage}"
        bad = sorted(
            module
            for module in _imported_modules(path, package)
            if any(module == name or module.startswith(f"{name}.") for name in forbidden)
        )
        if bad:
            found[path.name] = bad
    return found


def test_domain_imports_no_io_or_orchestrator() -> None:
    assert (PACKAGE_ROOT / "domain" / "__init__.py").exists()
    assert _violations("domain", FORBIDDEN_IN_DOMAIN) == {}


def test_application_imports_no_io_or_orchestrator() -> None:
    assert (PACKAGE_ROOT / "application" / "__init__.py").exists()
    assert _violations("application", FORBIDDEN_EVERYWHERE) == {}


def test_boundary_checker_detects_relative_orchestrator_import(tmp_path) -> None:
    source = tmp_path / "leak.py"
    source.write_text("from ..orchestrator import TaskOrchestrator\nfrom .. import server\n")
    modules = _imported_modules(source, "contextual_orchestrator.domain")
    assert "contextual_orchestrator.orchestrator" in modules
    assert "contextual_orchestrator.server" in modules
