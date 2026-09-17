"""Every ``review_gateway`` annotation must resolve at runtime.

``review_pool_admissions`` was annotated ``Sequence[Any]`` while the module
imported only ``Mapping`` and ``Sequence`` from ``typing``. ``from __future__
import annotations`` keeps annotations as strings, so the module still imported
and every test passed -- the break only surfaces for a caller that *resolves*
the annotations: ``typing.get_type_hints``, a dataclass/schema generator, a
docs builder, or a runtime type checker. This module pins resolution itself,
because nothing else here would notice the next such name.

``TYPE_CHECKING``-deferred imports are a deliberate circular-import remedy and
are out of scope: this contract covers ``review_gateway``, which declares no
``TYPE_CHECKING`` block and therefore has no name it is entitled to leave
unresolvable.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from contextual_orchestrator import review_gateway


def _module_owned_members() -> list[tuple[str, object]]:
    """Return the functions and classes ``review_gateway`` itself defines."""
    return [
        (name, obj)
        for name, obj in vars(review_gateway).items()
        if (inspect.isfunction(obj) or inspect.isclass(obj))
        and getattr(obj, "__module__", None) == review_gateway.__name__
    ]


def test_the_module_defines_members_to_check() -> None:
    """Guard the guard: an empty sweep would pass vacuously."""
    assert len(_module_owned_members()) >= 5


@pytest.mark.parametrize("name", [name for name, _obj in _module_owned_members()])
def test_annotations_resolve_for_each_public_member(name: str) -> None:
    """No annotation may name something the module never imported."""
    obj = getattr(review_gateway, name)
    typing.get_type_hints(obj)


def test_review_pool_admissions_resolves_its_any_annotation() -> None:
    """The specific regression: ``Sequence[Any]`` with no ``Any`` in scope."""
    hints = typing.get_type_hints(review_gateway.review_pool_admissions)
    assert hints["agents"] == typing.Sequence[typing.Any]


def test_the_module_declares_no_type_checking_block() -> None:
    """The premise of the sweep: every annotation name is a real import here."""
    source = inspect.getsource(review_gateway)
    assert "TYPE_CHECKING" not in source
