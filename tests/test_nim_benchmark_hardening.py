"""Adversarial contracts for NIM transport, budget, and cost evidence hardening."""

from __future__ import annotations

import datetime as datetime_module
import json
from pathlib import Path
import urllib.error

import pytest

from contextual_orchestrator import nim_benchmark as nb
from contextual_orchestrator import nim_benchmark_hardening as hardening
from contextual_orchestrator.orchestrator import ModelAgent


ROOT = Path(__file__).resolve().parents[1]
TASK_MANIFEST = str(ROOT / "examples" / "nim_task_manifest.json")
PRICING_SCENARIO = str(ROOT / "examples" / "nim_pricing_scenario.json")
PUBLIC_ENDPOINT = "https://integrate.api.nvidia.com/v1"


class _FakeDelegate:
    """Small model-client stand-in exposing output caps and provider usage."""

    def __init__(self, answer: str = "short answer", usage: object = None) -> None:
        """Configure the delegated answer and one optional usage payload."""
        self.max_output_tokens = 256
        self.answer = answer
        self.usage = usage
        self.observed_caps: list[int] = []

    def chat(self, _agent: ModelAgent, _messages: list[dict[str, object]], _temperature: float) -> str:
        """Record the temporary output cap and return the configured answer."""
        self.observed_caps.append(self.max_output_tokens)
        return self.answer

    def take_usage(self) -> object:
        """Return the configured provider usage payload."""
        return self.usage


class _FakeResponse:
    """Minimal direct-connection response with deterministic cleanup evidence."""

    def __init__(self, status: int, body: bytes) -> None:
        """Store one status/body pair returned by the fake provider."""
        self.status = status
        self._body = body
        self.closed = False

    def read(self) -> bytes:
        """Return the configured provider bytes."""
        return self._body

    def close(self) -> None:
        """Record deterministic response cleanup."""
        self.closed = True


class _FakePinnedConnection:
    """Pinned HTTPS connection stand-in used to inspect the security boundary."""

    attempts: list["_FakePinnedConnection"] = []
    responses: dict[str, _FakeResponse] = {}
    failing_addresses: set[str] = set()

    def __init__(
        self,
        server_hostname: str,
        pinned_ip: str,
        port: int,
        timeout: float,
        context: object,
    ) -> None:
        """Capture original host, pinned address, and TLS context inputs."""
        self.server_hostname = server_hostname
        self.pinned_ip = pinned_ip
        self.port = port
        self.timeout = timeout
        self.context = context
        self.method = ""
        self.target = ""
        self.body: bytes | None = None
        self.headers: dict[str, str] = {}
        self.closed = False
        type(self).attempts.append(self)

    def request(
        self,
        method: str,
        target: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> None:
        """Record one request or emulate a failed pinned address."""
        self.method = method
        self.target = target
        self.body = body
        self.headers = headers
        if self.pinned_ip in type(self).failing_addresses:
            raise OSError("pinned address unavailable")

    def getresponse(self) -> _FakeResponse:
        """Return the response configured for this pinned address."""
        return type(self).responses[self.pinned_ip]

    def close(self) -> None:
        """Record deterministic connection cleanup."""
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_connection() -> None:
    """Reset all class-level direct-connection evidence between tests."""
    _FakePinnedConnection.attempts = []
    _FakePinnedConnection.responses = {}
    _FakePinnedConnection.failing_addresses = set()


def _agent() -> ModelAgent:
    """Return one valid mock worker for cell-budget tests."""
    return ModelAgent(
        id="nim_test_worker",
        model="dryrun/chat-basic",
        base_url="mock://nim-hardening-test",
        credential_key=nb.NIM_CREDENTIAL_NAME,
        tags=("reasoning", "writing"),
    )


def test_hardening_installer_is_active_and_idempotent() -> None:
    """Package import installs hardening once without replacing it repeatedly."""
    installed_transport = nb.build_default_transport
    hardening.install_nim_benchmark_hardening(nb)
    assert nb._evidence_hardening_installed is True
    assert nb.build_default_transport is installed_transport


def test_endpoint_validation_rejects_http_and_non_global_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP and RFC 6598 shared space fail before any bearer credential is sent."""
    with pytest.raises(nb.BenchmarkContractError, match="must use https"):
        nb.require_public_https_endpoint("http://integrate.api.nvidia.com/v1")

    def reject_shared_space(_host: str, _port: int, _label: str) -> tuple[str, ...]:
        raise RuntimeError("benchmark provider resolves to non-public address")

    monkeypatch.setattr(hardening, "_validated_public_addresses", reject_shared_space)
    with pytest.raises(nb.BenchmarkContractError, match="non-public address"):
        nb.require_public_https_endpoint(PUBLIC_ENDPOINT)


def test_endpoint_validation_accepts_reviewed_public_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A globally routable validation-time answer remains eligible for direct TLS."""
    monkeypatch.setattr(
        hardening,
        "_validated_public_addresses",
        lambda _host, _port, _label: ("93.184.216.34",),
    )
    nb.require_public_https_endpoint(PUBLIC_ENDPOINT)


def test_secure_transport_pins_dns_preserves_host_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The connected address is pinned while authority, SNI, and redirect scope stay fixed."""
    resolution_calls: list[tuple[str, int, str]] = []

    def resolve(host: str, port: int, label: str) -> tuple[str, ...]:
        resolution_calls.append((host, port, label))
        return ("93.184.216.34",)

    monkeypatch.setattr(hardening, "_validated_public_addresses", resolve)
    monkeypatch.setattr(hardening, "_PinnedHTTPSConnection", _FakePinnedConnection)
    redirect = _FakeResponse(302, b"redirect not followed")
    _FakePinnedConnection.responses = {"93.184.216.34": redirect}

    transport = nb.build_default_transport(7.5)
    status, body = transport(
        "POST",
        f"{PUBLIC_ENDPOINT}/chat/completions?audit=1",
        {"authorization": "Bearer redacted"},
        b"{}",
    )
    second_status, _ = transport("GET", f"{PUBLIC_ENDPOINT}/models", {}, None)

    assert (status, body) == (302, b"redirect not followed")
    assert second_status == 302
    assert resolution_calls == [("integrate.api.nvidia.com", 443, "benchmark")]
    first = _FakePinnedConnection.attempts[0]
    assert first.server_hostname == "integrate.api.nvidia.com"
    assert first.pinned_ip == "93.184.216.34"
    assert first.port == 443
    assert first.timeout == 7.5
    assert first.method == "POST"
    assert first.target == "/v1/chat/completions?audit=1"
    assert first.headers["Connection"] == "close"
    assert first.headers["authorization"] == "Bearer redacted"
    assert redirect.closed is True
    assert first.closed is True


def test_secure_transport_falls_back_only_within_the_validated_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed public address can fall back only to another validation-time address."""
    monkeypatch.setattr(
        hardening,
        "_validated_public_addresses",
        lambda _host, _port, _label: ("93.184.216.34", "93.184.216.35"),
    )
    monkeypatch.setattr(hardening, "_PinnedHTTPSConnection", _FakePinnedConnection)
    _FakePinnedConnection.failing_addresses = {"93.184.216.34"}
    success = _FakeResponse(200, b"catalog")
    _FakePinnedConnection.responses = {"93.184.216.35": success}

    transport = nb.build_default_transport(5.0)
    assert transport("GET", f"{PUBLIC_ENDPOINT}/models", {}, None) == (200, b"catalog")
    assert [attempt.pinned_ip for attempt in _FakePinnedConnection.attempts] == [
        "93.184.216.34",
        "93.184.216.35",
    ]
    assert all(attempt.closed for attempt in _FakePinnedConnection.attempts)
    assert success.closed is True


def test_secure_transport_reports_network_failure_after_all_pins_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exhausting every approved address yields one urllib-compatible network error."""
    monkeypatch.setattr(
        hardening,
        "_validated_public_addresses",
        lambda _host, _port, _label: ("93.184.216.34", "93.184.216.35"),
    )
    monkeypatch.setattr(hardening, "_PinnedHTTPSConnection", _FakePinnedConnection)
    _FakePinnedConnection.failing_addresses = {"93.184.216.34", "93.184.216.35"}

    with pytest.raises(urllib.error.URLError, match="pinned address unavailable"):
        nb.build_default_transport(5.0)("GET", f"{PUBLIC_ENDPOINT}/models", {}, None)
    assert all(attempt.closed for attempt in _FakePinnedConnection.attempts)


def test_equal_budget_client_validates_allowances() -> None:
    """Boolean, zero, and negative allowances are never accepted as real budgets."""
    with pytest.raises(ValueError, match="total_token_budget"):
        hardening.EqualBudgetModelClient(_FakeDelegate(), False, 5)
    with pytest.raises(ValueError, match="total_token_budget"):
        hardening.EqualBudgetModelClient(_FakeDelegate(), 0, 5)
    with pytest.raises(ValueError, match="maximum_calls"):
        hardening.EqualBudgetModelClient(_FakeDelegate(), 10, True)
    with pytest.raises(ValueError, match="maximum_calls"):
        hardening.EqualBudgetModelClient(_FakeDelegate(), 10, -1)


def test_equal_budget_client_caps_each_call_and_restores_delegate_state() -> None:
    """Each call receives only the remaining total allowance and restores shared state."""
    delegate = _FakeDelegate(answer="ok")
    client = hardening.EqualBudgetModelClient(delegate, total_token_budget=80, maximum_calls=5)
    answer = client.chat(_agent(), [{"role": "user", "content": "hi"}], 0.0)

    assert answer == "ok"
    assert delegate.observed_caps
    assert 0 < delegate.observed_caps[0] <= 80
    assert delegate.max_output_tokens == 256
    assert client.observed_calls == 1
    assert 0 < client.observed_tokens <= 80
    assert client.remaining_tokens == 80 - client.observed_tokens


def test_equal_budget_client_enforces_call_and_prompt_exhaustion() -> None:
    """No policy cell can exceed its common call envelope or token allowance."""
    call_limited = hardening.EqualBudgetModelClient(
        _FakeDelegate(answer="ok"),
        total_token_budget=100,
        maximum_calls=1,
    )
    call_limited.chat(_agent(), [{"role": "user", "content": "hi"}], 0.0)
    with pytest.raises(hardening.PolicyTokenBudgetExceeded, match="maximum-call"):
        call_limited.chat(_agent(), [{"role": "user", "content": "again"}], 0.0)

    prompt_limited = hardening.EqualBudgetModelClient(
        _FakeDelegate(answer="ok"),
        total_token_budget=1,
        maximum_calls=5,
    )
    with pytest.raises(hardening.PolicyTokenBudgetExceeded, match="total-token"):
        prompt_limited.chat(
            _agent(),
            [{"role": "user", "content": "this prompt cannot fit"}],
            0.0,
        )


def test_equal_budget_client_reconciles_provider_usage_and_flags_overage() -> None:
    """Usable provider counts replace estimates; invalid counts remain estimates."""
    delegate = _FakeDelegate(
        answer="ok",
        usage={"prompt_tokens": 2, "completion_tokens": 3},
    )
    client = hardening.EqualBudgetModelClient(delegate, total_token_budget=100, maximum_calls=5)
    client.chat(_agent(), [{"role": "user", "content": "hi"}], 0.0)
    assert client.take_usage() == delegate.usage
    assert client.observed_tokens == 5

    invalid_delegate = _FakeDelegate(
        answer="ok",
        usage={"prompt_tokens": True, "completion_tokens": float("inf")},
    )
    invalid_client = hardening.EqualBudgetModelClient(
        invalid_delegate,
        total_token_budget=100,
        maximum_calls=5,
    )
    invalid_client.chat(_agent(), [{"role": "user", "content": "hi"}], 0.0)
    estimated = invalid_client.observed_tokens
    assert invalid_client.take_usage() == invalid_delegate.usage
    assert invalid_client.observed_tokens == estimated

    over_delegate = _FakeDelegate(
        answer="ok",
        usage={"prompt_tokens": 90, "completion_tokens": 90},
    )
    over_client = hardening.EqualBudgetModelClient(
        over_delegate,
        total_token_budget=100,
        maximum_calls=5,
    )
    over_client.chat(_agent(), [{"role": "user", "content": "hi"}], 0.0)
    over_client.take_usage()
    assert over_client.exceeded is True
    with pytest.raises(hardening.PolicyTokenBudgetExceeded):
        over_client.chat(_agent(), [{"role": "user", "content": "again"}], 0.0)


def test_cost_evidence_is_authoritative_complete_and_time_bounded() -> None:
    """Zero actual cost is tied to official NVIDIA evidence and an expiry date."""
    report = {"actual_cost_evidence": dict(hardening.ACTUAL_COST_EVIDENCE)}
    hardening._validate_actual_cost_evidence(report)
    hardening._require_current_actual_cost_evidence(datetime_module.date(2026, 9, 3))
    with pytest.raises(RuntimeError, match="expired"):
        hardening._require_current_actual_cost_evidence(datetime_module.date(2026, 9, 4))

    with pytest.raises(ValueError, match="missing actual_cost_evidence"):
        hardening._validate_actual_cost_evidence({})
    missing = {"actual_cost_evidence": dict(hardening.ACTUAL_COST_EVIDENCE)}
    del missing["actual_cost_evidence"]["source_title"]
    with pytest.raises(ValueError, match="missing fields"):
        hardening._validate_actual_cost_evidence(missing)
    wrong_cost = {"actual_cost_evidence": dict(hardening.ACTUAL_COST_EVIDENCE)}
    wrong_cost["actual_cost_evidence"]["actual_cost_usd"] = 1.0
    with pytest.raises(ValueError, match="zero-cost"):
        hardening._validate_actual_cost_evidence(wrong_cost)
    wrong_source = {"actual_cost_evidence": dict(hardening.ACTUAL_COST_EVIDENCE)}
    wrong_source["actual_cost_evidence"]["source_url"] = "https://example.test/claim"
    with pytest.raises(ValueError, match="official NVIDIA"):
        hardening._validate_actual_cost_evidence(wrong_source)


def test_dry_run_records_equal_policy_budgets_and_actual_cost_provenance(tmp_path: Path) -> None:
    """Every comparable cell carries equal configured budgets and reviewed cost evidence."""
    report = nb.run_benchmark(
        "dry_run",
        TASK_MANIFEST,
        PRICING_SCENARIO,
        str(tmp_path),
        max_total_requests=500,
        max_output_tokens=256,
        max_eval_models=3,
    )

    evidence = report["actual_cost_evidence"]
    assert evidence["source_url"].startswith("https://docs.nvidia.com/")
    assert evidence["actual_cost_usd"] == 0.0
    cells = report["evaluation"]["evaluation_cells"]
    assert cells
    assert {cell["configured_total_token_budget"] for cell in cells} == {256}
    assert {cell["configured_maximum_calls"] for cell in cells} == {
        nb.MAX_WORKFLOW_DEPTH
    }
    assert all(cell["observed_budget_calls"] <= nb.MAX_WORKFLOW_DEPTH for cell in cells)
    assert all(cell["observed_budget_tokens"] >= 0 for cell in cells)
    markdown = Path(report["artifact_paths"]["markdown_path"]).read_text(encoding="utf-8")
    assert "Actual API cost evidence" in markdown
    assert evidence["valid_until_date"] in markdown


def test_live_run_fails_closed_when_cost_evidence_has_expired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A live run cannot silently carry an obsolete free-access assertion forward."""
    monkeypatch.setitem(hardening.ACTUAL_COST_EVIDENCE, "valid_until_date", "2000-01-01")
    with pytest.raises(nb.BenchmarkContractError, match="expired"):
        nb.run_benchmark(
            "live",
            TASK_MANIFEST,
            None,
            str(tmp_path),
            git_sha="a" * 40,
            workflow_run_id="123",
        )


def test_budget_fields_survive_json_artifact_serialization(tmp_path: Path) -> None:
    """Configured/observed budgets and evidence remain machine-readable in JSON."""
    report = nb.run_benchmark(
        "dry_run",
        TASK_MANIFEST,
        None,
        str(tmp_path),
        max_total_requests=500,
        max_output_tokens=128,
        max_eval_models=2,
    )
    serialized = json.loads(
        Path(report["artifact_paths"]["json_path"]).read_text(encoding="utf-8")
    )
    assert serialized["actual_cost_evidence"]["evidence_schema_version"] == "1.0.0"
    assert all(
        cell["configured_total_token_budget"] == 128
        for cell in serialized["evaluation"]["evaluation_cells"]
    )
