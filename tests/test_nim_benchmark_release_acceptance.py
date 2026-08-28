"""Release-level security, fairness, and evidence contracts for the NIM benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import urllib.parse

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    register_credential,
    set_backend,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST_PATH = str(REPOSITORY_ROOT / "examples" / "nim_task_manifest.json")
EXAMPLE_PRICING_PATH = REPOSITORY_ROOT / "examples" / "nim_pricing_scenario.json"
FAKE_ENDPOINT = "https://nim.example.test/v1"


@pytest.fixture(autouse=True)
def _isolated_credentials() -> None:
    """Give every test a fresh KV backend and remove it after the assertion."""
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _write_json(path: Path, payload: object) -> str:
    """Write one deterministic JSON fixture and return its string path."""
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return str(path)


def _reviewed_pricing_scenario(**overrides: object) -> dict[str, object]:
    """Return a complete reviewed hypothetical-price evidence fixture."""
    scenario: dict[str, object] = {
        "scenario_version": "test-reviewed.1",
        "scenario_status": "reviewed",
        "source_url": "https://pricing.example.test/reviewed-rate-card",
        "reviewed_by": "independent_pricing_reviewer",
        "reviewed_at_date": "2026-08-05",
        "valid_until_date": "2026-09-04",
        "rate_basis": "hypothetical_usd_per_million_prompt_and_completion_tokens",
        "uncertainty": "Scenario rates are explicit assumptions, not NVIDIA model prices.",
        "usd_per_million_tokens": {
            "vendor/model-one": {"input": 1.0, "output": 2.0}
        },
    }
    scenario.update(overrides)
    return scenario


def _unexpected_transport(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
    """Fail a test when validation did not stop before provider egress."""
    raise AssertionError("provider transport must not run before evidence validation")


def test_package_import_does_not_eagerly_load_optional_benchmark() -> None:
    """Normal gateway imports must not load or mutate the optional evaluator."""
    command = [
        sys.executable,
        "-c",
        (
            "import sys; import contextual_orchestrator; "
            "assert 'contextual_orchestrator.nim_benchmark' not in sys.modules; "
            "assert 'contextual_orchestrator.nim_benchmark_hardening' not in sys.modules"
        ),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_live_run_rejects_unreviewed_pricing_before_egress(tmp_path: Path) -> None:
    """Schema-demo prices can support dry runs but can never drive a live policy."""
    register_credential(nb.NIM_CREDENTIAL_NAME, "secret-test-key")
    scenario = json.loads(EXAMPLE_PRICING_PATH.read_text(encoding="utf-8"))
    scenario_path = _write_json(tmp_path / "unreviewed_pricing.json", scenario)

    with pytest.raises(nb.BenchmarkContractError, match="reviewed"):
        nb.run_benchmark(
            "live",
            TASK_MANIFEST_PATH,
            scenario_path,
            str(tmp_path / "artifacts"),
            endpoint=FAKE_ENDPOINT,
            git_sha="a" * 40,
            workflow_run_id="123",
            transport=_unexpected_transport,
        )


def test_live_run_rejects_incomplete_or_expired_pricing_before_egress(
    tmp_path: Path,
) -> None:
    """Live hypothetical prices need complete, current, independently reviewed evidence."""
    register_credential(nb.NIM_CREDENTIAL_NAME, "secret-test-key")
    incomplete = _reviewed_pricing_scenario()
    del incomplete["reviewed_by"]
    incomplete_path = _write_json(tmp_path / "incomplete_pricing.json", incomplete)
    with pytest.raises(nb.BenchmarkContractError, match="reviewed_by"):
        nb.run_benchmark(
            "live",
            TASK_MANIFEST_PATH,
            incomplete_path,
            str(tmp_path / "incomplete_artifacts"),
            endpoint=FAKE_ENDPOINT,
            git_sha="b" * 40,
            workflow_run_id="124",
            transport=_unexpected_transport,
        )

    expired_path = _write_json(
        tmp_path / "expired_pricing.json",
        _reviewed_pricing_scenario(
            reviewed_at_date="1999-01-01", valid_until_date="2000-01-01"
        ),
    )
    with pytest.raises(nb.BenchmarkContractError, match="expired"):
        nb.run_benchmark(
            "live",
            TASK_MANIFEST_PATH,
            expired_path,
            str(tmp_path / "expired_artifacts"),
            endpoint=FAKE_ENDPOINT,
            git_sha="c" * 40,
            workflow_run_id="125",
            transport=_unexpected_transport,
        )


def test_probe_concurrency_executes_the_complete_cartesian_plan() -> None:
    """Thread scheduling cannot turn a complete probe plan into a biased prefix."""
    models = [
        {"model_id": "a/model-one", "owned_by": "vendor"},
        {"model_id": "b/model-two", "owned_by": "vendor"},
    ]
    first_model_started = threading.Event()
    second_model_four_calls = threading.Event()
    second_model_call_count = 0
    count_lock = threading.Lock()

    def transport(
        _method: str,
        _url: str,
        _headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        """Force completion-order drift while every preflighted cell still runs."""
        nonlocal second_model_call_count
        payload = (body or b"").decode("utf-8", errors="ignore")
        if "a/model-one" in payload:
            first_model_started.set()
            second_model_four_calls.wait(timeout=0.25)
        elif "b/model-two" in payload:
            first_model_started.wait(timeout=0.25)
            with count_lock:
                second_model_call_count += 1
                if second_model_call_count == 4:
                    second_model_four_calls.set()
        return 400, b"{}"

    budget = nb.RequestBudget(
        len(models) * len(nb.CAPABILITY_PROBE_ORDER)
    )
    rows = nb.probe_discovered_models(
        models,
        transport,
        FAKE_ENDPOINT,
        "credential-redacted",
        budget,
        probe_concurrency=2,
        clock=lambda: 1.0,
        timer=lambda: 0.0,
    )

    assert [row["model_id"] for row in rows] == ["a/model-one", "b/model-two"]
    for model_row in rows:
        assert [
            probe_row["capability_name"]
            for probe_row in model_row["capability_probe_rows"]
        ] == list(nb.CAPABILITY_PROBE_ORDER)
        assert all(
            probe_row["probe_outcome"] != "skipped"
            for probe_row in model_row["capability_probe_rows"]
        )
    assert budget.requests_spent == 18


def test_complete_request_plan_rejects_invalid_counts() -> None:
    """Planning inputs are positive integers, never booleans or empty counts."""
    invalid_cases = [
        {"discovered_model_count": 0, "max_eval_models": 7, "locked_task_count": 10},
        {"discovered_model_count": True, "max_eval_models": 7, "locked_task_count": 10},
        {"discovered_model_count": 1, "max_eval_models": 0, "locked_task_count": 10},
        {"discovered_model_count": 1, "max_eval_models": 7, "locked_task_count": 0},
    ]

    for case in invalid_cases:
        with pytest.raises(nb.BenchmarkContractError, match="positive integer"):
            nb.plan_complete_request_budget(**case)


def test_complete_request_plan_covers_a_127_model_catalog() -> None:
    """The reviewed current-catalog scale fits only when probes and eval are reserved."""
    plan = nb.plan_complete_request_budget(
        discovered_model_count=127,
        max_eval_models=7,
        locked_task_count=10,
    )

    assert plan == {
        "catalog_request_count": 1,
        "capability_probe_request_count": 127 * 9,
        "evaluation_reserve_request_count": 260,
        "planned_worker_count": 7,
        "total_required_request_count": 1404,
    }


def test_buyer_facing_request_plan_matches_internal_plan() -> None:
    """The stable operator view exposes the same complete-run reservation."""
    assert nb.planned_complete_run_requests(127, 30, 7) == {
        "catalog_discovery_requests": 1,
        "capability_probe_requests": 127 * 9,
        "evaluation_worker_ceiling": 7,
        "evaluation_requests": 780,
        "requests_after_catalog": 127 * 9 + 780,
        "total_requests": 1924,
    }


def test_one_request_short_fails_after_catalog_before_any_probe(tmp_path: Path) -> None:
    """An undersized live-style plan spends discovery only, then fails closed."""
    model_rows = [
        {"id": f"vendor/model-{index:03d}", "owned_by": "vendor"}
        for index in range(127)
    ]
    calls: list[tuple[str, str]] = []

    def transport(
        method: str,
        url: str,
        _headers: dict[str, str],
        _body: bytes | None,
    ) -> tuple[int, bytes]:
        calls.append((method, urllib.parse.urlparse(url).path))
        if method == "GET":
            return 200, json.dumps({"data": model_rows}).encode("utf-8")
        raise AssertionError("capability egress must not begin after failed preflight")

    with pytest.raises(
        nb.BenchmarkBudgetError,
        match="complete benchmark needs 1924 requests but configured cap is 1923",
    ):
        nb.run_benchmark(
            "dry_run",
            TASK_MANIFEST_PATH,
            None,
            str(tmp_path / "insufficient"),
            endpoint=FAKE_ENDPOINT,
            max_total_requests=1923,
            max_eval_models=7,
            transport=transport,
        )

    assert calls == [("GET", "/v1/models")]


def test_exact_complete_request_boundary_runs_and_records_plan(tmp_path: Path) -> None:
    """The exact conservative boundary succeeds and records configured reserves."""
    manifest_path = _write_json(
        tmp_path / "boundary_manifest.json",
        {
            "manifest_version": "boundary.1",
            "tasks": [
                {
                    "task_id": "locked_boundary_task",
                    "split": "locked",
                    "prompt": "Name a striped animal.",
                    "scorer": {"name": "substring_match", "version": "1"},
                    "expected": {"substring": "zebra"},
                }
            ],
        },
    )

    def transport(
        method: str,
        url: str,
        _headers: dict[str, str],
        _body: bytes | None,
    ) -> tuple[int, bytes]:
        path = urllib.parse.urlparse(url).path
        if method == "GET":
            return 200, json.dumps(
                {"data": [{"id": "vendor/model-one", "owned_by": "vendor"}]}
            ).encode("utf-8")
        return 200, nb._dry_run_success_body(path)

    report = nb.run_benchmark(
        "dry_run",
        manifest_path,
        None,
        str(tmp_path / "exact_boundary"),
        endpoint=FAKE_ENDPOINT,
        max_total_requests=24,
        max_eval_models=1,
        transport=transport,
    )

    assert report["request_budget"]["max_total_requests"] == 24
    assert report["request_budget"]["planned_total_requests"] == 24
    assert report["request_budget"]["catalog_requests"] == 1
    assert report["request_budget"]["capability_probe_requests"] == 9
    assert report["request_budget"]["evaluation_reserve_requests"] == 14
    assert report["request_budget"]["requests_spent"] <= 24


def test_video_probe_fixture_is_one_decodable_frame_with_stable_hash() -> None:
    """A video-capable model receives a real one-frame MP4, not an ftyp-only stub."""
    fixture = nb._tiny_mp4_bytes()
    metadata = nb.validate_video_probe_fixture(fixture)

    assert metadata == {
        "codec_name": "h264",
        "width": 16,
        "height": 16,
        "frame_count": 1,
    }
    assert hashlib.sha256(fixture).hexdigest() == nb.VIDEO_PROBE_FIXTURE_SHA256
    assert len(fixture) > 1000


def test_smoke_manifest_cannot_authorize_production_routing(tmp_path: Path) -> None:
    """Ten smoke tasks produce diagnostics, not a buyer-facing routing decision."""
    report = nb.run_benchmark(
        "dry_run",
        TASK_MANIFEST_PATH,
        None,
        str(tmp_path),
        max_total_requests=600,
        max_eval_models=2,
    )
    evaluation = report["evaluation"]

    assert evaluation["evidence_status"] == "insufficient_evidence"
    assert evaluation["decision_use"] == "benchmark_smoke_only"
    assert evaluation["minimum_paired_task_count"] == 30
    assert evaluation["required_completion_fraction"] == 0.9
    assert evaluation["routing_recommendation"] is None
    assert report["honesty_labels"]["actual_cost_basis"] == (
        "deterministic_dry_run_no_provider_egress"
    )


class _BudgetDelegate:
    """Minimal provider client used to exercise direct equal-budget behavior."""

    def __init__(self, answer: str = "ok", usage: object = None) -> None:
        """Configure one answer and optional provider usage payload."""
        self.max_output_tokens = 256
        self.answer = answer
        self.usage = usage
        self.observed_caps: list[int] = []

    def chat(self, _agent, _messages, _temperature=0.2) -> str:
        """Record the temporary output cap and return the configured answer."""
        self.observed_caps.append(self.max_output_tokens)
        return self.answer

    def take_usage(self):
        """Return the configured provider usage payload."""
        return self.usage


def _budget_agent():
    """Return one valid mock worker for cell-budget tests."""
    from contextual_orchestrator.orchestrator import ModelAgent

    return ModelAgent(
        id="nim_budget_worker",
        model="dryrun/chat-basic",
        base_url="mock://nim-budget-test",
        credential_key=nb.NIM_CREDENTIAL_NAME,
        tags=("reasoning", "writing"),
    )


def _mp4_box(box_type: bytes, payload: bytes = b"") -> bytes:
    """Build one small ISO-BMFF box for malformed-fixture regression tests."""
    import struct

    return struct.pack(">I4s", len(payload) + 8, box_type) + payload


def test_default_transport_rejects_invalid_timeout_values() -> None:
    """Only finite positive real timeout values can reach socket setup."""
    for value in (False, 0, -1, "5", float("nan"), float("inf")):
        with pytest.raises(nb.BenchmarkContractError, match="timeout_seconds"):
            nb.build_default_transport(value)


def test_equal_budget_client_validates_and_exposes_delegate_cap() -> None:
    """Equal budgets are positive integers and preserve the client cap interface."""
    for token_budget in (False, 0, 1.5):
        with pytest.raises(ValueError, match="total_token_budget"):
            nb.EqualBudgetModelClient(_BudgetDelegate(), token_budget, 5)
    for maximum_calls in (False, 0, 1.5):
        with pytest.raises(ValueError, match="maximum_calls"):
            nb.EqualBudgetModelClient(_BudgetDelegate(), 20, maximum_calls)

    delegate = _BudgetDelegate()
    client = nb.EqualBudgetModelClient(delegate, 20, 5)
    assert client.max_output_tokens == 256
    client.max_output_tokens = 128
    assert delegate.max_output_tokens == 128


@pytest.mark.parametrize("value", [True, "3", float("nan"), float("inf"), -1])
def test_equal_budget_usage_count_rejects_invalid_values(value: object) -> None:
    """Provider token counts must be finite non-negative real numbers, never booleans."""
    assert nb.EqualBudgetModelClient._coerce_usage_count(value) is None
    assert nb.EqualBudgetModelClient._coerce_usage_count(3.9) == 3


def test_equal_budget_usage_reconciliation_covers_all_sources() -> None:
    """Reported usage replaces estimates only when both counts are usable."""
    no_usage = nb.EqualBudgetModelClient(_BudgetDelegate(usage=None), 100, 5)
    assert no_usage.take_usage() is None

    non_mapping = nb.EqualBudgetModelClient(_BudgetDelegate(usage="unknown"), 100, 5)
    non_mapping.chat(_budget_agent(), [{"role": "user", "content": "hi"}], 0.0)
    estimated_non_mapping = non_mapping.observed_tokens
    assert non_mapping.take_usage() == "unknown"
    assert non_mapping.observed_tokens == estimated_non_mapping

    invalid_counts = nb.EqualBudgetModelClient(
        _BudgetDelegate(usage={"prompt_tokens": True, "completion_tokens": -1}),
        100,
        5,
    )
    invalid_counts.chat(_budget_agent(), [{"role": "user", "content": "hi"}], 0.0)
    estimated_invalid = invalid_counts.observed_tokens
    assert invalid_counts.take_usage() == {
        "prompt_tokens": True,
        "completion_tokens": -1,
    }
    assert invalid_counts.observed_tokens == estimated_invalid

    reported = nb.EqualBudgetModelClient(
        _BudgetDelegate(usage={"prompt_tokens": 2, "completion_tokens": 3}),
        100,
        5,
    )
    reported.chat(_budget_agent(), [{"role": "user", "content": "hi"}], 0.0)
    assert reported.take_usage() == {"prompt_tokens": 2, "completion_tokens": 3}
    assert reported.observed_tokens == 5


def test_mp4_parser_rejects_every_malformed_box_class() -> None:
    """Fixture validation fails closed on truncation, bad bounds, and missing evidence."""
    import struct

    with pytest.raises(nb.BenchmarkContractError, match="truncated box header"):
        list(nb._iter_mp4_boxes(b"x"))
    with pytest.raises(nb.BenchmarkContractError, match="truncated extended box"):
        list(nb._iter_mp4_boxes(struct.pack(">I4s", 1, b"free")))

    extended = struct.pack(">I4sQ", 1, b"free", 16)
    assert list(nb._iter_mp4_boxes(extended)) == [(b"free", 16, 16)]
    zero_sized = struct.pack(">I4s", 0, b"free") + b"payload"
    assert list(nb._iter_mp4_boxes(zero_sized)) == [
        (b"free", 8, len(zero_sized))
    ]
    with pytest.raises(nb.BenchmarkContractError, match="parent bounds"):
        list(nb._iter_mp4_boxes(struct.pack(">I4s", 20, b"free")))

    with pytest.raises(nb.BenchmarkContractError, match="meta box"):
        list(nb._walk_mp4_boxes(_mp4_box(b"meta")))
    with pytest.raises(nb.BenchmarkContractError, match="lacks ftyp"):
        nb.validate_video_probe_fixture(_mp4_box(b"ftyp"))

    required_top_level = _mp4_box(b"ftyp") + _mp4_box(b"moov") + _mp4_box(b"mdat")
    with pytest.raises(nb.BenchmarkContractError, match="one 16x16 one-frame"):
        nb.validate_video_probe_fixture(required_top_level)

    truncated_tkhd = (
        _mp4_box(b"ftyp")
        + _mp4_box(b"moov", _mp4_box(b"tkhd", b"x"))
        + _mp4_box(b"mdat")
    )
    with pytest.raises(nb.BenchmarkContractError, match="tkhd box"):
        nb.validate_video_probe_fixture(truncated_tkhd)

    truncated_stsz = (
        _mp4_box(b"ftyp")
        + _mp4_box(b"moov", _mp4_box(b"stsz", b"short"))
        + _mp4_box(b"mdat")
    )
    with pytest.raises(nb.BenchmarkContractError, match="stsz box"):
        nb.validate_video_probe_fixture(truncated_stsz)


def test_video_fixture_checksum_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed embedded media payload cannot silently enter provider probes."""
    monkeypatch.setattr(nb, "VIDEO_PROBE_FIXTURE_SHA256", "0" * 64)
    with pytest.raises(nb.BenchmarkContractError, match="checksum"):
        nb._tiny_mp4_bytes()


def test_reviewed_pricing_metadata_rejects_invalid_provenance(tmp_path: Path) -> None:
    """Reviewed scenarios require valid dates, HTTPS source, and non-empty review fields."""
    invalid_scenarios = [
        _reviewed_pricing_scenario(source_url="http://pricing.example.test/rates"),
        _reviewed_pricing_scenario(reviewed_by=""),
        _reviewed_pricing_scenario(rate_basis=""),
        _reviewed_pricing_scenario(uncertainty=""),
        _reviewed_pricing_scenario(reviewed_at_date=3),
        _reviewed_pricing_scenario(reviewed_at_date="not-a-date"),
        _reviewed_pricing_scenario(
            reviewed_at_date="2026-08-05", valid_until_date="2026-08-04"
        ),
        _reviewed_pricing_scenario(
            usd_per_million_tokens={"": {"input": 1.0, "output": 2.0}}
        ),
    ]
    for index, scenario in enumerate(invalid_scenarios):
        path = _write_json(tmp_path / f"invalid_reviewed_{index}.json", scenario)
        with pytest.raises(nb.BenchmarkContractError):
            nb.load_pricing_scenario(path)


def test_live_pricing_rejects_future_review_and_accepts_current_evidence() -> None:
    """A live run date must fall within the reviewed pricing validity interval."""
    future = _reviewed_pricing_scenario(
        reviewed_at_date="2026-08-06", valid_until_date="2026-09-04"
    )
    with pytest.raises(nb.BenchmarkContractError, match="future"):
        nb.validate_live_pricing_scenario(
            future,
            today=__import__("datetime").date(2026, 8, 5),
        )
    nb.validate_live_pricing_scenario(
        _reviewed_pricing_scenario(),
        today=__import__("datetime").date(2026, 8, 5),
    )


def test_actual_cost_evidence_validation_and_expiry_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The zero access-cost claim remains complete, official, and time bounded."""
    with pytest.raises(nb.BenchmarkContractError, match="missing actual_cost_evidence"):
        nb._validate_actual_cost_evidence({})

    missing = {"actual_cost_evidence": dict(nb.ACTUAL_COST_EVIDENCE)}
    del missing["actual_cost_evidence"]["source_title"]
    with pytest.raises(nb.BenchmarkContractError, match="missing fields"):
        nb._validate_actual_cost_evidence(missing)

    wrong_cost = {"actual_cost_evidence": dict(nb.ACTUAL_COST_EVIDENCE)}
    wrong_cost["actual_cost_evidence"]["actual_cost_usd"] = 1.0
    with pytest.raises(nb.BenchmarkContractError, match="zero-cost"):
        nb._validate_actual_cost_evidence(wrong_cost)

    wrong_source = {"actual_cost_evidence": dict(nb.ACTUAL_COST_EVIDENCE)}
    wrong_source["actual_cost_evidence"]["source_url"] = "https://example.test"
    with pytest.raises(nb.BenchmarkContractError, match="General FAQ"):
        nb._validate_actual_cost_evidence(wrong_source)

    invalid_dates = {"actual_cost_evidence": dict(nb.ACTUAL_COST_EVIDENCE)}
    invalid_dates["actual_cost_evidence"]["reviewed_at_date"] = "2026-09-05"
    with pytest.raises(nb.BenchmarkContractError, match="validity precedes"):
        nb._validate_actual_cost_evidence(invalid_dates)

    monkeypatch.setitem(nb.ACTUAL_COST_EVIDENCE, "reviewed_at_date", "2026-08-06")
    with pytest.raises(nb.BenchmarkContractError, match="future"):
        nb._require_current_actual_cost_evidence(
            __import__("datetime").date(2026, 8, 5)
        )
    monkeypatch.setitem(nb.ACTUAL_COST_EVIDENCE, "reviewed_at_date", "2026-08-05")
    monkeypatch.setitem(nb.ACTUAL_COST_EVIDENCE, "valid_until_date", "2026-08-05")
    nb._require_current_actual_cost_evidence(__import__("datetime").date(2026, 8, 5))
    with pytest.raises(nb.BenchmarkContractError, match="expired"):
        nb._require_current_actual_cost_evidence(
            __import__("datetime").date(2026, 8, 6)
        )


def test_sufficient_evidence_is_still_human_review_gated() -> None:
    """Meeting sample thresholds changes status but never auto-selects a route."""
    cells = []
    for task_index in range(nb.MINIMUM_PAIRED_TASK_COUNT):
        task_id = f"paired_task_{task_index}"
        for policy_name in ("route_once", "conduct_bounded"):
            cells.append(
                {
                    "policy_name": policy_name,
                    "task_id": task_id,
                    "run_outcome": "success",
                }
            )
    summary = nb._evaluation_evidence_summary(
        cells,
        nb.MINIMUM_PAIRED_TASK_COUNT,
    )
    assert summary["evidence_status"] == "evidence_review_required"
    assert summary["decision_use"] == "production_candidate_review"
    assert summary["routing_recommendation"] is None


def test_live_run_requires_provenance_before_transport(tmp_path: Path) -> None:
    """Missing live revision identity fails before credentials or transport are used."""
    with pytest.raises(nb.BenchmarkContractError, match="git-sha"):
        nb.run_benchmark(
            "live",
            TASK_MANIFEST_PATH,
            None,
            str(tmp_path),
            transport=_unexpected_transport,
        )
