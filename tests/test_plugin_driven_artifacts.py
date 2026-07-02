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
        "Library Split Decision For KRW 2B Sale",
        "KRW 2B Completion Scorecard",
        "KRW 2B Buyer Deal Room Evidence Matrix",
        "KRW 2B Buyer Acceptance Go No Go Workflow",
        "KRW 2B Buyer Evidence Manifest Workflow",
        "KRW 2B Runtime Buyer Evidence Endpoint",
        "Contextual Orchestrator Plugin-Driven Product Plan",
        "Contextual Orchestrator KRW 2B Commercial Readiness Plan",
        "KRW 2B Commercial Evidence Export",
        "KRW 2B Commercial Acceptance Check",
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


def test_commercial_plugin_operating_model_defines_plugin_execution_scope() -> None:
    model = read_text("docs/commercial_plugin_operating_model.md")

    for expected_text in [
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Product Design Plan",
        "Figma Plan",
        "Ponytail Packaging Decision",
        "Data Analytics Plan",
        "Superpowers Execution Loop",
        "Do not create a separate library, Git submodule, or extracted package",
        "Library Split Decision For KRW 2B Sale",
        "commercial_readiness_pass_rate",
        "proposed until production",
        "proposed until buyer-specific",
    ]:
        assert expected_text in model


def test_commercial_completion_scorecard_defines_ready_warning_blocker_rules() -> None:
    scorecard = read_text("docs/commercial_completion_scorecard.md")

    for expected_text in [
        "Commercial Completion Scorecard",
        "KRW 2,000,000,000 enterprise sale",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Product Design",
        "Superpowers",
        "Ponytail",
        "Data Analytics",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Measured local evidence",
        "Proposed until production",
        "Proposed until buyer-specific",
        "Ready:",
        "Warning:",
        "Blocked:",
    ]:
        assert expected_text in scorecard


def test_commercial_buyer_diligence_packet_defines_deal_room_evidence() -> None:
    packet = read_text("docs/commercial_buyer_diligence_packet.md")

    for expected_text in [
        "Commercial Buyer Diligence Packet",
        "KRW 2,000,000,000 buyer review",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "measured_local",
        "repository_artifact",
        "figma_artifact",
        "proposed_until_production",
        "proposed_until_buyer_specific",
        "/api/v1/commercial_readiness/latest",
        "KRW 2B Buyer Deal Room Evidence Matrix",
    ]:
        assert expected_text in packet


def test_commercial_buyer_acceptance_runbook_defines_go_no_go_workflow() -> None:
    runbook = read_text("docs/commercial_buyer_acceptance_runbook.md")

    for expected_text in [
        "Commercial Buyer Acceptance Runbook",
        "KRW 2,000,000,000 commercial review",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Acceptance Workflow",
        "Go, Warning, No-Go Rules",
        "KRW 2B Buyer Acceptance Go No Go Workflow",
        "/api/v1/commercial_readiness/latest",
        "measured_local",
        "proposed_until_production",
        "proposed_until_buyer_specific",
    ]:
        assert expected_text in runbook


def test_commercial_buyer_evidence_manifest_indexes_sale_evidence() -> None:
    manifest = read_text("docs/commercial_buyer_evidence_manifest.md")

    for expected_text in [
        "Commercial Buyer Evidence Manifest",
        "KRW 2,000,000,000 buyer diligence review",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Evidence Type Legend",
        "Manifest Inventory",
        "KRW 2B Buyer Evidence Manifest Workflow",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/analytics_snapshots/latest",
        "local_buyer_evidence_manifest",
        "measured_local",
        "repository_artifact",
        "figma_artifact",
        "proposed_until_production",
        "proposed_until_buyer_specific",
    ]:
        assert expected_text in manifest


def test_commercial_buyer_handoff_bundle_packages_sale_evidence() -> None:
    bundle = read_text("docs/commercial_buyer_handoff_bundle.md")

    for expected_text in [
        "Commercial Buyer Handoff Bundle",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Handoff Contents",
        "Runtime Shape",
        "Acceptance Rules",
        "KRW 2B Buyer Handoff Bundle Workflow",
        "/api/v1/buyer_handoff_bundles/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/analytics_snapshots/latest",
        "local_buyer_handoff_bundle",
        "measured_local",
        "repository_artifact",
        "figma_artifact",
        "proposed_until_production",
        "proposed_until_buyer_specific",
    ]:
        assert expected_text in bundle


def test_commercial_saleability_decision_defines_final_gate() -> None:
    decision = read_text("docs/commercial_saleability_decision.md")

    for expected_text in [
        "Commercial Saleability Decision",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Decision Inputs",
        "Runtime Shape",
        "Decision Rules",
        "KRW 2B Saleability Decision Gate",
        "/api/v1/saleability_decisions/latest",
        "/api/v1/buyer_handoff_bundles/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/sales_readiness/latest",
        "local_saleability_decision",
        "concrete_blockers",
        "warning_conditions",
    ]:
        assert expected_text in decision


def test_commercial_evidence_export_defines_buyer_export_index() -> None:
    export = read_text("docs/commercial_evidence_export.md")
    plan = read_text("docs/superpowers/plans/2026-07-02-commercial-evidence-export.md")

    for expected_text in [
        "Commercial Evidence Export",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Export Inputs",
        "Runtime Shape",
        "Export Status Rules",
        "KRW 2B Commercial Evidence Export",
        "/api/v1/commercial_evidence_exports/latest",
        "/api/v1/saleability_decisions/latest",
        "/api/v1/buyer_handoff_bundles/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/sales_readiness/latest",
        "/api/v1/analytics_snapshots/latest",
        "local_commercial_evidence_export",
        "required_external_evidence",
        "export_sections",
    ]:
        assert expected_text in export

    for expected_text in [
        "Commercial Evidence Export Implementation Plan",
        "get_latest_commercial_evidence_export",
        "No new repo dependencies",
        "python tests/test_commercial_evidence_export.py",
        "pytest -q",
    ]:
        assert expected_text in plan


def test_commercial_acceptance_check_defines_buyer_acceptance_gate() -> None:
    acceptance = read_text("docs/commercial_acceptance_check.md")
    plan = read_text("docs/superpowers/plans/2026-07-02-commercial-acceptance-check.md")

    for expected_text in [
        "Commercial Acceptance Check",
        "KRW 2,000,000,000",
        "Figma Code Connect is not used",
        "Review process is not a blocker",
        "Do not create a separate library, Git submodule, or extracted package now",
        "Acceptance Inputs",
        "Runtime Shape",
        "Acceptance Status Rules",
        "KRW 2B Commercial Acceptance Check",
        "/api/v1/commercial_acceptance_checks/latest",
        "/api/v1/commercial_evidence_exports/latest",
        "/api/v1/saleability_decisions/latest",
        "/api/v1/buyer_handoff_bundles/latest",
        "/api/v1/buyer_evidence_manifests/latest",
        "/api/v1/commercial_readiness/latest",
        "/api/v1/sales_readiness/latest",
        "/api/v1/analytics_snapshots/latest",
        "local_commercial_acceptance_check",
        "acceptance_items",
        "follow_up_items",
    ]:
        assert expected_text in acceptance

    for expected_text in [
        "Commercial Acceptance Check Implementation Plan",
        "get_latest_commercial_acceptance_check",
        "No new repo dependencies",
        "python tests/test_commercial_acceptance_check.py",
        "pytest -q",
    ]:
        assert expected_text in plan


if __name__ == "__main__":  # pragma: no cover
    test_plugin_design_brief_preserves_enterprise_control_plane()
    test_visual_directions_define_three_options_and_canonical_choice()
    test_analytics_spec_separates_metric_design_from_real_measurement()
    test_superpowers_plan_records_no_code_connect_constraint()
    test_figma_artifacts_are_recorded_without_code_connect()
    test_ponytail_packaging_decision_keeps_commercial_product_unified()
    test_commercial_plugin_operating_model_defines_plugin_execution_scope()
    test_commercial_completion_scorecard_defines_ready_warning_blocker_rules()
    test_commercial_buyer_diligence_packet_defines_deal_room_evidence()
    test_commercial_buyer_acceptance_runbook_defines_go_no_go_workflow()
    test_commercial_buyer_evidence_manifest_indexes_sale_evidence()
    test_commercial_buyer_handoff_bundle_packages_sale_evidence()
    test_commercial_saleability_decision_defines_final_gate()
    test_commercial_evidence_export_defines_buyer_export_index()
    test_commercial_acceptance_check_defines_buyer_acceptance_gate()
    print("ok")
