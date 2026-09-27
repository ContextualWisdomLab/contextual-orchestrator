"""Verify byte reproduction of the exact dateutil 2.9.0.post0 timezone payload.

Uses the existing zic recipe and verified IANA data without extracting archive
paths or changing a user's database. A mismatch returns failure, not permission.
"""
import argparse
import hashlib, io, json, subprocess, tarfile, tempfile, zipfile
from pathlib import Path, PurePosixPath

def main() -> int:
    """Compare every embedded timezone path and byte with a confined rebuild."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('wheel', 'tzdata', 'zic', 'output'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    wheel = Path(args.wheel)
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == 'a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427'
    source = Path(args.tzdata).read_bytes()
    with zipfile.ZipFile(wheel) as z:
        embedded = z.read('dateutil/zoneinfo/dateutil-zoneinfo.tar.gz')
    with tarfile.open(fileobj=io.BytesIO(embedded)) as t:
        members = t.getmembers()
        assert len(members) < 1000
        for m in members:
            assert not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts
            assert m.size < 65536 and (m.isfile() or m.islnk() or m.isdir())
            if m.islnk():
                assert not PurePosixPath(m.linkname).is_absolute() and '..' not in PurePosixPath(m.linkname).parts
        with t.extractfile('METADATA') as f:
            metadata = json.load(f)
        expected = {}
        for m in members:
            if m.isdir() or m.name == 'METADATA':
                continue
            with t.extractfile(m) as f:
                expected[m.name] = f.read(65537)
    assert hashlib.sha512(source).hexdigest() == metadata['tzdata_file_sha512']
    groups = metadata['zonegroups']
    assert groups == ['africa', 'antarctica', 'asia', 'australasia', 'europe', 'northamerica', 'southamerica', 'etcetera', 'factory', 'backzone', 'backward']
    owned = Path(tempfile.mkdtemp(prefix='co1083-zic-repro-'))
    inputs = owned / 'inputs'
    inputs.mkdir()
    out = owned / 'out'
    with tarfile.open(fileobj=io.BytesIO(source)) as t:
        for name in groups:
            m = t.getmember(name)
            assert m.isfile() and m.size < 1024 * 1024
            with t.extractfile(m) as f:
                (inputs / name).write_bytes(f.read())
    cmd = [args.zic, '-b', 'fat', '-d', str(out), *[str(inputs / n) for n in groups]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    actual = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob('*') if p.is_file()} if r.returncode == 0 else {}
    matched = [n for n in expected if actual.get(n) == expected[n]]
    mismatch = [{'name': n, 'expected_sha256': hashlib.sha256(expected[n]).hexdigest(), 'actual_sha256': hashlib.sha256(actual[n]).hexdigest()} for n in expected.keys() & actual.keys() if actual[n] != expected[n]]
    receipt = {'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'embedded_sha256': hashlib.sha256(embedded).hexdigest(), 'source_sha512': hashlib.sha512(source).hexdigest(), 'compiler_version': subprocess.check_output([args.zic, '--version'], text=True).strip(), 'compiler_sha256': hashlib.sha256(Path(args.zic).read_bytes()).hexdigest(), 'command': cmd, 'exit_code': r.returncode, 'stderr': r.stderr, 'expected_files': len(expected), 'generated_files': len(actual), 'matched': len(matched), 'missing': sorted(expected.keys() - actual.keys()), 'extra': sorted(actual.keys() - expected.keys()), 'mismatch': mismatch, 'owned_directory': str(owned), 'verification_scope': 'timezone member bytes and paths; excludes METADATA and tar/gzip headers', 'producer_tool_identity_verified': False, 'transformation_verified': r.returncode == 0 and len(matched) == len(expected) and (not actual.keys() - expected.keys())}
    Path(args.output).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ['command', 'mismatch', 'stderr']}))
    print('stderr', r.stderr[:1000])
    print('mismatch_first', mismatch[:3])
    return 0 if receipt['transformation_verified'] else 1
if __name__ == '__main__':
    raise SystemExit(main())
