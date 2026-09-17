"""Reject native/core wheel ownership overlap before isolated installation."""

import sys
import zipfile


def verify_wheels(core_path, native_path):
    """Require a native-only extension distribution disjoint from the core wheel."""
    with zipfile.ZipFile(core_path) as core_archive, zipfile.ZipFile(native_path) as native_archive:
        core_files = set(core_archive.namelist())
        native_files = set(native_archive.namelist())
    if core_files & native_files:
        raise ValueError("core and native wheel files overlap")
    payload = {name for name in native_files if ".dist-info/" not in name}
    if len(payload) != 1 or not all(
        name.startswith("contextual_orchestrator/_decision_receipt.")
        and name.endswith((".so", ".pyd")) for name in payload
    ):
        raise ValueError("native wheel must contain only the receipt extension")


if __name__ == "__main__":
    verify_wheels(*sys.argv[1:])
