from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from changeattest.cli import main
from changeattest.engine import canonical
from changeattest.merge_identity import MergeIdentityError
from changeattest.merge_identity import verify_merge_identity


def git(root, *args):
    return subprocess.check_output(('git', *args), cwd=root).strip().decode('ascii')


def write(root, name, contents):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding='utf-8')


def commit(root, message):
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def merge_repo(tmp_path):
    root = tmp_path / 'merge-repository'
    root.mkdir()
    git(root, 'init', '-qb', 'main')
    for name, value in (
        ('user.name', 'Test'), ('user.email', 'ci@example.invalid'),
        ('core.autocrlf', 'false'),
    ):
        git(root, 'config', name, value)
    write(root, 'src/base.py', 'base = 1\n')
    first = commit(root, 'initial')
    git(root, 'checkout', '-qb', 'feature')
    write(root, 'src/feature.py', 'feature = True\n')
    head = commit(root, 'proposed head')
    git(root, 'checkout', '-q', 'main')
    write(root, 'src/base.py', 'base = 2\n')
    base = commit(root, 'updated base')
    git(root, 'merge', '-q', '--no-ff', '-m', 'synthetic merge', 'feature')
    merge = git(root, 'rev-parse', 'HEAD')
    return root, first, base, head, merge


def test_exact_parent_order_and_checksum(merge_repo):
    root, _, base, head, merge = merge_repo
    result = verify_merge_identity(root, base, head, merge)
    assert result['status'] == 'verified'
    assert result['parents'] == [base, head]
    assert result['reasons'] == []
    unsigned = {k: v for k, v in result.items() if k != 'report_sha256'}
    assert result['report_sha256'] == hashlib.sha256(canonical(unsigned)).hexdigest()


def test_swapped_or_stale_parents_are_rejected(merge_repo):
    root, first, base, head, merge = merge_repo
    swapped = verify_merge_identity(root, head, base, merge)
    assert swapped['status'] == 'rejected'
    assert swapped['reasons'] == ['merge-parent-identity-mismatch']
    stale = verify_merge_identity(root, first, head, merge)
    assert stale['status'] == 'rejected'
    assert stale['reasons'] == ['merge-parent-identity-mismatch']


def test_non_merge_commit_is_rejected(merge_repo):
    root, first, base, head, merge = merge_repo
    report = verify_merge_identity(root, base, head, first)
    assert report['status'] == 'rejected'
    assert report['reasons'] == ['merge-parent-count-mismatch']


@pytest.mark.parametrize('malformed', (
    'HEAD', 'main', 'not-a-sha', 'a' * 39, 'b' * 65,
    'c' * 40 + ':path', 'd' * 40 + '--upload-pack=unsafe',
))
def test_rejects_symbolic_or_incomplete_git_identity(merge_repo, malformed):
    root, _, base, head, merge = merge_repo
    with pytest.raises(MergeIdentityError):
        verify_merge_identity(root, base, head, malformed)


def test_rejects_blob_objects_instead_of_merges(merge_repo):
    root, _, base, head, _ = merge_repo
    blob = git(root, 'hash-object', 'src/base.py')
    with pytest.raises(MergeIdentityError, match='commit'):
        verify_merge_identity(root, base, head, blob)


def test_nonexistent_merge_oid_fails_closed(merge_repo):
    root, _, base, head, _ = merge_repo
    with pytest.raises(MergeIdentityError):
        verify_merge_identity(root, base, head, 'f' * 40)


def test_cli_emits_provenance_of_actual_merge(merge_repo, tmp_path):
    root, _, base, head, merge = merge_repo
    output = tmp_path / 'merge-evidence.json'
    code = main((
        'verify-merge', '--root', str(root),
        '--base', base, '--head', head, '--merge', merge,
        '--report', str(output),
    ))
    assert code == 0
    recorded = json.loads(output.read_text())
    assert recorded['merge'] == merge
    assert recorded['parents'] == [base, head]
    assert recorded['status'] == 'verified'


def test_cli_rejects_mismatching_parents(merge_repo, tmp_path):
    root, first, base, head, merge = merge_repo
    output = tmp_path / 'rejected.json'
    code = main((
        'verify-merge', '--root', str(root),
        '--base', first, '--head', head, '--merge', merge,
        '--report', str(output),
    ))
    assert code == 1
    assert json.loads(output.read_text())['status'] == 'rejected'


def test_commit_metadata_read_does_not_touch_worktree(merge_repo):
    root, _, base, head, merge = merge_repo
    write(root, 'src/feature.py', 'def broken(:\n')
    state = git(root, 'status', '--porcelain')
    assert verify_merge_identity(root, base, head, merge)['status'] == 'verified'
    assert git(root, 'status', '--porcelain') == state
