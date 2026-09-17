"""Wheel ownership is validated before installation can mask package omissions."""

from pathlib import Path
import runpy
import zipfile

import pytest

verify_wheels = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "verify_decision_wheel_manifest.py")
)["verify_wheels"]


@pytest.mark.parametrize("native_payload,expected_error", [
    ("contextual_orchestrator/_decision_receipt.abi3.so", None),
    ("contextual_orchestrator/__init__.py", "overlap"),
    ("unexpected_package/module.py", "only the receipt extension"),
])
def test_native_wheel_ownership(tmp_path, native_payload, expected_error):
    """Reject overlapping or unexpected native payloads; accept disjoint bindings."""
    core_path, native_path = tmp_path / "core.whl", tmp_path / "native.whl"
    with zipfile.ZipFile(core_path, "w") as archive:
        archive.writestr("contextual_orchestrator/__init__.py", "")
    with zipfile.ZipFile(native_path, "w") as archive:
        archive.writestr(native_payload, "unit fixture")
        archive.writestr("native.dist-info/METADATA", "")
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            verify_wheels(core_path, native_path)
    else:
        verify_wheels(core_path, native_path)
