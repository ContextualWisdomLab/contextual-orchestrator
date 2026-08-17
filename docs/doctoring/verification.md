# Verification checklist

Moved off the product README. Each test file is a directly runnable script.
Hypothesis property tests live under `tests/fuzz/`; Atheris harnesses live
under `fuzz/`.

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
python tests/test_self_check.py
python tests/test_paper_contracts.py
python tests/test_admin_contract.py
python tests/test_conventions.py
python tests/test_api_contract.py
python tests/test_security_hardening.py
python tests/test_repository_security_metadata.py
python tests/test_product_planning_contract.py
python tests/test_plugin_driven_artifacts.py
python tests/test_analytics_runtime.py
python tests/test_sales_readiness.py
python tests/test_buyer_evidence_manifest.py
python tests/test_buyer_handoff_bundle.py
python tests/test_saleability_decision.py
python tests/test_commercial_evidence_export.py
python tests/test_commercial_acceptance_check.py
python tests/test_commercial_buyer_acceptance_workflow.py
python tests/test_commercial_release_candidate.py
python tests/test_commercial_gap_register.py
python tests/test_commercial_procurement_readiness.py
python tests/test_commercial_contract_readiness.py
python tests/test_commercial_onboarding_readiness.py
python tests/test_commercial_operations_readiness.py
python tests/test_commercial_security_attestation.py
python tests/test_commercial_value_readiness.py
python tests/test_commercial_close_readiness.py
python tests/test_commercial_go_to_market_readiness.py
python tests/test_commercial_launch_readiness.py
python tests/test_commercial_completion_scorecard.py
python tests/test_commercial_demo_scenarios.py
python tests/test_commercial_proposal_packet.py
python tests/test_commercial_purchase_approval_packet.py
python tests/test_commercial_due_diligence_room.py
python tests/test_commercial_investment_committee_memo.py
```

Or via pytest (conftest excludes the Atheris `fuzz/` directory from collection):

```bash
python -m pytest tests -q
```
