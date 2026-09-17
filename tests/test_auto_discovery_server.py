"""Server-startup model discovery activates discovered runtime agents."""

from dataclasses import replace
import os
from unittest.mock import patch

import pytest

from contextual_orchestrator.__main__ import (
    _auto_discover_runtime_agents,
    _probe_configured_gateway_structured_chat,
    main,
)
from contextual_orchestrator.model_discovery import (
    DiscoveredModel,
    agent_from_discovered,
    agent_id_for,
    legacy_agent_id_for,
    model_group_name_for,
)
from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator


def test_auto_discovery_activates_chat_and_embedding_capable_agents(monkeypatch) -> None:
    """Startup retains a provider-declared embedding route beside chat."""
    chat = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    embedding = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="embedding-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([chat, embedding], []),
    )

    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 2
    chat_agent = next(agent for agent in orchestrator.agents if agent.model == chat.model_id)
    embedding_agent = next(agent for agent in orchestrator.agents if agent.model == embedding.model_id)
    assert chat_agent.disabled is False
    assert "chat" in chat_agent.tags
    assert embedding_agent.disabled is False
    assert "embedding" in embedding_agent.tags
    assert orchestrator.select_capability_agent("embedding").id == embedding_agent.id
    assert all(not candidate.base_url.startswith("mock://") for candidate in orchestrator.agents)
    assert "bootstrap_agent" in result["updated"]


def test_embedding_only_discovery_keeps_chat_fallbacks(monkeypatch) -> None:
    embedding = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="text-embedding-only",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
        spend_admitted=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([embedding], []),
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent(
                "configured_gateway_placeholder",
                "",
                provider_name="configured_gateway",
                base_url="https://gateway.synthetic.example/v1",
            ),
            ModelAgent(
                "bootstrap_chat_agent",
                "bootstrap-chat-model",
                tags=("bootstrap_seed",),
            ),
        ]
    )

    _auto_discover_runtime_agents(orchestrator)

    by_id = {agent.id: agent for agent in orchestrator.candidates}
    assert "configured_gateway_placeholder" in by_id
    assert by_id["bootstrap_chat_agent"].disabled is False


def test_configured_gateway_discovery_retains_only_structured_probe_successes(
    monkeypatch,
) -> None:
    """Configured-gateway chat rows require a successful bounded structured probe."""
    models = [
        DiscoveredModel(
            provider_name="configured_gateway",
            model_id=model_id,
            credential_name="LLM_GATEWAY_API_KEY",
            chat_base_url="https://gateway.synthetic.example/v1",
            auth_scheme="Bearer",
            capabilities=("chat",),
        )
        for model_id in ("stale-model", "live-model")
    ]
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential",
        lambda name: "present" if name == "LLM_GATEWAY_API_KEY" else None,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: (models, []),
    )
    probes: list[str] = []

    def probe(_orchestrator, model):
        probes.append(model.model_id)
        return model.model_id == "live-model"

    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        probe,
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert probes == ["stale-model", "live-model"]
    assert result["added"] == [agent_id_for(models[1])]
    assert all(agent.model != "stale-model" for agent in orchestrator.agents)


def test_failed_gateway_catalog_probes_remove_unprobed_blank_seed(monkeypatch) -> None:
    """A catalog-wide auth failure cannot fall through to the blank seed row."""
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="auth-failing-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    live_model = DiscoveredModel(
        provider_name="openrouter",
        model_id="synthetic-live-model",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.synthetic.example/v1",
        provider_name="configured_gateway",
        credential_key="LLM_GATEWAY_API_KEY",
        tags=("bootstrap_seed",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model, live_model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: False,
    )
    orchestrator = TaskOrchestrator([seed])

    _auto_discover_runtime_agents(orchestrator)

    assert all(agent.id != seed.id for agent in orchestrator.candidates)
    selected = orchestrator._select_agent("task", "synthesizer")
    assert selected.provider_name == "openrouter"
    assert selected.model == live_model.model_id


def test_failed_gateway_catalog_probe_transiently_retires_the_only_blank_seed(
    monkeypatch, tmp_path
) -> None:
    """A failed sole seed is uncallable now and can be reprobed after restart."""
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="auth-failing-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.synthetic.example/v1",
        provider_name="configured_gateway",
        credential_key="LLM_GATEWAY_API_KEY",
        tags=("bootstrap_seed",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: False,
    )
    agents_db = str(tmp_path / "agents.db")
    orchestrator = TaskOrchestrator([seed], agents_db=agents_db)

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["updated"] == []
    assert orchestrator.agents == []
    assert orchestrator.candidates == []
    with pytest.raises(RuntimeError, match="no chat-compatible agent available"):
        orchestrator._select_agent("task", "synthesizer")

    restarted = TaskOrchestrator([seed], agents_db=agents_db)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: True,
    )

    recovered = _auto_discover_runtime_agents(restarted)

    assert recovered["added"] == [agent_id_for(model)]
    assert restarted.agents[0].model == model.model_id


def test_auto_discovery_restart_recovers_a_persisted_disabled_gateway_seed(
    monkeypatch, tmp_path
) -> None:
    """A legacy failure tombstone cannot stop a later healthy discovery pass."""
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="recovered-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    seed = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        base_url="https://gateway.synthetic.example/v1",
        provider_name="configured_gateway",
        credential_key="LLM_GATEWAY_API_KEY",
        tags=("bootstrap_seed",),
    )
    agents_db = str(tmp_path / "agents.db")
    failed = TaskOrchestrator([seed], agents_db=agents_db)
    failed.sync_discovered_agents([replace(seed, disabled=True)])
    failed.close()

    monkeypatch.setattr(
        "contextual_orchestrator.__main__.load_agents", lambda _path: [seed]
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: True,
    )
    active_models = []

    def complete(orchestrator, *_args, **_kwargs):
        active_models.extend(agent.model for agent in orchestrator.agents)
        return {"answer": "ok"}

    monkeypatch.setattr(TaskOrchestrator, "complete", complete)

    main([
        "recover",
        "--agents-db", agents_db,
        "--auto-discover-model-agents",
    ])

    assert active_models == [model.model_id]


def test_failed_gateway_probe_disables_persisted_discovered_agent_after_restart(
    monkeypatch, tmp_path
) -> None:
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="stale-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    existing = replace(agent_from_discovered(model), disabled=False)
    agents_db = str(tmp_path / "agents.db")
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: False,
    )
    orchestrator = TaskOrchestrator([existing], agents_db=agents_db)

    _auto_discover_runtime_agents(orchestrator)
    restarted = TaskOrchestrator([], agents_db=agents_db, allow_empty_agents=True)

    assert restarted.candidates[0].disabled is True
    assert "structured:blocked" in restarted.candidates[0].tags


def test_failed_gateway_probe_disables_legacy_id_persisted_agent(
    monkeypatch, tmp_path
) -> None:
    """A persisted agent kept under the pre-fingerprint legacy id is disabled too.

    A failed configured-gateway structured probe is recorded only under the
    new fingerprinted id (``agent_id_for``), but a persisted agent from
    before model-group fingerprinting keeps its legacy id
    (``legacy_agent_id_for``). The ``runtime_models`` membership check must
    accept either id form -- matching the ``existing_by_id`` fallback lookup
    used later in the same function -- otherwise a legacy-id agent whose
    model now fails the probe is silently dropped from ``runtime_models``,
    ``sync_discovered_agents`` is never called for it, and it is left
    enabled (and unpersisted) indefinitely.
    """
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="stale-legacy-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    existing = replace(
        agent_from_discovered(model),
        id=legacy_agent_id_for(model),
        disabled=False,
    )
    agents_db = str(tmp_path / "agents.db")
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: False,
    )
    orchestrator = TaskOrchestrator([existing], agents_db=agents_db)

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["updated"] == [existing.id]
    persisted = next(agent for agent in orchestrator.candidates if agent.id == existing.id)
    assert persisted.disabled is True
    assert "structured:blocked" in persisted.tags


def test_failed_gateway_probe_keeps_persisted_embedding_capability(
    monkeypatch, tmp_path
) -> None:
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="mixed-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "embedding"),
    )
    mixed = replace(agent_from_discovered(model), disabled=False, priority=100)
    fallback = ModelAgent("fallback_agent", "fallback-chat-model")
    agents_db = str(tmp_path / "agents.db")
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.get_credential", lambda _name: "present"
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([model], []),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__._probe_configured_gateway_structured_chat",
        lambda *_args: False,
    )
    orchestrator = TaskOrchestrator([fallback, mixed], agents_db=agents_db)

    _auto_discover_runtime_agents(orchestrator)
    restarted = TaskOrchestrator([fallback], agents_db=agents_db)

    persisted = next(agent for agent in restarted.candidates if agent.id == mixed.id)
    assert persisted.disabled is False
    assert "structured:blocked" in persisted.tags
    assert restarted.select_capability_agent("embedding").id == mixed.id
    assert restarted._select_agent("task", "synthesizer").id == fallback.id


def test_configured_gateway_structured_probe_is_bounded_and_validates_output() -> None:
    """The startup probe proves JSON object service with a bounded synthetic call."""
    model = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="candidate-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    orchestrator = TaskOrchestrator([], allow_empty_agents=True)
    observed = {}

    def send(agent, payload):
        observed.update(agent=agent, payload=payload)
        return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    orchestrator.client.probe_structured_chat = send

    assert _probe_configured_gateway_structured_chat(orchestrator, model) is True
    assert observed["payload"]["max_tokens"] == 8
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    assert "json" in observed["payload"]["messages"][0]["content"].casefold()


def test_auto_discovery_activates_a_free_vision_model_but_free_pool_excludes_it(
    monkeypatch,
) -> None:
    """A free vision-input model becomes a normal agent, not a blind-free one.

    Reproduces the second locus of ContextualWisdomLab/.github#1198's incident
    (Devin review on PR #933): ``_auto_discover_runtime_agents`` activates
    every routable discovered model directly through
    ``model_discovery.agent_from_discovered`` and never consulted
    ``model_discovery.free_discovered_models``'s exclusion at all, so NVIDIA
    NIM's ``meta/llama-3.2-90b-vision-instruct`` kept its ``cost:free`` tag and
    stayed blindly selectable by ``orchestrator/free`` through this second
    path even after that first function was fixed. Pre-fix, every assertion
    from ``_is_general_free_agent`` onward here fails: the agent is (wrongly)
    treated as blind-free-pool eligible and ``orchestrator/free`` is (wrongly)
    advertised.
    """
    vision = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="meta/llama-3.2-90b-vision-instruct",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        input_modalities=("text", "image"),
        output_modalities=("text",),
        is_free=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([vision], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert len(result["added"]) == 1
    agent = next(
        candidate for candidate in orchestrator.agents if candidate.id == result["added"][0]
    )
    # The model is a legitimate chat-capable agent (e.g. for a caller that
    # explicitly requests it with an image) and its price evidence is honest.
    assert agent.disabled is False
    assert "cost:free" in agent.tags
    # Its own capability route can still serve it for free (price-only).
    assert orchestrator._is_free_agent(agent) is True
    # It must never be selectable by the capability-blind general chat pool.
    assert orchestrator._is_general_free_agent(agent) is False
    assert orchestrator.FREE_MODEL not in {
        row["id"] for row in orchestrator.list_openai_models()["data"]
    }


def test_auto_discovery_activates_bare_chat_but_not_embedding_ids(monkeypatch) -> None:
    """A metadata-free gateway listing still activates chat deployments.

    Mirrors the user-facing report: on a bare OpenAI-compatible gateway
    (``LLM_GATEWAY_API_URL`` + ``LLM_GATEWAY_API_KEY``) whose /model/info
    merge leaves chat rows without capability evidence, chat models must be
    activated while embedding-named models stay out of the routing pool.
    """
    bare_chat = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="gpt-chat-7x",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://llm-gateway-dev.example/v1",
        auth_scheme="Bearer",
        capabilities=(),
    )
    bare_embedding = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="text-embedding-5",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://llm-gateway-dev.example/v1",
        auth_scheme="Bearer",
        capabilities=(),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([bare_chat, bare_embedding], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )
    result = _auto_discover_runtime_agents(orchestrator)
    assert result["added"] == [agent_id_for(bare_chat)]
    agents = orchestrator.agents
    assert any(agent.id == agent_id_for(bare_chat) for agent in agents)
    assert all(agent.model != "text-embedding-5" for agent in agents)


def test_auto_discovery_activates_provider_catalog_rows(monkeypatch) -> None:
    """Discovered provider rows with serving evidence enter the runtime pool."""
    provider_row = DiscoveredModel(
        provider_name="nvidia_nim",
        model_id="provider/nim-chat",
        credential_name="NVIDIA_NIM_API_KEY",
        chat_base_url="https://integrate.api.nvidia.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([provider_row], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {
        "added": [agent_id_for(provider_row)],
        "updated": ["bootstrap_agent"],
    }
    agent = orchestrator.candidates[-1]
    assert agent.model == provider_row.model_id
    assert agent.disabled is False


def test_auto_discovery_never_activates_evidence_only_rows(monkeypatch) -> None:
    """A row explicitly marked evidence_only never becomes a serving agent."""
    evidence = DiscoveredModel(
        provider_name="example_evidence_provider",
        model_id="provider/router-chat",
        credential_name="EXAMPLE_EVIDENCE_PROVIDER_API_KEY",
        chat_base_url="https://example-evidence-provider.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat", "response_format"),
        evidence_only=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([evidence], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert [agent.model for agent in orchestrator.agents] == ["bootstrap-model"]


def test_auto_discovery_never_activates_evidence_only_embedding_rows(monkeypatch) -> None:
    """Embedding capability cannot bypass the evidence-only serving boundary."""
    evidence = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="provider/evidence-embedding",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.synthetic.example/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
        evidence_only=True,
        spend_admitted=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([evidence], []),
    )
    orchestrator = TaskOrchestrator(
        [ModelAgent("bootstrap_agent", "bootstrap-model", tags=("bootstrap_seed",))]
    )

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert [agent.model for agent in orchestrator.agents] == ["bootstrap-model"]


def test_auto_discovery_keeps_metadata_free_general_chat_models(monkeypatch) -> None:
    """OpenAI-style model rows without capability metadata remain discoverable."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="gpt-5.4",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == [agent_id_for(discovered)]
    assert orchestrator.agents[-1].model == discovered.model_id


def test_auto_discovery_removes_the_configured_gateway_placeholder(monkeypatch) -> None:
    """A blank discovery seed never participates in inference after expansion."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([placeholder])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == [agent_id_for(discovered)]
    assert [agent.model for agent in orchestrator.agents] == ["chat-capable-model"]
    assert placeholder.id not in orchestrator._group_router.snapshot()


def test_auto_discovery_removes_placeholder_for_existing_gateway_model(monkeypatch) -> None:
    """A successful gateway refresh cleans its seed even when no agent is added."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "configured_gateway_chat_capable_model",
        "chat-capable-model",
        provider_name="configured_gateway",
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([existing, placeholder])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.agents == [existing]


def test_auto_discovery_assigns_group_to_legacy_discovered_agent(monkeypatch) -> None:
    discovered = DiscoveredModel(
        "openrouter", "Vendor/Model", "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1", "Bearer", capabilities=("chat",),
    )
    legacy = replace(
        agent_from_discovered(discovered),
        id="openrouter_vendor_model",
        group_name="",
        disabled=False,
    )
    orchestrator = TaskOrchestrator([legacy])
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": [legacy.id]}
    assert orchestrator.candidates[0].id == legacy.id
    assert orchestrator.candidates[0].group_name == model_group_name_for(discovered)


def test_auto_discovery_keeps_last_enabled_placeholder_for_disabled_gateway_model(
    monkeypatch,
) -> None:
    """Discovery preserves operator quarantine without aborting server startup."""
    discovered = DiscoveredModel(
        provider_name="configured_gateway",
        model_id="chat-capable-model",
        credential_name="LLM_GATEWAY_API_KEY",
        chat_base_url="https://gateway.example/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "configured_gateway_chat_capable_model",
        "chat-capable-model",
        provider_name="configured_gateway",
        disabled=True,
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([existing, placeholder])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.candidates == [existing, placeholder]
    assert orchestrator.agents == [placeholder]


def test_auto_discovery_adds_embedding_without_disabling_configured_chat_pool(monkeypatch) -> None:
    """A capability route coexists with an explicitly configured chat pool."""
    embedding = DiscoveredModel(
        provider_name="openai",
        model_id="embedding-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([embedding], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)
    assert result == {"added": [agent_id_for(embedding)], "updated": []}
    assert {agent.id for agent in orchestrator.agents} == {
        "bootstrap_agent", agent_id_for(embedding)
    }


def test_unrelated_discovery_keeps_configured_gateway_placeholder(monkeypatch) -> None:
    """Another healthy provider must not erase a temporarily unavailable gateway."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    placeholder = ModelAgent(
        "configured_gateway_bootstrap",
        "",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([placeholder])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result["added"] == [agent_id_for(discovered)]
    assert placeholder in orchestrator.agents


def test_auto_discovery_uses_explicit_capabilities_before_model_id_heuristics(monkeypatch) -> None:
    generic_non_chat = DiscoveredModel(
        provider_name="openai",
        model_id="generic-deployment",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("embedding",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([generic_non_chat], []),
    )

    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])

    result = _auto_discover_runtime_agents(orchestrator)
    assert result["added"] == [agent_id_for(generic_non_chat)]
    agent = orchestrator.select_capability_agent("embedding")
    assert agent.model == "generic-deployment"
    assert "chat" not in agent.tags


def test_auto_discovery_preserves_sole_real_bootstrap_seed(monkeypatch) -> None:
    """A seed cannot count itself as the replacement that retires it."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args, **_kwargs: ([], []),
    )
    seed = ModelAgent(
        "bootstrap_agent",
        "bootstrap-model",
        base_url="https://provider.invalid/v1",
        tags=("bootstrap_seed",),
    )
    orchestrator = TaskOrchestrator([seed])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.agents == [seed]


def test_auto_discovery_preserves_existing_operator_settings(monkeypatch) -> None:
    """Startup discovery must not replace an operator-managed agent."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "openai_chat_capable_model",
        discovered.model_id,
        tags=("chat", "operator-tag"),
        disabled=True,
    )
    bootstrap = ModelAgent("bootstrap_agent", "bootstrap-model")
    orchestrator = TaskOrchestrator([bootstrap, existing])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert orchestrator.candidates == [bootstrap, existing]


def test_auto_discovery_refreshes_discovered_limits_across_restart(
    monkeypatch, tmp_path
) -> None:
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        max_output_tokens=8192,
        context_window=256000,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "openai_chat_capable_model",
        discovered.model_id,
        tags=("discovered", "chat", "operator-tag"),
        priority=17,
        group_name="operator-group",
        max_output_tokens=2048,
        context_window=128000,
    )
    bootstrap = ModelAgent("bootstrap_agent", "bootstrap-model")
    database = str(tmp_path / "agents.db")
    first = TaskOrchestrator([bootstrap, existing], agents_db=database)

    assert _auto_discover_runtime_agents(first)["updated"] == [existing.id]
    refreshed = first._agent(existing.id)
    assert (refreshed.max_output_tokens, refreshed.context_window) == (8192, 256000)
    assert (refreshed.priority, refreshed.group_name) == (17, "operator_group")
    assert refreshed.tags == existing.tags

    restarted = TaskOrchestrator([bootstrap, existing], agents_db=database)
    restored = restarted._agent(existing.id)
    assert (restored.max_output_tokens, restored.context_window) == (8192, 256000)
    assert (restored.priority, restored.group_name) == (17, "operator_group")
    assert restored.tags == existing.tags

    unavailable_limits = replace(
        discovered, max_output_tokens=None, context_window=None
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([unavailable_limits], []),
    )
    assert _auto_discover_runtime_agents(restarted) == {"added": [], "updated": []}
    preserved = restarted._agent(existing.id)
    assert (preserved.max_output_tokens, preserved.context_window) == (8192, 256000)

    conflicted_limits = replace(
        unavailable_limits,
        max_output_tokens_conflicted=True,
        context_window_conflicted=True,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([conflicted_limits], []),
    )
    assert _auto_discover_runtime_agents(restarted)["updated"] == [existing.id]
    cleared = restarted._agent(existing.id)
    assert (cleared.max_output_tokens, cleared.context_window) == (None, None)

    after_conflict_restart = TaskOrchestrator(
        [bootstrap, existing], agents_db=database
    )
    restored_clear = after_conflict_restart._agent(existing.id)
    assert (restored_clear.max_output_tokens, restored_clear.context_window) == (
        None,
        None,
    )


def test_auto_discovery_disables_existing_discovered_paid_openrouter_without_credit(
    monkeypatch,
) -> None:
    discovered = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/paid",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        spend_admitted=False,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([discovered], []),
    )
    existing = ModelAgent(
        "openrouter_provider_paid",
        discovered.model_id,
        base_url="https://custom.example/v1",
        provider_name="openrouter",
        tags=("discovered", "chat", "operator-tag"),
        priority=17,
    )
    orchestrator = TaskOrchestrator([existing])

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": [existing.id]}
    blocked = orchestrator.candidates[0]
    assert blocked.disabled is True
    assert blocked.base_url == existing.base_url
    assert blocked.priority == 17
    assert blocked.tags == (*existing.tags, "spend:blocked")

    _auto_discover_runtime_agents(orchestrator)
    assert orchestrator.candidates[0] == blocked

    recovered = replace(discovered, spend_admitted=True)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([recovered], []),
    )
    _auto_discover_runtime_agents(orchestrator)

    assert orchestrator.candidates[0] == replace(
        existing, group_name=model_group_name_for(recovered)
    )


def test_auto_discovery_recovers_model_first_discovered_while_spend_blocked(
    monkeypatch,
) -> None:
    blocked = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/paid",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        spend_admitted=False,
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([blocked], []),
    )
    orchestrator = TaskOrchestrator([], allow_empty_agents=True)
    _auto_discover_runtime_agents(orchestrator)
    assert orchestrator.candidates[0].disabled is True

    recovered = replace(blocked, spend_admitted=True)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([recovered], []),
    )
    _auto_discover_runtime_agents(orchestrator)

    assert orchestrator.candidates[0].disabled is False
    assert "spend:blocked" not in orchestrator.candidates[0].tags


def test_auto_discovery_preserves_operator_disable_across_spend_recovery(
    monkeypatch,
) -> None:
    blocked = DiscoveredModel(
        provider_name="openrouter",
        model_id="provider/paid",
        credential_name="OPENROUTER_API_KEY",
        chat_base_url="https://openrouter.ai/api/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
        spend_admitted=False,
    )
    existing = ModelAgent(
        "openrouter_provider_paid",
        blocked.model_id,
        provider_name="openrouter",
        tags=("discovered", "chat"),
        disabled=True,
    )
    orchestrator = TaskOrchestrator([existing], allow_empty_agents=True)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([blocked], []),
    )
    _auto_discover_runtime_agents(orchestrator)

    recovered = replace(blocked, spend_admitted=True)
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *_args, **_kwargs: ([recovered], []),
    )
    _auto_discover_runtime_agents(orchestrator)

    assert orchestrator.candidates[0] == replace(
        existing, group_name=model_group_name_for(recovered)
    )


def test_runtime_auto_discovery_does_not_read_gateway_environment(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources, **_kwargs: (captured.extend(sources) or [], []),
    )
    orchestrator = TaskOrchestrator([ModelAgent("bootstrap_agent", "bootstrap-model")])
    with patch.dict(
        os.environ,
        {
            "LLM_GATEWAY_URL": "http://unsafe.invalid/v1",
            "LLM_GATEWAY_API_KEY": "must-not-be-promoted",
        },
        clear=True,
    ):
        assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert all(source.provider_name != "configured_gateway" for source in captured)


def test_runtime_auto_discovery_skips_gateway_outside_allowlist(monkeypatch) -> None:
    """One stale persisted gateway cannot abort otherwise valid discovery."""
    captured = []
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda sources, **_kwargs: (captured.extend(sources) or [], []),
    )
    gateway = ModelAgent(
        "configured_gateway",
        "gateway-model",
        base_url="https://gateway.example/v1",
        provider_name="configured_gateway",
    )
    orchestrator = TaskOrchestrator([gateway])

    assert _auto_discover_runtime_agents(orchestrator) == {"added": [], "updated": []}
    assert all(source.provider_name != "configured_gateway" for source in captured)


def test_auto_discovery_retires_mock_seed_when_real_agent_already_exists(
    monkeypatch,
) -> None:
    """Restarted discovery cannot restore mocks beside an active real agent."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    real_agent = ModelAgent(
        "openai_chat_capable_model",
        discovered.model_id,
        base_url=discovered.chat_base_url,
        tags=("discovered", "chat"),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args, **_kwargs: ([discovered], []),
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("mock_seed_agent", "mock-model", tags=("bootstrap_seed",)),
            real_agent,
        ]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {
        "added": [],
        "updated": [real_agent.id, "mock_seed_agent"],
    }
    assert orchestrator.agents == [
        replace(real_agent, group_name=model_group_name_for(discovered))
    ]


def test_auto_discovery_retires_mock_seed_when_current_discovery_is_empty(
    monkeypatch,
) -> None:
    """A transient empty discovery cannot preserve a stale bootstrap fixture."""
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args, **_kwargs: ([], []),
    )
    real_agent = ModelAgent(
        "existing_real_agent",
        "existing-real-model",
        base_url="https://provider.invalid/v1",
        tags=("discovered", "chat"),
    )
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("mock_seed_agent", "mock-model", tags=("bootstrap_seed",)),
            real_agent,
        ]
    )

    result = _auto_discover_runtime_agents(orchestrator)

    assert result == {"added": [], "updated": ["mock_seed_agent"]}
    assert orchestrator.agents == [real_agent]


def test_auto_discovery_preserves_operator_configured_mock(monkeypatch) -> None:
    """Only tagged bootstrap fixtures retire when real discovery succeeds."""
    discovered = DiscoveredModel(
        provider_name="openai",
        model_id="chat-capable-model",
        credential_name="OPENAI_API_KEY",
        chat_base_url="https://api.openai.com/v1",
        auth_scheme="Bearer",
        capabilities=("chat",),
    )
    monkeypatch.setattr(
        "contextual_orchestrator.__main__.discover_all_models",
        lambda *args, **_kwargs: ([discovered], []),
    )
    operator_mock = ModelAgent(
        "operator_mock", "operator-model", base_url="mock://operator"
    )
    orchestrator = TaskOrchestrator([operator_mock])

    _auto_discover_runtime_agents(orchestrator)

    assert operator_mock in orchestrator.agents
