"""Three-way judge-failure split: misconfigured / unavailable / ordinary rejection.

ADR 0001 keeps every judge failure fail-closed (``accepted`` is ``False``).
What differs is whether the failure says anything about the *candidate*:

* ``judge_status == "misconfigured"`` -- no judge can run at all (fast-mlsirm
  missing/broken, the judge cannot be constructed, or no eligible judge agent).
* ``judge_status == "unavailable"`` -- the judge's own provider call hit a
  transient infrastructure failure (timeout, OSError, an error the canonical
  provider taxonomy marks retryable, endpoint unavailable, spend budget).
* no ``judge_status`` -- everything else, including failures the candidate
  answer can cause (request too large, missing assistant content, structured
  output exhausted, parse/encoding errors) and unknown exceptions. These stay
  ordinary rejections exactly as on ``main``: a quality-ledger failure is
  recorded and ``route_once`` cascades to the next candidate.

Unjudged verdicts (the first two) record no ledger/IRT observation, stop the
``route_once`` cascade on the top-ranked answer, and are never cached.
"""

from __future__ import annotations

import logging
import socket
import ssl
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator import orchestrator as orchestrator_module  # noqa: E402
from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    EndpointUnavailableError,
    ProviderRequestTooLargeError,
    ProviderResponseError,
    StructuredOutputExhaustedError,
)
from contextual_orchestrator.provider_errors import (  # noqa: E402
    ProviderUpstreamError,
    classify_provider_failure,
)

MESSAGES = [{"role": "user", "content": "do work"}]


@pytest.fixture(autouse=True)
def _reset_misconfigured_log_throttle():
    """Each test sees a fresh per-reason ERROR throttle for misconfigured judges."""
    orchestrator_module._JUDGE_MISCONFIGURED_LOG_LAST.clear()
    yield
    orchestrator_module._JUDGE_MISCONFIGURED_LOG_LAST.clear()


@pytest.fixture
def real_fast_mlsirm():
    """Skip only the tests that drive the real fast-mlsirm judge when it is missing."""
    return pytest.importorskip("fast_mlsirm")


def _raw_http_error(code: int) -> urllib.error.HTTPError:
    """A raw urllib HTTPError, which is also an OSError subclass."""
    return urllib.error.HTTPError("https://judge.invalid/v1", code, f"HTTP {code}", None, None)


def _upstream(code: str, status: int | None, *, retryable: bool = True) -> ProviderUpstreamError:
    return ProviderUpstreamError(
        agent_id="judge",
        model="mock",
        error_code=code,
        message=f"judge upstream {code}",
        client_status=status or 502,
        provider_status=status,
        retryable=retryable,
    )


def _classified(exc: BaseException) -> ProviderUpstreamError:
    """What the gateway's provider client actually raises for ``exc``."""
    return classify_provider_failure(exc, agent_id="judge", model="mock")


def _nxdomain() -> socket.gaierror:
    return socket.gaierror(socket.EAI_NONAME, "Name or service not known")


#: Judge 5xx codes the canonical taxonomy marks non-retryable (501) or leaves
#: unmapped (505/507 and Cloudflare 520-530). They are judge outages, not
#: evidence about the answer.
NON_RETRYABLE_JUDGE_5XX = (501, 505, 507, 520, 522, 524, 530)


TRANSIENT_ERRORS = {
    "timeout": lambda: TimeoutError("judge timed out"),
    "oserror": lambda: ConnectionResetError("judge connection reset"),
    "upstream-503": lambda: _upstream("service_unavailable", 503),
    "upstream-502": lambda: _upstream("api_error", 502),
    "upstream-429": lambda: _upstream("rate_limit_exceeded", 429),
    "upstream-retryable-409": lambda: _upstream("conflict", 409),
    "upstream-rate-limited-storm": lambda: _upstream("provider_rate_limited", None),
    "upstream-connection": lambda: _upstream("provider_connection_error", None),
    "endpoint-unavailable": lambda: EndpointUnavailableError("endpoint_unavailable"),
    "budget-exceeded": lambda: BudgetExceededError("spend budget exhausted"),
    "raw-http-503": lambda: _raw_http_error(503),
    "raw-http-429": lambda: _raw_http_error(429),
    **{
        f"classified-http-{code}": (lambda code=code: _classified(_raw_http_error(code)))
        for code in NON_RETRYABLE_JUDGE_5XX
    },
    **{f"raw-http-{code}": (lambda code=code: _raw_http_error(code)) for code in (501, 520)},
    "classified-nxdomain": lambda: _classified(_nxdomain()),
    "classified-nxdomain-in-urlerror": lambda: _classified(urllib.error.URLError(_nxdomain())),
    "raw-nxdomain": _nxdomain,
    "classified-tls-verification": lambda: _classified(
        ssl.SSLCertVerificationError("certificate verify failed")
    ),
    "classified-tls-failure": lambda: _classified(ssl.SSLError("tls handshake failed")),
    "upstream-tls-verification": lambda: _upstream(
        "tls_verification_failed", None, retryable=False
    ),
}

CANDIDATE_OR_UNKNOWN_ERRORS = {
    "request-too-large": lambda: ProviderRequestTooLargeError(
        "request body exceeds every eligible provider limit", agent_id="judge", model="mock"
    ),
    "upstream-413": lambda: _upstream("request_too_large", 413, retryable=False),
    "assistant-content-missing": lambda: ProviderResponseError(
        "provider returned no assistant content", failure_kind="assistant_content_missing"
    ),
    "structured-output-exhausted": lambda: StructuredOutputExhaustedError(
        "every structured candidate violated the contract"
    ),
    "upstream-400": lambda: _upstream("invalid_request_error", 400, retryable=False),
    "classified-http-404": lambda: _classified(_raw_http_error(404)),
    "unicode": lambda: UnicodeEncodeError("utf-8", "x", 0, 1, "bad"),
    "value-error": lambda: ValueError("judge answer exceeds the maximum length"),
    "unknown-runtime": lambda: RuntimeError("all 1 candidate agents failed for role=judge"),
    "raw-http-400": lambda: _raw_http_error(400),
    "raw-http-413": lambda: _raw_http_error(413),
}


class _Criterion:
    def __init__(self, criterion_id: str, description: str, weight: float) -> None:
        self.criterion_id = criterion_id


class _StubJudge:
    """Judge that issues its provider call only for the primary worker's answer."""

    def __init__(self, adapter, *, mode: str, accept_threshold: float) -> None:
        self.adapter = adapter
        self.mode = mode

    def judge(self, *, task: str, answer: str, criteria: tuple) -> object:
        if "primary_worker" in answer:
            # Raises whatever the (faked) judge provider call raises.
            self.adapter.complete([{"role": "user", "content": "judge"}], mode=self.mode)
        return SimpleNamespace(
            accepted=True,
            rationale="backup answer accepted",
            criterion_scores={"evidence_quality": 1.0, "risk_signal": 1.0},
            usage=None,
            orchestration_mode=self.mode,
            to_irt_row=lambda *, item_type: (1, 1),
        )


def _stub_components() -> orchestrator_module.FastMLSIRMJudgeComponents:
    return orchestrator_module.FastMLSIRMJudgeComponents(
        judge_cls=_StubJudge, criterion_cls=_Criterion, format_error=LookupError
    )


def _two_workers(**kwargs) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("primary_worker", "mock", tags=("reasoning",), priority=5),
            ModelAgent("backup_worker", "mock", tags=("reasoning",), priority=1),
        ],
        **kwargs,
    )


def _route_with_judge_error(monkeypatch: pytest.MonkeyPatch, error: BaseException, components):
    orchestrator = _two_workers()
    invoked: list[str] = []

    def fake_invoke(primary, messages, **kwargs):
        if kwargs.get("role") == "judge":
            raise error
        invoked.append(primary.id)
        return f"{primary.id} answer", primary.id, "mock", {"completion_tokens": 10}

    monkeypatch.setattr(orchestrator, "_invoke", fake_invoke)
    with patch.object(
        orchestrator_module, "_resolve_fast_mlsirm_components", return_value=components
    ):
        result = orchestrator.route_once(MESSAGES)
    return orchestrator, result, invoked


def _assert_unjudged_primary(orchestrator, result, invoked, status: str) -> None:
    assert result["verification"]["accepted"] is False
    assert result["verification"]["judge_status"] == status
    assert result["trace"][-1]["realtime_judge"]["judge_status"] == status
    assert invoked == ["primary_worker"]
    assert result["answer"] == "primary_worker answer"
    for member in ("primary_worker", "backup_worker"):
        assert orchestrator._quality_router.member_observation_count(member) == 0


def _assert_ordinary_rejection_then_backup(orchestrator, result, invoked) -> None:
    """Exactly main's behaviour: primary rejected + failure recorded, backup served."""
    assert invoked == ["primary_worker", "backup_worker"]
    assert result["answer"] == "backup_worker answer"
    assert result["verification"]["accepted"] is True
    assert "judge_status" not in result["verification"]
    assert orchestrator._quality_router.member_report("primary_worker")["failure_count"] == 1
    assert orchestrator._quality_router.member_report("backup_worker")["success_count"] == 1


# -- route_once: judge provider call raises (stub judge re-raises the adapter error) --


@pytest.mark.parametrize("make_error", TRANSIENT_ERRORS.values(), ids=TRANSIENT_ERRORS.keys())
def test_transient_judge_provider_failure_is_unavailable(monkeypatch, make_error) -> None:
    orchestrator, result, invoked = _route_with_judge_error(
        monkeypatch, make_error(), _stub_components()
    )
    _assert_unjudged_primary(orchestrator, result, invoked, "unavailable")
    assert "failed closed" in result["verification"]["reason"]


@pytest.mark.parametrize(
    "make_error", CANDIDATE_OR_UNKNOWN_ERRORS.values(), ids=CANDIDATE_OR_UNKNOWN_ERRORS.keys()
)
def test_candidate_caused_or_unknown_judge_failure_stays_an_ordinary_rejection(
    monkeypatch, make_error
) -> None:
    orchestrator, result, invoked = _route_with_judge_error(
        monkeypatch, make_error(), _stub_components()
    )
    _assert_ordinary_rejection_then_backup(orchestrator, result, invoked)


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        (_raw_http_error(400), False),
        (_raw_http_error(413), False),
        (_raw_http_error(404), False),
        (_raw_http_error(503), True),
        (_raw_http_error(429), True),
        (SimpleNamespace(status=413), False),
        (SimpleNamespace(status=502), True),
        (ConnectionResetError("reset"), True),
    ],
    ids=["http-400", "http-413", "http-404", "http-503", "http-429", "status-413", "status-502",
         "plain-oserror"],
)
def test_http_status_decides_before_the_oserror_fallback(error, transient) -> None:
    """``HTTPError`` subclasses ``OSError``: its status must decide, never the OSError check."""
    assert orchestrator_module._is_transient_judge_failure(error) is transient


def test_unjudged_stop_returns_the_current_candidates_answer(monkeypatch) -> None:
    """After a judged rejection, an unjudged verdict stops on the *current* candidate.

    The primary's judged rejection stays recorded as a failure; the backup's
    answer (the attempt whose judging could not run) is returned, unaccepted.
    """
    orchestrator = _two_workers()
    invoked: list[str] = []
    judged: list[str] = []

    def fake_invoke(primary, messages, **kwargs):
        invoked.append(primary.id)
        return f"{primary.id} answer", primary.id, "mock", None

    def judge(_text, fallback, **_kwargs):
        judged.append(fallback["verifier_output"])
        verdict = {
            "accepted": False,
            "verifier_output": fallback["verifier_output"],
            "judge": "model",
        }
        if "primary_worker" in fallback["verifier_output"]:
            return {**verdict, "reason": "judged: insufficient evidence"}
        return {**verdict, "reason": "judge outage", "judge_status": "unavailable"}

    monkeypatch.setattr(orchestrator, "_invoke", fake_invoke)
    monkeypatch.setattr(orchestrator, "_model_judge_verification", judge)
    result = orchestrator.route_once(MESSAGES)

    assert invoked == ["primary_worker", "backup_worker"]
    assert result["answer"] == "backup_worker answer"
    assert result["trace"][-1]["agent_id"] == "backup_worker"
    assert result["verification"]["judge_status"] == "unavailable"
    assert orchestrator._quality_router.member_report("primary_worker")["failure_count"] == 1
    assert orchestrator._quality_router.member_observation_count("backup_worker") == 0


# -- route_once with the real fast-mlsirm judge (it wraps adapter errors) --------------


@pytest.mark.parametrize(
    ("make_error", "expected_status"),
    [
        (TRANSIENT_ERRORS["upstream-503"], "unavailable"),
        (TRANSIENT_ERRORS["timeout"], "unavailable"),
        *(
            (TRANSIENT_ERRORS[f"classified-http-{code}"], "unavailable")
            for code in NON_RETRYABLE_JUDGE_5XX
        ),
        (TRANSIENT_ERRORS["classified-nxdomain"], "unavailable"),
        (TRANSIENT_ERRORS["classified-tls-verification"], "unavailable"),
        (TRANSIENT_ERRORS["classified-tls-failure"], "unavailable"),
        (CANDIDATE_OR_UNKNOWN_ERRORS["request-too-large"], None),
        (CANDIDATE_OR_UNKNOWN_ERRORS["assistant-content-missing"], None),
        (CANDIDATE_OR_UNKNOWN_ERRORS["structured-output-exhausted"], None),
    ],
    ids=[
        "503",
        "timeout",
        *(f"http-{code}" for code in NON_RETRYABLE_JUDGE_5XX),
        "nxdomain",
        "tls-verification",
        "tls-failure",
        "too-large",
        "content-missing",
        "structured-exhausted",
    ],
)
def test_real_fast_mlsirm_judge_call_failure_is_classified_at_the_adapter_seam(
    monkeypatch, real_fast_mlsirm, make_error, expected_status
) -> None:
    """fast-mlsirm turns any adapter exception into ``JudgeFormatError`` (``from None``).

    The gateway therefore classifies the exception its own adapter observed at
    the provider-call boundary, not the wrapped library error.
    """
    orchestrator = _two_workers()
    error = make_error()

    def failing_proxy_send(agent, path, request, *args, **kwargs):
        raise error

    monkeypatch.setattr(orchestrator.client, "proxy_send", failing_proxy_send)
    verdict = orchestrator._model_judge_verification(
        "task", {"verifier_output": "primary_worker answer"}
    )
    assert verdict["accepted"] is False
    assert verdict.get("judge_status") == expected_status
    invalid_verdict = (
        "model judge returned an invalid structured verdict; verification failed closed"
    )
    if expected_status is None:
        assert verdict["reason"] == invalid_verdict
    else:
        # A judge outage must not be reported as a malformed verdict.
        assert verdict["reason"] == (
            "model judge call failed transiently; verification failed closed"
        )


# -- misconfigured: no eligible judge agent ---------------------------------------------


def test_no_eligible_judge_agent_is_misconfigured_and_logged(monkeypatch, caplog) -> None:
    orchestrator = _two_workers()
    invoked: list[str] = []
    original_ranked = orchestrator._ranked_agents

    def ranked_without_verifiers(text, role, *args, **kwargs):
        return [] if role == "verifier" else original_ranked(text, role, *args, **kwargs)

    def fake_invoke(primary, messages, **kwargs):
        invoked.append(primary.id)
        return f"{primary.id} answer", primary.id, "mock", None

    monkeypatch.setattr(orchestrator, "_ranked_agents", ranked_without_verifiers)
    monkeypatch.setattr(orchestrator, "_invoke", fake_invoke)
    with caplog.at_level(logging.ERROR, logger=orchestrator_module.__name__), patch.object(
        orchestrator_module, "_resolve_fast_mlsirm_components", return_value=_stub_components()
    ):
        result = orchestrator.route_once(MESSAGES)

    _assert_unjudged_primary(orchestrator, result, invoked, "misconfigured")
    assert result["verification"]["reason"] == "no eligible judge agent; verification failed closed"
    assert any(
        record.levelno == logging.ERROR and "misconfigured" in record.getMessage()
        for record in caplog.records
    )


def test_misconfigured_error_log_is_rate_limited_per_reason(monkeypatch, caplog) -> None:
    """ERROR once per distinct reason per interval; repeats in between drop to DEBUG."""
    clock = {"now": 1_000.0}
    monkeypatch.setattr(orchestrator_module, "_judge_log_clock", lambda: clock["now"])
    orchestrator = _two_workers()

    def levels(reason: str) -> list[int]:
        return [
            record.levelno
            for record in caplog.records
            if "misconfigured" in record.getMessage() and reason in record.getMessage()
        ]

    with caplog.at_level(logging.DEBUG, logger=orchestrator_module.__name__):
        for _ in range(3):
            orchestrator._unjudged_verdict("misconfigured", "reason one", "answer")
        orchestrator._unjudged_verdict("misconfigured", "reason two", "answer")
        clock["now"] += orchestrator_module.JUDGE_MISCONFIGURED_LOG_INTERVAL_SECONDS - 1
        orchestrator._unjudged_verdict("misconfigured", "reason one", "answer")
        clock["now"] += 1
        orchestrator._unjudged_verdict("misconfigured", "reason one", "answer")

    assert levels("reason one") == [
        logging.ERROR, logging.DEBUG, logging.DEBUG, logging.DEBUG, logging.ERROR
    ]
    assert levels("reason two") == [logging.ERROR]


def test_empty_allowed_judge_pool_is_misconfigured() -> None:
    orchestrator = _two_workers()
    with patch.object(
        orchestrator_module, "_resolve_fast_mlsirm_components", return_value=_stub_components()
    ):
        verdict = orchestrator._model_judge_verification(
            "task", {"verifier_output": "report"}, allowed_agent_ids=set()
        )
    assert verdict["accepted"] is False
    assert verdict["judge_status"] == "misconfigured"


# -- streaming and batch paths ------------------------------------------------------------


def test_stream_route_unjudged_answer_records_no_ledger_observation_and_is_marked() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))]
    )
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):
        answer = "".join(orchestrator.stream_route([{"role": "user", "content": "stream this"}]))
    assert answer.startswith("[general_agent:worker]")
    record = next(iter(orchestrator._workflow_runs.values()))
    assert record["verification"]["accepted"] is False
    assert record["verification"]["judge_status"] == "misconfigured"
    assert record["trace"][-1]["realtime_judge"]["judge_status"] == "misconfigured"
    assert orchestrator._quality_router.member_observation_count("general_agent") == 0


def test_stream_route_candidate_caused_judge_failure_still_records_a_failure(monkeypatch) -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))]
    )
    original_invoke = orchestrator._invoke

    def judge_too_large(primary, messages, **kwargs):
        if kwargs.get("role") == "judge":
            raise CANDIDATE_OR_UNKNOWN_ERRORS["request-too-large"]()
        return original_invoke(primary, messages, **kwargs)

    monkeypatch.setattr(orchestrator, "_invoke", judge_too_large)
    components = orchestrator_module.FastMLSIRMJudgeComponents(
        judge_cls=_AlwaysCallJudge, criterion_cls=_Criterion, format_error=LookupError
    )
    with patch.object(
        orchestrator_module, "_resolve_fast_mlsirm_components", return_value=components
    ):
        "".join(orchestrator.stream_route([{"role": "user", "content": "stream this"}]))
    record = next(iter(orchestrator._workflow_runs.values()))
    assert record["verification"]["accepted"] is False
    assert "judge_status" not in record["verification"]
    assert orchestrator._quality_router.member_report("general_agent")["failure_count"] == 1


class _AlwaysCallJudge(_StubJudge):
    def judge(self, *, task: str, answer: str, criteria: tuple) -> object:
        self.adapter.complete([{"role": "user", "content": "judge"}], mode=self.mode)
        raise AssertionError("unreachable: the faked judge call raises")  # pragma: no cover


def test_batch_route_unjudged_rows_are_marked_without_ledger_observations() -> None:
    orchestrator = TaskOrchestrator(
        [ModelAgent("general_agent", "m-model", tags=("reasoning", "writing"))]
    )
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):
        records = orchestrator.batch_route(["task one", "task two"])
    assert len(records) == 2
    for record in records:
        assert record["verification"]["accepted"] is False
        assert record["verification"]["judge_status"] == "misconfigured"
        assert record["trace"][0]["realtime_judge"]["judge_status"] == "misconfigured"
    assert orchestrator._quality_router.member_observation_count("general_agent") == 0


# -- response cache ----------------------------------------------------------------------


def test_unjudged_result_is_not_stored_in_the_response_cache(monkeypatch) -> None:
    orchestrator = _two_workers(cache_ttl=60)
    invoked: list[str] = []

    def fake_invoke(primary, messages, **kwargs):
        invoked.append(primary.id)
        return f"{primary.id} answer", primary.id, "mock", None

    monkeypatch.setattr(orchestrator, "_invoke", fake_invoke)
    with patch.object(orchestrator_module, "_resolve_fast_mlsirm_components", return_value=None):
        first = orchestrator.complete(MESSAGES, mode="route")
        second = orchestrator.complete(MESSAGES, mode="route")
    assert first["verification"]["judge_status"] == "misconfigured"
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "miss"
    assert invoked == ["primary_worker", "primary_worker"]


def test_judged_result_is_still_cached(monkeypatch) -> None:
    orchestrator = _two_workers(cache_ttl=60)
    monkeypatch.setattr(
        orchestrator,
        "_invoke",
        lambda primary, messages, **kwargs: (f"{primary.id} answer", primary.id, "mock", None),
    )
    monkeypatch.setattr(
        orchestrator,
        "_model_judge_verification",
        lambda *args, **kwargs: {
            "accepted": True,
            "reason": "ok",
            "verifier_output": "x",
            "judge": "model",
        },
    )
    orchestrator.complete(MESSAGES, mode="route")
    assert orchestrator.complete(MESSAGES, mode="route")["cache_status"] == "hit"
