from __future__ import annotations

import re


TWO_WORD_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")


def is_two_word_snake_case(value: str) -> bool:
    return bool(TWO_WORD_SNAKE_CASE.fullmatch(value))


def require_object_name(value: str, field_name: str) -> None:
    if not is_two_word_snake_case(value):
        raise ValueError(f"{field_name} must be two or more words in snake_case: {value!r}")

