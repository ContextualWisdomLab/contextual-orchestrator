"""Retire synthetic test-time-compute heuristics on PR #1000.

The production contract keeps explicit caller-supplied ReasoningEffortProfile
objects, but removes the repository-authored role catalog, pseudo-psychometric
estimators, invented token arithmetic, and fixed RMSE unlock threshold as
substantive decision authority.  Test-only explicit profiles remain fixtures,
not production defaults.  This one-shot driver is removed by its workflow.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROFILE = Path("contextual_orchestrator/reasoning_effort_profile.py")
MAIN = Path("contextual_orchestrator/__main__.py")
REASONING_TEST = Path("tests/test_reasoning_effort_profile.py")
CLI_TEST = Path("tests/test_cli_role_effort_catalog.py")
MIXED_TEST = Path("tests/test_mixed_pool_role_effort_selection.py")
TOOL_TEST = Path("tests/test_tool_loop_role_effort_catalog_http.py")
GENERATED_TEST = Path("tests/test_generated_workflow.py")
PASSTHROUGH_TEST = Path("tests/test_passthrough_provider_failover.py")
DOCTORING = Path("docs/doctoring/reasoning-effort-profile.md")
RESEARCH = Path("docs/library_research.md")
ADR = Path("docs/planning/adrs/0034-anti-heuristic-routing-evidence.md")
GAP = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")
DOC_MARKER = "## 2026-09-02 reasoning-effort no-heuristics amendment"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_def(path: Path, name: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{path}:{name}: expected one function, found {len(matches)}")
    node = matches[0]
    if node.end_lineno is None:
        raise RuntimeError(f"{path}:{name}: parser did not expose end_lineno")
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [replacement.rstrip() + "\n"]
    path.write_text("".join(lines), encoding="utf-8")


def remove_defs(path: Path, names: tuple[str, ...]) -> None:
    for name in names:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ]
        if len(matches) != 1:
            raise RuntimeError(f"{path}:{name}: expected one function, found {len(matches)}")
        node = matches[0]
        if node.end_lineno is None:
            raise RuntimeError(f"{path}:{name}: parser did not expose end_lineno")
        lines = text.splitlines(keepends=True)
        del lines[node.lineno - 1 : node.end_lineno]
        path.write_text("".join(lines), encoding="utf-8")


def append_once(path: Path, marker: str, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def patch_profile() -> None:
    replace_once(
        PROFILE,
        'PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD = 0.55\n',
        'PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD = None\n',
        "fixed production RMSE threshold",
    )
    replace_once(
        PROFILE,
        '_EFFORT_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}\n',
        "",
        "synthetic effort rank",
    )
    replace_once(
        PROFILE,
        '_ACCESS_RANK = {"none": 0, "role": 1, "workflow": 2}\n',
        "",
        "synthetic access rank",
    )
    replace_def(
        PROFILE,
        "default_role_effort_catalog",
        '''def default_role_effort_catalog() -> dict[str, ReasoningEffortProfile]:
    """Fail closed: no repository-authored role-to-compute policy is authoritative."""
    raise EffortProfileError(
        "heuristic role-to-effort allocation is retired; supply an explicit governed "
        "profile with measured evaluation evidence"
    )''',
    )
    replace_def(
        PROFILE,
        "_shrinkage_weight",
        '''def _shrinkage_weight(
    reasoning_effort: str,
    extra_workflow_steps: float,
    extra_recursion_depth: float,
    access_list_scope: str,
) -> float:
    """Reject the retired synthetic shrinkage formula."""
    del reasoning_effort, extra_workflow_steps, extra_recursion_depth, access_list_scope
    raise EffortProfileError(
        "heuristic pseudo-psychometric shrinkage is retired; fitted measurement evidence is required"
    )''',
    )
    replace_def(
        PROFILE,
        "_estimated_tokens_used",
        '''def _estimated_tokens_used(
    reasoning_effort: str,
    extra_workflow_steps: int,
    extra_recursion_depth: int,
    budget_tokens: int,
) -> int:
    """Reject invented token-use arithmetic in favor of provider/tokenizer evidence."""
    del reasoning_effort, extra_workflow_steps, extra_recursion_depth, budget_tokens
    raise EffortProfileError(
        "heuristic token-use estimation is retired; provider/tokenizer evidence is required"
    )''',
    )
    replace_def(
        PROFILE,
        "estimate_theta",
        '''def estimate_theta(
    true_theta: Iterable[float],
    *,
    reasoning_effort: str,
    extra_workflow_steps: int,
    temperature: float,
    extra_recursion_depth: int = 0,
    access_list_scope: str = "role",
) -> ThetaEstimate:
    """Reject the retired pseudo-psychometric theta estimator."""
    del true_theta, reasoning_effort, extra_workflow_steps, temperature
    del extra_recursion_depth, access_list_scope
    raise EffortProfileError(
        "heuristic theta estimation is retired; a fitted psychometric measurement model is required"
    )''',
    )
    replace_def(
        PROFILE,
        "estimate_theta_rmse",
        '''def estimate_theta_rmse(
    true_theta: Iterable[float],
    *,
    reasoning_effort: str,
    extra_workflow_steps: int,
    temperature: float,
    extra_recursion_depth: int = 0,
    access_list_scope: str = "role",
) -> float:
    """Reject synthetic RMSE values that are not produced by fitted measurement."""
    del true_theta, reasoning_effort, extra_workflow_steps, temperature
    del extra_recursion_depth, access_list_scope
    raise EffortProfileError(
        "heuristic RMSE estimation is retired; measured fitted-model evidence is required"
    )''',
    )
    replace_def(
        PROFILE,
        "_ablation_arm",
        '''def _ablation_arm(
    theta: tuple[float, ...],
    *,
    mode: str,
    reasoning_effort: str,
    extra_workflow_steps: int,
    extra_recursion_depth: int,
    access_list_scope: str,
    temperature: float,
    budget_tokens: int,
) -> dict[str, Any]:
    """Reject synthetic ablation arms; only measured runs are evidence."""
    del theta, mode, reasoning_effort, extra_workflow_steps, extra_recursion_depth
    del access_list_scope, temperature, budget_tokens
    raise EffortProfileError(
        "heuristic ablation simulation is retired; execute and measure the governed variants"
    )''',
    )
    replace_def(
        PROFILE,
        "run_equal_budget_ablation",
        '''def run_equal_budget_ablation(true_theta: Iterable[float]) -> dict[str, Any]:
    """Reject synthetic ablation generation; production evidence must come from real runs."""
    del true_theta
    raise EffortProfileError(
        "heuristic equal-budget ablation is retired; real measured evaluation evidence is required"
    )''',
    )
    replace_def(
        PROFILE,
        "production_default_change_allowed",
        '''def production_default_change_allowed(report: Mapping[str, Any]) -> bool:
    """Never authorize a production default through the retired fixed-threshold gate."""
    del report
    return False''',
    )


def patch_cli() -> None:
    replace_once(
        MAIN,
        "from .reasoning_effort_profile import default_role_effort_catalog\n",
        "",
        "retired default catalog import",
    )
    text = MAIN.read_text(encoding="utf-8")
    old_help_start = '''        help=(\n            "Opt in to the issue #568 per-role reasoning-effort catalog (ADR 0021). "'''
    help_start = text.find(old_help_start)
    if help_start < 0:
        raise RuntimeError("role effort CLI help start not found")
    help_end = text.find("        ),\n    )\n", help_start)
    if help_end < 0:
        raise RuntimeError("role effort CLI help end not found")
    help_end += len("        ),\n")
    new_help = '''        help=(\n            "Retired compatibility flag. Repository-authored role-to-effort allocation is "\n            "not evidence-backed; supplying this flag fails closed. Configure explicit "\n            "governed profiles through the library/API after measured evaluation instead."\n        ),\n'''
    MAIN.write_text(text[:help_start] + new_help + text[help_end:], encoding="utf-8")
    replace_once(
        MAIN,
        "    args = parser.parse_args(arguments)\n\n    client = ModelClient(\n",
        '''    args = parser.parse_args(arguments)\n    if args.role_effort_catalog is not None:\n        parser.error(\n            "--role-effort-catalog default is retired: repository-authored "\n            "test-time-compute allocation is not evidence-backed"\n        )\n\n    client = ModelClient(\n''',
        "role effort CLI fail-closed gate",
    )
    replace_once(
        MAIN,
        '''        role_effort_catalog=(\n            default_role_effort_catalog() if args.role_effort_catalog == "default" else None\n        ),\n''',
        "        role_effort_catalog=None,\n",
        "role effort construction",
    )
    replace_once(
        MAIN,
        '''    if args.role_effort_catalog is not None:\n        _require_eligible_role_effort_agents(orchestrator, parser, args.agents)\n\n''',
        "",
        "obsolete default-catalog startup eligibility call",
    )


def explicit_catalog_helper() -> str:
    return '''\n\ndef _explicit_role_effort_catalog():\n    """Return a test-only explicit profile catalog, never a production default."""\n    profile = ReasoningEffortProfile(\n        reasoning_effort="high",\n        max_output_tokens=321,\n        max_calls=1,\n        max_workflow_steps=2,\n        max_recursion_depth=0,\n        max_worker_fan_out=1,\n        access_list_scope="role",\n        deadline_ms=60_000,\n        cost_token_budget=2_000,\n        temperature=0.3,\n        top_p=0.9,\n        seed=11,\n        unsupported_provider_fallback="abstain",\n    )\n    return {role: profile for role in WORKFLOW_ROLES}\n'''


def patch_simple_fixture_test(path: Path, import_old: str, import_new: str, anchor: str) -> None:
    text = path.read_text(encoding="utf-8")
    if "def _explicit_role_effort_catalog" in text:
        return
    if import_old not in text:
        raise RuntimeError(f"{path}: fixture import pattern missing")
    text = text.replace(import_old, import_new, 1)
    if anchor not in text:
        raise RuntimeError(f"{path}: fixture helper anchor missing")
    text = text.replace(anchor, anchor + explicit_catalog_helper(), 1)
    text = text.replace("default_role_effort_catalog()", "_explicit_role_effort_catalog()")
    path.write_text(text, encoding="utf-8")


def patch_fixture_tests() -> None:
    patch_simple_fixture_test(
        MIXED_TEST,
        '''from contextual_orchestrator import (  # noqa: E402\n    ModelAgent,\n    TaskOrchestrator,\n    default_role_effort_catalog,\n)\n''',
        '''from contextual_orchestrator import (  # noqa: E402\n    ModelAgent,\n    ReasoningEffortProfile,\n    TaskOrchestrator,\n)\nfrom contextual_orchestrator.reasoning_effort_profile import WORKFLOW_ROLES  # noqa: E402\n''',
        '_SUPPORTED_BASE_URL = "mlx://127.0.0.1:59482/v1"\n',
    )
    patch_simple_fixture_test(
        TOOL_TEST,
        '''from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402\n    default_role_effort_catalog,\n)\n''',
        '''from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402\n    ReasoningEffortProfile,\n    WORKFLOW_ROLES,\n)\n''',
        '_TEST_AUTH_TOKEN = "tool_loop_role_effort_catalog_http_token"  # noqa: S105\n',
    )
    patch_simple_fixture_test(
        GENERATED_TEST,
        '''from contextual_orchestrator import (  # noqa: E402\n    ModelAgent,\n    TaskOrchestrator,\n    default_role_effort_catalog,\n)\n''',
        '''from contextual_orchestrator import (  # noqa: E402\n    ModelAgent,\n    ReasoningEffortProfile,\n    TaskOrchestrator,\n)\nfrom contextual_orchestrator.reasoning_effort_profile import WORKFLOW_ROLES  # noqa: E402\n''',
        'PLAN = {\n',
    )
    patch_simple_fixture_test(
        PASSTHROUGH_TEST,
        '''from contextual_orchestrator import (\n    ModelAgent,\n    ReasoningEffortProfile,\n    TaskOrchestrator,\n    default_role_effort_catalog,\n)\n''',
        '''from contextual_orchestrator import (\n    ModelAgent,\n    ReasoningEffortProfile,\n    TaskOrchestrator,\n)\nfrom contextual_orchestrator.reasoning_effort_profile import WORKFLOW_ROLES\n''',
        'from contextual_orchestrator.provider_errors import ProviderUpstreamError\n',
    )


def patch_reasoning_test() -> None:
    text = REASONING_TEST.read_text(encoding="utf-8")
    if "def _explicit_role_effort_catalog" not in text:
        anchor = "from contextual_orchestrator.reasoning_effort_profile import (  # noqa: E402\n"
        start = text.find(anchor)
        if start < 0:
            raise RuntimeError("reasoning test import block missing")
        end = text.find(")\n", start)
        if end < 0:
            raise RuntimeError("reasoning test import block end missing")
        end += 2
        text = text[:end] + explicit_catalog_helper() + text[end:]
    text = text.replace("default_role_effort_catalog()", "_explicit_role_effort_catalog()")
    REASONING_TEST.write_text(text, encoding="utf-8")
    replace_def(
        REASONING_TEST,
        "test_default_catalog_binds_every_workflow_role",
        '''def test_default_catalog_binds_every_workflow_role() -> None:
    """The former repository-authored role catalog is a fail-closed tombstone."""
    try:
        default_role_effort_catalog()
    except EffortProfileError as exc:
        assert "heuristic" in str(exc) or "evidence" in str(exc)
        return
    raise AssertionError("repository-authored role-to-effort defaults must be retired")''',
    )
    remove_defs(
        REASONING_TEST,
        (
            "test_true_theta_rmse_improves_with_effort_not_temperature",
            "test_true_theta_values_change_estimated_rmse",
            "test_empty_true_theta_fails_closed",
            "test_access_list_scope_changes_rmse",
            "test_equal_budget_ablation_keeps_production_default_locked",
            "test_production_gate_rejects_junk_and_estimated_status",
            "test_estimator_rejects_invalid_factors_and_budget_overflow",
        ),
    )
    replace_def(
        REASONING_TEST,
        "test_snapshot_rejects_wrong_profile_type_and_release_gate_is_strict",
        '''def test_snapshot_rejects_wrong_profile_type_and_release_gate_is_strict() -> None:
    catalog = _explicit_role_effort_catalog()
    catalog["judge"] = object()  # type: ignore[assignment]
    try:
        snapshot_role_effort_catalog(catalog)
    except EffortProfileError:
        pass
    else:
        raise AssertionError("snapshot accepted a non-profile role")
    assert PRODUCTION_RMSE_IMPROVEMENT_THRESHOLD is None
    assert production_default_change_allowed(
        {
            "single_model_baseline": {"rmse": 1.0},
            "role_differentiated": {"rmse": 0.0},
            "measurement_status": "measured",
            "robustness_passed": True,
        }
    ) is False''',
    )


def patch_cli_test() -> None:
    CLI_TEST.write_text('''"""CLI contract for the retired repository-authored reasoning-effort catalog."""\n\nfrom __future__ import annotations\n\nimport json\nfrom io import StringIO\nfrom unittest.mock import patch\n\nfrom contextual_orchestrator.__main__ import main\n\n\ndef test_role_effort_catalog_default_flag_fails_closed() -> None:\n    stderr = StringIO()\n    with patch("sys.stderr", stderr):\n        try:\n            main(["--role-effort-catalog", "default", "hi"])\n        except SystemExit as exc:\n            assert exc.code == 2\n        else:  # pragma: no cover\n            raise AssertionError("retired role-effort default must fail closed")\n    message = stderr.getvalue()\n    assert "retired" in message\n    assert "evidence-backed" in message\n\n\ndef test_role_effort_catalog_omitted_keeps_catalog_none() -> None:\n    stdout = StringIO()\n    with patch("sys.stdout", stdout):\n        main(["hi"])\n    result = json.loads(stdout.getvalue())\n    assert "reasoning_effort_snapshot" not in result\n\n\ndef test_role_effort_catalog_rejects_unknown_value() -> None:\n    try:\n        main(["--role-effort-catalog", "bogus", "hi"])\n    except SystemExit as exc:\n        assert exc.code == 2\n    else:  # pragma: no cover\n        raise AssertionError("unknown role-effort catalog must fail closed")\n''', encoding="utf-8")


def patch_docs() -> None:
    section = f'''{DOC_MARKER}\n\nThe repository-authored role-to-effort table, pseudo-psychometric shrinkage/RMSE\nfunctions, invented token-use arithmetic, synthetic equal-budget ablation, and\nfixed 55% production-unlock threshold are retired as decision authority. They\nwere not fitted measurement models and therefore cannot allocate test-time\ncompute or authorize a production default. Explicit caller-supplied, versioned\n`ReasoningEffortProfile` objects remain supported as configuration only; their\nvalues are not evidence of superiority. Production policy changes require\nmeasured executions plus an identified statistical/psychometric evaluation\ncontract, with fast-mlsirm used where latent response quality is estimated.\n'''
    append_once(DOCTORING, DOC_MARKER, section)
    append_once(RESEARCH, DOC_MARKER, section)
    append_once(ADR, DOC_MARKER, section)
    append_once(GAP, DOC_MARKER, section)
    append_once(CHANGELOG, DOC_MARKER, section)


def main() -> None:
    patch_profile()
    patch_cli()
    patch_reasoning_test()
    patch_cli_test()
    patch_fixture_tests()
    patch_docs()


if __name__ == "__main__":
    main()
