"""Adversarial checks for immutable, publication-gated CI contract fixtures."""
import hashlib
import json

import pytest

from _ci_workflow_contract import execution_contract


@pytest.fixture
def contract(tmp_path):
    """Build isolated test data; this is never a published workflow pin."""
    name = 'fixture.yml'
    pin = 'a' * 40
    reference = f'ContextualWisdomLab/.github/.github/workflows/{name}@{pin}'
    caller = tmp_path / '.github/workflows/test.yml'
    caller.parent.mkdir(parents=True)
    caller.write_text(f'jobs:\n  test:\n    uses: {reference}\n')
    directory = tmp_path / 'tests/fixtures/central_workflows'
    directory.mkdir(parents=True)
    raw = b'name: Fixture\non:\n  workflow_call: {}\njobs: {}\n'
    (directory / name).write_bytes(raw)
    manifest_path = directory / f'{name}.json'
    manifest = {'reference': reference, 'protected_publication_commit': pin,
                'sha256': hashlib.sha256(raw).hexdigest(),
                'git_blob_sha': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw, usedforsecurity=False).hexdigest()}
    manifest_path.write_text(json.dumps(manifest))
    return tmp_path, caller, directory / name, manifest_path, manifest


def test_exact_fixture_is_used(contract):
    root, _, fixture, _, _ = contract
    assert execution_contract(root, '.github/workflows/test.yml') == fixture.read_text()


@pytest.mark.parametrize('field,value', [('protected_publication_commit', None),
                                        ('protected_publication_commit', 'b'*40),
                                        ('reference', 'foreign'), ('sha256', '0'*64),
                                        ('git_blob_sha', '0'*40)])
def test_wrong_identity_or_unpublished_supplier_fails(contract, field, value):
    root, _, _, path, manifest = contract
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(AssertionError):
        execution_contract(root, '.github/workflows/test.yml')


def test_tampered_fixture_fails(contract):
    root, _, fixture, _, _ = contract
    fixture.write_text('jobs: {}\n')
    with pytest.raises(AssertionError, match='digest'):
        execution_contract(root, '.github/workflows/test.yml')


@pytest.mark.parametrize('suffix', ['\n    steps: []\n', '\n    runs-on: ubuntu-latest\n',
                                  '\n  other:\n    uses: owner/action@main\n'])
def test_mixed_execution_is_rejected(contract, suffix):
    root, caller, _, _, _ = contract
    caller.write_text(caller.read_text() + suffix)
    with pytest.raises(AssertionError, match='thin'):
        execution_contract(root, '.github/workflows/test.yml')


@pytest.mark.parametrize('replacement', ['main', '${{ inputs.ref }}', 'A'*40])
def test_mutable_dynamic_or_noncanonical_pin_fails(contract, replacement):
    root, caller, _, _, _ = contract
    caller.write_text(caller.read_text().replace('a'*40, replacement))
    with pytest.raises(AssertionError):
        execution_contract(root, '.github/workflows/test.yml')


def test_current_local_workflow_remains_supported(tmp_path):
    path = tmp_path / 'local.yml'
    source = 'jobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps: []\n'
    path.write_text(source)
    assert execution_contract(tmp_path, 'local.yml') == source


def test_missing_execution_fails(tmp_path):
    (tmp_path / 'local.yml').write_text('jobs: {}\n')
    with pytest.raises(AssertionError, match='no local or central'):
        execution_contract(tmp_path, 'local.yml')
