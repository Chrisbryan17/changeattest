from __future__ import annotations

import pytest

from changeattest.engine import ConfigurationError
from changeattest.policy import load_policy
from changeattest.policy import strengthen_policy


def write_policy(tmp_path, name, *,
                 checks, prefixes, skip=None, scope='tracked',
                 timeout=30, max_bytes=1024, min_files=1):
    path = tmp_path / name
    q = lambda xs: '[' + ','.join(f'"{x}"' for x in xs) + ']'
    path.write_text(
        '[policy]\nversion=1\n'
        f'scope="{scope}"\n'
        f'required_checks={q(checks)}\n'
        f'allow_skipped_checks={q(skip or [])}\n'
        f'include_prefixes={q(prefixes)}\n'
        f'min_files={min_files}\n'
        f'timeout_seconds={timeout}\n'
        f'max_file_bytes={max_bytes}\n'
    )
    return load_policy(path)


def test_overlay_cannot_remove_requirements_or_widen_limits(tmp_path):
    org = write_policy(
        tmp_path, 'org.toml', checks=['python-ast', 'merge-conflict'],
        prefixes=['src/'], skip=['merge-conflict'], timeout=30,
        max_bytes=1024, min_files=2,
    )
    repo = write_policy(
        tmp_path, 'repo.toml', checks=['json'],
        prefixes=['api/'], skip=['json'], timeout=60,
        max_bytes=4096, min_files=1,
    )
    result = strengthen_policy(org, repo)
    assert result.required_checks == ('python-ast', 'json', 'merge-conflict')
    assert result.include_prefixes == ('api/', 'src/')
    assert result.min_files == 2
    assert result.max_file_bytes == 1024
    assert result.timeout_seconds == 30
    assert not result.allow_skipped_checks
    assert len(result.sha256) == 64


def test_all_files_scope_cannot_be_narrowed_by_overlay(tmp_path):
    org = write_policy(tmp_path, 'org.toml', checks=['python-ast'],
                       prefixes=[])
    repo = write_policy(tmp_path, 'repo.toml', checks=['yaml'],
                        prefixes=['src/'])
    assert strengthen_policy(org, repo).include_prefixes == ()


def test_scope_cannot_be_changed(tmp_path):
    org = write_policy(tmp_path, 'org.toml', checks=['python-ast'],
                       prefixes=['src/'])
    repo = write_policy(tmp_path, 'repo.toml', checks=['json'],
                        prefixes=['src/'], scope='staged')
    with pytest.raises(ConfigurationError):
        strengthen_policy(org, repo)
