"""Application services that run domain strategies through ports (ADR 0124).

Services here may use concurrency primitives but reach providers only
through callables supplied by the caller, so they are testable without a
network and never import ``contextual_orchestrator.orchestrator``.
"""
