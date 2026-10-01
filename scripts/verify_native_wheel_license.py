"""Verify PEP 639 metadata and license bytes in built native wheels."""

from __future__ import annotations

import email
import sys
import zipfile
from pathlib import Path


def verify_native_wheel_license(wheel_path: Path, expected_license: bytes) -> None:
    """Require one MIT metadata record and the matching bundled LICENSE bytes."""
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("native wheel must contain exactly one METADATA file")
        metadata_path = metadata_paths[0]
        metadata = email.message_from_bytes(archive.read(metadata_path))
        if metadata.get("License-Expression") != "MIT":
            raise ValueError("native wheel License-Expression must be MIT")
        if "LICENSE" not in (metadata.get_all("License-File") or []):
            raise ValueError("native wheel License-File must declare LICENSE")
        license_path = metadata_path.removesuffix("METADATA") + "licenses/LICENSE"
        try:
            bundled_license = archive.read(license_path)
        except KeyError as error:
            raise ValueError("native wheel must contain the bundled LICENSE") from error
        if bundled_license != expected_license:
            raise ValueError(
                "native wheel bundled LICENSE differs from repository LICENSE"
            )


if __name__ == "__main__":
    repository_license = Path(sys.argv[1]).read_bytes()
    for wheel_argument in sys.argv[2:]:
        verify_native_wheel_license(Path(wheel_argument), repository_license)
