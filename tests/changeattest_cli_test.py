from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from changeattest.cli import main
from changeattest.engine import CHECKS
from changeattest.engine import _run_check
from changeattest.engine import canonical


def git(root: Path, *args: str) -> None:
    subprocess.run(('git', *args), cwd=root, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def sample_repo(tmp_path):
    root = tmp_path / 'source repo'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'core.autocrlf', 'false')
    return root


def run_report(repo: Path, report: Path, *args: str) -> tuple[int, dict]:
    code = main(('check', '--root', str(repo), '--report', str(report), *args))
    return code, json.loads(report.read_text(encoding='utf-8'))


def test_staged_json_passes_and_emits_repeatable_evidence(sample_repo, tmp_path):
    (sample_repo / 'valid.json').write_text('{"hello":"world"}\n')
    git(sample_repo, 'add', 'valid.json')
    destination = tmp_path / 'evidence.json'

    code, report = run_report(sample_repo, destination)
    original = destination.read_bytes()
    assert code == 0
    assert report['schema'] == 'changeattest.report.v1'
    assert report['status'] == 'passed'
    assert report['scope'] == 'staged'
    assert report['head'] is None  # New Git repo with no commits.
    assert report['file_count'] == 1
    assert report['files'] == [
        {'path': 'valid.json',
         'sha256': hashlib.sha256((sample_repo / 'valid.json').read_bytes()).hexdigest()},
    ]
    assert [x['id'] for x in report['checks']] == [
        'json', 'toml', 'yaml', 'merge-conflict', 'private-key',
        'openpgp-secret-key',
    ]
    assert next(x for x in report['checks'] if x['id'] == 'json')['status'] == 'passed'
    digest = report.pop('report_sha256')
    assert digest == hashlib.sha256(canonical(report)).hexdigest()

    assert main(('check', '--root', str(sample_repo), '--report', str(destination))) == 0
    assert destination.read_bytes() == original


def test_invalid_json_is_a_check_failure(sample_repo, tmp_path, capsys):
    (sample_repo / 'broken.json').write_text('{"x":')
    git(sample_repo, 'add', 'broken.json')
    code, report = run_report(sample_repo, tmp_path / 'result.json')

    assert code == 1
    assert report['status'] == 'failed'
    assert next(x for x in report['checks'] if x['id'] == 'json')['exit_code'] == 1
    assert 'ChangeAttest: failed' in capsys.readouterr().out


def test_does_not_echo_secret_to_report_or_stdout(sample_repo, tmp_path, capsys):
    secret = 'BEGIN PRIVATE KEY\nSENSITIVE-SAMPLE-NOT-A-REAL-KEY'
    (sample_repo / 'keys.txt').write_text(secret)
    git(sample_repo, 'add', 'keys.txt')
    filename = tmp_path / 'evidence.json'

    code, report = run_report(sample_repo, filename)
    captured = capsys.readouterr()
    assert code == 1
    assert 'SENSITIVE-SAMPLE' not in filename.read_text()
    assert 'SENSITIVE-SAMPLE' not in captured.out + captured.err
    assert next(x for x in report['checks']
                if x['id'] == 'private-key')['status'] == 'failed'


def test_refuses_to_verify_staged_changes_with_unstaged_edits(sample_repo, tmp_path):
    f = sample_repo / 'package.json'
    f.write_text('{"valid":true}')
    git(sample_repo, 'add', 'package.json')
    f.write_text('{"valid":false}')

    code, report = run_report(sample_repo, tmp_path / 'evidence.json')
    assert code == 2
    assert report['status'] == 'error'
    assert report['problems'] == [
        {'path': 'package.json', 'reason': 'staged-worktree-mismatch'},
    ]
    assert report['files'] == []
    assert all(x['status'] == 'skipped' for x in report['checks'])


def test_tracked_scope_scans_worktree_without_staging(sample_repo, tmp_path):
    f = sample_repo / 'config.toml'
    f.write_text('enabled = true\n')
    git(sample_repo, 'add', 'config.toml')
    git(sample_repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '-qm', 'baseline')
    f.write_text('enabled = false\n')

    code, report = run_report(sample_repo, tmp_path / 'report.json',
                              '--scope', 'tracked')
    assert code == 0
    assert report['status'] == 'passed'
    assert report['head'] is not None
    assert next(x for x in report['checks'] if x['id'] == 'toml')['status'] == 'passed'
    assert report['files'][0]['sha256'] == hashlib.sha256(f.read_bytes()).hexdigest()


def test_explicit_config_enables_only_selected_checks(sample_repo, tmp_path):
    (sample_repo / '.changeattest.toml').write_text(
        '[changeattest]\nversion = 1\nchecks = ["json"]\n'
        'timeout_seconds = 5\nmax_file_bytes = 2048\n',
    )
    (sample_repo / 'example.json').write_text('{"ok":true}')
    git(sample_repo, 'add', '.changeattest.toml', 'example.json')

    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 0
    assert len(report['checks']) == 1
    assert report['checks'][0]['id'] == 'json'


@pytest.mark.parametrize('bad_config', (
    '[changeattest]\nversion = 2\n',
    '[changeattest]\nversion = 1\nchecks = ["rm -rf /"]\n',
    '[changeattest]\nversion = 1\ntimeout_seconds = true\n',
    '[changeattest]\nversion = 1\nchecks = ["json", "json"]\n',
))
def test_rejects_unsafe_or_invalid_configuration(sample_repo, bad_config):
    (sample_repo / '.changeattest.toml').write_text(bad_config)
    assert main(('check', '--root', str(sample_repo))) == 2


def test_no_staged_files_does_not_claim_any_checks_ran(sample_repo, tmp_path):
    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 0
    assert report['status'] == 'no-files'
    assert report['file_count'] == 0
    assert all(check['status'] == 'skipped' for check in report['checks'])


def test_file_limit_fails_closed(sample_repo, tmp_path):
    (sample_repo / '.changeattest.toml').write_text(
        '[changeattest]\nversion = 1\nmax_file_bytes = 10\n',
    )
    (sample_repo / 'big.json').write_text('{"long_value":99999}')
    git(sample_repo, 'add', 'big.json')
    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 2
    assert {'path': 'big.json', 'reason': 'file-size-limit'} in report['problems']


@pytest.mark.skipif(sys.platform == 'win32', reason='Symlink privilege not assured')
def test_symlinks_are_not_followed(sample_repo, tmp_path):
    outside = tmp_path / 'sensitive.txt'
    outside.write_text('SENSITIVE-SAMPLE')
    (sample_repo / 'escape').symlink_to(outside)
    git(sample_repo, 'add', 'escape')
    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 2
    assert report['problems'] == [
        {'path': 'escape', 'reason': 'unsafe-symlink-or-path'},
    ]
    assert 'SENSITIVE-SAMPLE' not in (tmp_path / 'report.json').read_text()


def test_timeout_is_reported_as_error(sample_repo, monkeypatch):
    from changeattest import engine

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=1)
    monkeypatch.setattr(engine.subprocess, 'run', timeout)

    result = _run_check(CHECKS[0], ['test.json'], sample_repo, 1)
    assert result['status'] == 'error'
    assert result['exit_code'] is None


def test_unicode_and_spaced_file_names(sample_repo, tmp_path):
    name = 'señor spaced.json'
    (sample_repo / name).write_text('{"ok":1}')
    git(sample_repo, 'add', '--', name)
    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 0
    assert report['files'][0]['path'] == name


def test_repository_cannot_shadow_trusted_python_check_module(sample_repo, tmp_path):
    # A repository being checked may contain a package with the same name as
    # our installed validators. Never run it merely by changing cwd there.
    fake = sample_repo / 'pre_commit_hooks'
    fake.mkdir()
    (fake / '__init__.py').write_text('')
    (fake / 'check_json.py').write_text(
        "from pathlib import Path\n"
        "Path('EXECUTED_UNTRUSTED_CODE').write_text('pwned')\n"
    )
    (sample_repo / 'safe.json').write_text('{"trusted":true}\n')
    git(sample_repo, 'add', 'safe.json')
    code, report = run_report(sample_repo, tmp_path / 'report.json')
    assert code == 0
    assert next(x for x in report['checks'] if x['id'] == 'json')['status'] == 'passed'
    assert not (sample_repo / 'EXECUTED_UNTRUSTED_CODE').exists()
