"""End-to-end durable provider catalog bootstrap contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading

import pytest

from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    get_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    ProviderDiscoveryError,
    ProviderModelSource,
)
from contextual_orchestrator.privacy_policy_analysis import PrivacyPolicyAssessment
from contextual_orchestrator.provider_bootstrap import PROVIDER_CREDENTIAL_NAMES
from contextual_orchestrator.provider_catalog_bootstrap import (
    AUTHENTICATION_FAILURE_CLASSIFICATION,
    TRANSIENT_FAILURE_CLASSIFICATION,
    UNKNOWN_FAILURE_CLASSIFICATION,
    bootstrap_provider_catalog_runtime,
    evaluate_provider_credential_inventory,
)
from contextual_orchestrator.provider_catalog_store import (
    InMemoryProviderCatalogStore,
)


def _environment() -> dict[str, str]:
    return {
        name: f"value-for-{name.casefold()}"
        for name in PROVIDER_CREDENTIAL_NAMES
    }


def _source(provider: str, credential: str) -> ProviderModelSource:
    return ProviderModelSource(
        provider_name=provider,
        credential_name=credential,
        list_url=f"https://{provider}.example/v1/models",
        chat_base_url=f"https://{provider}.example/v1",
    )


def _model(source: ProviderModelSource, model_id: str) -> DiscoveredModel:
    return DiscoveredModel(
        provider_name=source.provider_name,
        model_id=model_id,
        credential_name=source.credential_name,
        chat_base_url=source.chat_base_url,
        auth_scheme=source.auth_scheme,
        prompt_price_per_1k=1.0,
        completion_price_per_1k=2.0,
    )


def test_failed_provider_uses_persisted_last_known_good_model() -> None:
    """A later provider outage keeps its last successful compatible model."""
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        openrouter = _source("openrouter", "OPENROUTER_API_KEY")
        store = InMemoryProviderCatalogStore()

        first = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(openai, openrouter),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live"), _model(openrouter, "router-live")],
                [],
            ),
            model_limit=4,
        )
        assert first.catalog_model_count == 2
        assert first.last_known_good_model_count == 0

        second = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(openai, openrouter),
            discovery=lambda _sources: (
                [_model(openrouter, "router-new")],
                [ProviderDiscoveryError("openai", "secret-bearing detail")],
            ),
            model_limit=4,
        )
        assert second.live_discovered_model_count == 1
        assert second.catalog_model_count == 2
        assert second.last_known_good_model_count == 1
        assert second.catalog_refresh_failure_count == 1
        assert second.providers_with_errors == ("openai",)
        refreshes = second.as_dict()["catalog_refreshes"]
        assert isinstance(refreshes, list)
        assert [row["provider_account_id"] for row in refreshes] == [
            "openai_openai_api_key",
            "openrouter_openrouter_api_key",
        ]
        assert [row["refresh_status"] for row in refreshes] == [
            "failed",
            "succeeded",
        ]
        assert refreshes[0]["error_code"] == "provider_discovery_error"
        assert refreshes[1]["error_code"] is None
        assert all(row["finished_at"].endswith("+00:00") for row in refreshes)
        assert set(second.selected_agent_ids) == {
            "openai_gpt_live",
            "openrouter_router_new",
        }
        assert "secret-bearing detail" not in str(second.as_dict())
    finally:
        set_backend(None)


def test_empty_catalog_preserves_lkg_but_nonchat_success_withdraws_it() -> None:
    """Empty refresh is failure; authoritative non-chat success is withdrawal."""
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        store = InMemoryProviderCatalogStore()
        bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(openai,),
            discovery=lambda _sources: ([_model(openai, "gpt-live")], []),
            model_limit=1,
        )

        empty = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(openai,),
            discovery=lambda _sources: ([], []),
            model_limit=1,
        )
        assert empty.last_known_good_model_count == 1
        assert empty.catalog_model_count == 1

        try:
            bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=store,
                sources=(openai,),
                discovery=lambda _sources: (
                    [_model(openai, "text-embedding-3-small")],
                    [],
                ),
                model_limit=1,
            )
        except RuntimeError as error:
            assert "no persisted chat-compatible model" in str(error)
        else:
            raise AssertionError("non-chat-only authoritative catalog must fail")
    finally:
        set_backend(None)


def test_privacy_analysis_success_persists_and_empty_failure_preserves_lkg() -> None:
    """The opt-in bootstrap stores grounded evidence without erasing it on failure."""
    set_backend(InMemoryCredentialBackend())
    try:
        source = _source("openai", "OPENAI_API_KEY")
        model = _model(source, "gpt-live")
        model = type(model)(
            **{
                **model.__dict__,
                "privacy_policy_urls": ("https://provider.example/privacy",),
            }
        )
        evidence = PrivacyPolicyAssessment(
            subject_provider=source.provider_name,
            subject_credential=source.credential_name,
            subject_model=model.model_id,
            source_url=model.privacy_policy_urls[0],
            zero_data_retention_available=True,
            supports_no_training=True,
            supports_no_prompt_retention=True,
            evidence_quote="Prompts are not retained.",
            analyzer_provider="openrouter",
            analyzer_model="zdr-analyzer",
            observed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )
        store = InMemoryProviderCatalogStore()

        first = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(source,),
            discovery=lambda _sources: ([model], []),
            analyze_privacy_policies=True,
            privacy_analysis=lambda models: (list(models), [evidence]),
            model_limit=1,
        )
        assert first.privacy_assessment_count == 1
        assert store.privacy_assessments(source) == (evidence,)

        second = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=store,
            sources=(source,),
            discovery=lambda _sources: ([model], []),
            analyze_privacy_policies=True,
            privacy_analysis=lambda models: (list(models), []),
            model_limit=1,
        )
        assert second.privacy_assessment_count == 1
        assert store.privacy_assessments(source) == (evidence,)
    finally:
        set_backend(None)


def test_unexpected_discovery_failure_restores_entire_credential_inventory() -> None:
    """An unclassified bootstrap failure must not leave unvalidated secrets promoted."""
    set_backend(InMemoryCredentialBackend())
    try:
        previous = {
            name: f"previous-value-for-{name.casefold()}"
            for name in PROVIDER_CREDENTIAL_NAMES
        }
        for name, value in previous.items():
            register_credential(name, value)

        def fail_discovery(_sources):
            raise RuntimeError("unexpected discovery parser failure")

        with pytest.raises(RuntimeError, match="unexpected discovery parser failure"):
            bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=InMemoryProviderCatalogStore(),
                sources=(_source("openai", "OPENAI_API_KEY"),),
                discovery=fail_discovery,
                model_limit=1,
            )

        assert {
            name: get_credential(name)
            for name in PROVIDER_CREDENTIAL_NAMES
        } == previous
    finally:
        set_backend(None)


def test_concurrent_bootstraps_report_only_their_own_refresh_evidence() -> None:
    """A shared store must not mix concurrent bootstrap refresh evidence."""
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        openrouter = _source("openrouter", "OPENROUTER_API_KEY")
        store = InMemoryProviderCatalogStore()
        discoveries_ready = threading.Barrier(2)

        def run(source: ProviderModelSource):
            def discover(_sources):
                discoveries_ready.wait()
                return [_model(source, f"{source.provider_name}-live")], []

            return bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=store,
                sources=(source,),
                discovery=discover,
                model_limit=1,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            reports = tuple(executor.map(run, (openai, openrouter)))

        assert [
            [row.provider_account_id for row in report.catalog_refreshes]
            for report in reports
        ] == [
            ["openai_openai_api_key"],
            ["openrouter_openrouter_api_key"],
        ]
        assert len(store.refresh_evidence()) == 2
    finally:
        set_backend(None)


def test_transient_provider_outage_is_a_classified_and_tolerated_warning() -> None:
    """A real transient discovery error (e.g. HTTP 500) classifies as transient
    and the credential-inventory verdict tolerates it as a warning, not a
    failure -- end to end through the report the workflow actually consumes.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        report = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=InMemoryProviderCatalogStore(),
            sources=(openai, bytez),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live")],
                [ProviderDiscoveryError("bytez", "http_status_500")],
            ),
            model_limit=4,
        )
        assert dict(report.provider_error_classifications) == {
            "bytez": TRANSIENT_FAILURE_CLASSIFICATION
        }
        payload = report.as_dict()
        assert payload["provider_error_classifications"] == {
            "bytez": TRANSIENT_FAILURE_CLASSIFICATION
        }

        verdict = evaluate_provider_credential_inventory(payload, _environment())
        assert verdict.ok is True
        assert verdict.hard_fail_reason is None
        assert verdict.warning_message is not None
        assert "BYTEZ_API_KEY" in verdict.warning_message
    finally:
        set_backend(None)


def test_authentication_failure_is_classified_and_still_hard_fails() -> None:
    """A credential the provider itself rejects (401/403) must never be
    silently tolerated -- it would otherwise stay disabled forever with
    nobody alerted.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        for code in ("http_status_401", "http_status_403"):
            report = bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=InMemoryProviderCatalogStore(),
                sources=(openai, bytez),
                discovery=lambda _sources, code=code: (
                    [_model(openai, "gpt-live")],
                    [ProviderDiscoveryError("bytez", code)],
                ),
                model_limit=4,
            )
            assert dict(report.provider_error_classifications) == {
                "bytez": AUTHENTICATION_FAILURE_CLASSIFICATION
            }

            verdict = evaluate_provider_credential_inventory(
                report.as_dict(), _environment()
            )
            assert verdict.ok is False
            assert verdict.warning_message is None
            assert "not a tolerated transient outage" in verdict.hard_fail_reason
            assert "'BYTEZ_API_KEY': 'authentication_failure'" in verdict.hard_fail_reason
            assert "BYTEZ_API_KEY" in verdict.hard_fail_reason
    finally:
        set_backend(None)


def test_persistent_client_error_is_not_excused_as_a_transient_outage() -> None:
    """A persistent non-auth 4xx (a wrong endpoint, a malformed request
    shape) is not retryable-transient by standard semantics and must not be
    tolerated as an isolated outage -- it would otherwise let a genuinely
    broken integration pass every scheduled sync indefinitely.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        for code in ("http_status_400", "http_status_404", "invalid_response"):
            report = bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=InMemoryProviderCatalogStore(),
                sources=(openai, bytez),
                discovery=lambda _sources, code=code: (
                    [_model(openai, "gpt-live")],
                    [ProviderDiscoveryError("bytez", code)],
                ),
                model_limit=4,
            )
            assert dict(report.provider_error_classifications) == {
                "bytez": UNKNOWN_FAILURE_CLASSIFICATION
            }

            verdict = evaluate_provider_credential_inventory(
                report.as_dict(), _environment()
            )
            assert verdict.ok is False
            assert verdict.warning_message is None
            assert "not a tolerated transient outage" in verdict.hard_fail_reason
            assert "'BYTEZ_API_KEY': 'unknown_failure'" in verdict.hard_fail_reason
    finally:
        set_backend(None)


def test_genuinely_retryable_http_statuses_are_transient() -> None:
    """429 (rate limited), 408 (request timeout), and 5xx are exactly the
    conditions standard retry semantics call retryable -- confirm each one
    still gets the tolerated classification.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        for code in ("http_status_408", "http_status_429", "http_status_500", "http_status_503"):
            report = bootstrap_provider_catalog_runtime(
                environ=_environment(),
                catalog_store=InMemoryProviderCatalogStore(),
                sources=(openai, bytez),
                discovery=lambda _sources, code=code: (
                    [_model(openai, "gpt-live")],
                    [ProviderDiscoveryError("bytez", code)],
                ),
                model_limit=4,
            )
            assert dict(report.provider_error_classifications) == {
                "bytez": TRANSIENT_FAILURE_CLASSIFICATION
            }
            verdict = evaluate_provider_credential_inventory(
                report.as_dict(), _environment()
            )
            assert verdict.ok is True
            assert verdict.hard_fail_reason is None
    finally:
        set_backend(None)


def test_durable_rollback_with_auth_failure_still_hard_fails() -> None:
    """A rollback that restores an old-but-still-valid credential value (the
    durable-KV production path, simulated here by pre-registering a value
    before bootstrap so ``previous_credentials`` is non-``None``) must not
    let ``registered_credentials`` look complete and skip classification.
    An authentication failure for that provider must still hard-fail even
    though the credential name never actually drops out of
    ``registered_credentials``.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        # Simulate a prior successful run having already durably registered
        # BYTEZ_API_KEY, so this run's rollback restores that old value
        # rather than clearing it to None.
        register_credential("BYTEZ_API_KEY", "previous-value-for-bytez_api_key")

        report = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=InMemoryProviderCatalogStore(),
            sources=(openai, bytez),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live")],
                [ProviderDiscoveryError("bytez", "http_status_401")],
            ),
            model_limit=4,
        )
        # The durable-rollback signature this bug targets: the credential is
        # restored to its old value, not cleared, so it stays "registered".
        assert "BYTEZ_API_KEY" in report.registered_credentials
        assert "BYTEZ_API_KEY" in report.restored_credentials
        assert get_credential("BYTEZ_API_KEY") == "previous-value-for-bytez_api_key"

        verdict = evaluate_provider_credential_inventory(
            report.as_dict(), _environment()
        )
        assert verdict.ok is False
        assert verdict.warning_message is None
        assert "not a tolerated transient outage" in verdict.hard_fail_reason
        assert "'BYTEZ_API_KEY': 'authentication_failure'" in verdict.hard_fail_reason
    finally:
        set_backend(None)


def test_durable_rollback_with_two_simultaneous_failures_still_hard_fails() -> None:
    """Two providers failing at once, both restored to durable prior values
    (so neither drops out of ``registered_credentials``), must still hit the
    single-provider tolerance bound instead of silently reporting success.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        openrouter = _source("openrouter", "OPENROUTER_API_KEY")
        register_credential("BYTEZ_API_KEY", "previous-value-for-bytez_api_key")
        register_credential(
            "OPENROUTER_API_KEY", "previous-value-for-openrouter_api_key"
        )

        report = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=InMemoryProviderCatalogStore(),
            sources=(openai, bytez, openrouter),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live")],
                [
                    ProviderDiscoveryError("bytez", "http_status_500"),
                    ProviderDiscoveryError("openrouter", "timeout"),
                ],
            ),
            model_limit=4,
        )
        assert "BYTEZ_API_KEY" in report.registered_credentials
        assert "OPENROUTER_API_KEY" in report.registered_credentials
        assert set(report.restored_credentials) == {
            "BYTEZ_API_KEY",
            "OPENROUTER_API_KEY",
        }

        verdict = evaluate_provider_credential_inventory(
            report.as_dict(), _environment()
        )
        assert verdict.ok is False
        assert verdict.warning_message is None
        assert "too many providers degraded" in verdict.hard_fail_reason
    finally:
        set_backend(None)


def test_durable_rollback_with_single_transient_failure_is_still_tolerated() -> None:
    """The fix must not over-correct: a single transient failure whose
    credential is restored to a durable, still-valid prior value is still
    tolerated as a warning, not turned into an unconditional hard-fail.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        register_credential("BYTEZ_API_KEY", "previous-value-for-bytez_api_key")

        report = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=InMemoryProviderCatalogStore(),
            sources=(openai, bytez),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live")],
                [ProviderDiscoveryError("bytez", "http_status_500")],
            ),
            model_limit=4,
        )
        assert "BYTEZ_API_KEY" in report.registered_credentials
        assert "BYTEZ_API_KEY" in report.restored_credentials

        verdict = evaluate_provider_credential_inventory(
            report.as_dict(), _environment()
        )
        assert verdict.ok is True
        assert verdict.hard_fail_reason is None
        assert verdict.warning_message is not None
        assert "BYTEZ_API_KEY" in verdict.warning_message
    finally:
        set_backend(None)


def test_two_simultaneous_provider_failures_hard_fail_not_a_warning() -> None:
    """Tolerance is bounded to exactly one provider; a broader outage --
    more than one provider's credential missing at once -- must still fail
    the sync instead of reporting success on a stale catalog.
    """
    set_backend(InMemoryCredentialBackend())
    try:
        openai = _source("openai", "OPENAI_API_KEY")
        bytez = _source("bytez", "BYTEZ_API_KEY")
        openrouter = _source("openrouter", "OPENROUTER_API_KEY")
        report = bootstrap_provider_catalog_runtime(
            environ=_environment(),
            catalog_store=InMemoryProviderCatalogStore(),
            sources=(openai, bytez, openrouter),
            discovery=lambda _sources: (
                [_model(openai, "gpt-live")],
                [
                    ProviderDiscoveryError("bytez", "http_status_500"),
                    ProviderDiscoveryError("openrouter", "timeout"),
                ],
            ),
            model_limit=4,
        )
        assert set(report.providers_with_errors) == {"bytez", "openrouter"}
        assert "BYTEZ_API_KEY" not in report.registered_credentials
        assert "OPENROUTER_API_KEY" not in report.registered_credentials

        verdict = evaluate_provider_credential_inventory(
            report.as_dict(), _environment()
        )
        assert verdict.ok is False
        assert verdict.warning_message is None
        assert "too many providers degraded" in verdict.hard_fail_reason
    finally:
        set_backend(None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
