"""Verify the installed release bytes before reporting a gateway identity."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import marshal
import re
from pathlib import Path
from types import CodeType

from .api_contract import OPENAPI_SPEC


class RuntimeIdentityUnavailable(Exception):
    """The running package cannot prove its declared release identity."""


def current_schema_sha256() -> str:
    encoded = json.dumps(OPENAPI_SPEC, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def package_tree_sha256(files: list[tuple[str, bytes]]) -> str:
    """Hash sorted package names and file digests with unambiguous separators."""
    digest = hashlib.sha256()
    for name, data in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def verified_runtime_identity() -> dict[str, str]:
    """Return identity only for a complete, RECORD-verified installed wheel."""
    try:
        distribution = importlib.metadata.distribution("contextual-orchestrator")
        package = Path(distribution.locate_file("contextual_orchestrator")).resolve()
        if Path(__file__).resolve().parent != package or not distribution.files:
            raise RuntimeIdentityUnavailable()

        verified: list[tuple[str, bytes]] = []
        names: set[str] = set()
        for item in distribution.files:
            name = str(item).replace("\\", "/")
            path = Path(name)
            if not name.startswith("contextual_orchestrator/") or path.is_absolute() or ".." in path.parts:
                continue
            if item.hash is None or item.hash.mode != "sha256":
                raise RuntimeIdentityUnavailable()
            recorded_path = Path(distribution.locate_file(item))
            if recorded_path.is_symlink():
                raise RuntimeIdentityUnavailable()
            data = recorded_path.read_bytes()
            actual_hash = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            if actual_hash != item.hash.value or name in names:
                raise RuntimeIdentityUnavailable()
            names.add(name)
            verified.append((name, data))

        manifest_name = "contextual_orchestrator/_release_identity.json"
        if manifest_name not in names or "contextual_orchestrator/runtime_identity.py" not in names:
            raise RuntimeIdentityUnavailable()
        # Extra files can alter runtime behavior even when Python cannot import them.
        for path in package.rglob("*"):
            if path.is_symlink():
                raise RuntimeIdentityUnavailable()
            if path.is_file():
                relative = path.relative_to(package)
                if "__pycache__" in relative.parts and path.suffix == ".pyc":
                    try:
                        source = Path(importlib.util.source_from_cache(str(path))).relative_to(package)
                    except ValueError as exc:
                        raise RuntimeIdentityUnavailable() from exc
                    if f"contextual_orchestrator/{source.as_posix()}" in names:
                        # Python can execute cached code while the recorded source stays intact.
                        cached = path.read_bytes()
                        if cached[:4] != importlib.util.MAGIC_NUMBER or len(cached) < 16:
                            raise RuntimeIdentityUnavailable()
                        code = marshal.loads(cached[16:])
                        if not isinstance(code, CodeType):
                            raise RuntimeIdentityUnavailable()
                        for optimization in (0, 1, 2):
                            expected_path = importlib.util.cache_from_source(
                                str(package / source),
                                optimization=str(optimization) if optimization else "",
                            )
                            if path == Path(expected_path):
                                expected = compile(
                                    (package / source).read_bytes(), code.co_filename, "exec",
                                    dont_inherit=True, optimize=optimization,
                                )
                                if code == expected:
                                    break
                        else:
                            raise RuntimeIdentityUnavailable()
                        continue
                if f"contextual_orchestrator/{relative.as_posix()}" not in names:
                    raise RuntimeIdentityUnavailable()

        manifest = json.loads(dict(verified)[manifest_name].decode("utf-8"))
        version = distribution.version
        if (
            type(manifest) is not dict
            or set(manifest) != {"version", "release_tag", "source_sha", "schema_sha256"}
            or manifest["version"] != version
            or manifest["release_tag"] != f"v{version}"
            or not isinstance(manifest["source_sha"], str)
            or re.fullmatch(r"[0-9a-f]{40}", manifest["source_sha"]) is None
            or manifest["schema_sha256"] != current_schema_sha256()
        ):
            raise RuntimeIdentityUnavailable()
        return {
            "version": version,
            "release_tag": manifest["release_tag"],
            "source_sha": manifest["source_sha"],
            "schema_sha256": manifest["schema_sha256"],
            "package_tree_sha256": package_tree_sha256(verified),
        }
    except RuntimeIdentityUnavailable:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, EOFError, SyntaxError, RecursionError, KeyError, AttributeError, importlib.metadata.PackageNotFoundError) as exc:
        raise RuntimeIdentityUnavailable() from exc
