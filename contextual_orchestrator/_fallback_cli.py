"""Command-line adapter for the transport-neutral fallback policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._fallback_manifest import load_fallback_manifest
from ._fallback_plan import build_fallback_plan
from ._fallback_types import (
    ALLOWED_VISIBILITIES,
    FallbackContext,
    FallbackManifestError,
    validate_credentials,
)


def _load_manifest_path(path: Path) -> Mapping[str, Any]:
    """Read a UTF-8 JSON manifest and normalize input errors."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FallbackManifestError(
            f"manifest could not be read: {path}"
        ) from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FallbackManifestError(
            "manifest must contain valid JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise FallbackManifestError("manifest must be an object")
    return document


def _declared_credentials(names: Sequence[str]) -> frozenset[str]:
    """Validate and return credential names declared available by the caller."""
    normalized = tuple(names)
    validate_credentials(normalized)
    return frozenset(normalized)


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser for policy-only workflow integration."""
    parser = argparse.ArgumentParser(prog="contextual-model-fallback")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--manifest", type=Path, required=True)
    plan_parser.add_argument("--agent", required=True)
    plan_parser.add_argument(
        "--repository-visibility",
        choices=sorted(ALLOWED_VISIBILITIES),
        default="public",
    )
    plan_parser.add_argument(
        "--available-credential", action="append", default=[]
    )
    plan_parser.add_argument(
        "--required-capability", action="append", default=[]
    )
    plan_parser.add_argument("--deny-paid", action="store_true")
    plan_parser.add_argument(
        "--format",
        choices=("json", "ids", "models"),
        default="json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Render one validated plan and return an exit code."""
    args = _build_parser().parse_args(argv)
    if args.command != "plan":  # pragma: no cover - argparse constrains it.
        raise FallbackManifestError(
            f"unsupported command: {args.command}"
        )
    document = _load_manifest_path(args.manifest)
    candidates = load_fallback_manifest(document, args.agent)
    context = FallbackContext(
        repository_visibility=args.repository_visibility,
        available_credentials=_declared_credentials(
            args.available_credential
        ),
        required_capabilities=frozenset(args.required_capability),
        allow_paid=not args.deny_paid,
    )
    plan = build_fallback_plan(candidates, context=context)
    if args.format == "json":
        print(
            json.dumps(
                plan.to_public_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif args.format == "ids":
        print(" ".join(plan.candidate_ids))
    else:
        print(" ".join(candidate.model for candidate in plan.candidates))
    return 0
