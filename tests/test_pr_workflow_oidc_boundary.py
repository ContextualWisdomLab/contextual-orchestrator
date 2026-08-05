"""Regression tests for the pull-request workflow credential boundary.

Pull-request heads are untrusted input. A workflow may inspect or test that code,
but it must not give the same job an OpenID Connect token that can be exchanged
for repository-writing credentials. Publication belongs to a separately trusted
workflow whose executable source is not selected by the pull-request branch.
"""

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
TEMPORARY_REPAIR_WORKFLOW_PATHS = (
    WORKFLOW_DIRECTORY / "nim-source-repair.yml",
    WORKFLOW_DIRECTORY / "nim-source-repair-trigger.yml",
)
_YAML_KEY_TEMPLATE = r"(?:{plain}|'(?:{plain})'|\"(?:{plain})\")"
_ID_TOKEN_WRITE_RE = re.compile(
    r"^\s*id-token\s*:\s*['\"]?write['\"]?\s*(?:#.*)?$",
    re.MULTILINE,
)


def _mapping_entry(
    lines: list[str],
    key: str,
    indent: int,
) -> tuple[str, list[str]] | None:
    """Return one indentation-bounded YAML mapping entry.

    This focused scanner intentionally recognizes only mapping structure needed
    by the workflow contracts. It avoids dependency on a permissive YAML loader
    while still making assertions independent of exact whitespace and sibling
    ordering.
    """
    key_pattern = _YAML_KEY_TEMPLATE.format(plain=re.escape(key))
    pattern = re.compile(
        rf"^ {{{indent}}}{key_pattern}\s*:\s*(?P<inline>[^#]*?)(?:\s+#.*)?$"
    )
    matches = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := pattern.match(line)) is not None
    ]
    if not matches:
        return None
    assert len(matches) == 1, f"duplicate YAML mapping key {key!r}"
    start_index, match = matches[0]
    body: list[str] = []
    for line in lines[start_index + 1 :]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent <= indent:
                break
        body.append(line)
    return match.group("inline").strip(), body


def _direct_child_indent(lines: list[str]) -> int | None:
    """Return the indentation of direct child entries in one YAML mapping body."""
    indents = [
        len(line) - len(line.lstrip(" "))
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return min(indents) if indents else None


def _workflow_triggers_pull_request(workflow_text: str) -> bool:
    """Return whether one workflow structurally declares a pull-request trigger."""
    on_entry = _mapping_entry(workflow_text.splitlines(), "on", 0)
    assert on_entry is not None, "workflow must declare a top-level 'on' key"
    inline_value, body = on_entry
    if inline_value:
        return re.search(
            r"(?<![A-Za-z0-9_-])pull_request(?![A-Za-z0-9_-])",
            inline_value,
        ) is not None
    child_indent = _direct_child_indent(body)
    return (
        child_indent is not None
        and _mapping_entry(body, "pull_request", child_indent) is not None
    )


def test_pull_request_workflows_cannot_exchange_repository_write_credentials() -> None:
    """Keep every pull-request workflow read-only and unable to mint write tokens."""
    triggered_workflows: list[tuple[Path, str]] = []
    for workflow_path in sorted(WORKFLOW_DIRECTORY.glob("*.y*ml")):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        if _workflow_triggers_pull_request(workflow_text):
            triggered_workflows.append((workflow_path, workflow_text))

    assert triggered_workflows, "at least one pull-request workflow must be inspected"
    for workflow_path, workflow_text in triggered_workflows:
        assert not _ID_TOKEN_WRITE_RE.search(workflow_text), workflow_path
        assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in workflow_text, workflow_path
        assert "exchange_github_app_token" not in workflow_text, workflow_path
        assert "git push origin" not in workflow_text, workflow_path

    assert all(
        not workflow_path.exists()
        for workflow_path in TEMPORARY_REPAIR_WORKFLOW_PATHS
    )
