from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from changeattest.cli import main
from changeattest.engine import canonical
from changeattest.trust_changes import SensitiveChangeError
from changeattest.trust_changes import classify_commit_change
from changeattest.trust_changes import classify_path


def git(root, *args):
    return subprocess.check_output(('git', *args), cwd=root).strip().decode('ascii')


@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'security checkout'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    for k, v in (
        ('user.name', 'Test'), ('user.email', 'tests@example.invalid'),
        ('core.autocrlf', 'false'),
    ):
        subprocess.run(('git', 'config', k, v), cwd=root, check=True)
    (root / 'docs').mkdir()
    (root / 'docs/README.md').write_text('Safe change\n')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'base'), cwd=root, check=True)
    return root


def commit(root, message):
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', message), cwd=root, check=True)
    return git(root, 'rev-parse', 'HEAD')


def test_sensitive_policy_workflow_and_engine_changes_classified(root):
    base = git(root, 'rev-parse', 'HEAD')
    for folder in ('.github/workflows', 'changeattest'):
        (root / folder).mkdir(parents=True)
    (root / '.github/workflows/skip-ci.yml').write_text('on: push\n')
    (root / '.github/changeattest-policy.toml').write_text('[policy]\n')
    (root / 'changeattest/policy.py').write_text('pass\n')
    (root / 'docs/README.md').write_text('Still safe\n')
    head = commit(root, 'proposed change')
    report = classify_commit_change(root, base, head)
    assert report['status'] == 'review-required'
    assert report['counts'] == {'critical': 2, 'high': 1}
    assert [v['path'] for v in report['findings']] == [
        '.github/changeattest-policy.toml',
        '.github/workflows/skip-ci.yml',
        'changeattest/policy.py',
    ]
    clean = dict(report)
    clean.pop('report_sha256')
    assert report['report_sha256'] == hashlib.sha256(canonical(clean)).hexdigest()


def test_normal_docs_changes_do_not_claim_review_required(root):
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'docs/README.md').write_text('Modified\n')
    head = commit(root, 'docs')
    result = classify_commit_change(root, base, head)
    assert result['status'] == 'no-sensitive-changes'
    assert result['findings'] == []
    assert result['changed_paths'] == ['docs/README.md']


def test_comparison_to_same_revision_is_explicitly_empty(root):
    base = git(root, 'rev-parse', 'HEAD')
    result = classify_commit_change(root, base, base)
    assert result['status'] == 'no-changes'
    assert not result['changed_paths']


def test_current_worktree_changes_do_not_alter_report(root):
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'docs/README.md').write_text('Committed\n')
    head = commit(root, 'docs update')
    (root / '.github/workflows').mkdir(parents=True)
    (root / '.github/workflows/unsafe.yml').write_text('on: pull_request\n')
    report = classify_commit_change(root, base, head)
    assert report['findings'] == []
    assert report['status'] == 'no-sensitive-changes'


def test_deleted_policy_is_sensitive_even_without_file_contents(root):
    (root / '.github').mkdir()
    policy = root / '.github/changeattest-policy.toml'
    policy.write_text('[policy]\n')
    base = commit(root, 'baseline policy')
    policy.unlink()
    head = commit(root, 'deleted policy')
    report = classify_commit_change(root, base, head)
    assert report['counts']['critical'] == 1


@pytest.mark.parametrize('bad', ('HEAD', 'a' * 39, 'a' * 65, 'not-a-sha'))
def test_noncanonical_commit_identifiers_are_rejected(root, bad):
    base = git(root, 'rev-parse', 'HEAD')
    with pytest.raises(SensitiveChangeError):
        classify_commit_change(root, bad, base)


def test_nonexistent_sha_rejected_by_git(root):
    base = git(root, 'rev-parse', 'HEAD')
    with pytest.raises(SensitiveChangeError):
        classify_commit_change(root, 'a' * 40, base)


@pytest.mark.parametrize(('name', 'level'), (
    ('.github/workflows/verify.yml', 'critical'),
    ('.github/actions/verify/action.yml', 'critical'),
    ('.github/CODEOWNERS', 'critical'),
    ('changeattest/cli.py', 'high'),
    ('changeattest/new_source.py', 'high'),
    ('requirements-dev.txt', 'high'),
    ('SECURITY.md', 'high'),
    ('README.md', None),
    ('.github/workflows-adjacent/fake.yml', None),
))
def test_sensitive_patterns(name, level):
    result = classify_path(name)
    assert (result[0] if result else None) == level


def test_block_sensitive_cli_requires_review(root, tmp_path):
    base = git(root, 'rev-parse', 'HEAD')
    (root / '.github/workflows').mkdir(parents=True)
    (root / '.github/workflows/malicious.yml').write_text('on: push\n')
    head = commit(root, 'workflow change')
    output = tmp_path / 'report.json'
    status = main(('sensitive-change', '--root', str(root),
                   '--base', base, '--head', head,
                   '--report', str(output), '--block-sensitive'))
    assert status == 1
    report = json.loads(output.read_text())
    assert report['counts']['critical'] == 1


def test_default_cli_is_advisory(root, tmp_path):
    base = git(root, 'rev-parse', 'HEAD')
    (root / '.github/workflows').mkdir(parents=True)
    (root / '.github/workflows/x.yml').write_text('on: push\n')
    head = commit(root, 'workflow change')
    output = tmp_path / 'report.json'
    assert main(('sensitive-change', '--root', str(root), '--base', base,
                 '--head', head, '--report', str(output))) == 0
    assert json.loads(output.read_text())['status'] == 'review-required'


def test_critical_only_blocking_allows_ordinary_verifier_source_review(root, tmp_path):
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'changeattest').mkdir()
    (root / 'changeattest/snapshot.py').write_text('safe = True\n')
    head = commit(root, 'engine implementation')
    output = tmp_path / 'review.json'
    assert main(('sensitive-change', '--root', str(root),
                 '--base', base, '--head', head,
                 '--report', str(output), '--block-critical')) == 0
    report = json.loads(output.read_text())
    assert report['counts'] == {'critical': 0, 'high': 1}
    assert report['status'] == 'review-required'


def test_critical_only_blocking_rejects_workflow_change(root, tmp_path):
    base = git(root, 'rev-parse', 'HEAD')
    (root / '.github/workflows').mkdir(parents=True)
    (root / '.github/workflows/new-gate.yml').write_text('on: push\n')
    head = commit(root, 'workflow modification')
    output = tmp_path / 'review.json'
    assert main(('sensitive-change', '--root', str(root),
                 '--base', base, '--head', head,
                 '--report', str(output), '--block-critical')) == 1
    assert json.loads(output.read_text())['counts']['critical'] == 1
