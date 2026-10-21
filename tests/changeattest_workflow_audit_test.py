from __future__ import annotations

import hashlib
import subprocess

import pytest

from changeattest.engine import canonical
from changeattest.workflow_audit import audit_commit
from changeattest.workflow_audit import inspect_workflow

PIN = 'a' * 40


def rules(text):
    return [x['rule'] for x in inspect_workflow(
        '.github/workflows/verify.yml', text.encode('utf-8'),
    )]


def test_pinned_read_only_pr_workflow_has_no_findings():
    workflow = (
        'name: Safe\n'
        'on:\n  pull_request:\n    branches: [main]\n'
        'permissions: {contents: read}\n'
        'jobs:\n'
        '  verify:\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        f'      - uses: actions/checkout@{PIN}\n'
        '        with:\n'
        '          persist-credentials: false\n'
        '      - run: echo safe\n'
    )
    assert rules(workflow) == []


def test_privileged_checkout_then_shell_is_critical():
    workflow = (
        'on: pull_request_target\n'
        'permissions: {contents: read}\n'
        'jobs:\n'
        '  check:\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        f'      - uses: actions/checkout@{PIN}\n'
        '        with:\n'
        '          persist-credentials: false\n'
        '          ref: ${{ github.event.pull_request.head.sha }}\n'
        '      - run: npm test\n'
    )
    findings = inspect_workflow('x.yml', workflow.encode())
    assert 'privileged-pr-trigger' in [x['rule'] for x in findings]
    assert 'privileged-checkout-of-pr-code' in [x['rule'] for x in findings]
    assert any(x['severity'] == 'critical' and
               x['rule'] == 'privileged-run-after-pr-checkout'
               for x in findings)


def test_unsafe_checkout_flag_detected_even_with_base_ref():
    workflow = (
        'on: pull_request_target\n'
        'permissions: {contents: read}\n'
        'jobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n'
        f'      - uses: actions/checkout@{PIN}\n'
        '        with:\n          allow-unsafe-pr-checkout: true\n'
    )
    assert 'privileged-checkout-of-pr-code' in rules(workflow)


def test_injected_shell_expression_and_write_token():
    workflow = (
        'on: pull_request_target\n'
        'permissions: write-all\n'
        'jobs:\n'
        '  check:\n'
        '    permissions: {contents: write}\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        '      - run: echo "${{ github.event.pull_request.title }}"\n'
    )
    issues = rules(workflow)
    assert 'write-token-for-pr-event' in issues
    assert 'untrusted-expression-in-shell' in issues


def test_floating_action_refs_and_download_piped_shell_warn():
    workflow = (
        'on: push\n'
        'jobs:\n'
        '  check:\n    runs-on: ubuntu-latest\n    steps:\n'
        '      - uses: actions/checkout@v4\n'
        '      - run: curl -sSL https://example.invalid/get.sh | bash\n'
    )
    issues = rules(workflow)
    assert 'unpinned-action-reference' in issues
    assert 'download-piped-to-shell' in issues


def test_invalid_yaml_rejected_without_crashing():
    assert rules('on: [') == ['invalid-workflow-yaml']
    assert rules('- 1\n- 2\n') == ['invalid-workflow-shape']
    assert rules('on: pull_request\n') == ['missing-jobs']


def _git(root, *argv):
    return subprocess.check_output(('git', *argv), cwd=root).strip().decode()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    subprocess.run(('git', 'config', 'user.name', 'Test'), cwd=root, check=True)
    subprocess.run(('git', 'config', 'user.email', 'ci@example.invalid'),
                   cwd=root, check=True)
    (root / '.github' / 'workflows').mkdir(parents=True)
    wf = root / '.github' / 'workflows' / 'safe.yml'
    wf.write_text(
        'on: pull_request\npermissions: {contents: read}\n'
        'jobs:\n  check:\n    runs-on: ubuntu-latest\n'
        '    steps:\n'
        f'      - uses: actions/checkout@{PIN}\n'
        '        with: {persist-credentials: false}\n',
        encoding='utf-8',
    )
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'safe workflow'),
                   cwd=root, check=True)
    return root, wf


def test_git_blob_audit_is_immutable_and_checksumed(repository):
    root, wf = repository
    head = _git(root, 'rev-parse', 'HEAD')
    wf.write_text('on: pull_request_target\npermissions: write-all\n')
    report = audit_commit(root)
    assert report['head'] == head
    assert report['workflows_scanned'] == 1
    assert report['finding_counts'] == {
        'critical': 0, 'high': 0, 'medium': 0, 'info': 0,
    }
    assert report['findings'] == []
    unsealed = {k: v for k, v in report.items() if k != 'report_sha256'}
    assert hashlib.sha256(canonical(unsealed)).hexdigest() == report['report_sha256']


def test_workflow_change_in_commit_generates_findings(repository):
    root, wf = repository
    wf.write_text(
        'on: pull_request\npermissions: {contents: write}\n'
        'jobs:\n  check:\n    runs-on: ubuntu-latest\n'
        '    steps:\n      - uses: actions/checkout@v4\n',
        encoding='utf-8',
    )
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'less safe'),
                   cwd=root, check=True)
    report = audit_commit(root)
    assert report['finding_counts']['high'] >= 1
    assert report['finding_counts']['medium'] >= 1
