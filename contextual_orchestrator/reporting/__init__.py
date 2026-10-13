"""Read-only reporting generated from orchestrator state.

Modules here consume a :class:`~contextual_orchestrator.orchestrator.TaskOrchestrator`
instance passed in by the caller and must not import the orchestrator module
at import time (docs/adr/0124-incremental-domain-extraction.md).
"""
