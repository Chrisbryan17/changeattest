from __future__ import annotations

import hashlib
import subprocess

import pytest

from changeattest.engine import canonical
from changeattest.impact import ImpactError
from changeattest.impact import plan_impact


def run_git(root, *args):
    result = subprocess.run(
        ('git', *args), cwd=root, check=True, capture_output=True,
    )
    return result.stdout.strip().decode('ascii')


def commit(root, message='change'):
    run_git(root, 'add', '-A')
    run_git(root, 'commit', '-qm', message)
    return run_git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    run_git(root, 'init', '-q')
    for k, v in (
        ('user.name', 'ChangeAttest CI'),
        ('user.email', 'ci@example.invalid'),
        ('core.autocrlf', 'false'),
    ):
        run_git(root, 'config', k, v)
    for dirname in ('pkg', 'tests'):
        (root / dirname).mkdir()
    files = {
        'pkg/__init__.py': '',
        'pkg/lib.py': 'def value():\n    return 1\n',
        'pkg/service.py': 'from . import lib\n\n'
                          'def serve():\n    return lib.value()\n',
        'pkg/other.py': 'def other():\n    return 2\n',
        'tests/test_service.py': 'from pkg import service\n\n'
                                 'def test_service():\n'
                                 '    assert service.serve() == 1\n',
        'tests/test_other.py': 'from pkg.other import other\n\n'
                               'def test_other():\n'
                               '    assert other() == 2\n',
        'README.md': '# project\n',
    }
    for name, contents in files.items():
        (root / name).write_text(contents, encoding='utf-8')
    first = commit(root, 'initial')
    return root, first


def changed(root, name, contents):
    (root / name).write_text(contents, encoding='utf-8')
    return commit(root)


def test_transitive_import_graph_selects_relevant_tests(repo):
    root, base = repo
    head = changed(root, 'pkg/lib.py', 'def value():\n    return 3\n')
    report = plan_impact(root, base, head)
    assert report['status'] == 'advisory-only'
    assert report['decision'] == 'targeted-advisory'
    assert report['changed_files'] == ['pkg/lib.py']
    assert report['all_tests'] == ['tests/test_other.py', 'tests/test_service.py']
    assert report['suggested_tests'] == ['tests/test_service.py']
    assert report['selected_count'] == 1
    assert report['total_count'] == 2
    assert report['potential_test_reduction_percent'] == 50.0
    assert 'pkg/service.py' in report['affected_python_files']
    assert 'run-full-test-suite' == report['mandatory_ci_recommendation']
    unsealed = {k: v for k, v in report.items() if k != 'report_sha256'}
    assert hashlib.sha256(canonical(unsealed)).hexdigest() == report['report_sha256']


def test_modified_test_is_included(repo):
    root, base = repo
    head = changed(
        root, 'tests/test_other.py',
        'from pkg.other import other\n\ndef test_other():\n    assert other()\n',
    )
    result = plan_impact(root, base, head)
    assert result['decision'] == 'targeted-advisory'
    assert result['suggested_tests'] == ['tests/test_other.py']


def test_config_changes_require_full_suite(repo):
    root, base = repo
    head = changed(root, 'README.md', '# updated\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'non-python-change' in result['fallback_reasons']
    assert result['selected_count'] == 2


def test_python_package_init_triggers_full_suite(repo):
    root, base = repo
    head = changed(root, 'pkg/__init__.py', 'VERSION = 1\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'global-import-or-fixture-change' in result['fallback_reasons']


def test_pytest_fixture_changes_trigger_full_suite(repo):
    root, base = repo
    head = changed(root, 'tests/conftest.py', 'import pytest\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'global-import-or-fixture-change' in result['fallback_reasons']


def test_dynamic_imports_fall_back(repo):
    root, base = repo
    head = changed(
        root, 'pkg/lib.py',
        "import importlib\n\nx = importlib.import_module('pkg.other')\n",
    )
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'dynamic-or-star-import' in result['fallback_reasons']


def test_import_module_function_call_requires_full_suite(repo):
    root, base = repo
    head = changed(
        root, 'pkg/lib.py',
        "from importlib import import_module\n\n"
        "something = import_module('pkg.other')\n",
    )
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'dynamic-or-star-import' in result['fallback_reasons']


def test_syntax_errors_fall_back(repo):
    root, base = repo
    head = changed(root, 'pkg/lib.py', 'def broken(:\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'source-parse-error' in result['fallback_reasons']


def test_unlinked_python_code_does_not_silently_skip_all_tests(repo):
    root, base = repo
    head = changed(root, 'pkg/new.py', 'def new():\n    return True\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'no-test-dependency-match' in result['fallback_reasons']


def test_deleted_python_source_falls_back(repo):
    root, base = repo
    (root / 'pkg' / 'lib.py').unlink()
    head = commit(root)
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'deleted-or-unreadable-python' in result['fallback_reasons']


def test_no_diff_does_not_claim_incremental_safety(repo):
    root, base = repo
    result = plan_impact(root, base, base)
    assert result['decision'] == 'full'
    assert 'no-diff' in result['fallback_reasons']


def test_plan_binds_to_git_objects_not_uncommitted_worktree(repo):
    root, base = repo
    head = changed(root, 'pkg/lib.py', 'def value():\n    return 3\n')
    (root / 'pkg/lib.py').write_text('def broken(:\n')
    result = plan_impact(root, base, head)
    assert result['decision'] == 'targeted-advisory'
    assert result['suggested_tests'] == ['tests/test_service.py']


@pytest.mark.parametrize('bad', ('HEAD', 'abc', 'a' * 39, 'a' * 65))
def test_requires_complete_git_revisions(repo, bad):
    root, base = repo
    with pytest.raises(ImpactError):
        plan_impact(root, base, bad)


def test_rename_is_conservative(repo):
    root, base = repo
    (root / 'pkg/lib.py').rename(root / 'pkg/renamed.py')
    head = commit(root)
    result = plan_impact(root, base, head)
    assert result['decision'] == 'full'
    assert 'deleted-or-unreadable-python' in result['fallback_reasons']
