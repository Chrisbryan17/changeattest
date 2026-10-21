from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from changeattest.adapters import ADAPTER_INDEX
from changeattest.adapters import _select
from changeattest.adapters import run_adapters
from changeattest.agent import read_contract
from changeattest.agent import verify_agent_change
from changeattest.attestation import sign_evidence
from changeattest.attestation import verify_evidence
from changeattest.engine import canonical


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=path, check=True)
    subprocess.run(('git', 'config', 'core.autocrlf', 'false'), cwd=path, check=True)
    subprocess.run(('git', 'config', 'user.name', 'ChangeAttest Test'),
                   cwd=path, check=True)
    subprocess.run(('git', 'config', 'user.email', 'test@example.invalid'),
                   cwd=path, check=True)
    (path / 'a.py').write_text('x = 1\n')
    subprocess.run(('git', 'add', '-A'), cwd=path, check=True)
    subprocess.run(('git', 'commit', '-qm', 'initial'), cwd=path, check=True)
    return path


def sha(root):
    return subprocess.check_output(('git', 'rev-parse', 'HEAD'), cwd=root,
                                   text=True).strip()


def test_parallel_adapters_are_sorted_and_bounded(repo, monkeypatch):
    import changeattest.adapters as adapters
    monkeypatch.setattr(adapters, '_run', lambda a, root, files, timeout: {
        'id': a.id, 'status': 'passed' if files else 'skipped',
        'file_count': len(files), 'exit_code': 0 if files else None,
        'tool_sha256': None, 'output_sha256': None,
    })
    report = run_adapters(repo, ['ruff', 'pytest'], ['a.py'], jobs=2)
    assert report['schema'] == 'changeattest.tools.v1'
    assert report['selected_tools'] == ['pytest', 'ruff']
    assert report['status'] == 'passed'
    assert report['root_git_head'] == sha(repo)
    assert report['report_sha256'] == hashlib.sha256(canonical({
        k: v for k, v in report.items() if k != 'report_sha256'
    })).hexdigest()


@pytest.mark.parametrize('bad', (['unknown'], ['ruff', 'ruff']))
def test_invalid_tool_ids_fail(repo, bad):
    with pytest.raises(ValueError):
        run_adapters(repo, bad, ['a.py'])


def test_tool_selectors_do_not_select_incompatible_sources(repo):
    assert _select(ADAPTER_INDEX['ruff'], repo, ['index.ts', 'a.py']) == ['a.py']
    assert _select(ADAPTER_INDEX['cargo-fmt'], repo, ['a.py']) == []
    (repo / 'Cargo.toml').write_text('[package]\nname="test"\n')
    assert _select(ADAPTER_INDEX['cargo-fmt'], repo, []) == ['.']


@pytest.fixture
def signing_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    wrong = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public, wrong


@pytest.fixture
def evidence():
    result = {'schema': 'changeattest.report.v1', 'head': 'a' * 40,
              'status': 'passed', 'checks': [
                  {'id': 'python-ast', 'status': 'passed',
                   'exit_code': 0, 'file_count': 1},
              ]}
    result['report_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def test_signed_evidence_roundtrip_and_tamper(evidence, signing_keys):
    private, public, wrong = signing_keys
    signed = sign_evidence(evidence, private, 'controlled-ci')
    assert verify_evidence(signed, public, expected_head='a' * 40)
    assert not verify_evidence(signed, wrong)
    assert not verify_evidence(signed, public, expected_head='b' * 40)
    signed['evidence']['head'] = 'b' * 40
    assert not verify_evidence(signed, public)


def test_signature_rejects_corrupted_unsigned_report(evidence, signing_keys):
    private, public, _ = signing_keys
    evidence['head'] = 'b' * 40
    with pytest.raises(ValueError, match='checksum'):
        sign_evidence(evidence, private)


def test_agent_contract_blocks_out_of_scope_and_denied_changes(repo, tmp_path):
    base = sha(repo)
    (repo / 'a.py').write_text('x = 2\n')
    (repo / 'secret.pem').write_text('DO NOT TOUCH')
    subprocess.run(('git', 'add', '-A'), cwd=repo, check=True)
    subprocess.run(('git', 'commit', '-qm', 'agent edit'), cwd=repo, check=True)
    contract = tmp_path / 'contract.json'
    contract.write_text(json.dumps({
        'version': 1, 'allowed_paths': ['*.py'],
        'forbidden_paths': ['*.pem'], 'required_checks': [],
        'max_changed_files': 10,
    }))
    decision = verify_agent_change(repo, read_contract(str(contract)),
                                   base, sha(repo))
    assert decision['status'] == 'blocked'
    assert 'forbidden-path:secret.pem' in decision['violations']


def test_agent_needs_trusted_evidence_for_claimed_tests(
    repo, tmp_path, signing_keys,
):
    base = sha(repo)
    (repo / 'a.py').write_text('x = 2\n')
    subprocess.run(('git', 'add', '-A'), cwd=repo, check=True)
    subprocess.run(('git', 'commit', '-qm', 'agent edit'), cwd=repo, check=True)
    contract = tmp_path / 'contract.json'
    contract.write_text(json.dumps({
        'version': 1, 'allowed_paths': ['*.py'],
        'forbidden_paths': [], 'required_checks': ['python-ast'],
        'max_changed_files': 10,
    }))
    cfg = read_contract(str(contract))
    without = verify_agent_change(repo, cfg, base, sha(repo))
    assert without['status'] == 'blocked'
    assert without['evidence_status'] == 'unverified'
    private, public, wrong = signing_keys
    report = {'schema': 'changeattest.report.v1', 'head': sha(repo),
              'status': 'passed', 'checks': [
                  {'id': 'python-ast', 'status': 'passed',
                   'exit_code': 0, 'file_count': 1},
              ]}
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    signed = sign_evidence(report, private)
    assert verify_agent_change(repo, cfg, base, sha(repo),
                               signed, public)['status'] == 'passed'
    assert verify_agent_change(repo, cfg, base, sha(repo),
                               signed, wrong)['status'] == 'blocked'


def test_agent_empty_change_denied(repo, tmp_path):
    contract = tmp_path / 'contract.json'
    contract.write_text(json.dumps({
        'version': 1, 'allowed_paths': ['*.py'],
        'forbidden_paths': [], 'required_checks': [],
        'max_changed_files': 10,
    }))
    result = verify_agent_change(repo, read_contract(str(contract)),
                                 sha(repo), sha(repo))
    assert 'no-changes' in result['violations']


def test_unsigned_signature_never_claimed_trusted(signing_keys, evidence):
    from changeattest.attestation import verify_evidence
    _, public, _ = signing_keys
    assert not verify_evidence({'schema': 'changeattest.attestation.v1'},
                               public)
