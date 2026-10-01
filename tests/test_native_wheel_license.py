"""Built native wheels must carry exact PEP 639 license evidence."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.verify_native_wheel_license import verify_native_wheel_license


MIT_TEXT = b"MIT License\n\nunit fixture\n"


def _write_wheel(
    path: Path, *, expression: str = "MIT", include_license: bool = True
) -> None:
    """Write a minimal synthetic wheel fixture for artifact-only unit tests."""
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: native-fixture\n"
        "Version: 1.0.0\n"
        f"License-Expression: {expression}\n"
        "License-File: LICENSE\n\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("native_fixture-1.0.0.dist-info/METADATA", metadata)
        if include_license:
            archive.writestr(
                "native_fixture-1.0.0.dist-info/licenses/LICENSE", MIT_TEXT
            )


class NativeWheelLicenseTest(unittest.TestCase):
    """Verify native wheel license metadata and bundled bytes fail closed."""

    def test_accepts_matching_pep_639_metadata_and_license(self) -> None:
        """Accept one authoritative metadata file with expected MIT bytes."""
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "native.whl"
            _write_wheel(wheel)
            verify_native_wheel_license(wheel, MIT_TEXT)

    def test_rejects_wrong_expression(self) -> None:
        """Reject a wheel whose expression differs from the repository grant."""
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "native.whl"
            _write_wheel(wheel, expression="Apache-2.0")
            with self.assertRaisesRegex(ValueError, "License-Expression"):
                verify_native_wheel_license(wheel, MIT_TEXT)

    def test_rejects_missing_bundled_license(self) -> None:
        """Reject declaration-only metadata without the referenced payload."""
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "native.whl"
            _write_wheel(wheel, include_license=False)
            with self.assertRaisesRegex(ValueError, "bundled LICENSE"):
                verify_native_wheel_license(wheel, MIT_TEXT)

    def test_rejects_different_bundled_license_bytes(self) -> None:
        """Reject a bundled license whose bytes differ from root authority."""
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "native.whl"
            _write_wheel(wheel)
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_native_wheel_license(wheel, b"different")


if __name__ == "__main__":
    unittest.main()
