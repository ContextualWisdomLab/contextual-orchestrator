"""Commercial, sales, and buyer readiness report generators.

Moved verbatim from ``TaskOrchestrator`` in ``orchestrator.py`` as step 1 of
docs/adr/0124-incremental-domain-extraction.md. Each function takes the
orchestrator instance as its first argument (formerly ``self``);
``TaskOrchestrator`` keeps thin delegating methods with identical signatures,
and its per-request report cache still wraps those methods, so callers see no
behaviour change. Calls between reports go back through the orchestrator's
methods so caching, subclass overrides, and test monkeypatches keep applying.

This module must not import ``contextual_orchestrator.orchestrator`` at import
time; the one runtime helper it needs is imported inside the function that uses
it, and the type is imported only for static analysis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..conventions import require_object_name
from ..release_authorization import evaluate_release_authorization

if TYPE_CHECKING:
    from ..orchestrator import TaskOrchestrator


DEFAULT_COMMERCIAL_TARGET_VALUE_KRW = 2_000_000_000


def sales_readiness_report(
    orchestrator: TaskOrchestrator,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a local, evidence-backed sales-readiness gate for enterprise pilots."""
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    runs = orchestrator._completed_workflow_runs()
    conducted_runs = [run for run in runs if run["mode"] == "conduct"]
    trace_complete_count = sum(1 for run in conducted_runs if orchestrator._is_trace_complete(run))
    event_counts = analytics["event_counts"]
    criteria = [
        orchestrator._criterion(
            "api_compatibility",
            "OpenAI-compatible API",
            "pass" if event_counts.get("chat_completion_requested", 0) > 0 else "warn",
            f"{event_counts.get('chat_completion_requested', 0)} compatible chat requests recorded",
            "Run a /v1/chat/completions smoke test before an enterprise evaluation.",
        ),
        orchestrator._criterion(
            "admin_evidence",
            "Operator evidence surface",
            "pass" if admin_state["agents"] and admin_state["policy"] else "fail",
            f"{len(admin_state['agents'])} agents, {len(admin_state['recent_audit_events'])} audit events exposed",
            "Expose agent pool, policy, and audit state before positioning the product as sellable.",
        ),
        orchestrator._criterion(
            "trace_evidence",
            "Workflow trace evidence",
            "pass" if trace_complete_count > 0 else "warn",
            f"{trace_complete_count} complete conducted traces across {len(conducted_runs)} conducted runs",
            "Run a conduct-mode workflow so access-list and verifier evidence are visible.",
        ),
        orchestrator._criterion(
            "evaluation_replay",
            "Evaluation replay",
            "pass" if event_counts.get("evaluation_run_created", 0) > 0 else "warn",
            f"{event_counts.get('evaluation_run_created', 0)} evaluation replay runs recorded",
            "Run at least one evaluation replay before customer-facing pilot review.",
        ),
        orchestrator._security_posture_criterion(security_profile or {}),
        orchestrator._criterion(
            "analytics_truthfulness",
            "Analytics truthfulness",
            "pass" if analytics["measurement_status"] == "local_runtime_snapshot" else "fail",
            analytics["source_note"],
            "Label metrics as proposed definitions unless backed by measured runtime telemetry.",
        ),
        orchestrator._locale_readiness_criterion(analytics),
        orchestrator._provider_egress_criterion(),
    ]
    summary = orchestrator._criteria_summary(criteria)
    readiness_summary = {"pass": summary["pass"], "warn": summary["warn"], "fail": summary["fail"]}
    if summary["fail"]:
        readiness_status = "not_ready"
    elif summary["warn"]:
        readiness_status = "pilot_ready_with_warnings"
    else:
        readiness_status = "sales_ready"

    return {
        "readiness_status": readiness_status,
        "measurement_status": "local_runtime_snapshot",
        "source_note": (
            "Sales readiness is based on this process-local runtime, configuration, and "
            "documentation evidence; it is not a production compliance certificate."
        ),
        "summary": readiness_summary,
        "readiness_summary": readiness_summary,
        "criteria": criteria,
    }


def commercial_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a diligence-oriented readiness gate for high-value enterprise sales."""
    sales_readiness = orchestrator.sales_readiness_report(
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    sales_rows = orchestrator._criteria_by_name(sales_readiness["criteria"])
    analytics_guardrails = orchestrator._metrics_by_name(analytics["guardrails"])
    documentation = orchestrator._commercial_documentation_profile()
    security_profile = security_profile or {}
    policy_safe_metric = orchestrator._metrics_by_name(analytics["kpis"])["policy_safe_routing_rate"]
    provider_metric = analytics_guardrails["provider_exclusion_miss_rate"]
    locale_metric = analytics_guardrails["locale_key_parity"]

    criteria = [
        orchestrator._criterion(
            "product_capability_evidence",
            "Product capability evidence",
            "pass" if sales_readiness["readiness_status"] == "sales_ready" else "warn",
            (
                f"sales_readiness={sales_readiness['readiness_status']}; "
                f"{sales_readiness['readiness_summary']['pass']} sales criteria passing"
            ),
            "Resolve all sales-readiness warnings before presenting the product for a high-value diligence review.",
        ),
        orchestrator._criterion(
            "security_and_access_control",
            "Security and access control",
            "pass"
            if sales_rows["security_posture"]["status"] == "pass"
            and sales_rows["provider_egress_safety"]["status"] == "pass"
            else "fail",
            (
                f"{sales_rows['security_posture']['evidence']}; "
                f"{sales_rows['provider_egress_safety']['evidence']}"
            ),
            "Keep split admin/inference tokens, private bind defaults, hidden traces, and safe provider egress.",
        ),
        orchestrator._criterion(
            "operational_resilience",
            "Operational resilience",
            "pass"
            if int(security_profile.get("rate_limit_requests") or 0) > 0
            and int(security_profile.get("max_concurrent_runs") or 0) > 0
            and policy_safe_metric.get("value_percent") == 100.0
            else "warn",
            (
                f"rate_limit_requests={security_profile.get('rate_limit_requests')}; "
                f"max_concurrent_runs={security_profile.get('max_concurrent_runs')}; "
                f"policy_safe_routing_rate={policy_safe_metric.get('value_percent')}%"
            ),
            "Publish production SLOs, backup policy, and incident runbooks before a production sale.",
        ),
        orchestrator._criterion(
            "audit_and_compliance_evidence",
            "Audit and compliance evidence",
            "pass"
            if sales_rows["trace_evidence"]["status"] == "pass"
            and provider_metric.get("value") == 0
            else "warn",
            (
                f"{sales_rows['trace_evidence']['evidence']}; "
                f"provider_exclusion_misses={provider_metric.get('value')}"
            ),
            "Capture customer-specific access reports and compliance exceptions during paid pilot onboarding.",
        ),
        orchestrator._criterion(
            "buyer_due_diligence_packet",
            "Buyer due-diligence packet",
            "pass" if not documentation["missing_documents"] else "warn",
            (
                f"{documentation['present_count']}/{documentation['required_count']} required documents present; "
                f"missing={', '.join(documentation['missing_documents']) or 'none'}"
            ),
            "Complete README, security, API, analytics, product, and commercial readiness documents.",
        ),
        orchestrator._criterion(
            "support_and_localization",
            "Support and localization",
            "pass" if locale_metric.get("value_percent") == 100.0 and documentation["has_security_policy"] else "warn",
            (
                f"locale_key_parity={locale_metric.get('value_percent')}%; "
                f"security_policy={documentation['has_security_policy']}"
            ),
            "Keep Korean and English operator copy aligned and publish support ownership for customer operations.",
        ),
        orchestrator._criterion(
            "commercial_value_case",
            "Commercial value case",
            "pass" if target_contract_value_krw >= DEFAULT_COMMERCIAL_TARGET_VALUE_KRW else "warn",
            (
                f"target_contract_value_krw={target_contract_value_krw:,}; "
                "value case uses compatibility API, evidence control plane, replay, and audit controls"
            ),
            "Anchor high-value sales review at KRW 2,000,000,000 or higher with buyer-specific ROI evidence.",
        ),
    ]
    summary = orchestrator._criteria_summary(criteria)
    commercial_summary = {"pass": summary["pass"], "warn": summary["warn"], "fail": summary["fail"]}
    if commercial_summary["fail"]:
        commercial_status = "not_commercial_ready"
    elif commercial_summary["warn"]:
        commercial_status = "commercial_ready_with_warnings"
    else:
        commercial_status = "commercial_ready"

    return {
        "commercial_status": commercial_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_due_diligence_snapshot",
        "source_note": (
            "Commercial readiness is based on process-local runtime, repository documentation, "
            "security configuration, and analytics evidence; it is not a valuation guarantee, "
            "purchase commitment, or production compliance certificate."
        ),
        "summary": commercial_summary,
        "commercial_summary": commercial_summary,
        "criteria": criteria,
        "documentation": documentation,
        "sales_readiness": sales_readiness,
    }


def commercial_evidence_manifest_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the evidence index for commercial readiness review."""
    commercial = orchestrator.commercial_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    commercial_rows = orchestrator._criteria_by_name(commercial["criteria"])
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    items = [
        orchestrator._buyer_evidence_item(
            "product_scope",
            "Product scope",
            "Economic buyer",
            ["README.md", "docs/product_planning.md", "docs/commercial_readiness.md"],
            "repository_artifact",
            "ready" if all(has_file(path) for path in ("README.md", "docs/product_planning.md", "docs/commercial_readiness.md")) else "blocked",
            "Single enterprise orchestration control plane is documented.",
            "Keep product scope unified for buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "compatible_inference_api",
            "Compatible inference API",
            "Platform reviewer",
            ["/v1/chat/completions", "docs/rest_api_design.md", "tests/test_api_contract.py"],
            "repository_artifact",
            "ready" if has_file("docs/rest_api_design.md") and has_file("tests/test_api_contract.py") else "blocked",
            "OpenAI-compatible endpoint and API contract tests are present.",
            "Restore API contract docs and tests before buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "admin_evidence_control_plane",
            "Admin evidence control plane",
            "Platform operator",
            ["/admin", "/admin/state", "docs/screen_design.md"],
            "repository_artifact",
            "ready" if has_file("docs/screen_design.md") else "blocked",
            "Admin screen design and runtime state endpoint are present.",
            "Restore admin evidence design before buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "sales_readiness",
            "Sales readiness",
            "Product owner",
            ["/api/v1/sales_readiness/latest", "tests/test_sales_readiness.py"],
            "measured_local",
            "ready" if commercial["sales_readiness"]["readiness_summary"]["fail"] == 0 else "blocked",
            f"sales_readiness={commercial['sales_readiness']['readiness_status']}",
            "Resolve sales-readiness failures before commercial review.",
        ),
        orchestrator._buyer_evidence_item(
            "commercial_readiness",
            "Commercial readiness",
            "Economic buyer",
            ["/api/v1/commercial_readiness/latest", "tests/test_commercial_readiness.py"],
            "measured_local",
            "ready" if commercial["commercial_summary"]["fail"] == 0 else "blocked",
            f"commercial_status={commercial['commercial_status']}",
            "Resolve commercial-readiness failures before buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "analytics_honesty",
            "Analytics honesty",
            "Analytics reviewer",
            ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
            "measured_local",
            "ready" if analytics["measurement_status"] == "local_runtime_snapshot" else "blocked",
            analytics["source_note"],
            "Keep measured local evidence separate from production KPI proposals.",
        ),
        orchestrator._buyer_evidence_item(
            "access_list_evidence",
            "Access-list evidence",
            "Security and compliance reviewer",
            ["/api/v1/access_reports/{workflow_run_id}", "docs/product_planning.md"],
            "repository_artifact",
            "ready" if has_file("docs/product_planning.md") else "blocked",
            "Workflow trace and access-report evidence are documented.",
            "Restore access-list evidence docs before compliance review.",
        ),
        orchestrator._buyer_evidence_item(
            "evaluation_replay",
            "Evaluation replay",
            "Quality reviewer",
            ["/api/v1/evaluation_runs", "docs/screen_design.md"],
            "repository_artifact",
            "ready" if has_file("docs/screen_design.md") else "blocked",
            "Evaluation replay surface is documented.",
            "Restore evaluation replay docs before quality review.",
        ),
        orchestrator._buyer_evidence_item(
            "security_posture",
            "Security posture",
            "Security reviewer",
            ["SECURITY.md", "tests/test_security_hardening.py", "CodeQL", "Dependency review", "Trivy"],
            "measured_local",
            "ready" if commercial_rows["security_and_access_control"]["status"] == "pass" else "blocked",
            commercial_rows["security_and_access_control"]["evidence"],
            "Resolve concrete security failures before buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "visual_stakeholder_evidence",
            "Visual stakeholder evidence",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable Figma, FigJam, and Slides artifacts are recorded.",
            "Record editable Figma artifacts before stakeholder review.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_diligence_packet",
            "Buyer diligence packet",
            "Procurement reviewer",
            ["docs/commercial_buyer_diligence_packet.md"],
            "repository_artifact",
            "ready" if has_file("docs/commercial_buyer_diligence_packet.md") else "blocked",
            "Buyer questions map to evidence paths and caveats.",
            "Restore the buyer diligence packet before procurement review.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_acceptance_runbook",
            "Buyer acceptance runbook",
            "Procurement reviewer",
            ["docs/commercial_buyer_acceptance_runbook.md"],
            "repository_artifact",
            "ready" if has_file("docs/commercial_buyer_acceptance_runbook.md") else "blocked",
            "Go, warning, and no-go rules are documented.",
            "Restore acceptance runbook before procurement review.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_evidence_manifest",
            "Buyer evidence manifest",
            "Deal owner",
            ["docs/commercial_buyer_evidence_manifest.md", "/api/v1/commercial_evidence_manifests/latest"],
            "measured_local",
            "ready" if has_file("docs/commercial_buyer_evidence_manifest.md") else "blocked",
            "Buyer evidence is indexed by owner, source, evidence type, and completion state.",
            "Restore the manifest document and endpoint before buyer review.",
        ),
        orchestrator._buyer_evidence_item(
            "packaging_decision",
            "Packaging decision",
            "Procurement and security reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            "Single repo and one deployable product remain the current decision.",
            "Document extraction triggers before changing package boundaries.",
        ),
        orchestrator._buyer_evidence_item(
            "production_slo_support",
            "Production SLO and support proof",
            "Customer operations reviewer",
            ["production telemetry", "incident drill records", "support ownership"],
            "proposed_until_production",
            "warning",
            "Production SLO, incident, and support evidence require a deployed customer environment.",
            "Collect production telemetry during paid onboarding.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_specific_roi_legal",
            "Buyer-specific ROI and legal proof",
            "Economic buyer and procurement",
            ["ROI model", "legal questionnaire", "data-processing terms", "support plan"],
            "proposed_until_buyer_specific",
            "warning",
            "ROI, legal, procurement, and deployment evidence require a named buyer.",
            "Collect buyer-specific inputs during account diligence.",
        ),
    ]
    summary = orchestrator._buyer_manifest_summary(items)
    if summary["by_completion_state"].get("blocked", 0):
        manifest_status = "buyer_review_blocked"
    elif summary["by_completion_state"].get("warning", 0):
        manifest_status = "buyer_review_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        manifest_status = "buyer_review_ready"  # pragma: no cover

    return {
        "manifest_status": manifest_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_buyer_evidence_manifest",
        "source_note": (
            "Buyer evidence manifest combines process-local runtime reports, repository documents, "
            "Figma artifact records, and explicit production or buyer-specific caveats; it is not a "
            "valuation guarantee, purchase commitment, or production compliance certificate."
        ),
        "summary": summary,
        "items": items,
        "related_runtime_reports": {
            "commercial_status": commercial["commercial_status"],
            "sales_readiness_status": commercial["sales_readiness"]["readiness_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
    }


def commercial_handoff_bundle_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the commercial handoff bundle for sale-readiness evidence."""
    manifest = orchestrator.commercial_evidence_manifest_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    manifest_summary = manifest["summary"]["by_completion_state"]
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    runtime_state = "blocked" if manifest_summary.get("blocked", 0) else "ready"
    included_artifacts = [
        orchestrator._buyer_evidence_item(
            "runtime_reports",
            "Runtime reports",
            "Deal owner",
            [
                "/api/v1/sales_readiness/latest",
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_evidence_manifests/latest",
                "/api/v1/analytics_snapshots/latest",
            ],
            "measured_local",
            runtime_state,
            (
                f"buyer_manifest_status={manifest['manifest_status']}; "
                f"commercial_status={manifest['related_runtime_reports']['commercial_status']}"
            ),
            "Resolve runtime report blockers before buyer handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "repository_packet",
            "Repository packet",
            "Procurement reviewer",
            [
                "README.md",
                "docs/commercial_buyer_diligence_packet.md",
                "docs/commercial_buyer_acceptance_runbook.md",
                "docs/commercial_buyer_evidence_manifest.md",
                "docs/commercial_buyer_handoff_bundle.md",
            ],
            "repository_artifact",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                )
            )
            else "blocked",
            "Buyer-facing diligence, acceptance, manifest, and handoff documents are present.",
            "Restore missing buyer packet documents before procurement review.",
        ),
        orchestrator._buyer_evidence_item(
            "figma_stakeholder_artifacts",
            "Figma stakeholder artifacts",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable Figma, FigJam, and Slides artifacts are recorded without Code Connect.",
            "Record editable stakeholder artifacts before buyer handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "verification_commands",
            "Verification commands",
            "Technical reviewer",
            [
                "tests/test_buyer_handoff_bundle.py",
                "tests/test_buyer_evidence_manifest.py",
                "tests/test_plugin_driven_artifacts.py",
                "tests/test_api_contract.py",
                "pytest -q",
            ],
            "measured_local",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "tests/test_buyer_handoff_bundle.py",
                    "tests/test_buyer_evidence_manifest.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                )
            )
            else "blocked",
            "Focused contract tests and full pytest verification are named for buyer review.",
            "Restore focused tests before technical buyer handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "packaging_decision",
            "Packaging decision",
            "Procurement and security reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            "Single repository and one deployable product remain the current decision.",
            "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
        ),
    ]
    follow_up_items = [
        orchestrator._buyer_evidence_item(
            "production_handoff_readiness",
            "Production handoff readiness",
            "Customer operations reviewer",
            ["production SLO", "incident drill", "support rota", "deployment history"],
            "proposed_until_production",
            "warning",
            "Production SLO, incident, deployment, and support evidence require a live customer environment.",
            "Collect production telemetry and support evidence during paid onboarding.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_specific_commercial_close",
            "Buyer-specific commercial close",
            "Economic buyer and legal reviewer",
            ["ROI model", "legal questionnaire", "data-processing terms", "support plan"],
            "proposed_until_buyer_specific",
            "warning",
            "ROI, legal, procurement, and deployment commitments require a named buyer.",
            "Collect buyer-specific inputs during account diligence.",
        ),
    ]
    all_items = included_artifacts + follow_up_items
    summary = orchestrator._buyer_manifest_summary(all_items)
    if summary["by_completion_state"].get("blocked", 0):
        bundle_status = "buyer_handoff_blocked"
    elif summary["by_completion_state"].get("warning", 0):
        bundle_status = "buyer_handoff_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        bundle_status = "buyer_handoff_ready"  # pragma: no cover

    return {
        "bundle_status": bundle_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_buyer_handoff_bundle",
        "source_note": (
            "Buyer handoff bundle packages local runtime reports, repository documents, "
            "Figma artifact records, verification commands, and explicit production or "
            "buyer-specific caveats; it is not a valuation guarantee, purchase commitment, "
            "or production compliance certificate."
        ),
        "summary": summary,
        "included_artifacts": included_artifacts,
        "follow_up_items": follow_up_items,
        "acceptance_gates": [
            {
                "gate_name": "go",
                "rule": "no blocked included artifacts and concrete security checks have no failure",
            },
            {
                "gate_name": "warning",
                "rule": "production or buyer-specific evidence remains proposed and explicitly caveated",
            },
            {
                "gate_name": "blocked",
                "rule": "security failure, API contract regression, document mismatch, product defect, or Code Connect usage",
            },
        ],
        "related_runtime_reports": {
            "buyer_manifest_status": manifest["manifest_status"],
            **manifest["related_runtime_reports"],
        },
        "library_split_decision": {
            "decision": "keep_single_product",
            "reason": "No second product, independent release cadence, or security provenance trigger exists.",
            "allowed_future_triggers": [
                "second product requires core only",
                "independent release cadence is needed",
                "buyer security provenance requires package extraction",
            ],
        },
        "plugin_traceability": {
            "figma": "editable stakeholder artifacts and FigJam workflow",
            "product_design": "buyer handoff surface and admin evidence workflow",
            "superpowers": "implementation plan and verification checklist",
            "ponytail": "single-product packaging and no new dependency",
            "data_analytics": "measured versus proposed evidence separation",
        },
    }


def buyer_evidence_manifest_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the deprecated manifest alias for existing Python consumers."""
    return orchestrator.commercial_evidence_manifest_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )


def buyer_handoff_bundle_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the deprecated handoff alias for existing Python consumers."""
    return orchestrator.commercial_handoff_bundle_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )


def saleability_decision_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the buyer-facing saleability decision for high-value review."""
    handoff = orchestrator.commercial_handoff_bundle_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    # Blockers must be hashable, operator-readable identifiers: downstream
    # readiness reports deduplicate inherited blocker lists via
    # ``dict.fromkeys``, which crashes on unhashable evidence-item dicts.
    concrete_blockers = [
        item["item_name"]
        for item in handoff["included_artifacts"]
        if item["completion_state"] == "blocked"
    ]
    warning_conditions = [
        item
        for item in handoff["follow_up_items"]
        if item["completion_state"] == "warning"
    ]
    if concrete_blockers:
        saleability_status = "saleability_blocked"
        decision_label = "Blocked by concrete defect"
    elif warning_conditions:
        saleability_status = "saleability_ready_with_warnings"
        decision_label = "Ready for buyer diligence with explicit warnings"
    else:  # pragma: no cover - unreachable while handoff follow-up warnings are literal report sections
        saleability_status = "saleability_ready"  # pragma: no cover
        decision_label = "Ready for buyer diligence"  # pragma: no cover

    return {
        "saleability_status": saleability_status,
        "decision_label": decision_label,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_saleability_decision",
        "source_note": (
            "Saleability decision is a local buyer due-diligence gate based on runtime "
            "reports, repository documents, Figma artifacts, verification commands, and "
            "explicit caveats; it is not a valuation guarantee, purchase commitment, "
            "or production compliance certificate."
        ),
        "decision_summary": {
            "included_artifact_count": len(handoff["included_artifacts"]),
            "blocked_count": len(concrete_blockers),
            "warning_count": len(warning_conditions),
            "review_process_is_blocker": False,
        },
        "decision_basis": [
            {
                "basis_name": "buyer_handoff_bundle",
                "status": handoff["bundle_status"],
                "source": "/api/v1/commercial_handoff_bundles/latest",
            },
            {
                "basis_name": "buyer_evidence_manifest",
                "status": handoff["related_runtime_reports"]["buyer_manifest_status"],
                "source": "/api/v1/commercial_evidence_manifests/latest",
            },
            {
                "basis_name": "commercial_readiness",
                "status": handoff["related_runtime_reports"]["commercial_status"],
                "source": "/api/v1/commercial_readiness/latest",
            },
            {
                "basis_name": "sales_readiness",
                "status": handoff["related_runtime_reports"]["sales_readiness_status"],
                "source": "/api/v1/sales_readiness/latest",
            },
        ],
        "concrete_blockers": concrete_blockers,
        "warning_conditions": warning_conditions,
        "review_process_policy": {
            "is_blocker": False,
            "non_blocker_examples": [
                "reviewer delay",
                "review bot delay",
                "queued model review",
                "pending check without concrete failure",
            ],
            "blocker_definition": "concrete security, API contract, document, or product defect",
        },
        "related_runtime_reports": {
            "buyer_handoff_status": handoff["bundle_status"],
            **handoff["related_runtime_reports"],
        },
        "library_split_decision": handoff["library_split_decision"],
        "plugin_traceability": handoff["plugin_traceability"],
    }


def commercial_evidence_export_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a portable buyer due-diligence export index for commercial review."""
    saleability = orchestrator.saleability_decision_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = saleability["concrete_blockers"]
    required_external_evidence = [
        {
            "evidence_name": item["item_name"],
            "label": item["label"],
            "reviewer": item["reviewer"],
            "sources": item["sources"],
            "evidence_type": item["evidence_type"],
            "evidence": item["evidence"],
            "next_action": item["next_action"],
        }
        for item in saleability["warning_conditions"]
    ]
    saleability_state = "blocked" if saleability["saleability_status"] == "saleability_blocked" else "ready"
    export_sections = [
        orchestrator._buyer_evidence_item(
            "saleability_decision",
            "Saleability decision",
            "Deal owner",
            ["/api/v1/saleability_decisions/latest", "docs/commercial_saleability_decision.md"],
            "measured_local",
            saleability_state,
            f"saleability_status={saleability['saleability_status']}",
            "Resolve concrete saleability blockers before exporting buyer evidence.",
        ),
        orchestrator._buyer_evidence_item(
            "runtime_reports",
            "Runtime reports",
            "Technical reviewer",
            [
                "/api/v1/sales_readiness/latest",
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_evidence_manifests/latest",
                "/api/v1/commercial_handoff_bundles/latest",
                "/api/v1/saleability_decisions/latest",
                "/api/v1/analytics_snapshots/latest",
            ],
            "measured_local",
            "blocked" if concrete_blockers else "ready",
            (
                f"buyer_handoff_status={saleability['related_runtime_reports']['buyer_handoff_status']}; "
                f"buyer_manifest_status={saleability['related_runtime_reports']['buyer_manifest_status']}"
            ),
            "Resolve blocked runtime reports before buyer export.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_packet_documents",
            "Buyer packet documents",
            "Procurement reviewer",
            [
                "docs/commercial_buyer_diligence_packet.md",
                "docs/commercial_buyer_acceptance_runbook.md",
                "docs/commercial_buyer_evidence_manifest.md",
                "docs/commercial_buyer_handoff_bundle.md",
                "docs/commercial_saleability_decision.md",
                "docs/commercial_evidence_export.md",
            ],
            "repository_artifact",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                )
            )
            else "blocked",
            "Buyer diligence, acceptance, manifest, handoff, decision, and export documents are present.",
            "Restore missing buyer packet documents before export.",
        ),
        orchestrator._buyer_evidence_item(
            "figma_stakeholder_artifacts",
            "Figma stakeholder artifacts",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
            "Record Figma artifacts before exporting buyer evidence.",
        ),
        orchestrator._buyer_evidence_item(
            "verification_commands",
            "Verification commands",
            "Technical reviewer",
            [
                "tests/test_commercial_evidence_export.py",
                "tests/test_saleability_decision.py",
                "tests/test_plugin_driven_artifacts.py",
                "tests/test_api_contract.py",
                "pytest -q",
            ],
            "measured_local",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "tests/test_commercial_evidence_export.py",
                    "tests/test_saleability_decision.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                )
            )
            else "blocked",
            "Focused commercial export, saleability, plugin artifact, and API contract tests are named.",
            "Restore focused tests before buyer export.",
        ),
        orchestrator._buyer_evidence_item(
            "review_process_policy",
            "Review process policy",
            "Deal owner",
            ["docs/commercial_saleability_decision.md", "/api/v1/saleability_decisions/latest"],
            "repository_artifact",
            "ready",
            "Reviewer delay, review bot delay, and queued model review are not concrete blockers.",
            "Escalate only concrete security, API contract, document, or product defects.",
        ),
        orchestrator._buyer_evidence_item(
            "packaging_decision",
            "Packaging decision",
            "Procurement and security reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            saleability["library_split_decision"]["reason"],
            "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
        ),
    ]
    export_section_summary = orchestrator._buyer_manifest_summary(export_sections)
    blocked_count = export_section_summary["by_completion_state"]["blocked"] + len(concrete_blockers)
    warning_count = len(required_external_evidence)
    if blocked_count:
        export_status = "commercial_export_blocked"
    elif warning_count:
        export_status = "commercial_export_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        export_status = "commercial_export_ready"  # pragma: no cover

    return {
        "export_status": export_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_evidence_export",
        "source_note": (
            "Commercial evidence export packages local runtime decisions, repository documents, "
            "Figma artifact records, verification commands, review-process policy, packaging decision, "
            "and explicit production or buyer-specific evidence gaps; it is not a valuation guarantee, "
            "purchase commitment, or production compliance certificate."
        ),
        "export_summary": {
            "section_count": len(export_sections),
            "blocked_count": blocked_count,
            "warning_count": warning_count,
            "review_process_is_blocker": saleability["review_process_policy"]["is_blocker"],
        },
        "export_sections": export_sections,
        "required_external_evidence": required_external_evidence,
        "concrete_blockers": concrete_blockers,
        "review_process_policy": saleability["review_process_policy"],
        "related_runtime_reports": {
            "saleability_status": saleability["saleability_status"],
            **saleability["related_runtime_reports"],
        },
        "library_split_decision": saleability["library_split_decision"],
        "plugin_traceability": saleability["plugin_traceability"],
        "export_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_evidence_exports/latest",
            "documentation": "docs/commercial_evidence_export.md",
        },
    }


def commercial_acceptance_check_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the buyer acceptance check over the commercial evidence export."""
    evidence_export = orchestrator.commercial_evidence_export_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = evidence_export["concrete_blockers"]
    export_blocked = evidence_export["export_status"] == "commercial_export_blocked"
    runtime_state = "blocked" if export_blocked or concrete_blockers else "ready"
    acceptance_items = [
        orchestrator._buyer_evidence_item(
            "runtime_endpoint_chain",
            "Runtime endpoint chain",
            "Technical reviewer",
            [
                "/api/v1/analytics_snapshots/latest",
                "/api/v1/sales_readiness/latest",
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_evidence_manifests/latest",
                "/api/v1/commercial_handoff_bundles/latest",
                "/api/v1/saleability_decisions/latest",
                "/api/v1/commercial_evidence_exports/latest",
            ],
            "measured_local",
            runtime_state,
            f"commercial_export_status={evidence_export['export_status']}",
            "Resolve blocked runtime report chain before buyer acceptance.",
        ),
        orchestrator._buyer_evidence_item(
            "buyer_packet_documents",
            "Buyer packet documents",
            "Procurement reviewer",
            [
                "docs/commercial_buyer_diligence_packet.md",
                "docs/commercial_buyer_acceptance_runbook.md",
                "docs/commercial_buyer_evidence_manifest.md",
                "docs/commercial_buyer_handoff_bundle.md",
                "docs/commercial_saleability_decision.md",
                "docs/commercial_evidence_export.md",
                "docs/commercial_acceptance_check.md",
            ],
            "repository_artifact",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_acceptance_check.md",
                )
            )
            else "blocked",
            "Buyer packet documents cover diligence, acceptance, manifest, handoff, decision, export, and check.",
            "Restore missing buyer packet documents before buyer acceptance.",
        ),
        orchestrator._buyer_evidence_item(
            "admin_operator_surface",
            "Admin operator surface",
            "Platform operator",
            ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_acceptance_checks/latest"],
            "repository_artifact",
            "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
            "Admin observability surface exposes the commercial acceptance check status with bilingual labels.",
            "Expose acceptance check status in admin observability before buyer acceptance.",
        ),
        orchestrator._buyer_evidence_item(
            "verification_evidence",
            "Verification evidence",
            "Technical reviewer",
            [
                "tests/test_commercial_acceptance_check.py",
                "tests/test_commercial_evidence_export.py",
                "tests/test_saleability_decision.py",
                "tests/test_plugin_driven_artifacts.py",
                "tests/test_api_contract.py",
                "pytest -q",
            ],
            "measured_local",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_evidence_export.py",
                    "tests/test_saleability_decision.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                )
            )
            else "blocked",
            "Focused commercial acceptance, export, saleability, plugin artifact, and API contract tests are named.",
            "Restore focused tests before buyer acceptance.",
        ),
        orchestrator._buyer_evidence_item(
            "figma_stakeholder_artifacts",
            "Figma stakeholder artifacts",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
            "Record editable Figma artifacts before buyer acceptance.",
        ),
        orchestrator._buyer_evidence_item(
            "review_process_policy",
            "Review process policy",
            "Deal owner",
            ["docs/commercial_saleability_decision.md", "/api/v1/saleability_decisions/latest"],
            "repository_artifact",
            "ready",
            "Reviewer delay, review bot delay, queued model review, and pending checks without concrete failure are not blockers.",
            "Block only on concrete security, API contract, document, or product defects.",
        ),
        orchestrator._buyer_evidence_item(
            "packaging_decision",
            "Packaging decision",
            "Procurement and security reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            evidence_export["library_split_decision"]["reason"],
            "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
        ),
    ]
    follow_up_items = [
        orchestrator._buyer_evidence_item(
            item["evidence_name"],
            item["label"],
            item["reviewer"],
            item["sources"],
            item["evidence_type"],
            "warning",
            item["evidence"],
            item["next_action"],
        )
        for item in evidence_export["required_external_evidence"]
    ]
    all_items = acceptance_items + follow_up_items
    summary = orchestrator._buyer_manifest_summary(all_items)
    blocked_count = summary["by_completion_state"]["blocked"] + len(concrete_blockers)
    warning_count = summary["by_completion_state"]["warning"]
    if blocked_count:
        acceptance_status = "commercial_acceptance_blocked"
    elif warning_count:
        acceptance_status = "commercial_acceptance_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        acceptance_status = "commercial_acceptance_ready"  # pragma: no cover

    return {
        "acceptance_status": acceptance_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_acceptance_check",
        "source_note": (
            "Commercial acceptance check evaluates local commercial evidence export, admin visibility, "
            "repository packet, Figma artifacts, verification commands, review-process policy, packaging "
            "decision, and explicit production or buyer-specific gaps; it is not a valuation guarantee, "
            "purchase commitment, or production compliance certificate."
        ),
        "acceptance_summary": {
            "item_count": len(all_items),
            "blocked_count": blocked_count,
            "warning_count": warning_count,
            "review_process_is_blocker": evidence_export["review_process_policy"]["is_blocker"],
        },
        "acceptance_items": acceptance_items,
        "follow_up_items": follow_up_items,
        "concrete_blockers": concrete_blockers,
        "required_external_evidence": evidence_export["required_external_evidence"],
        "acceptance_gates": [
            {
                "gate_name": "go",
                "rule": "no blocked acceptance items and no required external evidence gaps",
            },
            {
                "gate_name": "warning",
                "rule": "only production or buyer-specific evidence remains explicitly caveated",
            },
            {
                "gate_name": "blocked",
                "rule": "security failure, API contract regression, document mismatch, product defect, or Code Connect usage",
            },
        ],
        "review_process_policy": evidence_export["review_process_policy"],
        "related_runtime_reports": {
            "commercial_export_status": evidence_export["export_status"],
            **evidence_export["related_runtime_reports"],
        },
        "library_split_decision": evidence_export["library_split_decision"],
        "plugin_traceability": evidence_export["plugin_traceability"],
        "acceptance_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_acceptance_checks/latest",
            "documentation": "docs/commercial_acceptance_check.md",
        },
    }


def commercial_release_candidate_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return product evidence separately from protected release authority."""
    acceptance = orchestrator.commercial_acceptance_check_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = acceptance["concrete_blockers"]
    acceptance_blocked = acceptance["acceptance_status"] == "commercial_acceptance_blocked"
    runtime_state = "blocked" if acceptance_blocked or concrete_blockers else "ready"
    release_authorization = evaluate_release_authorization(release_authority)
    release_artifacts = [
        orchestrator._buyer_evidence_item(
            "commercial_acceptance_check",
            "Commercial acceptance check",
            "Deal owner",
            ["/api/v1/commercial_acceptance_checks/latest", "docs/commercial_acceptance_check.md"],
            "measured_local",
            runtime_state,
            f"acceptance_status={acceptance['acceptance_status']}",
            "Resolve blocked acceptance checks before tagging a release candidate.",
        ),
        orchestrator._buyer_evidence_item(
            "runtime_endpoint_chain",
            "Runtime endpoint chain",
            "Technical reviewer",
            [
                "/api/v1/analytics_snapshots/latest",
                "/api/v1/sales_readiness/latest",
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_evidence_manifests/latest",
                "/api/v1/commercial_handoff_bundles/latest",
                "/api/v1/saleability_decisions/latest",
                "/api/v1/commercial_evidence_exports/latest",
                "/api/v1/commercial_acceptance_checks/latest",
                "/api/v1/commercial_release_candidates/latest",
            ],
            "measured_local",
            runtime_state,
            "Commercial release candidate endpoint is chained after acceptance, export, decision, handoff, manifest, readiness, and analytics reports.",
            "Restore blocked runtime endpoint evidence before release-candidate handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "repository_distribution_packet",
            "Repository distribution packet",
            "Procurement reviewer",
            [
                "README.md",
                "docs/rest_api_design.md",
                "docs/commercial_buyer_diligence_packet.md",
                "docs/commercial_buyer_acceptance_runbook.md",
                "docs/commercial_buyer_evidence_manifest.md",
                "docs/commercial_buyer_handoff_bundle.md",
                "docs/commercial_saleability_decision.md",
                "docs/commercial_evidence_export.md",
                "docs/commercial_acceptance_check.md",
                "docs/commercial_release_candidate.md",
            ],
            "repository_artifact",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/rest_api_design.md",
                    "docs/commercial_buyer_diligence_packet.md",
                    "docs/commercial_buyer_acceptance_runbook.md",
                    "docs/commercial_buyer_evidence_manifest.md",
                    "docs/commercial_buyer_handoff_bundle.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_evidence_export.md",
                    "docs/commercial_acceptance_check.md",
                    "docs/commercial_release_candidate.md",
                )
            )
            else "blocked",
            "Repository packet contains the README, REST API contract notes, and commercial buyer documents.",
            "Restore missing distribution documents before buyer release-candidate review.",
        ),
        orchestrator._buyer_evidence_item(
            "security_package_metadata",
            "Security and package metadata",
            "Security reviewer",
            [
                "LICENSE",
                "SECURITY.md",
                "pyproject.toml",
                "requirements.lock",
                ".github/workflows/security.yml",
                ".github/dependabot.yml",
                "ContextualWisdomLab/.github central required security workflows",
            ],
            "repository_artifact",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "LICENSE",
                    "SECURITY.md",
                    "pyproject.toml",
                    "requirements.lock",
                    ".github/workflows/security.yml",
                    ".github/dependabot.yml",
                )
            )
            else "blocked",
            "License, security policy, package metadata, locked requirements, local supply-chain workflow, Dependabot metadata, and central required security workflows are present.",
            "Restore missing security or package metadata before release-candidate handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "admin_operator_surface",
            "Admin operator surface",
            "Platform operator",
            ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_release_candidates/latest"],
            "repository_artifact",
            "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
            "Admin observability surface exposes the release-candidate status with bilingual labels.",
            "Expose release-candidate status in admin observability before buyer handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "verification_evidence",
            "Verification evidence",
            "Technical reviewer",
            [
                "tests/test_commercial_release_candidate.py",
                "tests/test_commercial_acceptance_check.py",
                "tests/test_commercial_evidence_export.py",
                "tests/test_saleability_decision.py",
                "tests/test_plugin_driven_artifacts.py",
                "tests/test_api_contract.py",
                "pytest -q",
            ],
            "measured_local",
            "ready"
            if all(
                has_file(path)
                for path in (
                    "tests/test_commercial_release_candidate.py",
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_evidence_export.py",
                    "tests/test_saleability_decision.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                )
            )
            else "blocked",
            "Focused release-candidate, acceptance, export, saleability, plugin artifact, and API contract tests are named.",
            "Restore focused verification before release-candidate handoff.",
        ),
        orchestrator._buyer_evidence_item(
            "figma_stakeholder_artifacts",
            "Figma stakeholder artifacts",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable stakeholder artifacts are recorded and Code Connect is excluded.",
            "Record editable Figma artifacts before buyer release-candidate review.",
        ),
        orchestrator._buyer_evidence_item(
            "review_process_policy",
            "Review process policy",
            "Deal owner",
            ["docs/commercial_saleability_decision.md", "docs/commercial_release_candidate.md"],
            "repository_artifact",
            "ready",
            "Product evidence remains inspectable while protected release authority is evaluated separately.",
            "Supply a fresh protected-main authority snapshot before authorizing release.",
        ),
        orchestrator._buyer_evidence_item(
            "release_authority_collector",
            "Protected-head authority collector",
            "Release owner",
            ["scripts/ci/release_authority_snapshot.py", "docs/doctoring/release-authorization.md"],
            "repository_artifact",
            "ready" if has_file("scripts/ci/release_authority_snapshot.py") else "blocked",
            "Read-only gh API collector binds checks and reviews to the exact pull-request head without emitting secrets.",
            "Run the collector with the exact candidate SHA and attach its JSON snapshot to release review.",
        ),
        orchestrator._buyer_evidence_item(
            "packaging_decision",
            "Packaging decision",
            "Procurement and security reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            acceptance["library_split_decision"]["reason"],
            "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
        ),
    ]
    external_release_gaps = [
        orchestrator._buyer_evidence_item(
            item["item_name"],
            item["label"],
            item["reviewer"],
            item["sources"],
            item["evidence_type"],
            "warning",
            item["evidence"],
            item["next_action"],
        )
        for item in acceptance["follow_up_items"]
    ]
    summary = orchestrator._buyer_manifest_summary(release_artifacts + external_release_gaps)
    product_blocked_count = summary["by_completion_state"]["blocked"] + len(concrete_blockers)
    warning_count = summary["by_completion_state"]["warning"]
    product_evidence_status = (
        "commercial_release_blocked"
        if product_blocked_count
        else "commercial_release_ready_with_warnings"
        if acceptance["follow_up_items"]
        else "commercial_release_ready"
    )
    release_blocked_count = product_blocked_count + len(release_authorization["blockers"])
    if release_blocked_count:
        release_status = "commercial_release_blocked"
    elif warning_count:
        release_status = "commercial_release_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        release_status = "commercial_release_ready"  # pragma: no cover

    return {
        "release_status": release_status,
        "product_evidence_status": product_evidence_status,
        "release_authorization": release_authorization,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_release_candidate",
        "source_note": (
            "Commercial release candidate packages local acceptance, runtime endpoints, repository "
            "distribution documents, security metadata, admin visibility, verification commands, "
            "Figma artifact records, review-process policy, packaging decision, and explicit external "
            "release gaps; it is not a valuation guarantee, purchase commitment, or production "
            "compliance certificate."
        ),
        "release_summary": {
            "artifact_count": len(release_artifacts),
            "blocked_count": release_blocked_count,
            "product_blocked_count": product_blocked_count,
            "warning_count": warning_count,
            "release_authority_blocker_count": len(release_authorization["blockers"]),
        },
        "release_artifacts": release_artifacts,
        "external_release_gaps": external_release_gaps,
        "concrete_blockers": concrete_blockers,
        "release_gates": [
            {
                "gate_name": "package",
                "rule": "runtime endpoint chain, repository packet, security metadata, admin surface, tests, Figma artifacts, review policy, and packaging decision are present",
            },
            {
                "gate_name": "warning",
                "rule": "only production or buyer-specific external evidence remains explicitly caveated",
            },
            {
                "gate_name": "blocked",
                "rule": "security failure, API contract regression, missing distribution artifact, document mismatch, product defect, or Code Connect usage",
            },
        ],
        "review_process_policy": acceptance["review_process_policy"],
        "related_runtime_reports": {
            "commercial_acceptance_status": acceptance["acceptance_status"],
            **acceptance["related_runtime_reports"],
        },
        "library_split_decision": acceptance["library_split_decision"],
        "plugin_traceability": acceptance["plugin_traceability"],
        "release_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_release_candidates/latest",
            "documentation": "docs/commercial_release_candidate.md",
        },
    }


def commercial_gap_register_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an owner/action register for commercial release-candidate gaps."""
    release = orchestrator.commercial_release_candidate_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    concrete_blockers = release["concrete_blockers"]
    release_blocked = release["release_status"] == "commercial_release_blocked"
    gap_items = []
    for item in release["external_release_gaps"]:
        source_type = item["evidence_type"]
        if source_type == "proposed_until_production":
            gap_status = "production_input_required"
            gap_type = "production_evidence_gap"
            owner = "Operations and support owner"
        else:
            gap_status = "buyer_input_required"
            gap_type = "buyer_specific_gap"
            owner = "Buyer and deal owner"
        gap_items.append({
            "gap_name": item["item_name"],
            "label": item["label"],
            "gap_type": gap_type,
            "gap_status": gap_status,
            "owner": owner,
            "reviewer": item["reviewer"],
            "sources": item["sources"],
            "source_evidence_type": source_type,
            "current_evidence": item["evidence"],
            "required_input": item["next_action"],
            "is_blocker": False,
        })

    release_authority_blockers = release["release_authorization"]["blockers"]
    product_blocked_count = release["release_summary"]["product_blocked_count"]
    blocked_count = (
        max(1, product_blocked_count + len(release_authority_blockers))
        if release_blocked
        else len(concrete_blockers)
    )
    if blocked_count:
        gap_register_status = "commercial_gap_register_blocked"
    elif gap_items:
        gap_register_status = "commercial_gap_register_open"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        gap_register_status = "commercial_gap_register_clear"  # pragma: no cover

    production_gap_count = sum(1 for item in gap_items if item["gap_type"] == "production_evidence_gap")
    buyer_specific_gap_count = sum(1 for item in gap_items if item["gap_type"] == "buyer_specific_gap")
    return {
        "gap_register_status": gap_register_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_gap_register",
        "source_note": (
            "Commercial gap register converts local release-candidate warning gaps into owner, action, "
            "source, and required-input rows for buyer due diligence; it is not a valuation guarantee, "
            "purchase commitment, or production compliance certificate."
        ),
        "gap_summary": {
            "total_gap_count": len(gap_items),
            "production_gap_count": production_gap_count,
            "buyer_specific_gap_count": buyer_specific_gap_count,
            "blocked_count": blocked_count,
            "release_authority_blocker_count": len(release_authority_blockers),
        },
        "gap_items": gap_items,
        "concrete_blockers": concrete_blockers,
        "release_authorization": release["release_authorization"],
        "gap_status_rules": [
            {
                "gap_status": "production_input_required",
                "rule": "production deployment, support, SLO, or operational evidence must be supplied before production claim",
            },
            {
                "gap_status": "buyer_input_required",
                "rule": "buyer-specific legal, procurement, ROI, or deployment context must be supplied before buyer-specific claim",
            },
            {
                "gap_status": "blocked",
                "rule": "concrete security, API contract, document, product defect, or Code Connect usage blocks commercial release",
            },
        ],
        "review_process_policy": release["review_process_policy"],
        "related_runtime_reports": {
            "commercial_release_status": release["release_status"],
            "release_authorization_status": release["release_authorization"]["status"],
            **release["related_runtime_reports"],
        },
        "library_split_decision": release["library_split_decision"],
        "plugin_traceability": release["plugin_traceability"],
        "gap_register_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_gap_registers/latest",
            "documentation": "docs/commercial_gap_register.md",
        },
    }


def commercial_procurement_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a procurement/legal readiness gate over commercial evidence."""
    gap_register = orchestrator.commercial_gap_register_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    gap_by_status = {item["gap_status"]: item for item in gap_register["gap_items"]}
    production_gap = gap_by_status.get("production_input_required")
    buyer_gap = gap_by_status.get("buyer_input_required")
    concrete_blockers = gap_register["concrete_blockers"]
    release_authorization = gap_register["release_authorization"]
    release_authority_blockers = release_authorization["blockers"]
    procurement_items = [
        {
            "item_name": "license_and_rights",
            "label": "License and rights",
            "owner": "Procurement reviewer",
            "sources": ["LICENSE", "pyproject.toml"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready" if has_file("LICENSE") and has_file("pyproject.toml") else "blocked",
            "evidence": "MIT license and package metadata are present for buyer rights review.",
            "required_input": "Restore license or package metadata before procurement review.",
        },
        {
            "item_name": "security_package_metadata",
            "label": "Security package metadata",
            "owner": "Security reviewer",
            "sources": [
                "SECURITY.md",
                "requirements.lock",
                ".github/workflows/security.yml",
                ".github/dependabot.yml",
                "ContextualWisdomLab/.github central required security workflows",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "SECURITY.md",
                    "requirements.lock",
                    ".github/workflows/security.yml",
                    ".github/dependabot.yml",
                )
            )
            else "blocked",
            "evidence": "Security policy, locked dependencies, local supply-chain workflow, Dependabot metadata, and central required security workflows are present.",
            "required_input": "Restore missing security metadata before procurement review.",
        },
        {
            "item_name": "distribution_packet",
            "label": "Distribution packet",
            "owner": "Deal owner",
            "sources": [
                "README.md",
                "docs/rest_api_design.md",
                "docs/commercial_release_candidate.md",
                "docs/commercial_gap_register.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/rest_api_design.md",
                    "docs/commercial_release_candidate.md",
                    "docs/commercial_gap_register.md",
                )
            )
            else "blocked",
            "evidence": "Repository overview, REST contract, release candidate, and gap register documents are present.",
            "required_input": "Restore missing distribution documents before procurement review.",
        },
        {
            "item_name": "admin_evidence_surface",
            "label": "Admin evidence surface",
            "owner": "Platform operator",
            "sources": ["/admin", "contextual_orchestrator/admin.py", "/api/v1/commercial_procurement_readiness/latest"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready" if has_file("contextual_orchestrator/admin.py") else "blocked",
            "evidence": "Admin observability surface exposes procurement readiness with bilingual labels.",
            "required_input": "Expose procurement readiness in admin observability before buyer review.",
        },
        {
            "item_name": "production_support_slo_input",
            "label": "Production support and SLO input",
            "owner": production_gap["owner"] if production_gap else "Operations and support owner",
            "sources": production_gap["sources"] if production_gap else ["docs/commercial_gap_register.md"],
            "evidence_type": "proposed_until_production",
            "completion_state": "warning" if production_gap else "ready",
            "source_gap_status": production_gap["gap_status"] if production_gap else "resolved",
            "evidence": production_gap["current_evidence"] if production_gap else "No production evidence gap is open.",
            "required_input": production_gap["required_input"] if production_gap else "No production input required.",
        },
        {
            "item_name": "buyer_legal_roi_procurement_input",
            "label": "Buyer legal, ROI, and procurement input",
            "owner": buyer_gap["owner"] if buyer_gap else "Buyer and deal owner",
            "sources": buyer_gap["sources"] if buyer_gap else ["docs/commercial_gap_register.md"],
            "evidence_type": "proposed_until_buyer_specific",
            "completion_state": "warning" if buyer_gap else "ready",
            "source_gap_status": buyer_gap["gap_status"] if buyer_gap else "resolved",
            "evidence": buyer_gap["current_evidence"] if buyer_gap else "No buyer-specific evidence gap is open.",
            "required_input": buyer_gap["required_input"] if buyer_gap else "No buyer input required.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_procurement_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Reviewer delay, review bot delay, queued model review, and pending checks without concrete failure are not blockers.",
            "required_input": "Block only on concrete security, API contract, document, or product defects.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": "Procurement and security reviewer",
            "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready" if has_file("docs/library_research.md") and has_file("docs/commercial_plugin_operating_model.md") else "blocked",
            "evidence": gap_register["library_split_decision"]["reason"],
            "required_input": "Only extract a library after a second product, independent release cadence, or provenance trigger exists.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in procurement_items)
    production_gap_count = 1 if production_gap else 0
    buyer_specific_gap_count = 1 if buyer_gap else 0
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        procurement_status = "commercial_procurement_blocked"
    elif warning_count:
        procurement_status = "commercial_procurement_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        procurement_status = "commercial_procurement_ready"  # pragma: no cover

    return {
        "procurement_status": procurement_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_procurement_readiness",
        "source_note": (
            "Commercial procurement readiness packages local license, security, distribution, admin, "
            "gap-register, review-process, and packaging evidence for buyer due diligence; it is not "
            "a valuation guarantee, purchase commitment, or production compliance certificate."
        ),
        "procurement_summary": {
            "item_count": len(procurement_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "production_gap_count": production_gap_count,
            "buyer_specific_gap_count": buyer_specific_gap_count,
            "review_process_is_blocker": gap_register["review_process_policy"]["is_blocker"],
            "release_authority_blocker_count": len(release_authority_blockers),
        },
        "procurement_items": procurement_items,
        "concrete_blockers": concrete_blockers,
        "release_authorization": release_authorization,
        "procurement_status_rules": [
            {
                "procurement_status": "commercial_procurement_ready",
                "rule": "license, security, distribution, admin, support, legal, ROI, review, and packaging evidence are ready",
            },
            {
                "procurement_status": "commercial_procurement_ready_with_warnings",
                "rule": "local packet is ready while production or buyer-specific inputs remain explicit warnings",
            },
            {
                "procurement_status": "commercial_procurement_blocked",
                "rule": "missing packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks procurement",
            },
        ],
        "review_process_policy": gap_register["review_process_policy"],
        "related_runtime_reports": {
            "commercial_gap_register_status": gap_register["gap_register_status"],
            **gap_register["related_runtime_reports"],
        },
        "library_split_decision": gap_register["library_split_decision"],
        "plugin_traceability": gap_register["plugin_traceability"],
        "procurement_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_procurement_readiness/latest",
            "documentation": "docs/commercial_procurement_readiness.md",
        },
    }


def commercial_contract_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a contract-readiness gate over procurement evidence."""
    procurement = orchestrator.commercial_procurement_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    procurement_by_name = {item["item_name"]: item for item in procurement["procurement_items"]}
    license_item = procurement_by_name["license_and_rights"]
    security_item = procurement_by_name["security_package_metadata"]
    support_item = procurement_by_name["production_support_slo_input"]
    buyer_item = procurement_by_name["buyer_legal_roi_procurement_input"]
    packaging_item = procurement_by_name["packaging_decision"]
    concrete_blockers = procurement["concrete_blockers"]
    release_authorization = procurement["release_authorization"]
    release_authority_blockers = release_authorization["blockers"]
    support_slo_gap_count = 1 if support_item["completion_state"] == "warning" else 0
    buyer_order_form_gap_count = 1 if buyer_item["completion_state"] == "warning" else 0
    contract_items = [
        {
            "item_name": "license_commercial_rights",
            "label": "License and commercial rights terms",
            "owner": "Legal reviewer",
            "sources": license_item["sources"],
            "evidence_type": license_item["evidence_type"],
            "completion_state": license_item["completion_state"],
            "evidence": license_item["evidence"],
            "required_input": license_item["required_input"],
        },
        {
            "item_name": "security_privacy_terms",
            "label": "Security and privacy terms",
            "owner": "Security and legal reviewer",
            "sources": [*security_item["sources"], "docs/commercial_procurement_readiness.md"],
            "evidence_type": security_item["evidence_type"],
            "completion_state": security_item["completion_state"],
            "evidence": (
                f"{security_item['evidence']} Runtime readiness profile uses "
                f"auth_mode={security_profile.get('auth_mode', 'unknown') if security_profile else 'unknown'}, "
                f"public_bind={security_profile.get('allow_public_bind', 'unknown') if security_profile else 'unknown'}, "
                "and trace exposure controls."
            ),
            "required_input": security_item["required_input"],
        },
        {
            "item_name": "audit_export_obligations",
            "label": "Audit and export obligations",
            "owner": "Compliance reviewer",
            "sources": [
                "/api/v1/commercial_evidence_exports/latest",
                "docs/commercial_evidence_export.md",
                "docs/rest_api_design.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "docs/commercial_evidence_export.md",
                    "docs/rest_api_design.md",
                )
            )
            else "blocked",
            "evidence": "Commercial evidence export and REST API contract describe buyer-readable audit evidence.",
            "required_input": "Restore evidence export docs and REST contract before contract review.",
        },
        {
            "item_name": "contract_packet_docs",
            "label": "Contract packet documents",
            "owner": "Deal owner",
            "sources": [
                "README.md",
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_saleability_decision.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/commercial_contract_readiness.md",
                    "docs/commercial_procurement_readiness.md",
                    "docs/commercial_saleability_decision.md",
                )
            )
            else "blocked",
            "evidence": "Contract packet, procurement gate, and saleability blocker policy are documented.",
            "required_input": "Restore buyer contract packet docs before legal review.",
        },
        {
            "item_name": "support_slo_terms",
            "label": "Support and SLO terms",
            "owner": support_item["owner"],
            "sources": support_item["sources"],
            "evidence_type": support_item["evidence_type"],
            "completion_state": support_item["completion_state"],
            "source_gap_status": support_item.get("source_gap_status", "resolved"),
            "evidence": support_item["evidence"],
            "required_input": support_item["required_input"],
        },
        {
            "item_name": "buyer_order_form_input",
            "label": "Buyer order-form input",
            "owner": buyer_item["owner"],
            "sources": buyer_item["sources"],
            "evidence_type": buyer_item["evidence_type"],
            "completion_state": buyer_item["completion_state"],
            "source_gap_status": buyer_item.get("source_gap_status", "resolved"),
            "evidence": buyer_item["evidence"],
            "required_input": buyer_item["required_input"],
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_contract_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review process delay is not a contract blocker unless a concrete failure is produced.",
            "required_input": "Block only on concrete security, API contract, document, or product defects.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": packaging_item["owner"],
            "sources": packaging_item["sources"],
            "evidence_type": packaging_item["evidence_type"],
            "completion_state": packaging_item["completion_state"],
            "evidence": packaging_item["evidence"],
            "required_input": packaging_item["required_input"],
        },
    ]
    state_counts = Counter(item["completion_state"] for item in contract_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        contract_status = "commercial_contract_blocked"
    elif warning_count:
        contract_status = "commercial_contract_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        contract_status = "commercial_contract_ready"  # pragma: no cover

    return {
        "contract_status": contract_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_contract_readiness",
        "source_note": (
            "Commercial contract readiness packages local license, security/privacy, audit export, "
            "support/SLO, buyer order-form, review-process, and packaging evidence for legal and "
            "procurement due diligence; it is not a valuation guarantee, purchase commitment, or "
            "production compliance certificate."
        ),
        "contract_summary": {
            "item_count": len(contract_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "support_slo_gap_count": support_slo_gap_count,
            "buyer_order_form_gap_count": buyer_order_form_gap_count,
            "review_process_is_blocker": procurement["review_process_policy"]["is_blocker"],
            "release_authority_blocker_count": len(release_authority_blockers),
        },
        "contract_items": contract_items,
        "concrete_blockers": concrete_blockers,
        "release_authorization": release_authorization,
        "contract_status_rules": [
            {
                "contract_status": "commercial_contract_ready",
                "rule": "license, security/privacy, audit/export, support/SLO, buyer order-form, review, and packaging terms are ready",
            },
            {
                "contract_status": "commercial_contract_ready_with_warnings",
                "rule": "local contract packet is ready while production support/SLO or buyer order-form inputs remain explicit warnings",
            },
            {
                "contract_status": "commercial_contract_blocked",
                "rule": "missing contract packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks contract readiness",
            },
        ],
        "review_process_policy": procurement["review_process_policy"],
        "related_runtime_reports": {
            "commercial_procurement_status": procurement["procurement_status"],
            **procurement["related_runtime_reports"],
        },
        "library_split_decision": procurement["library_split_decision"],
        "plugin_traceability": procurement["plugin_traceability"],
        "contract_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_contract_readiness/latest",
            "documentation": "docs/commercial_contract_readiness.md",
        },
    }


def commercial_onboarding_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a paid-onboarding readiness gate over contract evidence."""
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    contract_by_name = {item["item_name"]: item for item in contract["contract_items"]}
    support_item = contract_by_name["support_slo_terms"]
    buyer_item = contract_by_name["buyer_order_form_input"]
    packaging_item = contract_by_name["packaging_decision"]
    concrete_blockers = contract["concrete_blockers"]
    release_authorization = contract["release_authorization"]
    support_slo_action_count = 1 if support_item["completion_state"] == "warning" else 0
    buyer_input_action_count = 1 if buyer_item["completion_state"] == "warning" else 0
    onboarding_items = [
        {
            "item_name": "buyer_kickoff_packet",
            "label": "Buyer kickoff packet",
            "owner": "Deal owner",
            "sources": [
                "README.md",
                "docs/commercial_onboarding_readiness.md",
                "docs/commercial_contract_readiness.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/commercial_onboarding_readiness.md",
                    "docs/commercial_contract_readiness.md",
                )
            )
            else "blocked",
            "evidence": "Buyer kickoff packet connects product overview, contract readiness, and onboarding plan.",
            "action": "Use the packet to start paid onboarding with named buyer stakeholders.",
            "exit_criteria": "Buyer confirms kickoff owner, onboarding dates, and evidence review cadence.",
        },
        {
            "item_name": "support_slo_kickoff",
            "label": "Support and SLO kickoff",
            "owner": support_item["owner"],
            "sources": support_item["sources"],
            "evidence_type": support_item["evidence_type"],
            "completion_state": support_item["completion_state"],
            "source_gap_status": support_item.get("source_gap_status", "resolved"),
            "evidence": support_item["evidence"],
            "action": "Collect support rota, escalation path, SLO target, and incident drill evidence during paid onboarding.",
            "exit_criteria": "Buyer and operator approve support owner, response target, escalation path, and first incident drill record.",
        },
        {
            "item_name": "buyer_order_form_kickoff",
            "label": "Buyer order-form kickoff",
            "owner": buyer_item["owner"],
            "sources": buyer_item["sources"],
            "evidence_type": buyer_item["evidence_type"],
            "completion_state": buyer_item["completion_state"],
            "source_gap_status": buyer_item.get("source_gap_status", "resolved"),
            "evidence": buyer_item["evidence"],
            "action": "Collect buyer order-form, ROI, legal questionnaire, deployment, and support inputs.",
            "exit_criteria": "Buyer-specific order form and legal/procurement inputs are attached to the diligence packet.",
        },
        {
            "item_name": "telemetry_capture_plan",
            "label": "Telemetry capture plan",
            "owner": "Data analytics owner",
            "sources": ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready" if has_file("docs/analytics_spec.md") else "blocked",
            "evidence": "Analytics spec separates measured local evidence from proposed production metrics.",
            "action": "Capture production onboarding telemetry without mixing it with local prototype metrics.",
            "exit_criteria": "First buyer environment records adoption, latency, verification, trace completeness, and support events.",
        },
        {
            "item_name": "acceptance_exit_criteria",
            "label": "Acceptance exit criteria",
            "owner": "Technical buyer reviewer",
            "sources": [
                "/api/v1/commercial_acceptance_checks/latest",
                "docs/commercial_acceptance_check.md",
                "docs/commercial_buyer_acceptance_runbook.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if has_file("docs/commercial_acceptance_check.md")
            and has_file("docs/commercial_buyer_acceptance_runbook.md")
            else "blocked",
            "evidence": "Acceptance check and buyer runbook define go/no-go review gates.",
            "action": "Run the buyer acceptance checklist after kickoff evidence is attached.",
            "exit_criteria": "Acceptance check has no concrete blockers and warnings are explicitly owned.",
        },
        {
            "item_name": "security_legal_handoff",
            "label": "Security and legal handoff",
            "owner": "Security and legal reviewer",
            "sources": ["SECURITY.md", "docs/commercial_contract_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if has_file("SECURITY.md") and has_file("docs/commercial_contract_readiness.md")
            else "blocked",
            "evidence": "Security policy and contract readiness packet are available for buyer handoff.",
            "action": "Attach security policy, dependency lock, and contract readiness rows to buyer diligence.",
            "exit_criteria": "Buyer security/legal reviewer accepts the packet or opens concrete findings.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_onboarding_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review delay is not an onboarding blocker unless a concrete failure is produced.",
            "action": "Continue onboarding work while queued reviews are pending.",
            "exit_criteria": "Only concrete security, API contract, document, or product defects block progress.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": packaging_item["owner"],
            "sources": packaging_item["sources"],
            "evidence_type": packaging_item["evidence_type"],
            "completion_state": packaging_item["completion_state"],
            "evidence": packaging_item["evidence"],
            "action": "Keep one deployable enterprise control-plane product through onboarding.",
            "exit_criteria": "Extract only after a second product, independent release cadence, or buyer provenance trigger exists.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in onboarding_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        onboarding_status = "commercial_onboarding_blocked"
    elif warning_count:
        onboarding_status = "commercial_onboarding_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        onboarding_status = "commercial_onboarding_ready"  # pragma: no cover

    return {
        "onboarding_status": onboarding_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_onboarding_readiness",
        "source_note": (
            "Commercial onboarding readiness converts local contract and procurement warnings into "
            "paid-onboarding owners, actions, and exit criteria; it is not a valuation guarantee, "
            "purchase commitment, or production compliance certificate."
        ),
        "onboarding_summary": {
            "item_count": len(onboarding_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "support_slo_action_count": support_slo_action_count,
            "buyer_input_action_count": buyer_input_action_count,
            "review_process_is_blocker": contract["review_process_policy"]["is_blocker"],
            "release_authority_blocker_count": len(release_authorization["blockers"]),
        },
        "onboarding_items": onboarding_items,
        "concrete_blockers": concrete_blockers,
        "release_authorization": release_authorization,
        "onboarding_status_rules": [
            {
                "onboarding_status": "commercial_onboarding_ready",
                "rule": "kickoff packet, support/SLO, buyer input, telemetry, acceptance, security/legal, review, and packaging actions are ready",
            },
            {
                "onboarding_status": "commercial_onboarding_ready_with_warnings",
                "rule": "local onboarding plan is ready while production support/SLO or buyer order-form actions remain explicit warnings",
            },
            {
                "onboarding_status": "commercial_onboarding_blocked",
                "rule": "missing onboarding packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks onboarding",
            },
        ],
        "review_process_policy": contract["review_process_policy"],
        "related_runtime_reports": {
            "commercial_contract_status": contract["contract_status"],
            **contract["related_runtime_reports"],
        },
        "library_split_decision": contract["library_split_decision"],
        "plugin_traceability": contract["plugin_traceability"],
        "onboarding_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_onboarding_readiness/latest",
            "documentation": "docs/commercial_onboarding_readiness.md",
        },
    }


def commercial_operations_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an operations-handoff readiness gate over onboarding evidence."""
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    onboarding_by_name = {item["item_name"]: item for item in onboarding["onboarding_items"]}
    support_item = onboarding_by_name["support_slo_kickoff"]
    telemetry_item = onboarding_by_name["telemetry_capture_plan"]
    acceptance_item = onboarding_by_name["acceptance_exit_criteria"]
    security_item = onboarding_by_name["security_legal_handoff"]
    packaging_item = onboarding_by_name["packaging_decision"]
    concrete_blockers = onboarding["concrete_blockers"]
    operations_items = [
        {
            "item_name": "deployment_runbook",
            "label": "Deployment runbook",
            "owner": "Platform operator",
            "sources": [
                "README.md",
                "docs/commercial_operations_readiness.md",
                "docs/commercial_onboarding_readiness.md",
                "docs/rest_api_design.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "docs/commercial_operations_readiness.md",
                    "docs/commercial_onboarding_readiness.md",
                    "docs/rest_api_design.md",
                )
            )
            else "blocked",
            "evidence": "Repository overview, REST contract, onboarding plan, and operations handoff plan are present.",
            "action": "Use existing stdlib server and documented endpoints for buyer operations handoff.",
            "exit_criteria": "Buyer operator can start, authenticate, inspect readiness endpoints, and run verification commands.",
        },
        {
            "item_name": "monitoring_telemetry_capture",
            "label": "Monitoring and telemetry capture",
            "owner": telemetry_item["owner"],
            "sources": telemetry_item["sources"],
            "evidence_type": "proposed_until_production",
            "completion_state": "warning",
            "source_gap_status": "production_input_required",
            "evidence": telemetry_item["evidence"],
            "action": "Capture adoption, latency, verifier outcomes, trace completeness, support events, and deployment health in the buyer environment.",
            "exit_criteria": "First production telemetry snapshot is attached without mixing it with local prototype metrics.",
        },
        {
            "item_name": "incident_rollback_plan",
            "label": "Incident and rollback plan",
            "owner": "Operations and support owner",
            "sources": ["docs/commercial_onboarding_readiness.md", "docs/commercial_buyer_acceptance_runbook.md"],
            "evidence_type": "proposed_until_production",
            "completion_state": "warning",
            "source_gap_status": "production_input_required",
            "evidence": "Incident drill and rollback proof require a buyer deployment or paid onboarding environment.",
            "action": "Run the first incident drill and rollback exercise during onboarding.",
            "exit_criteria": "Incident owner, escalation path, rollback steps, and drill record are attached.",
        },
        {
            "item_name": "backup_recovery_plan",
            "label": "Backup and recovery evidence",
            "owner": "Operations and data owner",
            "sources": ["docs/commercial_onboarding_readiness.md", "docs/commercial_buyer_diligence_packet.md"],
            "evidence_type": "proposed_until_production",
            "completion_state": "warning",
            "source_gap_status": "production_input_required",
            "evidence": "Backup and recovery evidence depends on the buyer deployment topology and persistence choices.",
            "action": "Define backup scope, retention, restore owner, and first restore proof during onboarding.",
            "exit_criteria": "Buyer accepts backup scope and a restore proof is attached or explicitly waived.",
        },
        {
            "item_name": "support_slo_ownership",
            "label": "Support rota and SLO ownership",
            "owner": support_item["owner"],
            "sources": support_item["sources"],
            "evidence_type": support_item["evidence_type"],
            "completion_state": support_item["completion_state"],
            "source_gap_status": support_item.get("source_gap_status", "resolved"),
            "evidence": support_item["evidence"],
            "action": support_item["action"],
            "exit_criteria": support_item["exit_criteria"],
        },
        {
            "item_name": "acceptance_handoff",
            "label": "Acceptance handoff",
            "owner": acceptance_item["owner"],
            "sources": acceptance_item["sources"],
            "evidence_type": acceptance_item["evidence_type"],
            "completion_state": acceptance_item["completion_state"],
            "evidence": acceptance_item["evidence"],
            "action": acceptance_item["action"],
            "exit_criteria": acceptance_item["exit_criteria"],
        },
        {
            "item_name": "security_legal_handoff",
            "label": "Security and legal handoff",
            "owner": security_item["owner"],
            "sources": security_item["sources"],
            "evidence_type": security_item["evidence_type"],
            "completion_state": security_item["completion_state"],
            "evidence": security_item["evidence"],
            "action": security_item["action"],
            "exit_criteria": security_item["exit_criteria"],
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_operations_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review delay is not an operations blocker unless a concrete failure is produced.",
            "action": "Continue operations handoff work while queued reviews are pending.",
            "exit_criteria": "Only concrete security, API contract, document, or product defects block progress.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": packaging_item["owner"],
            "sources": packaging_item["sources"],
            "evidence_type": packaging_item["evidence_type"],
            "completion_state": packaging_item["completion_state"],
            "evidence": packaging_item["evidence"],
            "action": packaging_item["action"],
            "exit_criteria": packaging_item["exit_criteria"],
        },
    ]
    state_counts = Counter(item["completion_state"] for item in operations_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    production_evidence_action_count = sum(
        1 for item in operations_items if item.get("source_gap_status") == "production_input_required"
    )
    if blocked_count:
        operations_status = "commercial_operations_blocked"
    elif warning_count:
        operations_status = "commercial_operations_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        operations_status = "commercial_operations_ready"  # pragma: no cover

    return {
        "operations_status": operations_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_operations_readiness",
        "source_note": (
            "Commercial operations readiness converts local onboarding evidence and production "
            "operations gaps into handoff owners, actions, and exit criteria; it is not a valuation "
            "guarantee, purchase commitment, or production compliance certificate."
        ),
        "operations_summary": {
            "item_count": len(operations_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "production_evidence_action_count": production_evidence_action_count,
            "review_process_is_blocker": onboarding["review_process_policy"]["is_blocker"],
        },
        "operations_items": operations_items,
        "concrete_blockers": concrete_blockers,
        "operations_status_rules": [
            {
                "operations_status": "commercial_operations_ready",
                "rule": "deployment, monitoring, incident, backup, support, acceptance, security/legal, review, and packaging evidence are ready",
            },
            {
                "operations_status": "commercial_operations_ready_with_warnings",
                "rule": "local operations plan is ready while production telemetry, incident, backup, or SLO evidence remains explicit warnings",
            },
            {
                "operations_status": "commercial_operations_blocked",
                "rule": "missing operations packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks operations handoff",
            },
        ],
        "review_process_policy": onboarding["review_process_policy"],
        "related_runtime_reports": {
            "commercial_onboarding_status": onboarding["onboarding_status"],
            **onboarding["related_runtime_reports"],
        },
        "library_split_decision": onboarding["library_split_decision"],
        "plugin_traceability": onboarding["plugin_traceability"],
        "operations_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_operations_readiness/latest",
            "documentation": "docs/commercial_operations_readiness.md",
        },
    }


def commercial_security_attestation_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a buyer security-review attestation gate over operations evidence."""
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    operations_by_name = {item["item_name"]: item for item in operations["operations_items"]}
    runtime_profile = security_profile or {}
    concrete_blockers = operations["concrete_blockers"]
    security_attestation_items = [
        {
            "item_name": "security_policy",
            "label": "Security policy",
            "owner": "Security owner",
            "sources": ["SECURITY.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready" if has_file("SECURITY.md") else "blocked",
            "evidence": "Repository security disclosure and support policy is present.",
            "action": "Attach SECURITY.md to the buyer security review packet.",
            "exit_criteria": "Buyer can identify the vulnerability reporting path and supported scope.",
        },
        {
            "item_name": "dependency_lock_package_metadata",
            "label": "Dependency lock and package metadata",
            "owner": "Release owner",
            "sources": ["requirements.lock", "pyproject.toml"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if has_file("requirements.lock") and has_file("pyproject.toml")
            else "blocked",
            "evidence": "Pinned dependency lock and Python package metadata are present for supply-chain review.",
            "action": "Use the pinned lockfile and package metadata as the buyer dependency baseline.",
            "exit_criteria": "Buyer can inspect package metadata and reproduce the dependency installation path.",
        },
        {
            "item_name": "security_workflow_metadata",
            "label": "Security workflow metadata",
            "owner": "Security owner",
            "sources": [
                ".github/dependabot.yml",
                ".github/workflows/security.yml",
                "ContextualWisdomLab/.github central required security workflows",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    ".github/dependabot.yml",
                    ".github/workflows/security.yml",
                )
            )
            else "blocked",
            "evidence": "Dependabot plus local CodeQL and pip-audit/SBOM workflows are defined; dependency review, Trivy, OSV, and Scorecard are delegated to central required workflows.",
            "action": "Attach workflow definitions and latest passing run evidence when the buyer review requests hosted CI proof.",
            "exit_criteria": "Buyer can inspect the configured security workflow controls and their latest run status separately.",
        },
        {
            "item_name": "runtime_access_control_profile",
            "label": "Runtime access-control profile",
            "owner": "Platform operator",
            "sources": ["contextual_orchestrator/server.py", "/api/v1/commercial_operations_readiness/latest"],
            "evidence_type": "runtime_configuration",
            "completion_state": "ready",
            "evidence": (
                f"Runtime profile uses auth_mode={runtime_profile.get('auth_mode', 'unknown')}, "
                f"allow_public_bind={runtime_profile.get('allow_public_bind', False)}, "
                f"expose_trace_by_default={runtime_profile.get('expose_trace_by_default', False)}, "
                f"rate_limit_requests={runtime_profile.get('rate_limit_requests', 'unknown')}, "
                f"max_concurrent_runs={runtime_profile.get('max_concurrent_runs', 'unknown')}."
            ),
            "action": "Use the secret-free runtime profile as buyer-visible access-control evidence.",
            "exit_criteria": "Buyer can verify admin and inference scopes, public bind opt-in, trace exposure default, rate limit, and concurrency controls.",
        },
        {
            "item_name": "audit_export_evidence",
            "label": "Audit and evidence export",
            "owner": "Evidence owner",
            "sources": [
                "docs/commercial_evidence_export.md",
                "docs/commercial_operations_readiness.md",
                "/api/v1/commercial_evidence_exports/latest",
                "/api/v1/commercial_operations_readiness/latest",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if has_file("docs/commercial_evidence_export.md")
            and has_file("docs/commercial_operations_readiness.md")
            else "blocked",
            "evidence": "Commercial evidence export and operations readiness documents are present for buyer audit review.",
            "action": "Package runtime evidence export with operations readiness for the security review data room.",
            "exit_criteria": "Buyer can trace security claims to runtime endpoints and Markdown artifacts.",
        },
        {
            "item_name": "vulnerability_scan_evidence",
            "label": "Vulnerability scan evidence",
            "owner": "Security owner",
            "sources": [
                ".github/workflows/security.yml",
                "ContextualWisdomLab/.github central required security workflows",
            ],
            "evidence_type": "external_attestation_required",
            "completion_state": "warning",
            "source_gap_status": "external_attestation_required",
            "evidence": "Local supply-chain workflow metadata and central security scan workflow metadata exist, but the buyer packet still needs the latest hosted scan result or buyer-accepted equivalent.",
            "action": "Attach latest CodeQL, pip-audit, Trivy, SBOM, and Scorecard results when CI completes or the buyer requests evidence.",
            "exit_criteria": "Hosted scan outputs are attached, or the buyer explicitly accepts workflow definitions as sufficient for this stage.",
        },
        {
            "item_name": "third_party_attestation_pen_test",
            "label": "Third-party attestation or penetration test",
            "owner": "Security owner",
            "sources": ["buyer security review", "external assessor"],
            "evidence_type": "external_attestation_required",
            "completion_state": "warning",
            "source_gap_status": "external_attestation_required",
            "evidence": "Independent SOC 2, ISO 27001, penetration-test, or buyer security assessment evidence is outside the repo-local prototype.",
            "action": "Provide the buyer-requested attestation, schedule an assessment, or document an explicit waiver.",
            "exit_criteria": "Buyer accepts the third-party security evidence, scheduled assessment, or waiver.",
        },
        {
            "item_name": "buyer_privacy_dpa_questionnaire",
            "label": "Buyer privacy, DPA, and questionnaire input",
            "owner": "Deal owner",
            "sources": ["buyer DPA", "buyer privacy questionnaire", "buyer order form"],
            "evidence_type": "buyer_input_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_input_required",
            "evidence": "Privacy, DPA, subprocessors, data residency, and questionnaire answers depend on buyer-specific terms.",
            "action": "Collect buyer privacy questionnaire, DPA requirements, subprocessors, and data residency constraints.",
            "exit_criteria": "Buyer-specific privacy inputs are completed or explicitly waived in the deal packet.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": operations_by_name["review_process_policy"]["sources"],
            "evidence_type": operations_by_name["review_process_policy"]["evidence_type"],
            "completion_state": operations_by_name["review_process_policy"]["completion_state"],
            "evidence": operations_by_name["review_process_policy"]["evidence"],
            "action": operations_by_name["review_process_policy"]["action"],
            "exit_criteria": operations_by_name["review_process_policy"]["exit_criteria"],
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": operations_by_name["packaging_decision"]["owner"],
            "sources": operations_by_name["packaging_decision"]["sources"],
            "evidence_type": operations_by_name["packaging_decision"]["evidence_type"],
            "completion_state": operations_by_name["packaging_decision"]["completion_state"],
            "evidence": operations_by_name["packaging_decision"]["evidence"],
            "action": operations_by_name["packaging_decision"]["action"],
            "exit_criteria": operations_by_name["packaging_decision"]["exit_criteria"],
        },
    ]
    state_counts = Counter(item["completion_state"] for item in security_attestation_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    external_attestation_gap_count = sum(
        1 for item in security_attestation_items if item.get("source_gap_status") == "external_attestation_required"
    )
    buyer_privacy_gap_count = sum(
        1 for item in security_attestation_items if item.get("source_gap_status") == "buyer_input_required"
    )
    if blocked_count:
        security_attestation_status = "commercial_security_attestation_blocked"
    elif warning_count:
        security_attestation_status = "commercial_security_attestation_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        security_attestation_status = "commercial_security_attestation_ready"  # pragma: no cover

    return {
        "security_attestation_status": security_attestation_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_security_attestation",
        "source_note": (
            "Commercial security attestation separates repo-local security evidence from external "
            "attestation, hosted scan, and buyer privacy inputs; it is not a valuation guarantee, "
            "purchase commitment, production compliance certificate, or third-party security audit."
        ),
        "security_attestation_summary": {
            "item_count": len(security_attestation_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "external_attestation_gap_count": external_attestation_gap_count,
            "buyer_privacy_gap_count": buyer_privacy_gap_count,
            "review_process_is_blocker": operations["review_process_policy"]["is_blocker"],
        },
        "security_attestation_items": security_attestation_items,
        "concrete_blockers": concrete_blockers,
        "security_attestation_status_rules": [
            {
                "security_attestation_status": "commercial_security_attestation_ready",
                "rule": "security policy, dependency metadata, workflow metadata, access controls, audit export, external attestation, buyer privacy input, review policy, and packaging evidence are ready",
            },
            {
                "security_attestation_status": "commercial_security_attestation_ready_with_warnings",
                "rule": "repo-local security packet is ready while hosted scan evidence, third-party attestation, or buyer privacy input remains explicit warnings",
            },
            {
                "security_attestation_status": "commercial_security_attestation_blocked",
                "rule": "missing local security packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks security attestation",
            },
        ],
        "review_process_policy": operations["review_process_policy"],
        "related_runtime_reports": {
            "commercial_operations_status": operations["operations_status"],
            **operations["related_runtime_reports"],
        },
        "library_split_decision": operations["library_split_decision"],
        "plugin_traceability": operations["plugin_traceability"],
        "security_attestation_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_security_attestations/latest",
            "documentation": "docs/commercial_security_attestation.md",
        },
    }


def commercial_value_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a buyer economic-review gate over value and ROI evidence."""
    commercial = orchestrator.commercial_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    export = orchestrator.commercial_evidence_export_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    criteria_by_name = orchestrator._criteria_by_name(commercial["criteria"])
    value_case = criteria_by_name["commercial_value_case"]
    kpis = orchestrator._metrics_by_name(analytics["kpis"])
    guardrails = orchestrator._metrics_by_name(analytics["guardrails"])
    security_items = {item["item_name"]: item for item in security["security_attestation_items"]}
    value_items = [
        {
            "item_name": "commercial_value_case_basis",
            "label": "Commercial value-case basis",
            "owner": "Deal owner",
            "sources": ["/api/v1/commercial_readiness/latest", "docs/commercial_readiness.md"],
            "evidence_type": "local_due_diligence_snapshot",
            "completion_state": "ready" if value_case["status"] == "pass" else "warning",
            "evidence": value_case["evidence"],
            "action": "Use commercial readiness as the value-case baseline without presenting it as a valuation guarantee.",
            "exit_criteria": "Buyer sees the KRW target as a review anchor, not as a guaranteed valuation.",
        },
        {
            "item_name": "local_analytics_evidence",
            "label": "Local analytics evidence",
            "owner": "Product analytics owner",
            "sources": ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
            "evidence_type": "measured_local",
            "completion_state": "ready",
            "evidence": (
                f"compatible_api_adoption={kpis['compatible_api_adoption'].get('value')}; "
                f"trace_complete_workflow_rate={kpis['trace_complete_workflow_rate'].get('value_percent')}%; "
                f"policy_safe_routing_rate={kpis['policy_safe_routing_rate'].get('value_percent')}%; "
                f"provider_exclusion_miss_rate={guardrails['provider_exclusion_miss_rate'].get('value')}"
            ),
            "action": "Use local measured adoption, trace, policy, and provider-safety metrics as evidence only for this prototype.",
            "exit_criteria": "Buyer understands these are local measured signals, not production revenue or customer usage claims.",
        },
        {
            "item_name": "buyer_evidence_export",
            "label": "Buyer evidence export",
            "owner": "Evidence owner",
            "sources": [
                "/api/v1/commercial_evidence_exports/latest",
                "/api/v1/commercial_security_attestations/latest",
                "docs/commercial_evidence_export.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready" if has_file("docs/commercial_evidence_export.md") else "blocked",
            "evidence": (
                f"commercial_export_status={export['export_status']}; "
                f"security_attestation_status={security['security_attestation_status']}"
            ),
            "action": "Package value evidence with export and security attestation outputs in the buyer data room.",
            "exit_criteria": "Buyer can trace economic claims back to runtime endpoints and repo artifacts.",
        },
        {
            "item_name": "pricing_package_rationale",
            "label": "Pricing and package rationale",
            "owner": "Deal owner",
            "sources": [
                "docs/commercial_readiness.md",
                "docs/commercial_saleability_decision.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_value_readiness.md",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "docs/commercial_readiness.md",
                    "docs/commercial_saleability_decision.md",
                    "docs/commercial_procurement_readiness.md",
                )
            )
            else "blocked",
            "evidence": "Commercial readiness, saleability, and procurement documents anchor the package rationale.",
            "action": "Keep the KRW 2B package rationale tied to API compatibility, evidence control plane, replay, audit, security, and operations readiness.",
            "exit_criteria": "Buyer can inspect which product capabilities support the package rationale.",
        },
        {
            "item_name": "roi_model_inputs",
            "label": "ROI model inputs",
            "owner": "Buyer sponsor and deal owner",
            "sources": ["buyer ROI model", "customer discovery", "procurement value case"],
            "evidence_type": "buyer_input_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_financial_input_required",
            "evidence": "Buyer-specific baseline cost, workflow volume, error/rework cost, compliance cost, and time-saving assumptions are not repo-local facts.",
            "action": "Collect buyer baseline metrics and map them to API compatibility, trace audit, replay, and operations savings.",
            "exit_criteria": "Buyer accepts the ROI model inputs or marks them waived for the commercial review.",
        },
        {
            "item_name": "reference_customer_or_case_study",
            "label": "Reference customer or proof",
            "owner": "Deal owner",
            "sources": ["reference customer", "case study", "paid pilot result"],
            "evidence_type": "external_value_proof_required",
            "completion_state": "warning",
            "source_gap_status": "external_value_proof_required",
            "evidence": "Reference customer, paid pilot, or production proof is external to the repo-local prototype.",
            "action": "Attach a reference, pilot result, or explicit buyer waiver before treating the value case as externally proven.",
            "exit_criteria": "Buyer accepts the reference proof, pilot result, or waiver.",
        },
        {
            "item_name": "procurement_budget_owner",
            "label": "Procurement budget owner",
            "owner": "Buyer sponsor and procurement owner",
            "sources": ["buyer order form", "procurement process", "budget approval"],
            "evidence_type": "buyer_input_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_financial_input_required",
            "evidence": "Budget owner, approval path, and order-form authority are buyer-specific inputs.",
            "action": "Identify sponsor, budget owner, procurement path, and order-form authority.",
            "exit_criteria": "Buyer confirms the budget owner and approval path for the KRW 2B review.",
        },
        {
            "item_name": "implementation_payback_assumption",
            "label": "Implementation payback assumption",
            "owner": "Buyer sponsor and onboarding owner",
            "sources": ["buyer onboarding plan", "implementation estimate", "operations handoff"],
            "evidence_type": "buyer_input_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_financial_input_required",
            "evidence": "Implementation timeline, staffing, opportunity cost, and payback window depend on buyer deployment scope.",
            "action": "Estimate implementation effort and payback window during paid onboarding or buyer diligence.",
            "exit_criteria": "Buyer accepts the payback assumptions or marks them out of scope.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": security_items["review_process_policy"]["sources"],
            "evidence_type": security_items["review_process_policy"]["evidence_type"],
            "completion_state": security_items["review_process_policy"]["completion_state"],
            "evidence": security_items["review_process_policy"]["evidence"],
            "action": security_items["review_process_policy"]["action"],
            "exit_criteria": security_items["review_process_policy"]["exit_criteria"],
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": security_items["packaging_decision"]["owner"],
            "sources": security_items["packaging_decision"]["sources"],
            "evidence_type": security_items["packaging_decision"]["evidence_type"],
            "completion_state": security_items["packaging_decision"]["completion_state"],
            "evidence": security_items["packaging_decision"]["evidence"],
            "action": security_items["packaging_decision"]["action"],
            "exit_criteria": security_items["packaging_decision"]["exit_criteria"],
        },
    ]
    state_counts = Counter(item["completion_state"] for item in value_items)
    concrete_blockers = security["concrete_blockers"]
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    buyer_financial_gap_count = sum(
        1
        for item in value_items
        if item.get("source_gap_status") in {"buyer_financial_input_required", "external_value_proof_required"}
    )
    external_value_proof_gap_count = sum(
        1 for item in value_items if item.get("source_gap_status") == "external_value_proof_required"
    )
    if blocked_count:
        value_status = "commercial_value_blocked"
    elif warning_count:
        value_status = "commercial_value_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        value_status = "commercial_value_ready"  # pragma: no cover

    return {
        "value_status": value_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_value_readiness",
        "source_note": (
            "Commercial value readiness separates repo-local measured evidence from buyer-specific "
            "ROI, reference, budget, and payback inputs; it is not a valuation guarantee, purchase "
            "commitment, revenue proof, or financial advice."
        ),
        "value_summary": {
            "item_count": len(value_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "buyer_financial_gap_count": buyer_financial_gap_count,
            "external_value_proof_gap_count": external_value_proof_gap_count,
            "review_process_is_blocker": security["review_process_policy"]["is_blocker"],
        },
        "value_items": value_items,
        "concrete_blockers": concrete_blockers,
        "value_status_rules": [
            {
                "value_status": "commercial_value_ready",
                "rule": "commercial value case, local analytics, evidence export, pricing rationale, ROI inputs, reference proof, budget owner, payback assumptions, review policy, and packaging evidence are ready",
            },
            {
                "value_status": "commercial_value_ready_with_warnings",
                "rule": "repo-local value evidence is ready while buyer ROI inputs, reference proof, budget owner, or payback assumptions remain explicit warnings",
            },
            {
                "value_status": "commercial_value_blocked",
                "rule": "missing local value packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks value readiness",
            },
        ],
        "review_process_policy": security["review_process_policy"],
        "related_runtime_reports": {
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_export_status": export["export_status"],
            "commercial_status": commercial["commercial_status"],
            **security["related_runtime_reports"],
        },
        "library_split_decision": security["library_split_decision"],
        "plugin_traceability": security["plugin_traceability"],
        "value_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_value_readiness/latest",
            "documentation": "docs/commercial_value_readiness.md",
        },
    }


def commercial_close_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the final buyer-close gate over commercial readiness evidence."""
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    export = orchestrator.commercial_evidence_export_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = [
        *value["concrete_blockers"],
        *security["concrete_blockers"],
        *contract["concrete_blockers"],
        *onboarding["concrete_blockers"],
        *operations["concrete_blockers"],
        *export["concrete_blockers"],
    ]
    concrete_blockers = list(dict.fromkeys(concrete_blockers))
    close_items = [
        {
            "item_name": "sellable_product_packet",
            "label": "Sellable product packet",
            "owner": "Deal owner",
            "sources": [
                "/api/v1/commercial_value_readiness/latest",
                "/api/v1/commercial_security_attestations/latest",
                "/api/v1/commercial_evidence_exports/latest",
                "docs/commercial_value_readiness.md",
                "docs/commercial_security_attestation.md",
                "docs/commercial_evidence_export.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if value["value_status"] != "commercial_value_blocked"
            and security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and export["export_status"] != "commercial_export_blocked"
            and has_file("docs/commercial_value_readiness.md")
            and has_file("docs/commercial_security_attestation.md")
            and has_file("docs/commercial_evidence_export.md")
            else "blocked",
            "evidence": (
                f"value_status={value['value_status']}; "
                f"security_attestation_status={security['security_attestation_status']}; "
                f"commercial_export_status={export['export_status']}"
            ),
            "action": "Attach the repo-local product, security, value, and evidence export packet to buyer close review.",
            "exit_criteria": "Buyer can inspect the sellable packet without treating it as a purchase commitment or valuation guarantee.",
        },
        {
            "item_name": "contract_close_packet",
            "label": "Contract close packet",
            "owner": "Legal and procurement owner",
            "sources": [
                "/api/v1/commercial_contract_readiness/latest",
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if contract["contract_status"] != "commercial_contract_blocked"
            and has_file("docs/commercial_contract_readiness.md")
            else "blocked",
            "evidence": f"contract_status={contract['contract_status']}",
            "action": "Use contract readiness as the local legal/procurement packet and track final signatures separately.",
            "exit_criteria": "Buyer legal/procurement sees local contract evidence and the remaining signature inputs.",
        },
        {
            "item_name": "onboarding_operations_packet",
            "label": "Onboarding and operations packet",
            "owner": "Customer success and platform owner",
            "sources": [
                "/api/v1/commercial_onboarding_readiness/latest",
                "/api/v1/commercial_operations_readiness/latest",
                "docs/commercial_onboarding_readiness.md",
                "docs/commercial_operations_readiness.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and operations["operations_status"] != "commercial_operations_blocked"
            and has_file("docs/commercial_onboarding_readiness.md")
            and has_file("docs/commercial_operations_readiness.md")
            else "blocked",
            "evidence": (
                f"onboarding_status={onboarding['onboarding_status']}; "
                f"operations_status={operations['operations_status']}"
            ),
            "action": "Attach onboarding and operations readiness as the go-live support packet.",
            "exit_criteria": "Buyer can identify implementation, support, operations, and acceptance owners.",
        },
        {
            "item_name": "buyer_evidence_export_packet",
            "label": "Buyer evidence export packet",
            "owner": "Evidence owner",
            "sources": [
                "/api/v1/commercial_evidence_exports/latest",
                "docs/commercial_evidence_export.md",
                "docs/figma_artifacts.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if export["export_status"] != "commercial_export_blocked"
            and has_file("docs/commercial_evidence_export.md")
            and has_file("docs/figma_artifacts.md")
            else "blocked",
            "evidence": f"commercial_export_status={export['export_status']}",
            "action": "Use the portable export packet as the buyer data-room index.",
            "exit_criteria": "Buyer can trace close evidence to runtime endpoints, docs, and Figma/FigJam artifacts.",
        },
        {
            "item_name": "signed_order_form_msa",
            "label": "Signed order form or MSA",
            "owner": "Buyer sponsor, procurement owner, and deal owner",
            "sources": ["buyer order form", "MSA", "signature packet"],
            "evidence_type": "buyer_signature_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": "Signed order form, MSA, commercial terms, and authority confirmation are buyer-side close inputs.",
            "action": "Collect final signed order form or MSA, or attach an explicit buyer waiver.",
            "exit_criteria": "Buyer and seller signature authority accept the order form or MSA.",
        },
        {
            "item_name": "dpa_security_acceptance",
            "label": "DPA and security acceptance",
            "owner": "Buyer security, privacy, and legal owner",
            "sources": ["buyer DPA", "security review acceptance", "privacy questionnaire"],
            "evidence_type": "buyer_signature_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": "DPA, security acceptance, privacy questionnaire, and attestation waivers are buyer-specific close inputs.",
            "action": "Collect DPA/security acceptance or documented waiver from buyer security and legal reviewers.",
            "exit_criteria": "Buyer signs or waives DPA/security acceptance requirements.",
        },
        {
            "item_name": "budget_approval_purchase_order",
            "label": "Budget approval and purchase order",
            "owner": "Buyer finance and procurement owner",
            "sources": ["budget approval", "purchase order", "finance approval"],
            "evidence_type": "buyer_signature_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": "Budget approval, purchase order, and finance authority are external buyer procurement evidence.",
            "action": "Collect buyer budget approval and PO or attach approved alternative payment authority.",
            "exit_criteria": "Buyer procurement confirms budget authority and payment path for KRW 2B.",
        },
        {
            "item_name": "go_live_authorization",
            "label": "Go-live authorization",
            "owner": "Buyer business sponsor and implementation owner",
            "sources": ["go-live approval", "implementation authorization", "acceptance signoff"],
            "evidence_type": "buyer_signature_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": "Go-live authorization and implementation acceptance require named buyer approval.",
            "action": "Collect go-live authorization or mark production activation out of scope for the signed deal.",
            "exit_criteria": "Buyer authorizes go-live, paid onboarding, or a scoped post-signature implementation plan.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_saleability_decision.md", "docs/commercial_close_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review process delay is not a close blocker unless a concrete product, security, API-contract, or document failure is produced.",
            "action": "Keep commercial close work moving while queued review processes are pending.",
            "exit_criteria": "Only concrete failures block close readiness.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": "Procurement and security reviewer",
            "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if value["library_split_decision"]["decision"] == "keep_single_product"
            else "warning",
            "evidence": value["library_split_decision"]["reason"],
            "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
            "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this close gate.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in close_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    buyer_signature_gap_count = sum(
        1 for item in close_items if item.get("source_gap_status") == "buyer_signature_required"
    )
    if blocked_count:
        close_status = "commercial_close_blocked"
    elif warning_count:
        close_status = "commercial_close_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        close_status = "commercial_close_ready"  # pragma: no cover

    return {
        "close_status": close_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_close_readiness",
        "source_note": (
            "Commercial close readiness separates repo-local sellable product evidence from buyer "
            "signature, legal, procurement, security acceptance, and go-live authorization inputs; "
            "it is not a valuation guarantee, purchase commitment, signed order, legal opinion, "
            "or production compliance certificate."
        ),
        "close_summary": {
            "item_count": len(close_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "buyer_signature_gap_count": buyer_signature_gap_count,
            "review_process_is_blocker": value["review_process_policy"]["is_blocker"],
        },
        "close_items": close_items,
        "concrete_blockers": concrete_blockers,
        "close_status_rules": [
            {
                "close_status": "commercial_close_ready",
                "rule": "sellable product packet, contract packet, onboarding/operations packet, evidence export, signatures, DPA/security acceptance, budget/PO, go-live authorization, review policy, and packaging evidence are ready",
            },
            {
                "close_status": "commercial_close_ready_with_warnings",
                "rule": "repo-local close packet is ready while buyer signatures, DPA/security acceptance, budget/PO, or go-live authorization remain explicit warnings",
            },
            {
                "close_status": "commercial_close_blocked",
                "rule": "missing local close evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks close readiness",
            },
        ],
        "review_process_policy": value["review_process_policy"],
        "related_runtime_reports": {
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_contract_status": contract["contract_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_operations_status": operations["operations_status"],
            "commercial_export_status": export["export_status"],
            **value["related_runtime_reports"],
        },
        "library_split_decision": value["library_split_decision"],
        "plugin_traceability": value["plugin_traceability"],
        "close_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_close_readiness/latest",
            "documentation": "docs/commercial_close_readiness.md",
        },
    }


def commercial_go_to_market_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a buyer-facing GTM readiness index over commercial evidence."""
    close = orchestrator.commercial_close_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    export = orchestrator.commercial_evidence_export_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    handoff = orchestrator.commercial_handoff_bundle_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    saleability = orchestrator.saleability_decision_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = [
        *close["concrete_blockers"],
        *value["concrete_blockers"],
        *security["concrete_blockers"],
        *export["concrete_blockers"],
        *saleability["concrete_blockers"],
    ]
    concrete_blockers = list(dict.fromkeys(concrete_blockers))
    gtm_items = [
        {
            "item_name": "commercial_close_packet",
            "label": "Commercial close packet",
            "owner": "Deal owner",
            "sources": ["/api/v1/commercial_close_readiness/latest", "docs/commercial_close_readiness.md"],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if close["close_status"] != "commercial_close_blocked"
            and has_file("docs/commercial_close_readiness.md")
            else "blocked",
            "evidence": f"close_status={close['close_status']}",
            "action": "Use close readiness as the buyer-facing final readiness packet.",
            "exit_criteria": "Buyer sees local close packet status and remaining buyer-side signature gaps.",
        },
        {
            "item_name": "economic_value_packet",
            "label": "Economic value packet",
            "owner": "Deal owner and analytics owner",
            "sources": [
                "/api/v1/commercial_value_readiness/latest",
                "/api/v1/analytics_snapshots/latest",
                "docs/commercial_value_readiness.md",
                "docs/analytics_spec.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if value["value_status"] != "commercial_value_blocked"
            and has_file("docs/commercial_value_readiness.md")
            and has_file("docs/analytics_spec.md")
            else "blocked",
            "evidence": (
                f"value_status={value['value_status']}; "
                f"kpi_count={len(analytics['kpis'])}; guardrail_count={len(analytics['guardrails'])}"
            ),
            "action": "Show value evidence with measured-local versus buyer-specific metric separation.",
            "exit_criteria": "Buyer can inspect value claims without treating them as revenue proof or financial advice.",
        },
        {
            "item_name": "security_trust_packet",
            "label": "Security trust packet",
            "owner": "Security owner",
            "sources": [
                "/api/v1/commercial_security_attestations/latest",
                "docs/commercial_security_attestation.md",
                "SECURITY.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and has_file("docs/commercial_security_attestation.md")
            and has_file("SECURITY.md")
            else "blocked",
            "evidence": f"security_attestation_status={security['security_attestation_status']}",
            "action": "Use security attestation as the buyer trust packet and keep external attestations separate.",
            "exit_criteria": "Buyer can inspect local security controls and external attestation gaps.",
        },
        {
            "item_name": "buyer_evidence_packet",
            "label": "Buyer evidence packet",
            "owner": "Evidence owner",
            "sources": [
                "/api/v1/commercial_evidence_exports/latest",
                "/api/v1/commercial_handoff_bundles/latest",
                "docs/commercial_evidence_export.md",
                "docs/commercial_buyer_handoff_bundle.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if export["export_status"] != "commercial_export_blocked"
            and handoff["bundle_status"] != "buyer_handoff_blocked"
            and has_file("docs/commercial_evidence_export.md")
            and has_file("docs/commercial_buyer_handoff_bundle.md")
            else "blocked",
            "evidence": f"commercial_export_status={export['export_status']}; buyer_handoff_status={handoff['bundle_status']}",
            "action": "Attach evidence export and handoff bundle as the buyer data-room index.",
            "exit_criteria": "Buyer can trace GTM claims to runtime endpoints, docs, tests, and Figma artifacts.",
        },
        {
            "item_name": "saleability_decision_packet",
            "label": "Saleability decision packet",
            "owner": "Deal owner",
            "sources": ["/api/v1/saleability_decisions/latest", "docs/commercial_saleability_decision.md"],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if saleability["saleability_status"] != "saleability_blocked"
            and has_file("docs/commercial_saleability_decision.md")
            else "blocked",
            "evidence": f"saleability_status={saleability['saleability_status']}",
            "action": "Use saleability decision as the GTM go/no-go baseline.",
            "exit_criteria": "Buyer and stakeholder review can distinguish warnings from concrete blockers.",
        },
        {
            "item_name": "admin_operator_evidence",
            "label": "Admin operator evidence",
            "owner": "Product design owner",
            "sources": ["/admin", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
            else "blocked",
            "evidence": "Admin surface exposes readiness status, source notes, measurement status, and warning/blocker summaries.",
            "action": "Use the existing admin observability surface instead of creating a separate sales dashboard.",
            "exit_criteria": "Operator can inspect GTM readiness from the current admin surface.",
        },
        {
            "item_name": "analytics_truthfulness_packet",
            "label": "Analytics truthfulness packet",
            "owner": "Data analytics owner",
            "sources": ["docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready" if has_file("docs/analytics_spec.md") else "blocked",
            "evidence": "Analytics spec separates measured local evidence from proposed production or buyer-specific inputs.",
            "action": "Keep GTM metrics from claiming production revenue, signed buyer proof, or unmeasured telemetry.",
            "exit_criteria": "Stakeholders can see which KPI fields are measured and which are proposed inputs.",
        },
        {
            "item_name": "stakeholder_artifacts_packet",
            "label": "Stakeholder artifacts packet",
            "owner": "Figma and Product Design owner",
            "sources": [
                "docs/figma_artifacts.md",
                "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            ],
            "evidence_type": "figma_artifact",
            "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "evidence": "Editable Figma/FigJam stakeholder artifacts are recorded and Figma Code Connect is excluded.",
            "action": "Use editable stakeholder artifacts for GTM review instead of screenshot-only evidence.",
            "exit_criteria": "Stakeholders can open the design file and FigJam board for GTM review.",
        },
        {
            "item_name": "buyer_signature_budget_follow_up",
            "label": "Buyer signature and budget follow-up",
            "owner": "Buyer sponsor, procurement owner, and deal owner",
            "sources": ["buyer order form", "MSA", "DPA", "security acceptance", "purchase order", "go-live approval"],
            "evidence_type": "buyer_input_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": (
                f"buyer_signature_gap_count={close['close_summary']['buyer_signature_gap_count']}; "
                "signed order/MSA, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
            ),
            "action": "Collect buyer signatures, approvals, or waivers before representing the packet as closed-won.",
            "exit_criteria": "Buyer accepts or waives all signature, budget, security acceptance, and go-live inputs.",
        },
        {
            "item_name": "production_external_proof_follow_up",
            "label": "Production and external proof follow-up",
            "owner": "Security, operations, and deal owner",
            "sources": ["hosted scan output", "third-party attestation", "reference proof", "production telemetry"],
            "evidence_type": "external_or_production_input_required",
            "completion_state": "warning",
            "source_gap_status": "external_or_production_input_required",
            "evidence": (
                f"security_warning_count={security['security_attestation_summary']['warning_count']}; "
                f"value_warning_count={value['value_summary']['warning_count']}; "
                f"export_warning_count={export['export_summary']['warning_count']}"
            ),
            "action": "Attach hosted scan, third-party attestation, reference proof, and production telemetry when available.",
            "exit_criteria": "Buyer accepts external proof, production proof, or an explicit waiver.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_go_to_market_readiness.md", "docs/commercial_saleability_decision.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review process delay is not a GTM blocker unless a concrete failure is produced.",
            "action": "Continue GTM readiness work while queued reviews are pending.",
            "exit_criteria": "Only concrete product, security, API contract, or document failures block GTM readiness.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": "Procurement and security reviewer",
            "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if close["library_split_decision"]["decision"] == "keep_single_product"
            else "warning",
            "evidence": close["library_split_decision"]["reason"],
            "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
            "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this GTM gate.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in gtm_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    buyer_signature_gap_count = close["close_summary"]["buyer_signature_gap_count"]
    external_or_production_gap_count = (
        security["security_attestation_summary"]["external_attestation_gap_count"]
        + value["value_summary"]["external_value_proof_gap_count"]
        + export["export_summary"]["warning_count"]
    )
    if blocked_count:
        gtm_status = "commercial_go_to_market_blocked"
    elif warning_count:
        gtm_status = "commercial_go_to_market_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        gtm_status = "commercial_go_to_market_ready"  # pragma: no cover

    return {
        "go_to_market_status": gtm_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_go_to_market_readiness",
        "source_note": (
            "Commercial go-to-market readiness indexes repo-local sellable product, evidence, "
            "admin, analytics, and stakeholder artifacts separately from buyer signatures, "
            "external proof, and production telemetry; it is not a valuation guarantee, purchase "
            "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
        ),
        "go_to_market_summary": {
            "item_count": len(gtm_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "buyer_signature_gap_count": buyer_signature_gap_count,
            "external_or_production_gap_count": external_or_production_gap_count,
            "review_process_is_blocker": close["review_process_policy"]["is_blocker"],
        },
        "go_to_market_items": gtm_items,
        "concrete_blockers": concrete_blockers,
        "go_to_market_status_rules": [
            {
                "go_to_market_status": "commercial_go_to_market_ready",
                "rule": "close, value, security, evidence, saleability, admin, analytics, stakeholder artifacts, buyer inputs, external proof, review policy, and packaging evidence are ready",
            },
            {
                "go_to_market_status": "commercial_go_to_market_ready_with_warnings",
                "rule": "repo-local GTM packet is ready while buyer signatures, budget/PO, DPA/security acceptance, production telemetry, reference proof, hosted scan, or third-party attestation remain explicit warnings",
            },
            {
                "go_to_market_status": "commercial_go_to_market_blocked",
                "rule": "missing local GTM packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks GTM readiness",
            },
        ],
        "review_process_policy": close["review_process_policy"],
        "related_runtime_reports": {
            "commercial_close_status": close["close_status"],
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_export_status": export["export_status"],
            "buyer_handoff_status": handoff["bundle_status"],
            "saleability_status": saleability["saleability_status"],
            **close["related_runtime_reports"],
        },
        "library_split_decision": close["library_split_decision"],
        "plugin_traceability": close["plugin_traceability"],
        "go_to_market_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_go_to_market_readiness/latest",
            "documentation": "docs/commercial_go_to_market_readiness.md",
        },
    }


def commercial_launch_readiness_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the buyer launch/trial readiness gate over commercial evidence."""
    gtm = orchestrator.commercial_go_to_market_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    acceptance = orchestrator.commercial_acceptance_check_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = [
        *gtm["concrete_blockers"],
        *operations["concrete_blockers"],
        *onboarding["concrete_blockers"],
        *acceptance["concrete_blockers"],
    ]
    concrete_blockers = list(dict.fromkeys(concrete_blockers))
    launch_items = [
        {
            "item_name": "go_to_market_packet",
            "label": "Go-to-market packet",
            "owner": "Deal owner",
            "sources": [
                "/api/v1/commercial_go_to_market_readiness/latest",
                "docs/commercial_go_to_market_readiness.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
            and has_file("docs/commercial_go_to_market_readiness.md")
            else "blocked",
            "evidence": f"go_to_market_status={gtm['go_to_market_status']}",
            "action": "Use the GTM packet as the launch/trial entry evidence.",
            "exit_criteria": "Buyer can inspect the launch packet without treating it as a signed deal or production proof.",
        },
        {
            "item_name": "runtime_launch_path",
            "label": "Runtime launch path",
            "owner": "Platform operator",
            "sources": [
                "README.md",
                "contextual_orchestrator/server.py",
                "contextual_orchestrator/api_contract.py",
                "docs/rest_api_design.md",
                "/v1/chat/completions",
                "/admin",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "README.md",
                    "contextual_orchestrator/server.py",
                    "contextual_orchestrator/api_contract.py",
                    "docs/rest_api_design.md",
                )
            )
            else "blocked",
            "evidence": "Stdlib server, OpenAI-compatible endpoint, admin console, and REST contract are present.",
            "action": "Run the existing server and admin/API smoke tests for buyer trial setup.",
            "exit_criteria": "Buyer can start the runtime, authenticate admin calls, and inspect launch readiness JSON.",
        },
        {
            "item_name": "acceptance_test_packet",
            "label": "Acceptance test packet",
            "owner": "Technical reviewer",
            "sources": [
                "/api/v1/commercial_acceptance_checks/latest",
                "tests/test_commercial_acceptance_check.py",
                "tests/test_commercial_go_to_market_readiness.py",
                "tests/test_commercial_launch_readiness.py",
                "pytest -q",
            ],
            "evidence_type": "measured_local",
            "completion_state": "ready"
            if acceptance["acceptance_status"] != "commercial_acceptance_blocked"
            and all(
                has_file(path)
                for path in (
                    "tests/test_commercial_acceptance_check.py",
                    "tests/test_commercial_go_to_market_readiness.py",
                    "tests/test_commercial_launch_readiness.py",
                )
            )
            else "blocked",
            "evidence": f"acceptance_status={acceptance['acceptance_status']}",
            "action": "Use focused acceptance and launch tests as the local verification packet.",
            "exit_criteria": "Focused launch, GTM, acceptance, API, and artifact tests pass before buyer handoff.",
        },
        {
            "item_name": "operator_runbook_packet",
            "label": "Operator runbook packet",
            "owner": "Customer success and platform owner",
            "sources": [
                "/api/v1/commercial_operations_readiness/latest",
                "/api/v1/commercial_onboarding_readiness/latest",
                "docs/commercial_operations_readiness.md",
                "docs/commercial_onboarding_readiness.md",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if operations["operations_status"] != "commercial_operations_blocked"
            and onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and has_file("docs/commercial_operations_readiness.md")
            and has_file("docs/commercial_onboarding_readiness.md")
            else "blocked",
            "evidence": (
                f"operations_status={operations['operations_status']}; "
                f"onboarding_status={onboarding['onboarding_status']}"
            ),
            "action": "Attach onboarding and operations readiness as the launch runbook.",
            "exit_criteria": "Buyer sees implementation, support, telemetry, incident, backup, and acceptance owners.",
        },
        {
            "item_name": "admin_observability_packet",
            "label": "Admin observability packet",
            "owner": "Product design owner",
            "sources": ["/admin", "/admin/state", "contextual_orchestrator/admin.py", "docs/screen_design.md"],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if admin_state["agents"] and has_file("contextual_orchestrator/admin.py") and has_file("docs/screen_design.md")
            else "blocked",
            "evidence": (
                f"agent_count={len(admin_state['agents'])}; "
                "admin surface exposes launch, source, measurement, and warning summaries."
            ),
            "action": "Use the current admin observability surface rather than a separate sales dashboard.",
            "exit_criteria": "Operator can review launch readiness from the existing admin console.",
        },
        {
            "item_name": "buyer_environment_inputs",
            "label": "Buyer environment inputs",
            "owner": "Buyer implementation owner and platform operator",
            "sources": ["buyer environment URL", "deployment topology", "admin token handoff", "data retention decision"],
            "evidence_type": "buyer_environment_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_environment_required",
            "evidence": "Buyer deployment URL, topology, credentials handoff, retention, and network policy are not repo-local evidence.",
            "action": "Collect buyer environment details or attach explicit trial-scope waivers.",
            "exit_criteria": "Buyer provides environment inputs or agrees the launch is limited to repo-local/demo execution.",
        },
        {
            "item_name": "production_telemetry_inputs",
            "label": "Production telemetry inputs",
            "owner": "Operations and analytics owner",
            "sources": [
                "/api/v1/commercial_operations_readiness/latest",
                "/api/v1/analytics_snapshots/latest",
                "production request logs",
                "incident drill record",
                "backup restore proof",
            ],
            "evidence_type": "proposed_until_production",
            "completion_state": "warning",
            "source_gap_status": "production_input_required",
            "evidence": (
                f"operations_production_evidence_action_count="
                f"{operations['operations_summary']['production_evidence_action_count']}; "
                f"analytics_measurement_status={analytics['measurement_status']}"
            ),
            "action": "Capture production telemetry, SLO evidence, incident drill, and restore proof in the buyer environment.",
            "exit_criteria": "First production telemetry snapshot and operations proof are attached or explicitly waived.",
        },
        {
            "item_name": "commercial_signature_inputs",
            "label": "Commercial signature inputs",
            "owner": "Buyer sponsor, procurement owner, and deal owner",
            "sources": ["signed order/MSA", "DPA/security acceptance", "purchase order", "go-live authorization"],
            "evidence_type": "buyer_signature_required",
            "completion_state": "warning",
            "source_gap_status": "buyer_signature_required",
            "evidence": (
                f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}; "
                "signed order, DPA/security acceptance, budget/PO, and go-live authorization are buyer inputs."
            ),
            "action": "Collect signatures, approvals, or waivers before representing launch readiness as closed-won.",
            "exit_criteria": "Buyer accepts all signature, DPA/security, budget, and go-live inputs.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_launch_readiness.md", "docs/commercial_go_to_market_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review process delay is not a launch blocker unless a concrete failure is produced.",
            "action": "Continue launch readiness work while queued review processes are pending.",
            "exit_criteria": "Only concrete product, security, API contract, or document failures block launch readiness.",
        },
        {
            "item_name": "packaging_decision",
            "label": "Packaging decision",
            "owner": "Procurement and security reviewer",
            "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if gtm["library_split_decision"]["decision"] == "keep_single_product"
            else "warning",
            "evidence": gtm["library_split_decision"]["reason"],
            "action": "Keep one deployable enterprise control-plane product until extraction triggers are real.",
            "exit_criteria": "Do not create a separate library, Git submodule, or extracted package for this launch gate.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in launch_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    buyer_environment_gap_count = sum(
        1 for item in launch_items if item.get("source_gap_status") == "buyer_environment_required"
    )
    production_telemetry_gap_count = sum(
        1 for item in launch_items if item.get("source_gap_status") == "production_input_required"
    )
    commercial_signature_gap_count = sum(
        1 for item in launch_items if item.get("source_gap_status") == "buyer_signature_required"
    )
    external_input_group_count = (
        buyer_environment_gap_count + production_telemetry_gap_count + commercial_signature_gap_count
    )
    if blocked_count:
        launch_status = "commercial_launch_blocked"
    elif warning_count:
        launch_status = "commercial_launch_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        launch_status = "commercial_launch_ready"  # pragma: no cover

    return {
        "launch_status": launch_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_launch_readiness",
        "source_note": (
            "Commercial launch readiness packages repo-local GTM, runtime, acceptance, operator, admin, "
            "analytics, Figma, review-process, and packaging evidence separately from buyer environment, "
            "production telemetry, and commercial signature inputs; it is not a valuation guarantee, "
            "purchase commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
        ),
        "launch_summary": {
            "item_count": len(launch_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "external_input_group_count": external_input_group_count,
            "buyer_environment_gap_count": buyer_environment_gap_count,
            "production_telemetry_gap_count": production_telemetry_gap_count,
            "commercial_signature_gap_count": commercial_signature_gap_count,
            "review_process_is_blocker": gtm["review_process_policy"]["is_blocker"],
        },
        "launch_items": launch_items,
        "concrete_blockers": concrete_blockers,
        "launch_status_rules": [
            {
                "launch_status": "commercial_launch_ready",
                "rule": "GTM, runtime, acceptance, operator, admin, buyer environment, production telemetry, commercial signature, review policy, and packaging evidence are ready",
            },
            {
                "launch_status": "commercial_launch_ready_with_warnings",
                "rule": "repo-local launch packet is ready while buyer environment, production telemetry, or commercial signature inputs remain explicit warnings",
            },
            {
                "launch_status": "commercial_launch_blocked",
                "rule": "missing local launch packet evidence, concrete product defect, API contract failure, document mismatch, security failure, or Code Connect usage blocks launch readiness",
            },
        ],
        "review_process_policy": gtm["review_process_policy"],
        "related_runtime_reports": {
            "commercial_go_to_market_status": gtm["go_to_market_status"],
            "commercial_operations_status": operations["operations_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_acceptance_status": acceptance["acceptance_status"],
            "analytics_measurement_status": analytics["measurement_status"],
            **gtm["related_runtime_reports"],
        },
        "library_split_decision": gtm["library_split_decision"],
        "plugin_traceability": gtm["plugin_traceability"],
        "launch_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_launch_readiness/latest",
            "documentation": "docs/commercial_launch_readiness.md",
        },
    }


def commercial_completion_scorecard_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
    release_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the final KRW 2B commercial completion scorecard."""
    commercial = orchestrator.commercial_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    gtm = orchestrator.commercial_go_to_market_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    launch = orchestrator.commercial_launch_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
        release_authority=release_authority,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    concrete_blockers = list(launch["concrete_blockers"])
    if commercial["commercial_status"] == "not_commercial_ready":
        concrete_blockers.append("commercial_readiness_failed")
    if launch["launch_status"] == "commercial_launch_blocked":
        concrete_blockers.append("commercial_launch_blocked")
    concrete_blockers = list(dict.fromkeys(concrete_blockers))
    scorecard_items = [
        {
            "item_name": "product_design_evidence",
            "label": "Product Design evidence",
            "owner": "Product design owner",
            "sources": [
                "docs/plugin_driven_design_brief.md",
                "docs/commercial_plugin_operating_model.md",
                "docs/screen_design.md",
                "/admin",
                "/api/v1/commercial_readiness/latest",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "docs/plugin_driven_design_brief.md",
                    "docs/commercial_plugin_operating_model.md",
                    "docs/screen_design.md",
                )
            )
            and admin_state["agents"]
            else "blocked",
            "evidence": "Buyer, operator, security/compliance, and procurement workflows map to admin and readiness evidence.",
            "action": "Keep buyer evidence paths visible in the existing admin control plane.",
            "exit_criteria": "Every persona has a product/API/docs evidence path.",
        },
        {
            "item_name": "figma_artifacts",
            "label": "Figma artifacts",
            "owner": "Figma owner",
            "sources": [
                "docs/figma_artifacts.md",
                "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            ],
            "evidence_type": "figma_artifact",
            "completion_state": "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "evidence": "Editable design, FigJam diagrams, and stakeholder artifact records exist without Code Connect.",
            "action": "Use Figma/FigJam artifacts for stakeholder review without generating Code Connect metadata.",
            "exit_criteria": "Figma artifacts are recorded and Code Connect remains unused.",
        },
        {
            "item_name": "superpowers_plan_evidence",
            "label": "Superpowers plan evidence",
            "owner": "Implementation owner",
            "sources": [
                "docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md",
                "docs/superpowers/plans/2026-07-02-commercial-launch-readiness.md",
                "tests/test_commercial_completion_scorecard.py",
            ],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if has_file("docs/superpowers/plans/2026-07-02-commercial-completion-scorecard-runtime.md")
            and has_file("tests/test_commercial_completion_scorecard.py")
            else "blocked",
            "evidence": "Dated plans and focused tests define files, expected failures, implementation, and verification commands.",
            "action": "Keep TDD plans and verification commands committed with the scorecard.",
            "exit_criteria": "Plan and focused test exist for the runtime scorecard.",
        },
        {
            "item_name": "ponytail_packaging_decision",
            "label": "Ponytail packaging decision",
            "owner": "Procurement and security reviewer",
            "sources": ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready"
            if launch["library_split_decision"]["decision"] == "keep_single_product"
            else "warning",
            "evidence": launch["library_split_decision"]["reason"],
            "action": "Keep one repository and one deployable product until extraction triggers are real.",
            "exit_criteria": "No separate library, Git submodule, or extracted package is created for this increment.",
        },
        {
            "item_name": "data_analytics_truthfulness",
            "label": "Data Analytics truthfulness",
            "owner": "Analytics owner",
            "sources": [
                "docs/analytics_spec.md",
                "/api/v1/analytics_snapshots/latest",
                "/api/v1/commercial_launch_readiness/latest",
            ],
            "evidence_type": "measured_local",
            "completion_state": "ready"
            if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot"
            else "blocked",
            "evidence": "Measured local evidence and proposed production or buyer-specific inputs are separated.",
            "action": "Do not present proposed buyer or production inputs as measured product results.",
            "exit_criteria": "Every commercial KPI has an evidence type and source expectation.",
        },
        {
            "item_name": "runtime_endpoint_chain",
            "label": "Runtime endpoint chain",
            "owner": "Platform operator",
            "sources": [
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_go_to_market_readiness/latest",
                "/api/v1/commercial_launch_readiness/latest",
                "/api/v1/commercial_completion_scorecards/latest",
            ],
            "evidence_type": "repository_and_runtime_artifact",
            "completion_state": "ready"
            if commercial["commercial_status"] != "not_commercial_ready"
            and gtm["go_to_market_status"] != "commercial_go_to_market_blocked"
            and launch["launch_status"] != "commercial_launch_blocked"
            else "blocked",
            "evidence": (
                f"commercial_status={commercial['commercial_status']}; "
                f"go_to_market_status={gtm['go_to_market_status']}; "
                f"launch_status={launch['launch_status']}"
            ),
            "action": "Expose completion status through the same admin-protected runtime API chain.",
            "exit_criteria": "Runtime chain has no blocked local evidence gate.",
        },
        {
            "item_name": "verification_packet",
            "label": "Verification packet",
            "owner": "Technical reviewer",
            "sources": [
                "tests/test_commercial_completion_scorecard.py",
                "tests/test_commercial_launch_readiness.py",
                "tests/test_plugin_driven_artifacts.py",
                "tests/test_api_contract.py",
                "pytest -q",
            ],
            "evidence_type": "measured_local",
            "completion_state": "ready"
            if all(
                has_file(path)
                for path in (
                    "tests/test_commercial_completion_scorecard.py",
                    "tests/test_commercial_launch_readiness.py",
                    "tests/test_plugin_driven_artifacts.py",
                    "tests/test_api_contract.py",
                )
            )
            else "blocked",
            "evidence": "Focused completion, launch, artifact, and API contract tests are present.",
            "action": "Run focused tests and full pytest before presenting completion status.",
            "exit_criteria": "Focused tests, compileall, full pytest, and diff hygiene pass.",
        },
        {
            "item_name": "review_process_policy",
            "label": "Review process policy",
            "owner": "Deal owner",
            "sources": ["docs/commercial_completion_scorecard.md", "docs/commercial_launch_readiness.md"],
            "evidence_type": "repository_artifact",
            "completion_state": "ready",
            "evidence": "Review delay, model-review delay, and queued review automation are not product blockers.",
            "action": "Block only on concrete security, API contract, document, or functional defects.",
            "exit_criteria": "Review process delay remains non-blocking without concrete failure evidence.",
        },
        {
            "item_name": "production_buyer_followups",
            "label": "Production and buyer follow-ups",
            "owner": "Buyer sponsor, operations owner, and deal owner",
            "sources": [
                "/api/v1/commercial_launch_readiness/latest",
                "buyer environment",
                "production telemetry",
                "commercial signatures",
            ],
            "evidence_type": "external_input_required",
            "completion_state": "warning",
            "source_gap_status": "external_input_required",
            "evidence": (
                f"external_input_group_count={launch['launch_summary']['external_input_group_count']}; "
                f"buyer_signature_gap_count={gtm['go_to_market_summary']['buyer_signature_gap_count']}"
            ),
            "action": "Collect buyer environment, production telemetry, and signature inputs or explicit waivers.",
            "exit_criteria": "Buyer supplies or waives remaining external inputs.",
        },
    ]
    state_counts = Counter(item["completion_state"] for item in scorecard_items)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        completion_status = "commercial_completion_blocked"
    elif warning_count:
        completion_status = "commercial_completion_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        completion_status = "commercial_completion_ready"  # pragma: no cover

    return {
        "completion_status": completion_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_completion_scorecard",
        "source_note": (
            "Commercial completion scorecard aggregates repo-local product design, Figma, Superpowers, "
            "Ponytail, Data Analytics, runtime, verification, review-process, and packaging evidence "
            "separately from buyer and production follow-ups; it is not a valuation guarantee, purchase "
            "commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
        ),
        "completion_summary": {
            "item_count": len(scorecard_items),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "external_input_group_count": launch["launch_summary"]["external_input_group_count"],
            "review_process_is_blocker": launch["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "completion_items": scorecard_items,
        "concrete_blockers": concrete_blockers,
        "completion_status_rules": [
            {
                "completion_status": "commercial_completion_ready",
                "rule": "product design, Figma, Superpowers, Ponytail, Data Analytics, runtime, verification, review policy, packaging, and external inputs are ready",
            },
            {
                "completion_status": "commercial_completion_ready_with_warnings",
                "rule": "repo-local program completion evidence is ready while buyer environment, production telemetry, commercial signatures, or other external inputs remain explicit warnings",
            },
            {
                "completion_status": "commercial_completion_blocked",
                "rule": "security failure, API contract regression, document mismatch, reproducible product defect, missing local completion evidence, or Code Connect usage blocks completion",
            },
        ],
        "review_process_policy": launch["review_process_policy"],
        "related_runtime_reports": {
            "commercial_readiness_status": commercial["commercial_status"],
            "commercial_go_to_market_status": gtm["go_to_market_status"],
            "commercial_launch_status": launch["launch_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": launch["library_split_decision"],
        "plugin_traceability": launch["plugin_traceability"],
        "completion_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_completion_scorecards/latest",
            "documentation": "docs/commercial_completion_scorecard.md",
        },
    }


def commercial_buyer_acceptance_workflow_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return owner-scoped buyer acceptance workflow evidence."""
    acceptance = orchestrator.commercial_acceptance_check_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    completion = orchestrator.commercial_completion_scorecard_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    handoff = orchestrator.commercial_handoff_bundle_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def step(
        step_name: str,
        label: str,
        owner: str,
        sources: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        decision_rule: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(step_name, "buyer_acceptance_workflow.step_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("buyer acceptance workflow state must be ready, warning, or blocked")
        return {
            "step_name": step_name,
            "label": label,
            "owner": owner,
            "sources": sources,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "decision_rule": decision_rule,
            "next_action": next_action,
        }

    concrete_blockers = list(dict.fromkeys(acceptance["concrete_blockers"] + completion["concrete_blockers"]))
    acceptance_blocked = acceptance["acceptance_status"] == "commercial_acceptance_blocked"
    completion_blocked = completion["completion_status"] == "commercial_completion_blocked"
    local_runtime_state = "blocked" if acceptance_blocked or completion_blocked or concrete_blockers else "ready"
    workflow_steps = [
        step(
            "confirm_product_scope",
            "Confirm product scope",
            "Product owner",
            ["README.md", "docs/product_planning.md", "docs/commercial_readiness.md"],
            "repository_artifact",
            "ready" if all_files("README.md", "docs/product_planning.md", "docs/commercial_readiness.md") else "blocked",
            "Product remains one enterprise orchestration control plane.",
            "Proceed when the buyer reviews one compatible API plus one admin evidence surface.",
            "Restore product scope docs before buyer acceptance.",
        ),
        step(
            "confirm_integration_surface",
            "Confirm integration surface",
            "Platform reviewer",
            ["/v1/chat/completions", "docs/rest_api_design.md", "tests/test_api_contract.py"],
            "repository_artifact",
            "ready" if all_files("docs/rest_api_design.md", "tests/test_api_contract.py") else "blocked",
            "OpenAI-compatible API and API contract tests are present.",
            "Proceed when API compatibility evidence is present and tests pass.",
            "Restore REST docs or API contract tests before buyer acceptance.",
        ),
        step(
            "confirm_operator_evidence",
            "Confirm operator evidence",
            "Platform operator",
            ["/admin", "/admin/state", "docs/screen_design.md", "contextual_orchestrator/admin.py"],
            "repository_artifact",
            "ready" if all_files("docs/screen_design.md", "contextual_orchestrator/admin.py") else "blocked",
            "Admin console exposes operator evidence for pool, policy, trace, access, replay, analytics, and readiness.",
            "Proceed when operator state and commercial readiness surfaces are visible.",
            "Restore admin evidence docs or implementation before buyer acceptance.",
        ),
        step(
            "confirm_readiness_endpoints",
            "Confirm readiness endpoints",
            "Product owner",
            [
                "/api/v1/sales_readiness/latest",
                "/api/v1/commercial_readiness/latest",
                "/api/v1/commercial_acceptance_checks/latest",
                "/api/v1/commercial_completion_scorecards/latest",
            ],
            "measured_local",
            local_runtime_state,
            (
                f"commercial_acceptance_status={acceptance['acceptance_status']}; "
                f"commercial_completion_status={completion['completion_status']}"
            ),
            "Proceed when local runtime gates have no concrete blockers.",
            "Resolve blocked readiness, acceptance, or completion gates before buyer acceptance.",
        ),
        step(
            "confirm_security_posture",
            "Confirm security posture",
            "Security reviewer",
            ["SECURITY.md", "tests/test_security_hardening.py", ".github/workflows/security.yml"],
            "repository_artifact",
            "ready" if all_files("SECURITY.md", "tests/test_security_hardening.py", ".github/workflows/security.yml") else "blocked",
            "Security policy, hardening tests, and hosted security workflow metadata are present.",
            "Proceed when concrete security failures are absent.",
            "Fix concrete security failures; queued security checks alone are not blockers.",
        ),
        step(
            "confirm_metric_honesty",
            "Confirm metric honesty",
            "Analytics reviewer",
            ["/api/v1/analytics_snapshots/latest", "docs/analytics_spec.md"],
            "measured_local",
            "ready" if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot" else "blocked",
            "Analytics spec and local snapshot separate measured local evidence from proposed production or buyer inputs.",
            "Proceed when measured and proposed claims are not mixed.",
            "Restore analytics source labels before buyer acceptance.",
        ),
        step(
            "confirm_visual_review_path",
            "Confirm visual review path",
            "Stakeholder reviewer",
            ["docs/figma_artifacts.md", "Figma design file", "FigJam board", "Figma Slides deck"],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "Editable design, FigJam, and stakeholder artifacts are recorded without Code Connect.",
            "Proceed when visual artifacts are available for stakeholder review.",
            "Record Figma artifacts before buyer acceptance.",
        ),
        step(
            "confirm_packaging_decision",
            "Confirm packaging decision",
            "Procurement reviewer",
            ["docs/library_research.md", "docs/commercial_plugin_operating_model.md"],
            "repository_artifact",
            "ready" if completion["library_split_decision"]["decision"] == "keep_single_product" else "warning",
            completion["library_split_decision"]["reason"],
            "Proceed with one repository and one deployable product.",
            "Extract only after a second product, independent release cadence, or provenance trigger exists.",
        ),
        step(
            "confirm_production_inputs",
            "Confirm production inputs",
            "Operations owner",
            ["production telemetry", "support plan", "SLO evidence", "incident drill"],
            "proposed_until_production",
            "warning",
            "Production telemetry, support, SLO, and incident evidence require a deployment or paid onboarding environment.",
            "Proceed with warning when production inputs are explicitly caveated.",
            "Collect production evidence during buyer onboarding or mark an explicit waiver.",
        ),
        step(
            "confirm_buyer_specific_inputs",
            "Confirm buyer-specific inputs",
            "Buyer and account team",
            ["ROI model", "security questionnaire", "legal review", "deployment target"],
            "proposed_until_buyer_specific",
            "warning",
            "ROI, legal, procurement, and deployment inputs require a named buyer.",
            "Proceed with warning when buyer-specific inputs are explicit follow-ups.",
            "Collect buyer-specific inputs during account diligence.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in workflow_steps)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        workflow_status = "buyer_acceptance_workflow_blocked"
    elif warning_count:
        workflow_status = "buyer_acceptance_workflow_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        workflow_status = "buyer_acceptance_workflow_ready"  # pragma: no cover

    return {
        "workflow_status": workflow_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_buyer_acceptance_workflow",
        "source_note": (
            "Commercial buyer acceptance workflow maps runbook owners, runtime evidence, "
            "Figma artifacts, analytics truthfulness, review-process policy, and packaging "
            "decision into Go, Warning, and No-Go steps; it is not a valuation guarantee, "
            "purchase commitment, signed order, legal opinion, production compliance certificate, "
            "or revenue proof."
        ),
        "workflow_summary": {
            "step_count": len(workflow_steps),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "production_follow_up_count": sum(
                1 for item in workflow_steps if item["evidence_type"] == "proposed_until_production"
            ),
            "buyer_specific_follow_up_count": sum(
                1 for item in workflow_steps if item["evidence_type"] == "proposed_until_buyer_specific"
            ),
            "review_process_is_blocker": acceptance["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "acceptance_steps": workflow_steps,
        "concrete_blockers": concrete_blockers,
        "go_warning_no_go_rules": [
            {
                "workflow_status": "buyer_acceptance_workflow_ready",
                "rule": "all acceptance owners have ready evidence and no external production or buyer-specific inputs remain open",
            },
            {
                "workflow_status": "buyer_acceptance_workflow_ready_with_warnings",
                "rule": "repo-local buyer acceptance evidence is ready while production or buyer-specific inputs remain explicit warnings",
            },
            {
                "workflow_status": "buyer_acceptance_workflow_blocked",
                "rule": "security failure, API contract regression, document mismatch, reproducible product defect, missing acceptance path, or Code Connect usage blocks acceptance",
            },
        ],
        "review_process_policy": acceptance["review_process_policy"],
        "related_runtime_reports": {
            "commercial_acceptance_status": acceptance["acceptance_status"],
            "commercial_completion_status": completion["completion_status"],
            "buyer_handoff_status": handoff["bundle_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": completion["library_split_decision"],
        "plugin_traceability": completion["plugin_traceability"],
        "workflow_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_buyer_acceptance_workflows/latest",
            "documentation": "docs/commercial_buyer_acceptance_runbook.md",
        },
    }


def commercial_demo_scenario_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return buyer-demo scenarios for the KRW 2B completion standard."""
    completion = orchestrator.commercial_completion_scorecard_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    buyer_workflow = orchestrator.commercial_buyer_acceptance_workflow_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def step(
        step_name: str,
        label: str,
        persona: str,
        sources: list[str],
        runtime_endpoints: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        demo_action: str,
        expected_evidence: str,
    ) -> dict[str, Any]:
        require_object_name(step_name, "commercial_demo.step_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("commercial demo step state must be ready, warning, or blocked")
        return {
            "step_name": step_name,
            "label": label,
            "persona": persona,
            "sources": sources,
            "runtime_endpoints": runtime_endpoints,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "demo_action": demo_action,
            "expected_evidence": expected_evidence,
        }

    concrete_blockers = list(
        dict.fromkeys(completion["concrete_blockers"] + buyer_workflow["concrete_blockers"])
    )
    local_runtime_state = (
        "blocked"
        if completion["completion_status"] == "commercial_completion_blocked"
        or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
        or concrete_blockers
        else "ready"
    )
    event_counts = analytics.get("event_counts", {})
    recent_runs = admin_state.get("recent_workflow_runs", [])
    demo_steps = [
        step(
            "compatible_api_smoke",
            "Compatible API smoke",
            "Economic buyer",
            ["README.md", "docs/rest_api_design.md", "/v1/chat/completions"],
            ["/v1/chat/completions"],
            "measured_local",
            "ready"
            if all_files("README.md", "docs/rest_api_design.md")
            and event_counts.get("chat_completion_requested", 0) > 0
            else "blocked",
            f"successful_chat_completion_events={event_counts.get('chat_completion_requested', 0)}",
            "Run the OpenAI-compatible chat completion call used by the buyer application.",
            "The buyer sees a compatible response and the runtime records a local analytics event.",
        ),
        step(
            "conducted_workflow_trace",
            "Conducted workflow trace",
            "Platform operator",
            ["/admin", "/api/v1/workflow_runs", "docs/screen_design.md"],
            ["/admin", "/api/v1/workflow_runs"],
            "measured_local",
            "ready" if recent_runs and has_file("docs/screen_design.md") else "blocked",
            f"recent_workflow_run_count={len(recent_runs)}",
            "Open the admin trace view for a conducted workflow run.",
            "The operator can inspect mode, policy mode, selected agents, and run trace evidence.",
        ),
        step(
            "access_list_inspection",
            "Access-list inspection",
            "Compliance reviewer",
            ["docs/product_planning.md", "/api/v1/access_reports/{workflow_run_id}", "/admin"],
            ["/api/v1/access_reports/{workflow_run_id}", "/admin"],
            "repository_and_runtime_artifact",
            "ready" if has_file("docs/product_planning.md") else "blocked",
            "access reports are scoped to workflow_run_id and exposed through the admin surface",
            "Open the access report for the conducted workflow run.",
            "The reviewer sees why each agent had access to context, tools, and trace evidence.",
        ),
        step(
            "evaluation_replay",
            "Evaluation replay",
            "Quality reviewer",
            ["docs/screen_design.md", "/api/v1/evaluation_runs", "/admin"],
            ["/api/v1/evaluation_runs", "/admin"],
            "measured_local",
            "ready" if event_counts.get("evaluation_run_created", 0) > 0 else "blocked",
            f"evaluation_run_created_events={event_counts.get('evaluation_run_created', 0)}",
            "Replay the buyer prompt through the evaluation endpoint.",
            "The reviewer sees replay status and trace-backed verification evidence.",
        ),
        step(
            "admin_readiness_console",
            "Admin readiness console",
            "Economic buyer",
            [
                "/admin",
                "/api/v1/commercial_completion_scorecards/latest",
                "/api/v1/commercial_buyer_acceptance_workflows/latest",
                "/api/v1/commercial_demo_scenarios/latest",
            ],
            [
                "/admin",
                "/api/v1/commercial_completion_scorecards/latest",
                "/api/v1/commercial_buyer_acceptance_workflows/latest",
                "/api/v1/commercial_demo_scenarios/latest",
            ],
            "repository_and_runtime_artifact",
            local_runtime_state,
            (
                f"commercial_completion_status={completion['completion_status']}; "
                f"buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}"
            ),
            "Show the readiness card chain in the admin console.",
            "The buyer sees completion, buyer acceptance, and demo status without leaving one control plane.",
        ),
        step(
            "metric_truthfulness",
            "Metric truthfulness",
            "Compliance reviewer",
            ["docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
            ["/api/v1/analytics_snapshots/latest"],
            "measured_local",
            "ready"
            if has_file("docs/analytics_spec.md") and analytics["measurement_status"] == "local_runtime_snapshot"
            else "blocked",
            "measured local metrics remain separate from proposed production and buyer-specific metrics",
            "Review the analytics spec and local analytics endpoint.",
            "The reviewer can distinguish measured runtime data from proposed KPI definitions.",
        ),
        step(
            "figma_stakeholder_review",
            "Figma stakeholder review",
            "Stakeholder reviewer",
            [
                "docs/figma_artifacts.md",
                "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
                "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            ],
            [],
            "figma_artifact",
            "ready" if has_file("docs/figma_artifacts.md") else "blocked",
            "editable Figma and FigJam stakeholder artifacts are recorded without Code Connect",
            "Walk through the design file and FigJam diagram packet.",
            "Stakeholders review the product narrative, admin surface, and runtime flow as editable artifacts.",
        ),
        step(
            "buyer_acceptance_decision",
            "Buyer acceptance decision",
            "Economic buyer",
            [
                "docs/commercial_buyer_acceptance_runbook.md",
                "/api/v1/commercial_buyer_acceptance_workflows/latest",
            ],
            ["/api/v1/commercial_buyer_acceptance_workflows/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state,
            f"buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}",
            "Use the buyer acceptance workflow as the Go/Warning/No-Go decision record.",
            "The buyer can sign off on repo-local evidence while external follow-ups stay explicit.",
        ),
        step(
            "production_buyer_followups",
            "Production and buyer follow-ups",
            "Economic buyer",
            ["production telemetry", "ROI model", "security questionnaire", "support plan"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Production telemetry, named-buyer ROI, security questionnaire, and support plan require buyer input.",
            "Capture buyer-specific production, ROI, legal, and support inputs after the local demo.",
            "External inputs are tracked as warnings, not hidden as measured product evidence.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in demo_steps)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        demo_status = "commercial_demo_blocked"
    elif warning_count:
        demo_status = "commercial_demo_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        demo_status = "commercial_demo_ready"  # pragma: no cover
    required_runtime_endpoints = list(
        dict.fromkeys(
            endpoint
            for item in demo_steps
            for endpoint in item["runtime_endpoints"]
            if endpoint.startswith("/")
        )
    )

    return {
        "demo_status": demo_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_demo_scenarios",
        "source_note": (
            "Commercial demo scenarios package repo-local runtime, admin, analytics, Figma, "
            "buyer acceptance, review-policy, and packaging evidence for KRW 2,000,000,000 "
            "saleability review; it is not a valuation guarantee, purchase commitment, "
            "signed order, legal opinion, production compliance certificate, or revenue proof."
        ),
        "demo_narrative": {
            "title": "KRW 2B commercial control-plane buyer demo",
            "promise": (
                "Show one enterprise orchestration control plane with a compatible inference API, "
                "operator/admin evidence, trace and access visibility, evaluation replay, and truthful metrics."
            ),
            "audience": [
                "Economic buyer",
                "Platform operator",
                "Compliance reviewer",
                "Quality reviewer",
                "Stakeholder reviewer",
            ],
        },
        "demo_summary": {
            "step_count": len(demo_steps),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "persona_count": len({item["persona"] for item in demo_steps}),
            "endpoint_count": len(required_runtime_endpoints),
            "review_process_is_blocker": completion["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "demo_steps": demo_steps,
        "required_runtime_endpoints": required_runtime_endpoints,
        "concrete_blockers": concrete_blockers,
        "demo_status_rules": [
            {
                "demo_status": "commercial_demo_ready",
                "rule": "all demo steps are ready and no production or buyer-specific follow-ups remain open",
            },
            {
                "demo_status": "commercial_demo_ready_with_warnings",
                "rule": "repo-local demo evidence is ready while production, ROI, legal, support, or buyer-specific inputs remain explicit warnings",
            },
            {
                "demo_status": "commercial_demo_blocked",
                "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local demo evidence, or Code Connect usage blocks the demo",
            },
        ],
        "review_process_policy": completion["review_process_policy"],
        "related_runtime_reports": {
            "commercial_completion_status": completion["completion_status"],
            "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": completion["library_split_decision"],
        "plugin_traceability": completion["plugin_traceability"],
        "demo_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_demo_scenarios/latest",
            "documentation": "docs/commercial_demo_scenarios.md",
        },
    }


def commercial_proposal_packet_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return buyer proposal sections for the KRW 2B saleability standard."""
    completion = orchestrator.commercial_completion_scorecard_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    demo = orchestrator.commercial_demo_scenario_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    buyer_workflow = orchestrator.commercial_buyer_acceptance_workflow_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def section(
        section_name: str,
        label: str,
        owner: str,
        sources: list[str],
        runtime_endpoints: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        buyer_message: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(section_name, "commercial_proposal.section_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("commercial proposal section state must be ready, warning, or blocked")
        return {
            "section_name": section_name,
            "label": label,
            "owner": owner,
            "sources": sources,
            "runtime_endpoints": runtime_endpoints,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "buyer_message": buyer_message,
            "next_action": next_action,
        }

    concrete_blockers = list(
        dict.fromkeys(
            completion["concrete_blockers"]
            + demo["concrete_blockers"]
            + buyer_workflow["concrete_blockers"]
        )
    )
    local_runtime_state = (
        "blocked"
        if completion["completion_status"] == "commercial_completion_blocked"
        or demo["demo_status"] == "commercial_demo_blocked"
        or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
        or concrete_blockers
        else "ready"
    )
    proposal_sections = [
        section(
            "executive_summary",
            "Executive summary",
            "Deal owner",
            ["README.md", "docs/commercial_completion_scorecard.md", "/api/v1/commercial_completion_scorecards/latest"],
            ["/api/v1/commercial_completion_scorecards/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state if all_files("README.md", "docs/commercial_completion_scorecard.md") else "blocked",
            f"commercial_completion_status={completion['completion_status']}",
            "One enterprise orchestration control plane is ready for a KRW 2B buyer review with explicit caveats.",
            "Use the completion scorecard as the proposal cover evidence.",
        ),
        section(
            "product_scope",
            "Product scope",
            "Product owner",
            ["docs/product_planning.md", "docs/commercial_plugin_operating_model.md", "docs/library_research.md"],
            [],
            "repository_artifact",
            "ready"
            if all_files("docs/product_planning.md", "docs/commercial_plugin_operating_model.md", "docs/library_research.md")
            and completion["library_split_decision"]["decision"] == "keep_single_product"
            else "blocked",
            completion["library_split_decision"]["reason"],
            "The offer is one compatible API plus one admin evidence surface, not a split product suite.",
            "Keep proposal language centered on a single deployable control plane.",
        ),
        section(
            "buyer_value_case",
            "Buyer value case",
            "Economic buyer",
            ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/commercial_value_readiness/latest"],
            ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if value["value_status"] != "commercial_value_blocked"
            and has_file("docs/commercial_value_readiness.md")
            and analytics["measurement_status"] == "local_runtime_snapshot"
            else "blocked",
            f"value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
            "Measured local value evidence is separated from buyer-specific ROI inputs.",
            "Attach buyer ROI assumptions only after buyer discovery validates them.",
        ),
        section(
            "demo_and_acceptance_path",
            "Demo and acceptance path",
            "Product design owner",
            [
                "docs/commercial_demo_scenarios.md",
                "docs/commercial_buyer_acceptance_runbook.md",
                "/api/v1/commercial_demo_scenarios/latest",
                "/api/v1/commercial_buyer_acceptance_workflows/latest",
            ],
            ["/api/v1/commercial_demo_scenarios/latest", "/api/v1/commercial_buyer_acceptance_workflows/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state
            if all_files("docs/commercial_demo_scenarios.md", "docs/commercial_buyer_acceptance_runbook.md")
            else "blocked",
            f"commercial_demo_status={demo['demo_status']}; buyer_acceptance_workflow_status={buyer_workflow['workflow_status']}",
            "Buyer review can move from demo script to Go/Warning/No-Go acceptance without leaving the control plane.",
            "Run the demo packet and record the acceptance decision.",
        ),
        section(
            "technical_evidence",
            "Technical evidence",
            "Platform reviewer",
            ["docs/rest_api_design.md", "docs/screen_design.md", "contextual_orchestrator/api_contract.py", "/admin"],
            ["/v1/chat/completions", "/admin", "/api/v1/workflow_runs", "/api/v1/access_reports/{workflow_run_id}"],
            "repository_and_runtime_artifact",
            "ready"
            if all_files("docs/rest_api_design.md", "docs/screen_design.md", "contextual_orchestrator/api_contract.py")
            and admin_state["agents"]
            else "blocked",
            f"agent_count={len(admin_state['agents'])}; recent_workflow_run_count={len(admin_state['recent_workflow_runs'])}",
            "The buyer can verify API compatibility, trace evidence, and access-list evidence.",
            "Include endpoint list and admin review screenshots or live walkthrough in the proposal.",
        ),
        section(
            "security_and_compliance",
            "Security and compliance",
            "Security reviewer",
            ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
            ["/api/v1/commercial_security_attestations/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
            else "blocked",
            f"security_attestation_status={security['security_attestation_status']}",
            "Repo-local security evidence is present while external attestation and buyer DPA inputs stay explicit.",
            "Do not claim third-party attestation until supplied.",
        ),
        section(
            "implementation_and_operations",
            "Implementation and operations",
            "Operations owner",
            [
                "docs/commercial_onboarding_readiness.md",
                "docs/commercial_operations_readiness.md",
                "/api/v1/commercial_onboarding_readiness/latest",
                "/api/v1/commercial_operations_readiness/latest",
            ],
            ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and operations["operations_status"] != "commercial_operations_blocked"
            and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
            else "blocked",
            f"onboarding_status={onboarding['onboarding_status']}; operations_status={operations['operations_status']}",
            "Implementation and operations evidence is proposal-ready with production environment follow-ups separated.",
            "Convert buyer environment details into an onboarding checklist after selection.",
        ),
        section(
            "proposal_review_packet",
            "Proposal review packet",
            "Stakeholder reviewer",
            [
                "docs/commercial_proposal_packet.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-proposal-packet-runtime.md",
            ],
            ["/api/v1/commercial_proposal_packets/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if all_files(
                "docs/commercial_proposal_packet.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-proposal-packet-runtime.md",
            )
            else "blocked",
            "Proposal docs, FigJam artifact record, and implementation plan are committed as repo artifacts.",
            "Stakeholders can review the proposal packet as docs, runtime JSON, and FigJam flow.",
            "Keep Figma Code Connect out of the proposal workflow.",
        ),
        section(
            "commercial_terms_followups",
            "Commercial terms follow-ups",
            "Deal owner",
            ["docs/commercial_contract_readiness.md", "buyer order form", "legal review", "pricing approval"],
            ["/api/v1/commercial_contract_readiness/latest"],
            "proposed_until_buyer_specific",
            "warning",
            f"contract_status={contract['contract_status']}",
            "Order-form, legal, pricing approval, and signature inputs need named-buyer review.",
            "Collect buyer-specific legal and commercial terms or record explicit waiver.",
        ),
        section(
            "production_buyer_inputs",
            "Production and buyer inputs",
            "Buyer sponsor",
            ["production telemetry", "buyer ROI model", "support plan", "security questionnaire"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Production telemetry, buyer ROI model, support plan, and security questionnaire are external inputs.",
            "The proposal is locally ready while buyer-specific inputs remain caveated.",
            "Collect external evidence during proposal negotiation or paid onboarding.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in proposal_sections)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        proposal_status = "commercial_proposal_blocked"
    elif warning_count:
        proposal_status = "commercial_proposal_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        proposal_status = "commercial_proposal_ready"  # pragma: no cover
    required_runtime_endpoints = list(
        dict.fromkeys(
            endpoint
            for item in proposal_sections
            for endpoint in item["runtime_endpoints"]
            if endpoint.startswith("/")
        )
    )

    return {
        "proposal_status": proposal_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_proposal_packet",
        "source_note": (
            "Commercial proposal packet packages repo-local completion, demo, acceptance, value, "
            "security, contract, onboarding, operations, analytics, Figma, review-policy, and packaging "
            "evidence for KRW 2,000,000,000 buyer proposal review; it is not a valuation guarantee, "
            "purchase commitment, signed order, legal opinion, production compliance certificate, or revenue proof."
        ),
        "proposal_narrative": {
            "title": "KRW 2B commercial buyer proposal packet",
            "promise": (
                "Present one enterprise orchestration control plane with compatible API integration, "
                "operator evidence, buyer demo path, acceptance workflow, and truthful commercial caveats."
            ),
            "audience": [
                "Economic buyer",
                "Platform reviewer",
                "Security reviewer",
                "Operations owner",
                "Stakeholder reviewer",
                "Deal owner",
            ],
        },
        "proposal_summary": {
            "section_count": len(proposal_sections),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "endpoint_count": len(required_runtime_endpoints),
            "review_process_is_blocker": completion["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "proposal_sections": proposal_sections,
        "required_runtime_endpoints": required_runtime_endpoints,
        "concrete_blockers": concrete_blockers,
        "proposal_status_rules": [
            {
                "proposal_status": "commercial_proposal_ready",
                "rule": "all proposal sections are ready and no buyer-specific commercial or production inputs remain open",
            },
            {
                "proposal_status": "commercial_proposal_ready_with_warnings",
                "rule": "repo-local proposal evidence is ready while pricing, legal, ROI, production, support, or signature inputs remain explicit warnings",
            },
            {
                "proposal_status": "commercial_proposal_blocked",
                "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local proposal evidence, or Code Connect usage blocks the proposal",
            },
        ],
        "review_process_policy": completion["review_process_policy"],
        "related_runtime_reports": {
            "commercial_completion_status": completion["completion_status"],
            "commercial_demo_status": demo["demo_status"],
            "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_contract_status": contract["contract_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_operations_status": operations["operations_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": completion["library_split_decision"],
        "plugin_traceability": completion["plugin_traceability"],
        "proposal_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_proposal_packets/latest",
            "documentation": "docs/commercial_proposal_packet.md",
        },
    }


def commercial_purchase_approval_packet_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return buyer-side purchase approval gates for the KRW 2B standard."""
    proposal = orchestrator.commercial_proposal_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    close = orchestrator.commercial_close_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    procurement = orchestrator.commercial_procurement_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def gate(
        gate_name: str,
        label: str,
        owner: str,
        sources: list[str],
        runtime_endpoints: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        approval_question: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(gate_name, "commercial_purchase_approval.gate_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("commercial purchase approval gate state must be ready, warning, or blocked")
        return {
            "gate_name": gate_name,
            "label": label,
            "owner": owner,
            "sources": sources,
            "runtime_endpoints": runtime_endpoints,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "approval_question": approval_question,
            "next_action": next_action,
        }

    concrete_blockers = list(dict.fromkeys(proposal["concrete_blockers"] + close["concrete_blockers"]))
    local_runtime_state = (
        "blocked"
        if proposal["proposal_status"] == "commercial_proposal_blocked"
        or close["close_status"] == "commercial_close_blocked"
        or concrete_blockers
        else "ready"
    )
    approval_gates = [
        gate(
            "proposal_packet_ready",
            "Proposal packet ready",
            "Deal owner",
            ["docs/commercial_proposal_packet.md", "/api/v1/commercial_proposal_packets/latest"],
            ["/api/v1/commercial_proposal_packets/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state if has_file("docs/commercial_proposal_packet.md") else "blocked",
            f"commercial_proposal_status={proposal['proposal_status']}",
            "Can the buyer review one coherent proposal packet?",
            "Use the proposal packet as the approval cover artifact.",
        ),
        gate(
            "procurement_path_ready",
            "Procurement path ready",
            "Procurement owner",
            ["docs/commercial_procurement_readiness.md", "/api/v1/commercial_procurement_readiness/latest"],
            ["/api/v1/commercial_procurement_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if procurement["procurement_status"] != "commercial_procurement_blocked"
            and has_file("docs/commercial_procurement_readiness.md")
            else "blocked",
            f"commercial_procurement_status={procurement['procurement_status']}",
            "Can procurement validate license, rights, distribution, admin, and caveat evidence?",
            "Route the packet to procurement with buyer-specific inputs still marked as warnings.",
        ),
        gate(
            "contract_legal_packet_ready",
            "Contract and legal packet ready",
            "Legal owner",
            ["docs/commercial_contract_readiness.md", "/api/v1/commercial_contract_readiness/latest"],
            ["/api/v1/commercial_contract_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if contract["contract_status"] != "commercial_contract_blocked"
            and has_file("docs/commercial_contract_readiness.md")
            else "blocked",
            f"commercial_contract_status={contract['contract_status']}",
            "Can legal review support, privacy, audit, license, and order-form obligations?",
            "Collect final legal edits and buyer order-form fields outside the local runtime claim.",
        ),
        gate(
            "financial_value_case_ready",
            "Financial value case ready",
            "Economic buyer",
            ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/commercial_value_readiness/latest"],
            ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if value["value_status"] != "commercial_value_blocked"
            and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
            and analytics["measurement_status"] == "local_runtime_snapshot"
            else "blocked",
            f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
            "Can finance separate measured local evidence from buyer ROI assumptions?",
            "Attach buyer ROI and payback assumptions only after buyer discovery.",
        ),
        gate(
            "security_acceptance_ready",
            "Security acceptance ready",
            "Security owner",
            ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
            ["/api/v1/commercial_security_attestations/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
            else "blocked",
            f"commercial_security_attestation_status={security['security_attestation_status']}",
            "Can security approve repo-local controls while external attestations remain caveated?",
            "Collect buyer DPA, privacy, and third-party attestation evidence separately.",
        ),
        gate(
            "implementation_readiness_ready",
            "Implementation readiness ready",
            "Implementation owner",
            [
                "docs/commercial_onboarding_readiness.md",
                "docs/commercial_operations_readiness.md",
                "/api/v1/commercial_onboarding_readiness/latest",
                "/api/v1/commercial_operations_readiness/latest",
            ],
            ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and operations["operations_status"] != "commercial_operations_blocked"
            and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
            else "blocked",
            f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
            "Can implementation owners see onboarding and operations evidence before purchase approval?",
            "Turn buyer environment details into the paid onboarding plan.",
        ),
        gate(
            "close_readiness_ready",
            "Close readiness ready",
            "Deal owner",
            ["docs/commercial_close_readiness.md", "/api/v1/commercial_close_readiness/latest"],
            ["/api/v1/commercial_close_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if close["close_status"] != "commercial_close_blocked"
            and has_file("docs/commercial_close_readiness.md")
            else "blocked",
            f"commercial_close_status={close['close_status']}",
            "Can the buyer see final signature, budget, security, and go-live caveats before approval?",
            "Use close readiness as the bridge between local product evidence and buyer approvals.",
        ),
        gate(
            "approval_runtime_packet_ready",
            "Approval runtime packet ready",
            "Stakeholder reviewer",
            [
                "docs/commercial_purchase_approval_packet.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-purchase-approval-packet-runtime.md",
            ],
            ["/api/v1/commercial_purchase_approval_packets/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if all_files(
                "docs/commercial_purchase_approval_packet.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-purchase-approval-packet-runtime.md",
            )
            and admin_state["agents"]
            else "blocked",
            "Purchase approval docs, FigJam artifact record, plan, and admin runtime are present.",
            "Can stakeholders review the approval packet as docs, runtime JSON, and FigJam flow?",
            "Keep Figma Code Connect out of the approval workflow.",
        ),
        gate(
            "buyer_signature_authority",
            "Buyer signature authority",
            "Buyer sponsor and legal owner",
            ["signed order form", "MSA", "DPA", "security acceptance"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Signed order form, MSA, DPA, and final security acceptance require buyer authority.",
            "Does the buyer have an identified signer and legal approval path?",
            "Collect named signer and final legal/security approvals.",
        ),
        gate(
            "buyer_budget_po_authority",
            "Buyer budget and PO authority",
            "Finance and procurement owner",
            ["budget approval", "purchase order", "finance authority", "go-live authorization"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Budget approval, purchase order, finance authority, and go-live authorization require buyer input.",
            "Can finance issue the KRW 2B purchase order and approve go-live?",
            "Collect budget owner, PO path, and go-live authorization or explicit waiver.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in approval_gates)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        purchase_approval_status = "commercial_purchase_approval_blocked"
    elif warning_count:
        purchase_approval_status = "commercial_purchase_approval_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        purchase_approval_status = "commercial_purchase_approval_ready"  # pragma: no cover
    required_runtime_endpoints = list(
        dict.fromkeys(
            endpoint
            for item in approval_gates
            for endpoint in item["runtime_endpoints"]
            if endpoint.startswith("/")
        )
    )

    return {
        "purchase_approval_status": purchase_approval_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_purchase_approval_packet",
        "source_note": (
            "Commercial purchase approval packet packages repo-local proposal, close, procurement, "
            "contract, value, security, onboarding, operations, analytics, Figma, review-policy, and "
            "packaging evidence for KRW 2,000,000,000 buyer purchase approval; it is not a valuation "
            "guarantee, purchase commitment, signed order, legal opinion, production compliance "
            "certificate, or revenue proof."
        ),
        "approval_narrative": {
            "title": "KRW 2B buyer purchase approval packet",
            "promise": (
                "Give finance, procurement, legal, security, and implementation owners one runtime "
                "approval packet that separates local product evidence from buyer-specific authority inputs."
            ),
            "audience": [
                "Economic buyer",
                "Finance owner",
                "Procurement owner",
                "Legal owner",
                "Security owner",
                "Implementation owner",
            ],
        },
        "approval_summary": {
            "gate_count": len(approval_gates),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "endpoint_count": len(required_runtime_endpoints),
            "review_process_is_blocker": proposal["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "approval_gates": approval_gates,
        "required_runtime_endpoints": required_runtime_endpoints,
        "concrete_blockers": concrete_blockers,
        "purchase_approval_status_rules": [
            {
                "purchase_approval_status": "commercial_purchase_approval_ready",
                "rule": "all approval gates are ready and no buyer signature, budget, PO, or go-live inputs remain open",
            },
            {
                "purchase_approval_status": "commercial_purchase_approval_ready_with_warnings",
                "rule": "repo-local purchase approval evidence is ready while buyer signature authority, budget, PO, or go-live authorization remain explicit warnings",
            },
            {
                "purchase_approval_status": "commercial_purchase_approval_blocked",
                "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local approval evidence, or Code Connect usage blocks purchase approval",
            },
        ],
        "review_process_policy": proposal["review_process_policy"],
        "related_runtime_reports": {
            "commercial_proposal_status": proposal["proposal_status"],
            "commercial_close_status": close["close_status"],
            "commercial_procurement_status": procurement["procurement_status"],
            "commercial_contract_status": contract["contract_status"],
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_operations_status": operations["operations_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": proposal["library_split_decision"],
        "plugin_traceability": proposal["plugin_traceability"],
        "approval_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_purchase_approval_packets/latest",
            "documentation": "docs/commercial_purchase_approval_packet.md",
        },
    }


def commercial_due_diligence_room_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return buyer due diligence room sections for the KRW 2B standard."""
    purchase = orchestrator.commercial_purchase_approval_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    proposal = orchestrator.commercial_proposal_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    completion = orchestrator.commercial_completion_scorecard_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    demo = orchestrator.commercial_demo_scenario_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    buyer_workflow = orchestrator.commercial_buyer_acceptance_workflow_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    close = orchestrator.commercial_close_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    procurement = orchestrator.commercial_procurement_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def section(
        section_name: str,
        label: str,
        reviewer: str,
        sources: list[str],
        runtime_endpoints: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        diligence_question: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(section_name, "commercial_due_diligence.section_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("commercial due diligence section state must be ready, warning, or blocked")
        return {
            "section_name": section_name,
            "label": label,
            "reviewer": reviewer,
            "sources": sources,
            "runtime_endpoints": runtime_endpoints,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "diligence_question": diligence_question,
            "next_action": next_action,
        }

    concrete_blockers = list(
        dict.fromkeys(
            purchase["concrete_blockers"]
            + proposal["concrete_blockers"]
            + completion["concrete_blockers"]
            + demo["concrete_blockers"]
            + buyer_workflow["concrete_blockers"]
        )
    )
    local_runtime_state = (
        "blocked"
        if purchase["purchase_approval_status"] == "commercial_purchase_approval_blocked"
        or proposal["proposal_status"] == "commercial_proposal_blocked"
        or completion["completion_status"] == "commercial_completion_blocked"
        or demo["demo_status"] == "commercial_demo_blocked"
        or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
        or concrete_blockers
        else "ready"
    )
    diligence_sections = [
        section(
            "purchase_approval_packet",
            "Purchase approval packet",
            "Purchase committee",
            ["docs/commercial_purchase_approval_packet.md", "/api/v1/commercial_purchase_approval_packets/latest"],
            ["/api/v1/commercial_purchase_approval_packets/latest", "/api/v1/commercial_proposal_packets/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state if has_file("docs/commercial_purchase_approval_packet.md") else "blocked",
            f"commercial_purchase_approval_status={purchase['purchase_approval_status']}",
            "Can the buyer review one approval packet before diligence sign-off?",
            "Use the approval packet as the diligence room cover index.",
        ),
        section(
            "runtime_api_evidence",
            "Runtime API evidence",
            "Platform reviewer",
            [
                "docs/rest_api_design.md",
                "contextual_orchestrator/api_contract.py",
                "README.md",
                "/v1/chat/completions",
            ],
            [
                "/v1/chat/completions",
                "/api/v1/workflow_runs",
                "/api/v1/access_reports/{workflow_run_id}",
                "/api/v1/commercial_due_diligence_rooms/latest",
            ],
            "repository_and_runtime_artifact",
            "ready"
            if local_runtime_state == "ready"
            and all_files("docs/rest_api_design.md", "contextual_orchestrator/api_contract.py", "README.md")
            and admin_state["agents"]
            else "blocked",
            f"agent_count={len(admin_state['agents'])}; api_contract_present={has_file('contextual_orchestrator/api_contract.py')}",
            "Can platform reviewers verify compatible API and evidence endpoints?",
            "Keep API compatibility and evidence endpoints in the diligence index.",
        ),
        section(
            "admin_trace_evidence",
            "Admin trace evidence",
            "Operator reviewer",
            ["docs/screen_design.md", "/admin", "/admin/state", "workflow trace", "access report"],
            ["/admin", "/admin/state", "/api/v1/workflow_runs", "/api/v1/access_reports/{workflow_run_id}"],
            "repository_and_runtime_artifact",
            "ready"
            if all_files("docs/screen_design.md", "contextual_orchestrator/admin.py")
            and admin_state["agents"]
            and admin_state["recent_workflow_runs"]
            else "blocked",
            f"recent_workflow_run_count={len(admin_state['recent_workflow_runs'])}",
            "Can the operator show trace and access-list evidence in the admin console?",
            "Run one conduct workflow before a live diligence walkthrough.",
        ),
        section(
            "security_and_compliance",
            "Security and compliance",
            "Security reviewer",
            ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
            ["/api/v1/commercial_security_attestations/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
            else "blocked",
            f"commercial_security_attestation_status={security['security_attestation_status']}",
            "Can security separate repo-local controls from external attestation gaps?",
            "Do not claim third-party certification until supplied.",
        ),
        section(
            "commercial_terms",
            "Commercial terms",
            "Legal and procurement reviewers",
            [
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_close_readiness.md",
            ],
            [
                "/api/v1/commercial_contract_readiness/latest",
                "/api/v1/commercial_procurement_readiness/latest",
                "/api/v1/commercial_close_readiness/latest",
            ],
            "repository_and_runtime_artifact",
            "ready"
            if contract["contract_status"] != "commercial_contract_blocked"
            and procurement["procurement_status"] != "commercial_procurement_blocked"
            and close["close_status"] != "commercial_close_blocked"
            and all_files(
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_close_readiness.md",
            )
            else "blocked",
            (
                f"commercial_contract_status={contract['contract_status']}; "
                f"commercial_procurement_status={procurement['procurement_status']}; "
                f"commercial_close_status={close['close_status']}"
            ),
            "Can legal and procurement review terms, rights, and close caveats together?",
            "Attach buyer-specific order-form language outside the local runtime claim.",
        ),
        section(
            "value_and_analytics",
            "Value and analytics",
            "Economic reviewer",
            ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
            ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if value["value_status"] != "commercial_value_blocked"
            and analytics["measurement_status"] == "local_runtime_snapshot"
            and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
            else "blocked",
            f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
            "Can finance tell measured local evidence apart from buyer ROI assumptions?",
            "Keep proposed KPI targets separate from measured local runtime data.",
        ),
        section(
            "implementation_readiness",
            "Implementation readiness",
            "Implementation and operations reviewers",
            ["docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md"],
            ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and operations["operations_status"] != "commercial_operations_blocked"
            and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
            else "blocked",
            f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
            "Can implementation owners see onboarding, operations, incident, and handoff evidence?",
            "Convert buyer environment specifics into the paid onboarding plan.",
        ),
        section(
            "figma_and_design_review",
            "Figma and design review",
            "Product design reviewer",
            [
                "docs/commercial_due_diligence_room.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-due-diligence-room-runtime.md",
            ],
            ["/api/v1/commercial_due_diligence_rooms/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if all_files(
                "docs/commercial_due_diligence_room.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-due-diligence-room-runtime.md",
            )
            else "blocked",
            "Due diligence doc, FigJam artifact record, and implementation plan are committed.",
            "Can stakeholders inspect the diligence room as docs, runtime JSON, and FigJam?",
            "Use FigJam only; do not use Figma Code Connect.",
        ),
        section(
            "buyer_authority_documents",
            "Buyer authority documents",
            "Buyer sponsor",
            ["named buyer signer", "budget owner and purchase order", "buyer DPA or privacy acceptance"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Named signer, budget owner, PO, and buyer privacy acceptance require buyer authority.",
            "Does the buyer have authority artifacts ready for final diligence?",
            "Collect signer, PO, DPA/privacy acceptance, or explicit waiver.",
        ),
        section(
            "production_external_attestations",
            "Production and external attestations",
            "Production and security owners",
            ["production telemetry", "third-party security attestation", "hosted scan evidence"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Production telemetry and third-party attestations are external evidence, not local repo measurements.",
            "Can the buyer distinguish local readiness from production and third-party evidence?",
            "Collect hosted telemetry and external attestation after environment selection.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in diligence_sections)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        due_diligence_status = "commercial_due_diligence_blocked"
    elif warning_count:
        due_diligence_status = "commercial_due_diligence_ready_with_warnings"
    else:  # pragma: no cover - unreachable while this report carries literal buyer-specific warning sections
        due_diligence_status = "commercial_due_diligence_ready"  # pragma: no cover
    required_runtime_endpoints = list(
        dict.fromkeys(
            endpoint
            for item in diligence_sections
            for endpoint in item["runtime_endpoints"]
            if endpoint.startswith("/")
        )
    )

    return {
        "due_diligence_status": due_diligence_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_due_diligence_room",
        "source_note": (
            "Commercial due diligence room packages repo-local purchase approval, proposal, runtime, "
            "admin trace, security, contract, value, onboarding, operations, analytics, Figma, "
            "review-policy, and packaging evidence for KRW 2,000,000,000 buyer diligence; it is "
            "not a valuation guarantee, purchase commitment, signed order, legal opinion, production "
            "compliance certificate, third-party attestation, or revenue proof."
        ),
        "diligence_narrative": {
            "title": "KRW 2B commercial due diligence room",
            "promise": (
                "Give finance, procurement, legal, security, product, and implementation reviewers "
                "one evidence room that separates measured local product evidence from buyer-specific "
                "and external production artifacts."
            ),
            "audience": [
                "Economic buyer",
                "Finance owner",
                "Procurement owner",
                "Legal owner",
                "Security owner",
                "Platform reviewer",
                "Implementation owner",
            ],
        },
        "diligence_summary": {
            "section_count": len(diligence_sections),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "endpoint_count": len(required_runtime_endpoints),
            "review_process_is_blocker": purchase["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "diligence_sections": diligence_sections,
        "required_runtime_endpoints": required_runtime_endpoints,
        "buyer_missing_artifacts": [
            "named buyer signer",
            "budget owner and purchase order",
            "buyer DPA or privacy acceptance",
            "production telemetry",
            "third-party security attestation",
        ],
        "concrete_blockers": concrete_blockers,
        "due_diligence_status_rules": [
            {
                "due_diligence_status": "commercial_due_diligence_ready",
                "rule": "all diligence sections are ready and no buyer authority, production, or third-party evidence remains open",
            },
            {
                "due_diligence_status": "commercial_due_diligence_ready_with_warnings",
                "rule": "repo-local diligence room evidence is ready while buyer authority, production telemetry, or external attestations remain explicit warnings",
            },
            {
                "due_diligence_status": "commercial_due_diligence_blocked",
                "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local diligence evidence, or Code Connect usage blocks buyer diligence",
            },
        ],
        "review_process_policy": purchase["review_process_policy"],
        "related_runtime_reports": {
            "commercial_purchase_approval_status": purchase["purchase_approval_status"],
            "commercial_proposal_status": proposal["proposal_status"],
            "commercial_completion_status": completion["completion_status"],
            "commercial_demo_status": demo["demo_status"],
            "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
            "commercial_close_status": close["close_status"],
            "commercial_procurement_status": procurement["procurement_status"],
            "commercial_contract_status": contract["contract_status"],
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_operations_status": operations["operations_status"],
            "analytics_measurement_status": analytics["measurement_status"],
        },
        "library_split_decision": purchase["library_split_decision"],
        "plugin_traceability": purchase["plugin_traceability"],
        "due_diligence_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_due_diligence_rooms/latest",
            "documentation": "docs/commercial_due_diligence_room.md",
        },
    }


def commercial_investment_committee_memo_report(
    orchestrator: TaskOrchestrator,
    target_contract_value_krw: int = DEFAULT_COMMERCIAL_TARGET_VALUE_KRW,
    locale_bundles: dict[str, dict[str, str]] | None = None,
    security_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return executive investment committee memo sections for the KRW 2B standard."""
    due_diligence = orchestrator.commercial_due_diligence_room_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    purchase = orchestrator.commercial_purchase_approval_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    proposal = orchestrator.commercial_proposal_packet_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    completion = orchestrator.commercial_completion_scorecard_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    demo = orchestrator.commercial_demo_scenario_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    buyer_workflow = orchestrator.commercial_buyer_acceptance_workflow_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    close = orchestrator.commercial_close_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    procurement = orchestrator.commercial_procurement_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    contract = orchestrator.commercial_contract_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    value = orchestrator.commercial_value_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    security = orchestrator.commercial_security_attestation_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    onboarding = orchestrator.commercial_onboarding_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    operations = orchestrator.commercial_operations_readiness_report(
        target_contract_value_krw=target_contract_value_krw,
        locale_bundles=locale_bundles,
        security_profile=security_profile,
    )
    analytics = orchestrator.analytics_snapshot(locale_bundles=locale_bundles)
    admin_state = orchestrator.admin_state()
    root = Path(__file__).resolve().parents[2]

    def has_file(path: str) -> bool:
        return (root / path).is_file()

    def all_files(*paths: str) -> bool:
        return all(has_file(path) for path in paths)

    def section(
        section_name: str,
        label: str,
        reviewer: str,
        sources: list[str],
        runtime_endpoints: list[str],
        evidence_type: str,
        completion_state: str,
        evidence: str,
        committee_question: str,
        next_action: str,
    ) -> dict[str, Any]:
        require_object_name(section_name, "commercial_investment_committee.section_name")
        if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
            raise ValueError("commercial investment committee section state must be ready, warning, or blocked")
        return {
            "section_name": section_name,
            "label": label,
            "reviewer": reviewer,
            "sources": sources,
            "runtime_endpoints": runtime_endpoints,
            "evidence_type": evidence_type,
            "completion_state": completion_state,
            "evidence": evidence,
            "committee_question": committee_question,
            "next_action": next_action,
        }

    concrete_blockers = list(
        dict.fromkeys(
            due_diligence["concrete_blockers"]
            + purchase["concrete_blockers"]
            + proposal["concrete_blockers"]
            + completion["concrete_blockers"]
            + demo["concrete_blockers"]
            + buyer_workflow["concrete_blockers"]
        )
    )
    local_runtime_state = (
        "blocked"
        if due_diligence["due_diligence_status"] == "commercial_due_diligence_blocked"
        or purchase["purchase_approval_status"] == "commercial_purchase_approval_blocked"
        or proposal["proposal_status"] == "commercial_proposal_blocked"
        or completion["completion_status"] == "commercial_completion_blocked"
        or demo["demo_status"] == "commercial_demo_blocked"
        or buyer_workflow["workflow_status"] == "buyer_acceptance_workflow_blocked"
        or concrete_blockers
        else "ready"
    )
    memo_sections = [
        section(
            "executive_recommendation",
            "Executive recommendation",
            "Investment committee chair",
            [
                "docs/commercial_investment_committee_memo.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-investment-committee-memo-runtime.md",
            ],
            ["/api/v1/commercial_investment_committee_memos/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state
            if all_files(
                "docs/commercial_investment_committee_memo.md",
                "docs/figma_artifacts.md",
                "docs/superpowers/plans/2026-07-02-commercial-investment-committee-memo-runtime.md",
            )
            else "blocked",
            "Investment committee memo, FigJam artifact record, and implementation plan are committed.",
            "Can the committee recommend the KRW 2B purchase path with explicit conditions?",
            "Use this memo as the executive decision cover artifact.",
        ),
        section(
            "diligence_room_ready",
            "Due diligence room ready",
            "Diligence owner",
            ["docs/commercial_due_diligence_room.md", "/api/v1/commercial_due_diligence_rooms/latest"],
            ["/api/v1/commercial_due_diligence_rooms/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state if has_file("docs/commercial_due_diligence_room.md") else "blocked",
            f"commercial_due_diligence_status={due_diligence['due_diligence_status']}",
            "Can the memo point to a complete diligence room?",
            "Reference due diligence room sections instead of duplicating evidence.",
        ),
        section(
            "purchase_approval_ready",
            "Purchase approval ready",
            "Purchase sponsor",
            ["docs/commercial_purchase_approval_packet.md", "/api/v1/commercial_purchase_approval_packets/latest"],
            ["/api/v1/commercial_purchase_approval_packets/latest"],
            "repository_and_runtime_artifact",
            local_runtime_state if has_file("docs/commercial_purchase_approval_packet.md") else "blocked",
            f"commercial_purchase_approval_status={purchase['purchase_approval_status']}",
            "Can the committee see finance, procurement, legal, security, and implementation gates?",
            "Use the purchase approval packet as committee appendix A.",
        ),
        section(
            "financial_case",
            "Financial case",
            "Economic buyer",
            ["docs/commercial_value_readiness.md", "docs/analytics_spec.md", "/api/v1/analytics_snapshots/latest"],
            ["/api/v1/commercial_value_readiness/latest", "/api/v1/analytics_snapshots/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if value["value_status"] != "commercial_value_blocked"
            and analytics["measurement_status"] == "local_runtime_snapshot"
            and all_files("docs/commercial_value_readiness.md", "docs/analytics_spec.md")
            else "blocked",
            f"commercial_value_status={value['value_status']}; analytics_measurement_status={analytics['measurement_status']}",
            "Does the memo separate measured local evidence from buyer ROI assumptions?",
            "Attach buyer ROI model only after buyer discovery supplies it.",
        ),
        section(
            "risk_and_security_summary",
            "Risk and security summary",
            "Security reviewer",
            ["SECURITY.md", "docs/commercial_security_attestation.md", "/api/v1/commercial_security_attestations/latest"],
            ["/api/v1/commercial_security_attestations/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if security["security_attestation_status"] != "commercial_security_attestation_blocked"
            and all_files("SECURITY.md", "docs/commercial_security_attestation.md")
            else "blocked",
            f"commercial_security_attestation_status={security['security_attestation_status']}",
            "Are security risks explicit without claiming external certification?",
            "Keep third-party attestation outside measured local evidence.",
        ),
        section(
            "commercial_terms_summary",
            "Commercial terms summary",
            "Legal and procurement reviewers",
            [
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_close_readiness.md",
            ],
            [
                "/api/v1/commercial_contract_readiness/latest",
                "/api/v1/commercial_procurement_readiness/latest",
                "/api/v1/commercial_close_readiness/latest",
            ],
            "repository_and_runtime_artifact",
            "ready"
            if contract["contract_status"] != "commercial_contract_blocked"
            and procurement["procurement_status"] != "commercial_procurement_blocked"
            and close["close_status"] != "commercial_close_blocked"
            and all_files(
                "docs/commercial_contract_readiness.md",
                "docs/commercial_procurement_readiness.md",
                "docs/commercial_close_readiness.md",
            )
            else "blocked",
            (
                f"commercial_contract_status={contract['contract_status']}; "
                f"commercial_procurement_status={procurement['procurement_status']}; "
                f"commercial_close_status={close['close_status']}"
            ),
            "Can legal and procurement conditions be approved or tracked?",
            "Attach order-form details only after buyer legal review.",
        ),
        section(
            "implementation_readiness_summary",
            "Implementation readiness summary",
            "Implementation owner",
            ["docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md"],
            ["/api/v1/commercial_onboarding_readiness/latest", "/api/v1/commercial_operations_readiness/latest"],
            "repository_and_runtime_artifact",
            "ready"
            if onboarding["onboarding_status"] != "commercial_onboarding_blocked"
            and operations["operations_status"] != "commercial_operations_blocked"
            and all_files("docs/commercial_onboarding_readiness.md", "docs/commercial_operations_readiness.md")
            else "blocked",
            f"commercial_onboarding_status={onboarding['onboarding_status']}; commercial_operations_status={operations['operations_status']}",
            "Can implementation start after buyer environment details are supplied?",
            "Convert buyer environment details into the paid onboarding plan.",
        ),
        section(
            "design_and_figma_review",
            "Design and Figma review",
            "Product design reviewer",
            ["docs/figma_artifacts.md", "docs/commercial_investment_committee_memo.md"],
            ["/api/v1/commercial_investment_committee_memos/latest"],
            "repository_and_runtime_artifact",
            "ready" if all_files("docs/figma_artifacts.md", "docs/commercial_investment_committee_memo.md") else "blocked",
            "FigJam memo flow and Product Design scope are recorded without Code Connect.",
            "Can stakeholders inspect the memo flow in FigJam and runtime JSON?",
            "Keep Figma Code Connect out of the committee workflow.",
        ),
        section(
            "buyer_final_authority",
            "Buyer final authority",
            "Buyer sponsor",
            ["executive sponsor approval", "named signer", "budget owner", "purchase order"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Executive sponsor approval, named signer, budget owner, and purchase order require buyer authority.",
            "Can the buyer approve the final KRW 2B purchase authority?",
            "Collect final buyer authority artifacts or explicit waiver.",
        ),
        section(
            "production_external_evidence",
            "Production and external evidence",
            "Production and security owners",
            ["production telemetry", "third-party security attestation", "hosted scan evidence"],
            [],
            "proposed_until_buyer_specific",
            "warning",
            "Production telemetry, third-party security attestation, and hosted scan evidence are external inputs.",
            "Can the committee approve with production and external evidence still tracked as conditions?",
            "Collect hosted evidence after environment selection.",
        ),
    ]
    state_counts = Counter(item["completion_state"] for item in memo_sections)
    blocked_count = state_counts.get("blocked", 0) + len(concrete_blockers)
    warning_count = state_counts.get("warning", 0)
    if blocked_count:
        investment_committee_status = "commercial_investment_committee_blocked"
        recommendation_status = "do_not_recommend_until_blockers_cleared"
    elif warning_count:
        investment_committee_status = "commercial_investment_committee_ready_with_warnings"
        recommendation_status = "recommend_with_buyer_conditions"
    else:  # pragma: no cover - unreachable while external-evidence warning sections remain literal
        investment_committee_status = "commercial_investment_committee_ready"  # pragma: no cover
        recommendation_status = "recommend"  # pragma: no cover
    required_runtime_endpoints = list(
        dict.fromkeys(
            endpoint
            for item in memo_sections
            for endpoint in item["runtime_endpoints"]
            if endpoint.startswith("/")
        )
    )

    return {
        "investment_committee_status": investment_committee_status,
        "target_contract_value_krw": target_contract_value_krw,
        "target_contract_value_display": f"KRW {target_contract_value_krw:,}",
        "measurement_status": "local_commercial_investment_committee_memo",
        "source_note": (
            "Commercial investment committee memo packages repo-local due diligence, purchase approval, "
            "proposal, runtime, admin trace, security, contract, value, onboarding, operations, analytics, "
            "Figma, review-policy, and packaging evidence for KRW 2,000,000,000 executive review; it is "
            "not a valuation guarantee, purchase commitment, signed order, legal opinion, production "
            "compliance certificate, third-party attestation, or revenue proof."
        ),
        "executive_recommendation": {
            "title": "KRW 2B commercial investment committee memo",
            "recommendation_status": recommendation_status,
            "recommendation": (
                "Recommend committee review with buyer authority, production telemetry, and external "
                "attestation conditions tracked separately from measured local product evidence."
                if recommendation_status == "recommend_with_buyer_conditions"
                else "Do not recommend until concrete blockers are cleared."
                if recommendation_status == "do_not_recommend_until_blockers_cleared"
                else "Recommend committee approval with no open local or buyer-specific conditions."
            ),
            "audience": [
                "Investment committee chair",
                "Economic buyer",
                "Finance owner",
                "Procurement owner",
                "Legal owner",
                "Security owner",
                "Implementation owner",
            ],
        },
        "memo_summary": {
            "section_count": len(memo_sections),
            "ready_count": state_counts.get("ready", 0),
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "endpoint_count": len(required_runtime_endpoints),
            "review_process_is_blocker": due_diligence["review_process_policy"]["is_blocker"],
            "code_connect_used": False,
        },
        "memo_sections": memo_sections,
        "required_runtime_endpoints": required_runtime_endpoints,
        "committee_decision_questions": [
            "Is the product evidence sufficient for KRW 2B buyer review?",
            "Are buyer authority documents named and tracked?",
            "Are production and third-party evidence gaps explicit warnings?",
            "Is any concrete blocker present?",
        ],
        "buyer_missing_artifacts": due_diligence["buyer_missing_artifacts"]
        + ["executive sponsor approval", "investment committee sign-off"],
        "concrete_blockers": concrete_blockers,
        "investment_committee_status_rules": [
            {
                "investment_committee_status": "commercial_investment_committee_ready",
                "rule": "all memo sections are ready and no buyer authority, production, or third-party evidence remains open",
            },
            {
                "investment_committee_status": "commercial_investment_committee_ready_with_warnings",
                "rule": "repo-local committee memo evidence is ready while buyer authority, production telemetry, or external attestations remain explicit warnings",
            },
            {
                "investment_committee_status": "commercial_investment_committee_blocked",
                "rule": "security failure, API contract regression, document mismatch, runtime defect, missing local memo evidence, or Code Connect usage blocks committee recommendation",
            },
        ],
        "review_process_policy": due_diligence["review_process_policy"],
        "related_runtime_reports": {
            "commercial_due_diligence_status": due_diligence["due_diligence_status"],
            "commercial_purchase_approval_status": purchase["purchase_approval_status"],
            "commercial_proposal_status": proposal["proposal_status"],
            "commercial_completion_status": completion["completion_status"],
            "commercial_demo_status": demo["demo_status"],
            "buyer_acceptance_workflow_status": buyer_workflow["workflow_status"],
            "commercial_close_status": close["close_status"],
            "commercial_procurement_status": procurement["procurement_status"],
            "commercial_contract_status": contract["contract_status"],
            "commercial_value_status": value["value_status"],
            "commercial_security_attestation_status": security["security_attestation_status"],
            "commercial_onboarding_status": onboarding["onboarding_status"],
            "commercial_operations_status": operations["operations_status"],
            "analytics_measurement_status": analytics["measurement_status"],
            "admin_agent_count": len(admin_state["agents"]),
        },
        "library_split_decision": due_diligence["library_split_decision"],
        "plugin_traceability": due_diligence["plugin_traceability"],
        "committee_links": {
            "figma_design_file": "https://www.figma.com/design/vsZMd8WAv42HDRgcZuNcWk",
            "figjam_board": "https://www.figma.com/board/Wr8iMlB9SHkerHSjv0Pe0M",
            "runtime_endpoint": "/api/v1/commercial_investment_committee_memos/latest",
            "documentation": "docs/commercial_investment_committee_memo.md",
        },
    }


def _criterion(
    orchestrator: TaskOrchestrator,
    criterion_name: str,
    label: str,
    status: str,
    evidence: str,
    remediation: str,
) -> dict[str, str]:
    require_object_name(criterion_name, "sales_readiness.criterion_name")
    if status not in {"pass", "warn", "fail"}:  # pragma: no cover
        raise ValueError("sales readiness status must be pass, warn, or fail")
    return {
        "criterion_name": criterion_name,
        "status": status,
        "label": label,
        "evidence": evidence,
        "remediation": remediation,
    }


def _buyer_evidence_item(
    orchestrator: TaskOrchestrator,
    item_name: str,
    label: str,
    reviewer: str,
    sources: list[str],
    evidence_type: str,
    completion_state: str,
    evidence: str,
    next_action: str,
) -> dict[str, Any]:
    require_object_name(item_name, "buyer_evidence_manifest.item_name")
    if evidence_type not in {
        "measured_local",
        "repository_artifact",
        "figma_artifact",
        "proposed_until_production",
        "proposed_until_buyer_specific",
    }:  # pragma: no cover
        raise ValueError("buyer evidence type is invalid")
    if completion_state not in {"ready", "warning", "blocked"}:  # pragma: no cover
        raise ValueError("buyer evidence completion state must be ready, warning, or blocked")
    return {
        "item_name": item_name,
        "label": label,
        "reviewer": reviewer,
        "sources": sources,
        "evidence_type": evidence_type,
        "completion_state": completion_state,
        "evidence": evidence,
        "next_action": next_action,
    }


def _buyer_manifest_summary(orchestrator: TaskOrchestrator, items: list[dict[str, Any]]) -> dict[str, Any]:
    completion_counts = Counter(item["completion_state"] for item in items)
    evidence_counts = Counter(item["evidence_type"] for item in items)
    return {
        "total_items": len(items),
        "by_completion_state": {
            "ready": completion_counts.get("ready", 0),
            "warning": completion_counts.get("warning", 0),
            "blocked": completion_counts.get("blocked", 0),
        },
        "by_evidence_type": {
            "measured_local": evidence_counts.get("measured_local", 0),
            "repository_artifact": evidence_counts.get("repository_artifact", 0),
            "figma_artifact": evidence_counts.get("figma_artifact", 0),
            "proposed_until_production": evidence_counts.get("proposed_until_production", 0),
            "proposed_until_buyer_specific": evidence_counts.get("proposed_until_buyer_specific", 0),
        },
    }


def _security_posture_criterion(orchestrator: TaskOrchestrator, security_profile: dict[str, Any]) -> dict[str, str]:
    auth_mode = security_profile.get("auth_mode", "loopback_no_auth")
    issues: list[str] = []
    warnings: list[str] = []
    if auth_mode == "single_token":
        warnings.append("single bearer token shared by admin and inference scopes")
    elif auth_mode not in {"split_token", "external_bearer_verifier"}:
        issues.append("no bearer token configured outside loopback-only development")
    if security_profile.get("allow_public_bind"):
        issues.append("public bind is enabled")
    if security_profile.get("expose_trace_by_default"):
        issues.append("trace exposure is enabled by default")
    if int(security_profile.get("rate_limit_requests") or 0) <= 0:
        issues.append("request rate limiting is disabled")
    if int(security_profile.get("max_concurrent_runs") or 0) <= 0:
        issues.append("run concurrency limiting is disabled")

    if issues:
        status = "fail"
        evidence = "; ".join(issues)
        remediation = "Require bearer auth, private bind defaults, hidden traces, rate limits, and run limits."
    elif warnings:
        status = "warn"
        evidence = "; ".join(warnings)
        remediation = "For enterprise pilots, split admin and inference tokens before customer evaluation."
    else:
        status = "pass"
        auth_evidence = (
            "external bearer verifier"
            if auth_mode == "external_bearer_verifier"
            else "split tokens"
        )
        evidence = f"{auth_evidence}, private bind default, hidden traces, rate limits, and run limits are configured"
        remediation = "Keep these controls enabled for customer-facing pilots."

    return orchestrator._criterion("security_posture", "Security posture", status, evidence, remediation)


def _locale_readiness_criterion(orchestrator: TaskOrchestrator, analytics: dict[str, Any]) -> dict[str, str]:
    locale_metric = next(
        metric for metric in analytics["guardrails"] if metric["metric_name"] == "locale_key_parity"
    )
    missing = locale_metric.get("missing_keys", [])
    parity = locale_metric.get("value_percent")
    if parity == 100.0:
        status = "pass"
        evidence = "English and Korean admin locale keys are aligned"
        remediation = "Keep locale parity tests updated when adding operator copy."
    else:
        status = "warn" if missing else "fail"
        evidence = f"{parity}% locale key parity; missing keys: {', '.join(missing) or 'locale bundles absent'}"
        remediation = "Fill missing Korean and English operator labels before customer review."
    return orchestrator._criterion("locale_readiness", "Locale readiness", status, evidence, remediation)


def _provider_egress_criterion(orchestrator: TaskOrchestrator) -> dict[str, str]:
    # Deferred to keep this module free of an eager orchestrator import.
    from ..orchestrator import _is_local_provider_url

    unsafe = []
    remote = []
    for agent in orchestrator.agents:
        if agent.base_url.startswith("mock://"):
            continue
        if _is_local_provider_url(agent.base_url):
            continue
        remote.append(agent.id)
        parsed = urlparse(agent.base_url)
        if parsed.scheme != "https" or not agent.credential_name:
            unsafe.append(agent.id)
    if unsafe:
        status = "fail"
        evidence = f"unsafe provider egress config for agents: {', '.join(sorted(unsafe))}"
        remediation = "Use https provider endpoints with a named KV credential before enabling remote egress."
    else:
        status = "pass"
        evidence = (
            "mock providers only"
            if not remote
            else f"{len(remote)} remote providers use https and a named KV credential"
        )
        remediation = "Keep provider allow-list enforcement enabled for non-mock providers."
    return orchestrator._criterion("provider_egress_safety", "Provider egress safety", status, evidence, remediation)


def _criteria_by_name(orchestrator: TaskOrchestrator, criteria: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["criterion_name"]: row for row in criteria}


def _metrics_by_name(orchestrator: TaskOrchestrator, metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["metric_name"]: row for row in metrics}


def _commercial_documentation_profile(orchestrator: TaskOrchestrator) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    required_documents = [
        "README.md",
        "SECURITY.md",
        "docs/product_planning.md",
        "docs/rest_api_design.md",
        "docs/analytics_spec.md",
        "docs/commercial_readiness.md",
    ]
    missing_documents = [
        document_path
        for document_path in required_documents
        if not (root / document_path).is_file()
    ]
    return {
        "required_documents": required_documents,
        "missing_documents": missing_documents,
        "present_count": len(required_documents) - len(missing_documents),
        "required_count": len(required_documents),
        "has_security_policy": (root / "SECURITY.md").is_file(),
        "source": "repository documentation files",
    }


def _criteria_summary(orchestrator: TaskOrchestrator, criteria: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter(row["status"] for row in criteria)
    return {
        "pass": counts.get("pass", 0),
        "warn": counts.get("warn", 0),
        "fail": counts.get("fail", 0),
    }
