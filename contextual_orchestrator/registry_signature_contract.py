"""Expose truthful semantic signatures while legacy registry keywords remain supported.

The durable registry keeps ``name=`` and ``key=`` as bounded compatibility
keywords for existing external Python callers. Those aliases require the
runtime implementation to accept omission of the new semantic parameters so
it can translate legacy keywords inside the function body. This module uses
Python's supported ``__signature__`` introspection hook to keep that adapter
private: signature-driven callers see ``registry_name`` and ``claim_key`` as
required, non-null ``str`` parameters, while legacy calls continue to execute
through the compatibility boundary.
"""

from __future__ import annotations

from inspect import Parameter, Signature, signature
from typing import Any, Callable


def _required_semantic_signature(
    public_callable: Callable[..., Any],
    *identifier_names: str,
) -> Signature:
    """Return a public signature with semantic identifiers marked required."""
    runtime_signature = signature(public_callable)
    public_parameters = [
        parameter.replace(default=Parameter.empty, annotation=str)
        if parameter.name in identifier_names
        else parameter
        for parameter in runtime_signature.parameters.values()
    ]
    return runtime_signature.replace(parameters=public_parameters)


def install_registry_signature_contract() -> None:
    """Install truthful required-identifier signatures on registry public seams."""
    from .batch_job_registry import JobRegistryFactory, ValkeyJsonMapping

    setattr(
        ValkeyJsonMapping.__init__,
        "__signature__",
        _required_semantic_signature(ValkeyJsonMapping.__init__, "registry_name"),
    )
    setattr(
        JobRegistryFactory.lock,
        "__signature__",
        _required_semantic_signature(
            JobRegistryFactory.lock,
            "registry_name",
            "claim_key",
        ),
    )
    setattr(
        JobRegistryFactory.mapping,
        "__signature__",
        _required_semantic_signature(JobRegistryFactory.mapping, "registry_name"),
    )
