"""Reconcile PR #1000 NIM repair-driver drift without weakening source checks."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import repair_pr1000_nim_evidence_v3 as v3


_original_replace_once = v3.replace_once


def _replace_once_with_post_v1_state(
    path: Path, old: str, new: str, label: str
) -> None:
    """Accept the one documented post-v1 skip-reason rewrite, else stay strict."""
    if label != "pricing skip reason provider usage":
        _original_replace_once(path, old, new, label)
        return

    text = path.read_text(encoding="utf-8")
    if text.count(old) == 1:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return

    post_v1_old = old.replace(
        '"no_worker_priced_by_scenario"',
        '"no_uniquely_price_dominant_worker"',
    )
    post_v1_new = new.replace(
        '"no_worker_priced_by_scenario"',
        '"no_uniquely_price_dominant_worker"',
    )
    count = text.count(post_v1_old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one legacy or post-v1 match, found {count} post-v1"
        )
    path.write_text(text.replace(post_v1_old, post_v1_new, 1), encoding="utf-8")


def main() -> None:
    """Run the existing strict repair with the verified post-v1 reconciliation."""
    v3.replace_once = _replace_once_with_post_v1_state
    v3.main()


if __name__ == "__main__":
    main()
