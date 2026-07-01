from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_plugin_design_brief_preserves_enterprise_control_plane() -> None:
    brief = read_text("docs/plugin_driven_design_brief.md")

    for expected_text in [
        "one enterprise orchestration control plane",
        "Code Connect is not used",
        "agent_pools",
        "workflow_runs",
        "access_reports",
        "evaluation_runs",
        "locale_bundles",
        "English",
        "Korean",
    ]:
        assert expected_text in brief


def test_visual_directions_define_three_options_and_canonical_choice() -> None:
    directions = read_text("docs/plugin_visual_directions.md")

    for expected_text in [
        "Direction 1: Evidence Console",
        "Direction 2: Policy Studio",
        "Direction 3: Audit Timeline",
        "Use Direction 1",
        "canonical build direction",
    ]:
        assert expected_text in directions


def test_analytics_spec_separates_metric_design_from_real_measurement() -> None:
    analytics = read_text("docs/analytics_spec.md")

    for expected_text in [
        "proposed definitions and source requirements, not measured product results",
        "Compatible API adoption",
        "Trace-complete workflow rate",
        "Policy-safe routing rate",
        "provider exclusion miss rate",
        "chat_completion_requested",
        "workflow_run_created",
        "provider_exclusion_changed",
    ]:
        assert expected_text in analytics


def test_superpowers_plan_records_no_code_connect_constraint() -> None:
    plan = read_text("docs/superpowers/plans/2026-07-02-plugin-driven-product-design.md")

    for expected_text in [
        "Figma Code Connect must not be used",
        "No new repo dependencies",
        "Evidence Console",
        "docs/figma_artifacts.md",
        "python tests/test_plugin_driven_artifacts.py",
    ]:
        assert expected_text in plan


def test_figma_artifacts_are_recorded_without_code_connect() -> None:
    artifacts = read_text("docs/figma_artifacts.md")

    for expected_text in [
        "Contextual Orchestrator Plugin-Driven Admin Design",
        "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
        "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
        "Workflow Trace And Access Lists Clean",
        "Contextual Orchestrator Plugin-Driven Product Plan",
        "Figma Code Connect was not used",
    ]:
        assert expected_text in artifacts


if __name__ == "__main__":  # pragma: no cover
    test_plugin_design_brief_preserves_enterprise_control_plane()
    test_visual_directions_define_three_options_and_canonical_choice()
    test_analytics_spec_separates_metric_design_from_real_measurement()
    test_superpowers_plan_records_no_code_connect_constraint()
    test_figma_artifacts_are_recorded_without_code_connect()
    print("ok")
