from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from changeattest.cli import main
from changeattest.engine import canonical
from changeattest.policy import evaluate
from changeattest.policy import load_policy
from changeattest.engine import ConfigurationError


@pytest.fixture
def root(tmp_path):
    root = tmp_path / 'my repo'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    subprocess.run(('git', 'config', 'core.autocrlf', 'false'), cwd=root, check=True)
    (root / 'src').mkdir()
    (root / 'src' / 'ok.py').write_text('answer = 42\n', encoding='utf-8')
    (root / 'skip_this.py').write_text('n = 42\n', encoding='utf-8')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'baseline'), cwd=root, check=True)
    return root


@pytest.fixture
def policy_file(tmp_path):
    dest = tmp_path / 'protected-policy.toml'
    dest.write_text(
        '[policy]\n'
        'version = 1\n'
        'scope = "tracked"\n'
        'include_prefixes = ["src/"]\n'
        'required_checks = ["python-ast", "merge-conflict"]\n'
        'allow_skipped_checks = []\n'
        'min_files = 1\n', encoding='utf-8',
    )
    return dest


def gate(root, policy, destination, *more):
    code = main(('gate', '--root', str(root), '--policy', str(policy),
                 '--report', str(destination), *more))
    return code, json.loads(destination.read_text(encoding='utf-8'))


def test_policy_gate_runs_required_checks(root, policy_file, tmp_path):
    dest = tmp_path / 'evidence.json'
    code, report = gate(root, policy_file, dest)
    assert code == 0, report['problems']
    assert report['status'] == 'passed'
    assert report['include_prefixes'] == ['src/']
    assert report['file_count'] == 1
    assert [c['id'] for c in report['checks']] == [
        'python-ast', 'merge-conflict',
    ]
    assert [c['status'] for c in report['checks']] == [
        'passed', 'passed',
    ]
    assert evaluate(report, load_policy(policy_file)) == ()
    assert hashlib.sha256(canonical({
        k: v for k, v in report.items() if k != 'report_sha256'
    })).hexdigest() == report['report_sha256']


def test_target_config_cannot_disable_required_checks(root, policy_file, tmp_path):
    (root / '.changeattest.toml').write_text(
        '[changeattest]\nversion=1\nchecks=[]\n',
        encoding='utf-8',
    )
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 0
    assert len(report['checks']) == 2
    assert all(c['status'] == 'passed' for c in report['checks'])


def test_ast_error_blocks_gate(root, policy_file, tmp_path):
    (root / 'src' / 'ok.py').write_text('def broken(:\n')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm',
                    'invalid syntax'), cwd=root, check=True)
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 1
    assert report['status'] == 'failed'
    assert 'report-not-passed' in evaluate(report, load_policy(policy_file))


def test_expected_head_mismatch_blocks_gate(root, policy_file, tmp_path):
    report_file = tmp_path / 'report.json'
    code, report = gate(root, policy_file, report_file,
                        '--expected-head', 'a' * 40)
    assert code == 1
    assert 'git-head-mismatch' in evaluate(report, load_policy(policy_file),
                                          expected_head='a' * 40)


def test_no_files_selected_is_not_a_pass(root, policy_file, tmp_path):
    policy_file.write_text(policy_file.read_text().replace(
        'include_prefixes = ["src/"]', 'include_prefixes = ["no-such-dir/"]',
    ))
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 1
    assert report['status'] == 'no-files'
    assert 'insufficient-files' in evaluate(report, load_policy(policy_file))


def test_required_skips_fail_closed(root, policy_file, tmp_path):
    policy_file.write_text(policy_file.read_text().replace(
        'required_checks = ["python-ast", "merge-conflict"]',
        'required_checks = ["python-ast", "yaml"]',
    ))
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 1
    assert 'required-check-skipped' in evaluate(report, load_policy(policy_file))


def test_explicit_opt_in_allows_skipping_inapplicable_check(
    root, policy_file, tmp_path,
):
    policy_file.write_text(
        policy_file.read_text().replace(
            'required_checks = ["python-ast", "merge-conflict"]',
            'required_checks = ["python-ast", "yaml"]',
        ).replace(
            'allow_skipped_checks = []',
            'allow_skipped_checks = ["yaml"]',
        ),
    )
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 0
    assert report['checks'][1]['status'] == 'skipped'


def test_report_missing_a_required_check_does_not_validate(
    root, policy_file, tmp_path,
):
    _, report = gate(root, policy_file, tmp_path / 'report.json')
    report['checks'].pop()
    report.pop('report_sha256')
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    assert 'missing-required-check' in evaluate(report, load_policy(policy_file))


def test_report_self_consistent_forgery_still_cannot_prove_execution(
    root, policy_file, tmp_path,
):
    # Rehashing alone can bypass an *offline* evidence check. The gate must
    # execute validators itself in trusted CI and never accept user artifacts.
    _, report = gate(root, policy_file, tmp_path / 'report.json')
    report['files'][0]['sha256'] = 'f' * 64
    report.pop('report_sha256')
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    assert evaluate(report, load_policy(policy_file)) == ()


def test_checksum_modifications_are_detected(root, policy_file, tmp_path):
    _, report = gate(root, policy_file, tmp_path / 'report.json')
    report['files'][0]['sha256'] = 'e' * 64
    assert 'invalid-report-checksum' in evaluate(report, load_policy(policy_file))


def test_malformed_report_does_not_crash_policy_evaluator(policy_file):
    policy = load_policy(policy_file)
    for malformed in (
        {},
        {'checks': None},
        {'checks': [{'id': 'python-ast', 'status': 'passed',
                     'file_count': 2, 'exit_code': 0,
                     'output_sha256': None}], 'file_count': None},
        {'checks': [3], 'file_count': 'untrusted', 'files': []},
        {'report_sha256': 2},
    ):
        assert evaluate(malformed, policy)


@pytest.mark.parametrize('contents', (
    '[policy]\nversion=2\n',
    '[policy]\nversion=true\n',
    '[policy]\nversion=1\nrequired_checks=[]\n',
    '[policy]\nversion=1\nrequired_checks=["not-a-check"]\n',
    '[policy]\nversion=1\nallow_skipped_checks=["json"]\n'
    'required_checks=["python-ast"]\n',
    '[policy]\nversion=1\ninclude_prefixes=["../"]\n',
    '[policy]\nversion=1\ninclude_prefixes=["src/", "src/"]\n',
    '[policy]\nversion=1\nmin_files=0\n',
    '[policy]\nversion=1\nmin_files=true\n',
    '[policy]\nversion=1\ntimeout_seconds=0\n',
    '[policy]\nversion=1\nmax_file_bytes=-1\n',
    '[policy]\nversion=1\nunknown="surprise"\n',
))
def test_invalid_policy_is_rejected(tmp_path, contents):
    path = tmp_path / 'policy.toml'
    path.write_text(contents)
    with pytest.raises(ConfigurationError):
        load_policy(path)


def test_error_on_invalid_expected_head(root, policy_file, tmp_path):
    code = main((
        'gate', '--root', str(root), '--policy', str(policy_file),
        '--report', str(tmp_path / 'evidence.json'),
        '--expected-head', 'not-a-sha',
    ))
    assert code == 2


def test_binary_and_symlink_rejections_block_policy(root, policy_file, tmp_path):
    (root / 'src' / 'very-large.py').write_bytes(b'a' * 100)
    subprocess.run(('git', 'add', 'src/very-large.py'),
                   cwd=root, check=True)
    policy_file.write_text(policy_file.read_text() + 'max_file_bytes = 16\n')
    subprocess.run(('git', '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm',
                    'add oversize file'), cwd=root, check=True)
    code, report = gate(root, policy_file, tmp_path / 'evidence.json')
    assert code == 1
    assert 'incomplete-file-verification' in evaluate(
        report, load_policy(policy_file),
    )


def test_gate_scans_committed_bytes_not_mutable_worktree(root, policy_file, tmp_path):
    source = root / 'src' / 'ok.py'
    source.write_text('def syntax_error(:\\n')
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 0
    assert report['status'] == 'passed'
    committed = subprocess.check_output(
        ('git', 'show', 'HEAD:src/ok.py'), cwd=root,
    )
    assert report['files'][0]['sha256'] == hashlib.sha256(
        committed,
    ).hexdigest()


def test_gate_rejects_committed_git_symlinks(root, policy_file, tmp_path):
    import sys
    if sys.platform == 'win32':
        pytest.skip('Windows symlink creation needs elevation')
    (root / 'src' / 'linked.py').symlink_to(root / 'src' / 'ok.py')
    subprocess.run(('git', 'add', 'src/linked.py'), cwd=root, check=True)
    subprocess.run(('git', '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm',
                    'include symlink'), cwd=root, check=True)
    code, report = gate(root, policy_file, tmp_path / 'report.json')
    assert code == 1
    assert {'path': 'src/linked.py',
            'reason': 'unsupported-git-object-type'} in report['problems']
