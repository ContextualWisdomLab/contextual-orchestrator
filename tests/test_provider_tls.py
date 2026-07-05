"""Provider TLS trust configuration for ModelClient.

A live run against a corporate OpenAI-compatible gateway failed because urllib could
not verify its certificate chain (custom CA not in Python's trust store), and there
was no way to supply a CA bundle short of disabling verification globally. This adds
a per-client CA bundle / verify toggle. Default stays verified against the system store.
"""

from __future__ import annotations

from pathlib import Path
import ssl
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelClient  # noqa: E402


def test_default_verifies_against_system_store() -> None:
    context = ModelClient()._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_insecure_skip_verify_disables_checks() -> None:
    context = ModelClient(verify_tls=False)._ssl_context
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_ca_bundle_is_loaded() -> None:
    # Build a valid CA file from the system trust store (stdlib only) and load it.
    base = ssl.create_default_context()
    ders = base.get_ca_certs(binary_form=True)
    assert ders, "system trust store unexpectedly empty"
    pem = "".join(ssl.DER_cert_to_PEM_cert(der) for der in ders[:3])
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write(pem)
        bundle_path = handle.name

    context = ModelClient(ca_bundle=bundle_path)._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED  # still verifying, now against our bundle
    assert len(context.get_ca_certs()) >= 1  # the supplied CA(s) are in effect


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("ok")
