"""Pure orchestration domain: standard library only, no IO (ADR 0124).

Modules here must not import ``contextual_orchestrator.orchestrator``,
``server``, adapters, or any network, database, or filesystem module. The
import boundary is enforced by ``tests/test_domain_import_boundary.py``.
"""
