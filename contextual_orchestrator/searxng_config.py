"""Render SearXNG deployment settings from the credential registry."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import quote

from .credentials import NotConfigured, get_credential

SEARXNG_SECRET_CREDENTIAL = "SEARXNG_SECRET"
WARDNET_EGRESS_PROXY_TOKEN_CREDENTIAL = "WARDNET_EGRESS_PROXY_TOKEN"


def _required_credential(name: str) -> str:
    """Return one non-empty KV credential or fail closed."""
    value = get_credential(name)
    if value is None or not value:
        raise NotConfigured(f"credential {name} is not configured")
    return value


def render_searxng_settings() -> str:
    """Build SearXNG YAML from KV-backed search and Wardnet credentials."""
    secret = json.dumps(_required_credential(SEARXNG_SECRET_CREDENTIAL))
    token = quote(_required_credential(WARDNET_EGRESS_PROXY_TOKEN_CREDENTIAL), safe="")
    proxy = json.dumps(f"http://wardnet:{token}@172.30.0.2:8080")
    return f"""use_default_settings: true
server:
  secret_key: {secret}
  bind_address: "0.0.0.0"
  limiter: false
  image_proxy: false
search:
  formats:
    - html
    - json
outgoing:
  proxies:
    all://: [{proxy}]
"""


def write_searxng_settings(path: Path) -> None:
    """Atomically write settings below a host directory protected from other users.

    The file is readable inside the nonroot SearXNG container. The parent
    directory supplies the host-side confidentiality boundary.
    """
    destination = path.expanduser().resolve(strict=False)
    destination.parent.mkdir(mode=stat.S_IRWXU, parents=True, exist_ok=True)
    parent = destination.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) != stat.S_IRWXU):
        raise ValueError("settings parent must already be an owner-private directory (0700)")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
    )
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(render_searxng_settings())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> None:
    """Render the KV-backed settings file without printing secret material."""
    parser = argparse.ArgumentParser(
        description="Render SearXNG settings from KV credentials.",
        allow_abbrev=False,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        write_searxng_settings(args.output)
    except NotConfigured as exc:
        parser.error(str(exc))
    print(json.dumps({"written": str(args.output), "source": "kv"}))


if __name__ == "__main__":
    main()
