"""Protect the native token-packer installation boundary in fuzz CI."""

from pathlib import Path


def test_fuzz_jobs_install_native_token_packer_from_pinned_builder() -> None:
    """Both orchestration fuzz jobs must install the required Rust extension."""
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/fuzz.yml").read_text(encoding="utf-8")
    installer = (root / "scripts/install_native_token_packer.sh").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: ./scripts/install_native_token_packer.sh") == 2
    assert "ghcr.io/pyo3/maturin@sha256:" in installer
    assert "--target token-wheel" in installer
    assert '--output "type=local,dest=${WHEEL_DIRECTORY}"' in installer
    assert "hashlib.sha256" in installer
    assert "--hash=sha256:" in installer
    assert 'python -m pip install --no-deps --require-hashes -r "${REQUIREMENTS_FILE}"' in installer
