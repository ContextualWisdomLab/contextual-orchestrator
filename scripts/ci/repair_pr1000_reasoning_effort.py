"""Retire synthetic test-time-compute heuristics on PR #1000.

This one-shot driver is intentionally exact-text guarded. It must be removed by
its workflow before the canonical PR becomes mergeable.
"""

from __future__ import annotations

from pathlib import Path

PROFILE = Path("contextual_orchestrator/reasoning_effort_profile.py")
MAIN = Path("contextual_orchestrator/__main__.py")
CLI_TEST = Path("tests/test_cli_role_effort_catalog.py")
MARKER = "# PR1000_EVIDENCE_ONLY_REASONING_EFFORT"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_profile() -> None:
    text = PROFILE.read_text(encoding="utf-8")
    if MARKER in text:
        return
    text = text.rstrip() + f'''\n\n{MARKER}\n# Compatibility tombstones for issue #568's retired synthetic policy. The\n# historical implementation remains above solely so old serialized/profile\n# shapes can be audited while callers migrate; these later definitions are the\n# module's live public decision surfaces.\nPRODUCTION_RMSE_IMPROVEMENT_THRESHOLD = None\n\n\ndef _retired_synthetic_effort_policy(*_args: Any, **_kwargs: Any) -> Any:\n    """Fail closed instead of fabricating test-time-compute evidence."""\n    raise EffortProfileError(\n        "heuristic reasoning-effort allocation/estimation is retired; "\n        "supply an explicit governed profile and measured evaluation evidence"\n    )\n\n\ndef default_role_effort_catalog() -> dict[str, ReasoningEffortProfile]:\n    """Reject the retired hand-authored role-to-effort catalog."""\n    return _retired_synthetic_effort_policy()\n\n\ndef _shrinkage_weight(\n    reasoning_effort: str,\n    extra_workflow_steps: float,\n    extra_recursion_depth: float,\n    access_list_scope: str,\n) -> float:\n    """Reject the retired synthetic shrinkage formula."""\n    return _retired_synthetic_effort_policy(\n        reasoning_effort, extra_workflow_steps, extra_recursion_depth, access_list_scope\n    )\n\n\ndef _estimated_tokens_used(\n    reasoning_effort: str,\n    extra_workflow_steps: int,\n    extra_recursion_depth: int,\n    budget_tokens: int,\n) -> int:\n    """Reject invented token-use arithmetic; use provider/tokenizer evidence."""\n    del reasoning_effort, extra_workflow_steps, extra_recursion_depth, budget_tokens\n    raise EffortProfileError(\n        "heuristic token-use estimation is retired; provider/tokenizer evidence is required"\n    )\n\n\ndef estimate_theta(\n    true_theta: Iterable[float],\n    *,\n    reasoning_effort: str,\n    extra_workflow_steps: int,\n    temperature: float,\n    extra_recursion_depth: int = 0,\n    access_list_scope: str = "role",\n) -> ThetaEstimate:\n    """Reject the retired pseudo-psychometric theta estimator."""\n    return _retired_synthetic_effort_policy(\n        true_theta,\n        reasoning_effort=reasoning_effort,\n        extra_workflow_steps=extra_workflow_steps,\n        temperature=temperature,\n        extra_recursion_depth=extra_recursion_depth,\n        access_list_scope=access_list_scope,\n    )\n\n\ndef estimate_theta_rmse(\n    true_theta: Iterable[float],\n    *,\n    reasoning_effort: str,\n    extra_workflow_steps: int,\n    temperature: float,\n    extra_recursion_depth: int = 0,\n    access_list_scope: str = "role",\n) -> float:\n    """Reject synthetic RMSE values that are not fitted psychometric estimates."""\n    return _retired_synthetic_effort_policy(\n        true_theta,\n        reasoning_effort=reasoning_effort,\n        extra_workflow_steps=extra_workflow_steps,\n        temperature=temperature,\n        extra_recursion_depth=extra_recursion_depth,\n        access_list_scope=access_list_scope,\n    )\n\n\ndef _ablation_arm(*_args: Any, **_kwargs: Any) -> dict[str, Any]:\n    """Reject synthetic ablation arms."""\n    return _retired_synthetic_effort_policy(*_args, **_kwargs)\n\n\ndef run_equal_budget_ablation(true_theta: Iterable[float]) -> dict[str, Any]:\n    """Reject simulated ablations; production evidence must come from real runs."""\n    return _retired_synthetic_effort_policy(true_theta)\n\n\ndef production_default_change_allowed(report: Mapping[str, Any]) -> bool:\n    """Never authorize a production default from this retired heuristic gate."""\n    del report\n    return False\n'''
    PROFILE.write_text(text, encoding="utf-8")


def patch_cli() -> None:
    replace_once(
        MAIN,
        "from .reasoning_effort_profile import default_role_effort_catalog\n",
        "",
        "retired default catalog import",
    )
    replace_once(
        MAIN,
        '''        help=(\n            "Opt in to the issue #568 per-role reasoning-effort catalog (ADR 0021). "\n            "'default' loads default_role_effort_catalog(), applying each workflow "\n            "role's temperature/top_p/seed/max_output_tokens and (only where a provider "\n            "proves support) native reasoning_effort, and attaching a replayable "\n            "reasoning_effort_snapshot to complete/run/stream_route/batch_route "\n            "results. Omit to keep today's payload unchanged -- this does not "\n            "change route/conduct selection defaults, which stay locked until "\n            "production_default_change_allowed is true. Every role in 'default' "\n            "fails closed for a provider that has not proven support, so at "\n            "least one --agents entry needs \\"reasoning_effort_supported\\": "\n            "true (or a mock:// base_url) -- startup refuses the flag "\n            "otherwise."\n        ),\n''',
        '''        help=(\n            "Retired compatibility flag. The hand-authored role-effort catalog is no "\n            "longer decision authority; supplying this flag fails closed. Use an "\n            "explicit governed profile through the library/API boundary after "\n            "measured evaluation instead."\n        ),\n''',
        "role effort CLI help",
    )
    replace_once(
        MAIN,
        "    args = parser.parse_args(arguments)\n\n    client = ModelClient(\n",
        '''    args = parser.parse_args(arguments)\n    if args.role_effort_catalog is not None:\n        parser.error(\n            "--role-effort-catalog default is retired: hand-authored role-based "\n            "test-time-compute allocation is not evidence-backed"\n        )\n\n    client = ModelClient(\n''',
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
        "obsolete role effort eligibility guard call",
    )


def patch_cli_test() -> None:
    CLI_TEST.write_text('''"""CLI contract for the retired hand-authored reasoning-effort catalog."""\n\nfrom __future__ import annotations\n\nimport json\nfrom io import StringIO\nfrom unittest.mock import patch\n\nfrom contextual_orchestrator.__main__ import main\n\n\ndef test_role_effort_catalog_default_flag_fails_closed() -> None:\n    stderr = StringIO()\n    with patch("sys.stderr", stderr):\n        try:\n            main(["--role-effort-catalog", "default", "hi"])\n        except SystemExit as exc:\n            assert exc.code == 2\n        else:  # pragma: no cover\n            raise AssertionError("retired role-effort default must fail closed")\n    message = stderr.getvalue()\n    assert "retired" in message\n    assert "evidence-backed" in message\n\n\ndef test_role_effort_catalog_omitted_keeps_catalog_none() -> None:\n    stdout = StringIO()\n    with patch("sys.stdout", stdout):\n        main(["hi"])\n    result = json.loads(stdout.getvalue())\n    assert "reasoning_effort_snapshot" not in result\n\n\ndef test_role_effort_catalog_rejects_unknown_value() -> None:\n    try:\n        main(["--role-effort-catalog", "bogus", "hi"])\n    except SystemExit as exc:\n        assert exc.code == 2\n    else:  # pragma: no cover\n        raise AssertionError("unknown role-effort catalog must fail closed")\n''', encoding="utf-8")


def main() -> None:
    patch_profile()
    patch_cli()
    patch_cli_test()


if __name__ == "__main__":
    main()
