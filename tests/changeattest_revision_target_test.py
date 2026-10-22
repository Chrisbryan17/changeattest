"""Explicit revision targeting must not execute or check out proposed code."""
from __future__ import annotations

import json
import subprocess

import pytest

from changeattest.cli import main
from changeattest.engine import ConfigurationError
from changeattest.snapshot import scan_commit


def git(root, *args):
    return subprocess.check_output(('git', *args), cwd=root).strip().decode('ascii')


@pytest.fixture
def revision_repo(tmp_path):
    root = tmp_path / 'target repo'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    for k, v in (
        ('user.name', 'Test'),
        ('user.email', 'tests@example.invalid'),
        ('core.autocrlf', 'false'),
    ):
        subprocess.run(('git', 'config', k, v), cwd=root, check=True)
    (root / 'src').mkdir()
    source = root / 'src' / 'module.py'
    source.write_text('answer = 42\n')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'safe'), cwd=root, check=True)
    safe = git(root, 'rev-parse', 'HEAD')
    source.write_text('def broken(:\n')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'unsafe'), cwd=root, check=True)
    unsafe = git(root, 'rev-parse', 'HEAD')
    policy = tmp_path / 'policy.toml'
    policy.write_text(
        '[policy]\nversion=1\nscope="tracked"\n'
        'required_checks=["python-ast","merge-conflict"]\n'
        'allow_skipped_checks=[]\ninclude_prefixes=["src/"]\n'
        'min_files=1\n',
    )
    return root, policy, safe, unsafe


def gate(root, policy, report, revision, expected=None, extra=()):
    opts = ('gate', '--root', str(root), '--policy', str(policy),
            '--report', str(report), '--revision', revision)
    if expected is not None:
        opts += ('--expected-head', expected)
    return main(opts + extra)


def test_explicit_older_commit_passes_while_current_head_fails(revision_repo, tmp_path):
    root, policy, safe, unsafe = revision_repo
    initial = git(root, 'status', '--porcelain')
    file_bytes = (root / 'src/module.py').read_bytes()
    good = tmp_path / 'good.json'
    assert gate(root, policy, good, safe, safe) == 0
    report = json.loads(good.read_text())
    assert report['head'] == safe
    assert report['status'] == 'passed'
    bad = tmp_path / 'bad.json'
    assert gate(root, policy, bad, unsafe, unsafe) == 1
    assert json.loads(bad.read_text())['status'] == 'failed'
    assert git(root, 'rev-parse', 'HEAD') == unsafe
    assert git(root, 'status', '--porcelain') == initial
    assert (root / 'src/module.py').read_bytes() == file_bytes


def test_mismatched_expected_head_fails_closed(revision_repo, tmp_path):
    root, policy, safe, unsafe = revision_repo
    output = tmp_path / 'mismatch.json'
    assert gate(root, policy, output, safe, unsafe) == 1
    assert json.loads(output.read_text())['head'] == safe


@pytest.mark.parametrize('value', (
    'HEAD', 'main', 'HEAD~1', 'x' * 40, '0' * 39,
    'a' * 65, 'b' * 40 + '--upload-pack=bad',
))
def test_untrusted_or_missing_revision_is_rejected(
    revision_repo, tmp_path, value,
):
    root, policy, safe, _ = revision_repo
    code = gate(root, policy, tmp_path / 'evidence.json', value, safe)
    assert code == 2


def test_unbound_revision_rejected_even_if_valid(revision_repo, tmp_path):
    root, policy, safe, _ = revision_repo
    assert gate(root, policy, tmp_path / 'evidence.json', safe) == 2


def test_revision_requires_tracked_scope(revision_repo, tmp_path):
    root, policy, safe, _ = revision_repo
    policy.write_text(policy.read_text().replace('scope="tracked"', 'scope="staged"'))
    assert gate(root, policy, tmp_path / 'evidence.json', safe, safe) == 2


def test_snapshot_accepts_only_commit_not_tag_object(revision_repo):
    root, _, safe, _ = revision_repo
    blob_oid = git(root, 'hash-object', 'src/module.py')
    with pytest.raises(ConfigurationError):
        scan_commit(root, {
            'checks': ('python-ast',), 'max_file_bytes': 4096,
            'timeout_seconds': 30, 'include_prefixes': ('src/',),
        }, revision=blob_oid)
