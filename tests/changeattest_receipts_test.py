from __future__ import annotations

import hashlib
import subprocess

import pytest

from changeattest.engine import canonical
from changeattest.test_receipts import collect


@pytest.fixture
def git_repo(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=source, check=True)
    subprocess.run(('git', 'config', 'user.name', 'Test'), cwd=source, check=True)
    subprocess.run(('git', 'config', 'user.email', 'test@example.invalid'),
                   cwd=source, check=True)
    (source / 'file.txt').write_text('data')
    subprocess.run(('git', 'add', '-A'), cwd=source, check=True)
    subprocess.run(('git', 'commit', '-qm', 'initial'), cwd=source, check=True)
    return source


def test_junit_receipts_are_hashed_and_counted(git_repo, tmp_path):
    xml = tmp_path / 'suite.xml'
    xml.write_text(
        '<testsuite><testcase name="a"/><testcase name="b">'
        '<skipped/></testcase></testsuite>',
    )
    report = collect(git_repo, [str(xml)])
    assert report['status'] == 'passed'
    assert report['test_cases'] == 2
    assert report['checks'][0]['passed'] == 1
    assert report['checks'][0]['skipped'] == 1
    assert report['checks'][0]['output_sha256'] == hashlib.sha256(
        xml.read_bytes(),
    ).hexdigest()
    canonical_body = {key: value for key, value in report.items()
                      if key != 'report_sha256'}
    assert report['report_sha256'] == hashlib.sha256(
        canonical(canonical_body),
    ).hexdigest()


def test_junit_failures_are_not_reported_as_success(git_repo, tmp_path):
    xml = tmp_path / 'suite.xml'
    xml.write_text('<testsuite><testcase name="a"><failure/></testcase></testsuite>')
    report = collect(git_repo, [str(xml)])
    assert report['status'] == 'failed'
    assert report['checks'][0]['failed'] == 1


@pytest.mark.parametrize('contents', (
    '<testsuite/>',
    '<message/>',
    '<testsuite><testcase>',
))
def test_rejects_empty_or_malformed_reports(git_repo, tmp_path, contents):
    xml = tmp_path / 'report.xml'
    xml.write_text(contents)
    with pytest.raises(ValueError):
        collect(git_repo, [str(xml)])
