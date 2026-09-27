"""Pinned evidence identity checks must survive optimized Python."""
import subprocess
import sys
from pathlib import Path


def test_optimized_verifier_rejects_unpinned_wheel_before_opening_archive(tmp_path):
    wheel = tmp_path / 'wrong.whl'
    wheel.write_bytes(b'not the pinned artifact')
    script = Path(__file__).parents[1] / 'scripts/ci/verify_dateutil_zoneinfo_reproduction.py'
    result = subprocess.run([sys.executable, '-O', str(script), '--wheel', str(wheel),
                             '--tzdata', str(tmp_path / 'missing-source'), '--zic', 'unused',
                             '--output', str(tmp_path / 'receipt.json')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'invalid pinned archive evidence' in result.stderr
    assert not (tmp_path / 'receipt.json').exists()
