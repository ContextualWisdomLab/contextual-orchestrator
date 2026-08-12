"""Repository contracts for fail-closed production coverage and public docstrings."""

from pathlib import Path
import tomli as tomllib


ROOT_DIR = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT_DIR / "pyproject.toml"
TESTS_WORKFLOW_PATH = ROOT_DIR / ".github" / "workflows" / "tests.yml"


def _pyproject() -> dict[str, object]:
    """Return the parsed project configuration used by local and CI evidence."""
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _named_step(workflow: str, name: str) -> str:
    """Return one exact named workflow step without depending on a YAML package."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def test_production_coverage_policy_is_branch_complete_and_has_no_omissions() -> None:
    """Require every production module to participate in the 100% branch gate."""
    config = _pyproject()
    coverage = config["tool"]["coverage"]

    assert coverage["run"].get("omit", []) == []
    assert coverage["run"]["branch"] is True
    assert coverage["report"]["fail_under"] == 100


def test_public_docstring_policy_requires_complete_evidence() -> None:
    """Require the package public-docstring threshold to be exactly 100 percent."""
    config = _pyproject()

    assert config["tool"]["interrogate"]["fail-under"] == 100


def test_exact_head_tests_workflow_enforces_coverage_and_docstrings() -> None:
    """Keep repository-local exact-head CI fail-closed on both evidence classes."""
    workflow = TESTS_WORKFLOW_PATH.read_text(encoding="utf-8")
    install_step = _named_step(workflow, "Install test dependencies")
    test_step = _named_step(workflow, "Run full test suite")

    assert "requirements-opencode-review-ci.txt" in install_step
    assert "python -m coverage run --branch -m pytest -q" in test_step
    assert "python -m coverage report --fail-under=100" in test_step
    assert "interrogate --fail-under 100 contextual_orchestrator" in test_step
