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
        "KRW 2,000,000,000 Commercial Completion Standard",
        "Product Design",
        "Ponytail",
        "Data Analytics",
        "Commercial readiness",
        "Review process is not a blocker",
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
        "/api/v1/commercial_readiness/latest",
        "Commercial Due-Diligence KPIs",
        "commercial_readiness_pass_rate",
        "buyer_evidence_completeness",
        "security_control_pass_rate",
        "trace_audit_completeness",
        "support_operability_score",
        "roi_evidence_status",
        "measured_local",
        "proposed_until_production",
        "proposed_until_buyer_specific",
        "Strix passing",
    ]:
        assert expected_text in analytics


def test_superpowers_plan_records_no_code_connect_constraint() -> None:
    plan = read_text("docs/superpowers/plans/2026-07-02-plugin-driven-product-design.md")
    commercial_plan = read_text("docs/superpowers/plans/2026-07-02-commercial-plugin-readiness.md")

    for expected_text in [
        "Figma Code Connect must not be used",
        "No new repo dependencies",
        "Evidence Console",
        "docs/figma_artifacts.md",
        "python tests/test_plugin_driven_artifacts.py",
    ]:
        assert expected_text in plan

    for expected_text in [
        "KRW 2,000,000,000 commercial",
        "Do not create a separate library, Git submodule, or extracted package",
        "commercial_readiness_pass_rate",
        "KRW 2B Commercial Readiness Flow",
        "Review process is not a blocker",
        "pytest -q",
    ]:
        assert expected_text in commercial_plan


def test_figma_artifacts_are_recorded_without_code_connect() -> None:
    artifacts = read_text("docs/figma_artifacts.md")

    for expected_text in [
        "Contextual Orchestrator Plugin-Driven Admin Design",
        "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
        "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
        "Workflow Trace And Access Lists Clean",
        "KRW 2B Commercial Readiness Flow",
        "Contextual Orchestrator Plugin-Driven Product Plan",
        "Contextual Orchestrator KRW 2B Commercial Readiness Plan",
        "team::1408252278989737675",
        "Figma Code Connect was not used",
    ]:
        assert expected_text in artifacts


def test_ponytail_packaging_decision_keeps_commercial_product_unified() -> None:
    research = read_text("docs/library_research.md")

    for expected_text in [
        "Commercial Packaging Decision",
        "one repository and one deployable product",
        "Do not split the",
        "Git submodule",
        "Extraction triggers",
        "single-repo product",
    ]:
        assert expected_text in research


if __name__ == "__main__":  # pragma: no cover
    test_plugin_design_brief_preserves_enterprise_control_plane()
    test_visual_directions_define_three_options_and_canonical_choice()
    test_analytics_spec_separates_metric_design_from_real_measurement()
    test_superpowers_plan_records_no_code_connect_constraint()
    test_figma_artifacts_are_recorded_without_code_connect()
    print("ok")
