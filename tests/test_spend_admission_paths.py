"""Every paid provider send is admitted against the spend caps (ADR 0138).

Regression tests for the #1268 review blockers:

* passthrough / judge / embeddings / batch / probe sends go through the same
  pre-call admission as chat (reservation, tightest limit, 50% rule);
* an unmeasured call counts at its admission bound and marks measurement
  incomplete, unless the transport provably failed before provider egress;
* the admission bound uses the ``max_tokens`` actually sent (effort profile)
  and the transport never sends more than the bound assumed;
* a paid call with no run scope opens an implicit single-call scope, and a
  caller can wrap a whole session in one ``run_scope`` to share one cap;
* no public ``ModelClient`` / ``TaskOrchestrator`` send path bypasses it.

Every provider is faked; no live or paid provider is called.
"""

from __future__ import annotations

import ast
import contextlib
import json
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

from contextual_orchestrator import __main__ as cli
from contextual_orchestrator import orchestrator as orchestrator_module
from contextual_orchestrator.cost_ledger import PriceEntry
from contextual_orchestrator.credentials import NotConfigured
from contextual_orchestrator.domain.budget import BudgetExceededError
from contextual_orchestrator.domain.money import Money
from contextual_orchestrator.domain.pricing import AdmissionTokenBounds
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator
from contextual_orchestrator.provider_errors import ProviderUpstreamError
from contextual_orchestrator.reasoning_effort_profile import ReasoningEffortProfile
from contextual_orchestrator.spend_guard import (
    SpendGuard,
    SpendGuardConfig,
    guarded_provider_call,
)
from contextual_orchestrator.spend_metering import (
    InMemorySpendLedgerStore,
    JsonlSpendLedgerStore,
    operator_settle_reservation,
)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "contextual_orchestrator"
MESSAGES = [{"role": "user", "content": "do work"}]


def _agent(
    agent_id: str = "paid_agent",
    *,
    ctx: int | None = 1000,
    max_out: int | None = None,
    tags: tuple[str, ...] = ("reasoning",),
) -> ModelAgent:
    return ModelAgent(
        id=agent_id,
        model="cheap/model",
        base_url="https://openrouter.ai/api/v1",
        provider_name="openrouter",
        context_window=ctx,
        max_output_tokens=max_out,
        tags=tags,
        priority=5,
    )


def _guard(
    cap: str | None, *, prompt: float = 0.001, completion: float = 0.002, store=None
) -> SpendGuard:
    guard = SpendGuard(
        config=SpendGuardConfig.from_values(run_max_cost_usd=cap), store=store
    )
    guard.price_book.set_price(
        PriceEntry("openrouter", "cheap/model", prompt, completion, "USD")
    )
    return guard


def _chat_response(content: str, usage: dict | None) -> dict:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


def _judge_transport(sent: dict, usage: dict):
    def fake(
        agent, endpoint, payload, *, allow_transient_retries, operation_kind="request"
    ):
        sent["judge"] += 1
        schema = payload["response_format"]["json_schema"]["schema"]["properties"]
        ids = list(schema["criterion_scores"]["properties"])
        verdict = {
            "score": 1.0,
            "accepted": True,
            "rationale": "ok",
            "criterion_scores": {name: 1.0 for name in ids},
        }
        return _chat_response(json.dumps(verdict), usage)

    return fake


def _chat_transport(client, sent: dict, usage: dict):
    def fake(agent, messages, temperature=None, top_p=None, effort_profile=None):
        sent["chat"] += 1
        client._local.usage = dict(usage)
        return "worker answer"

    return fake


# -- blocker 1: passthrough admission (probes p1, p1b) -------------------------


def test_passthrough_is_admitted_against_the_run_cap() -> None:
    """p1: a passthrough send is refused once the run cap is spent."""
    agent = _agent()
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    sent: list[str] = []

    def fake(
        agent, endpoint, payload, *, allow_transient_retries, operation_kind="request"
    ):
        sent.append(endpoint)
        return _chat_response(
            "x", {"prompt_tokens": 10, "completion_tokens": 400_000, "cost": 5.0}
        )

    orchestrator.client._proxy_send_transport = fake
    refused = []
    with guard.run_scope() as scope:
        for _ in range(3):
            try:
                orchestrator.client.proxy_send(
                    agent, "chat/completions", {"model": agent.model, "messages": []}
                )
            except BudgetExceededError as exc:
                refused.append(exc.detail)
    assert len(sent) == 1, "only the first passthrough call may reach the provider"
    assert [detail["reason"] for detail in refused] == ["budget_exhausted"] * 2
    assert {detail["channel"] for detail in refused} == {"passthrough"}
    # The provider reported more than the admitted bound: recorded, not hidden.
    assert scope.bound_overruns and scope.bound_overruns[0]["channel"] == "passthrough"


def test_route_once_judge_passthrough_is_admitted_before_send() -> None:
    """p1b: the fast-mlsirm judge call cannot overrun the run cap."""
    worker = _agent("paid_worker")
    guard = _guard("0.01", prompt=0.002, completion=0.006)
    orchestrator = TaskOrchestrator([worker], spend_guard=guard)
    sent = {"chat": 0, "judge": 0}
    orchestrator.client._chat_transport = _chat_transport(
        orchestrator.client, sent, {"prompt_tokens": 100, "completion_tokens": 900}
    )
    orchestrator.client._proxy_send_transport = _judge_transport(
        sent, {"prompt_tokens": 50_000, "completion_tokens": 1000, "cost": 1.25}
    )
    try:
        orchestrator.route_once(MESSAGES)
    except BudgetExceededError:
        pass
    summary = guard.last_run_summary()["budget"]
    assert sent == {"chat": 1, "judge": 0}
    assert Decimal(str(summary["run_spent_cost"])) <= Decimal("0.01")
    assert any(
        refusal.get("channel") == "passthrough" for refusal in summary["refusals"]
    ), summary["refusals"]


# -- blocker 2: unmeasured calls count at their bound (probe p7) ---------------


def test_passthrough_unknown_outcome_counts_at_its_bound() -> None:
    """p7: a passthrough timeout is not free; measurement becomes incomplete."""
    agent = _agent()
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)

    def boom(*_args, **_kwargs):
        raise TimeoutError("read timed out after the provider accepted the request")

    orchestrator.client._proxy_send_transport = boom
    with guard.run_scope() as scope, pytest.raises(TimeoutError):
        orchestrator.client.proxy_send(agent, "chat/completions", {})
    # context-window ceiling: 1000 tokens at the $0.002/1k completion price
    assert scope.spent == Money.usd("0.002")
    assert scope.measurement_complete is False


def test_unmeasured_call_counts_at_its_bound_in_an_uncapped_run() -> None:
    """No cap means no reservation, but the unknown call still costs its bound."""
    agent = _agent()
    guard = _guard(None)
    with guard.run_scope() as scope:
        guarded_provider_call(
            agent,
            MESSAGES,
            lambda: "ok",
            usage_reader=lambda: None,
            token_bounds=lambda: AdmissionTokenBounds(
                prompt_tokens=100, max_output_tokens=100
            ),
        )
    assert scope.spent == Money.usd("0.0003")
    assert scope.measurement_complete is False


def test_failure_before_provider_egress_costs_nothing() -> None:
    """A missing credential raises before any request leaves the process."""
    agent = _agent()
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    # The real passthrough transport runs; _validate_provider raises
    # NotConfigured because the test KV holds no OpenRouter credential.
    with guard.run_scope() as scope, pytest.raises(NotConfigured):
        orchestrator.client.proxy_send(
            agent, "chat/completions", {"model": agent.model, "messages": MESSAGES}
        )
    assert scope.spent == Money.zero("USD")
    assert scope.measurement_complete is True
    assert scope.reserved == Money.zero("USD")


def test_failure_after_provider_egress_counts_at_its_bound(monkeypatch) -> None:
    """Once the transport marked egress, a failure is an unknown outcome."""
    agent = _agent()
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    client = orchestrator.client
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)

    def lost(*_args, **_kwargs):
        raise ConnectionResetError("connection reset after the request was written")

    monkeypatch.setattr(client, "_send_raw_with_retry", lost)
    with (
        guard.run_scope() as scope,
        pytest.raises((ConnectionResetError, ProviderUpstreamError)),
    ):
        client.proxy_send(
            agent, "chat/completions", {"model": agent.model, "messages": []}
        )
    assert scope.spent == Money.usd("0.002")
    assert scope.measurement_complete is False


# -- blocker 3: the bound uses the max_tokens actually sent (probe p2) ---------


def _exact_counter(monkeypatch, tokens: int = 10) -> None:
    monkeypatch.setattr(
        orchestrator_module,
        "describe_message_count",
        lambda counter, messages, model, tools=None: types.SimpleNamespace(
            token_count=tokens
        ),
    )


def test_effort_profile_output_cap_is_what_admission_prices(monkeypatch) -> None:
    """p2: a 4000-token effort profile is priced at 4000, not the agent's 100."""
    _exact_counter(monkeypatch)
    agent = _agent(max_out=100, ctx=128_000)
    guard = _guard("0.01", completion=0.02)
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    profile = ReasoningEffortProfile(
        max_output_tokens=4000, unsupported_provider_fallback="omit"
    )
    sent: list[int] = []

    def fake_chat(agent, messages, temperature=None, top_p=None, effort_profile=None):
        payload = orchestrator.client.apply_effort_profile(
            agent, {"max_tokens": 100}, effort_profile
        )
        sent.append(payload["max_tokens"])
        orchestrator.client._local.usage = {
            "prompt_tokens": 10,
            "completion_tokens": payload["max_tokens"],
        }
        return "x"

    orchestrator.client._chat_transport = fake_chat
    with guard.run_scope() as scope, pytest.raises(BudgetExceededError) as refused:
        orchestrator.client.chat(agent, MESSAGES, effort_profile=profile)
    assert sent == [], "the call must be refused before it is sent"
    assert refused.value.detail["reason"] == "insufficient_remaining_budget"
    assert Decimal(str(refused.value.detail["estimated_call_cost"])) == Decimal(
        "0.08001"
    )
    assert scope.spent == Money.zero("USD")


def test_transport_never_sends_more_output_than_admission_priced(monkeypatch) -> None:
    """Any later payload rewrite is clamped to the admitted output cap."""
    _exact_counter(monkeypatch)
    agent = _agent(max_out=100, ctx=128_000)
    guard = _guard("1")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    client = orchestrator.client
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    monkeypatch.setattr(
        orchestrator_module, "_provider_credential", lambda _agent: "test-key"
    )
    # A rewrite the admission bound did not model (profile=None) raises the cap.
    monkeypatch.setattr(
        client,
        "apply_effort_profile",
        lambda agent, payload, profile: {**payload, "max_tokens": 4000},
    )
    sent: list[dict] = []

    def capture(agent, payload, destination=None, *, timeout=None):
        sent.append(dict(payload))
        client._local.usage = {"prompt_tokens": 10, "completion_tokens": 5}
        return "ok"

    monkeypatch.setattr(client, "_send_with_retry", capture)
    with guard.run_scope() as scope:
        assert client.chat(agent, MESSAGES) == "ok"
    assert sent[0]["max_tokens"] == 100
    assert scope.output_cap_clamps == [
        {"field": "max_tokens", "requested": 4000, "admitted": 100}
    ]


# -- blocker 4: no scope never means no guard ----------------------------------


def test_unscoped_passthrough_runs_in_an_implicit_scope() -> None:
    """A paid call with no run scope is still capped, and the scope is recorded."""
    agent = _agent(ctx=128_000)  # ceiling bound $0.256 > $0.01 cap
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    sent: list[str] = []
    orchestrator.client._proxy_send_transport = lambda *args, **kwargs: (
        sent.append("x") or _chat_response("x", None)
    )
    with pytest.raises(BudgetExceededError):
        orchestrator.client.proxy_send(agent, "chat/completions", {"messages": []})
    assert sent == []
    summary = guard.last_implicit_run_summary()
    assert summary["budget"]["implicit_scope"] is True
    assert summary["budget"]["refusals"][0]["channel"] == "passthrough"
    assert guard.implicit_scope_count == 1
    assert guard.last_run_summary() is None  # implicit scopes are kept separate


def test_probe_is_admitted_and_metered(monkeypatch) -> None:
    """The readiness probe is a paid call: it runs in an implicit scope."""
    agent = _agent()
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    client = orchestrator.client
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)

    def send(agent, payload, destination=None, timeout=None):
        client._local.usage = {"prompt_tokens": 12, "completion_tokens": 1}
        return "OK"

    monkeypatch.setattr(client, "_send", send)
    assert client.probe(agent)["status"] == "ready"
    summary = guard.last_implicit_run_summary()
    assert summary["totals"][0]["calls"] == 1
    assert summary["totals"][0]["prompt_tokens"] == 12


def test_proxy_capability_opens_one_run_scope(monkeypatch) -> None:
    """``proxy_capability`` is a top-level entry point with its own run."""
    agent = _agent(tags=("reasoning", "embedding"))
    guard = _guard("0.01")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    orchestrator.client._proxy_send_transport = lambda *args, **kwargs: {
        "data": [{"embedding": [0.1]}],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }
    orchestrator.proxy_capability(
        {"model": agent.model, "input": ["x"]},
        capability="embedding",
        endpoint="embeddings",
    )
    summary = guard.last_run_summary()
    assert summary is not None and summary["totals"][0]["calls"] == 1
    assert summary["totals"][0]["cost_complete"] is True
    assert guard.implicit_scope_count == 0


# -- session: "per run" is the outermost scope ---------------------------------


def test_outer_run_scope_shares_one_cap_across_route_once_calls() -> None:
    """A caller wraps a whole session in one ``run_scope``; nested runs join it."""
    worker = _agent("paid_worker")
    guard = _guard("0.01")  # ceiling bound per call: 1000 tokens x $0.002/1k
    orchestrator = TaskOrchestrator([worker], spend_guard=guard)
    sent = {"chat": 0, "judge": 0}
    usage = {"prompt_tokens": 500, "completion_tokens": 400}  # $0.0013 per call
    orchestrator.client._chat_transport = _chat_transport(
        orchestrator.client, sent, usage
    )
    orchestrator.client._proxy_send_transport = _judge_transport(sent, usage)
    outcomes = []
    with guard.run_scope() as session:
        for index in range(6):
            try:
                orchestrator.route_once([{"role": "user", "content": f"task {index}"}])
                outcomes.append("served")
            except BudgetExceededError:
                outcomes.append("refused")
            assert session.spent <= Money.usd("0.01")
    summary = guard.last_run_summary()
    assert summary["run_id"] == session.run_id
    assert summary["totals"][0]["calls"] == sent["chat"] + sent["judge"]
    assert Decimal(str(summary["budget"]["run_spent_cost"])) <= Decimal("0.01")
    assert outcomes[-2:] == ["refused", "refused"]
    assert sent["chat"] < 6
    # Without the outer scope every route_once would get a fresh $0.01 cap.
    fresh = _guard("0.01")
    solo = TaskOrchestrator([worker], spend_guard=fresh)
    solo_sent = {"chat": 0, "judge": 0}
    solo.client._chat_transport = _chat_transport(solo.client, solo_sent, usage)
    solo.client._proxy_send_transport = _judge_transport(solo_sent, usage)
    for index in range(6):
        solo.route_once([{"role": "user", "content": f"task {index}"}])
    assert solo_sent == {"chat": 6, "judge": 6}


def test_nested_run_scope_and_implicit_scope_join_the_outer_run() -> None:
    """Nested ``run_scope`` and implicit scopes reuse the active outer run."""
    guard = _guard("0.01")
    with guard.run_scope() as outer:
        with guard.run_scope() as inner:
            assert inner is outer
        with guard.implicit_run_scope() as implicit:
            assert implicit is outer
    assert guard.implicit_scope_count == 0


# -- enumeration: no send entry point bypasses admission -----------------------

_HOOKS = {
    "guarded_provider_call",
    "guarded_provider_stream",
    "metered_passthrough_call",
}
_PRIMITIVES = {"_open_provider", "_open_model_provider"}
#: Public ModelClient methods allowed to reach the HTTP primitive unguarded,
#: with the reason. None of them is a token-priced inference call.
_UNGUARDED_ALLOWLIST = {
    ("probe", "_open_provider"): "local /models registry GET before the guarded probe",
    ("proxy_get_json", "_open_model_provider"): "async job status GET (no token cost)",
    ("proxy_get_bytes", "_open_model_provider"): "async job media GET (no token cost)",
    (
        "proxy_delete_json",
        "_open_model_provider",
    ): "provider file DELETE (no token cost)",
    ("proxy_upload", "_open_model_provider"): "Files API upload (no token cost)",
}
#: Modules outside ModelClient that open provider connections directly.
_EXTERNAL_ALLOWLIST = {
    "privacy_policy_analysis.py": "Wardnet policy fetch, not a model provider",
    "web_search.py": "SearXNG search, not a model provider",
    "model_discovery.py": (
        "operator model discovery (catalog GET and a max_tokens=32 tool-call "
        "probe on a guard-less client); documented limitation in ADR 0138"
    ),
}


def _self_calls(function: ast.FunctionDef, *, skip_guarded: bool = True) -> set[str]:
    """``self.<name>`` references, optionally skipping arguments handed to a spend hook."""
    guarded_nodes: set[int] = set()
    guarded_names: set[str] = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _HOOKS
        ):
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                if isinstance(argument, ast.Lambda):
                    guarded_nodes.add(id(argument))
                elif isinstance(argument, ast.Name):
                    guarded_names.add(argument.id)
    for node in ast.walk(function):
        if (
            isinstance(node, ast.FunctionDef)
            and node is not function
            and node.name in guarded_names
        ):
            guarded_nodes.add(id(node))
    found: set[str] = set()

    def visit(node: ast.AST) -> None:
        if skip_guarded and id(node) in guarded_nodes:
            return
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            found.add(node.attr)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return found


def _model_client_methods() -> dict[str, ast.FunctionDef]:
    tree = ast.parse((PACKAGE / "orchestrator.py").read_text(encoding="utf-8"))
    model_client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ModelClient"
    )
    return {
        node.name: node
        for node in model_client.body
        if isinstance(node, ast.FunctionDef)
    }


def _paths_to_primitives(skip_guarded: bool) -> dict[str, list[tuple[str, ...]]]:
    """Public method -> call paths reaching an HTTP primitive through ``self``."""
    methods = _model_client_methods()
    graph = {
        name: _self_calls(node, skip_guarded=skip_guarded)
        for name, node in methods.items()
    }
    assert graph["chat"] and graph["probe"], "the scan must see ModelClient bodies"
    reached: dict[str, list[tuple[str, ...]]] = {}
    for name in sorted(methods):
        if name.startswith("_"):
            continue
        seen: set[str] = set()
        stack = [(name, (name,))]
        while stack:
            current, path = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for callee in graph.get(current, ()):
                if callee in _PRIMITIVES:
                    reached.setdefault(name, []).append((*path, callee))
                elif callee in graph:
                    stack.append((callee, (*path, callee)))
    return reached


def test_no_public_model_client_method_reaches_the_provider_unguarded() -> None:
    """Statically: every path to the HTTP opener passes through a spend hook."""
    violations = [
        " -> ".join(path)
        for name, paths in _paths_to_primitives(skip_guarded=True).items()
        for path in paths
        if (name, path[-1]) not in _UNGUARDED_ALLOWLIST
    ]
    assert violations == [], violations


def test_every_paid_model_client_send_is_exercised_at_runtime() -> None:
    """The runtime table below covers every public method that can reach a provider."""
    senders = set(_paths_to_primitives(skip_guarded=False))
    unguarded_only = {name for name, _primitive in _UNGUARDED_ALLOWLIST} - {"probe"}
    missing = senders - set(_ENTRY_POINTS) - unguarded_only
    assert "chat" in senders and "proxy_send" in senders
    assert missing == set(), missing


def test_no_module_opens_a_model_provider_outside_model_client() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "orchestrator.py":
            continue
        text = path.read_text(encoding="utf-8")
        opens_provider = any(f".{primitive}(" in text for primitive in _PRIMITIVES)
        if opens_provider and path.name not in _EXTERNAL_ALLOWLIST:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


class _Egress(Exception):
    """Raised by a patched send primitive: the call bypassed admission."""


def _refusing_orchestrator(monkeypatch):
    """A client whose every send primitive fails the test if reached."""
    agent = _agent(ctx=128_000, tags=("reasoning", "embedding"))  # ceiling $0.256
    guard = _guard("0.000001")
    orchestrator = TaskOrchestrator([agent], spend_guard=guard)
    client = orchestrator.client
    reached: list[str] = []

    def primitive(name):
        def fail(*_args, **_kwargs):
            reached.append(name)
            raise _Egress(name)

        return fail

    for name in (
        "_send",
        "_send_raw",
        "_send_with_retry",
        "_send_raw_with_retry",
        "_batch_run",
        "_open_provider",
        "_open_model_provider",
    ):
        monkeypatch.setattr(client, name, primitive(name))
    monkeypatch.setattr(client, "_validate_provider", lambda _agent: None)
    return orchestrator, agent, reached


def _drain(value):
    return list(value) if isinstance(value, types.GeneratorType) else value


_ENTRY_POINTS = {
    "chat": lambda o, a: o.client.chat(a, MESSAGES),
    "stream_chat": lambda o, a: _drain(o.client.stream_chat(a, MESSAGES)),
    "proxy_send": lambda o, a: o.client.proxy_send(
        a, "chat/completions", {"messages": MESSAGES}
    ),
    "proxy_send_once": lambda o, a: o.client.proxy_send_once(
        a, "chat/completions", {"messages": MESSAGES}
    ),
    "probe_structured_chat": lambda o, a: o.client.probe_structured_chat(
        a, {"messages": MESSAGES, "response_format": {"type": "json_object"}}
    ),
    "proxy_send_bytes": lambda o, a: o.client.proxy_send_bytes(
        a, "audio/speech", {"input": "hello"}
    ),
    "embed": lambda o, a: o.client.embed(a, ["hello"]),
    "embed_with_usage": lambda o, a: o.client.embed_with_usage(a, ["hello"]),
    "batch_chat": lambda o, a: o.client.batch_chat(a, {"row": MESSAGES}),
    "probe": lambda o, a: o.client.probe(a),
    "proxy_capability": lambda o, a: o.proxy_capability(
        {"model": a.model, "input": ["x"]},
        capability="embedding",
        endpoint="embeddings",
    ),
    "route_once": lambda o, a: o.route_once(MESSAGES),
    "batch_route": lambda o, a: o.batch_route(["hello"]),
}


@pytest.mark.parametrize("entry", sorted(_ENTRY_POINTS))
def test_send_entry_point_is_refused_before_egress_without_a_scope(
    entry: str, monkeypatch
) -> None:
    orchestrator, agent, reached = _refusing_orchestrator(monkeypatch)
    # Refusals surface in entry-specific shapes (raised, degraded, not_ready).
    with contextlib.suppress(Exception):
        _ENTRY_POINTS[entry](orchestrator, agent)
    assert reached == [], f"{entry} reached {reached} without spend admission"
    guard = orchestrator.spend_guard
    summary = guard.last_run_summary() or guard.last_implicit_run_summary()
    assert summary is not None, f"{entry} opened no spend scope"
    assert summary["budget"]["refusals"], f"{entry} was not refused by admission"


# -- spend-settle refuses a reservation whose call has not finished ------------


def test_settle_refuses_an_in_flight_reservation_unless_forced(
    tmp_path, monkeypatch, capsys
) -> None:
    from contextual_orchestrator.spend_metering import ReservationInFlightError

    ledger = tmp_path / "ledger.jsonl"
    guard = _guard("1", store=JsonlSpendLedgerStore(ledger))
    agent = _agent()
    observed: list[str] = []

    def in_flight() -> str:
        [reservation] = JsonlSpendLedgerStore(ledger).active_spend_reservations()
        observed.append(reservation.reservation_id)
        store = JsonlSpendLedgerStore(ledger)
        with pytest.raises(ReservationInFlightError):
            operator_settle_reservation(
                store,
                reservation.reservation_id,
                settled_cost=Money.zero("USD"),
                reason="looks stuck",
                settled_by="oncall",
                now=guard.now(),
            )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "spend-settle",
                "--spend-ledger-path",
                str(ledger),
                "--reservation-id",
                reservation.reservation_id,
                "--settled-cost-usd",
                "0",
                "--operator",
                "oncall",
                "--reason",
                "stuck",
            ],
        )
        with pytest.raises(SystemExit):
            cli.main()
        assert "in flight" in capsys.readouterr().err
        return "ok"

    with guard.run_scope():
        assert (
            guarded_provider_call(
                agent,
                MESSAGES,
                in_flight,
                usage_reader=lambda: {"prompt_tokens": 1, "completion_tokens": 1},
            )
            == "ok"
        )
    assert observed and JsonlSpendLedgerStore(ledger).active_spend_reservations() == []


def test_settle_force_clears_a_reservation_left_by_a_crashed_process() -> None:
    store = InMemorySpendLedgerStore()
    guard = _guard("1", store=store)
    scope = guard.open_run_scope()
    admission = scope.admit_call(
        _agent(),
        token_bounds=AdmissionTokenBounds(prompt_tokens=10, max_output_tokens=10),
        channel="sync",
    )
    # The process "crashed": no settle, no usage entry.
    settlement = operator_settle_reservation(
        store,
        admission.reservation.reservation_id,
        settled_cost=Money.zero("USD"),
        reason="worker pod OOM-killed before the request was sent",
        settled_by="oncall",
        now=guard.now(),
        force=True,
    )
    assert settlement.settled_cost == Money.zero("USD")
    assert store.active_spend_reservations() == []
