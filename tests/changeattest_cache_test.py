from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from changeattest.adapters import run_adapters
from changeattest.cache import AdvisoryCache

IMAGE = 'ghcr.io/example/reviewed-tools@sha256:' + 'b' * 64


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    for key, value in (
        ('user.name', 'Cache Test'),
        ('user.email', 'cache@example.invalid'),
        ('core.autocrlf', 'false'),
    ):
        subprocess.run(('git', 'config', key, value), cwd=root, check=True)
    (root / 'a.py').write_text('x = 1\n')
    (root / 'pyproject.toml').write_text('[tool.ruff]\nline-length = 88\n')
    subprocess.run(('git', 'add', '-A'), cwd=root, check=True)
    subprocess.run(('git', 'commit', '-qm', 'initial'), cwd=root, check=True)
    return root


def fake_docker_calls(monkeypatch):
    calls = []

    def run(adapter, selected, root, timeout, sandbox):
        calls.append(adapter.id)
        return {
            'id': adapter.id, 'status': 'passed',
            'file_count': len(selected), 'exit_code': 0,
            'output_sha256': 'a' * 64, 'tool_sha256': None,
            'sandbox_image': sandbox.image, 'execution_mode': 'docker-restricted',
        }

    monkeypatch.setattr('changeattest.sandbox.run_in_docker', run)
    return calls


def test_clean_tree_ruff_result_is_cached_and_labeled(checkout, tmp_path, monkeypatch):
    calls = fake_docker_calls(monkeypatch)
    cache = tmp_path / 'cache'
    first = run_adapters(checkout, ['ruff'], ['a.py'],
                         sandbox_image=IMAGE, cache_dir=cache)
    second = run_adapters(checkout, ['ruff'], ['a.py'],
                          sandbox_image=IMAGE, cache_dir=cache)
    assert calls == ['ruff']
    assert first['status'] == 'passed'
    assert second['status'] == 'passed-with-cache'
    assert second['results'][0]['status'] == 'cached-passed'
    assert second['results'][0]['cache_trust'] == 'advisory-unsigned'
    assert second['cached_check_count'] == 1


def test_untrusted_and_deleted_cache_entries_are_not_accepted(
    checkout, tmp_path, monkeypatch,
):
    calls = fake_docker_calls(monkeypatch)
    cache = tmp_path / 'cache'
    run_adapters(checkout, ['ruff'], ['a.py'],
                 sandbox_image=IMAGE, cache_dir=cache)
    record = next(cache.glob('*.json'))
    payload = json.loads(record.read_text())
    payload['result']['id'] = 'not-ruff'
    record.write_text(json.dumps(payload))
    rerun = run_adapters(checkout, ['ruff'], ['a.py'],
                         sandbox_image=IMAGE, cache_dir=cache)
    assert calls == ['ruff', 'ruff']
    assert rerun['status'] == 'passed'


def test_cache_expiry_requires_new_execution(checkout, tmp_path, monkeypatch):
    calls = fake_docker_calls(monkeypatch)
    cache = tmp_path / 'cache'
    run_adapters(checkout, ['ruff'], ['a.py'],
                 sandbox_image=IMAGE, cache_dir=cache)
    record = next(cache.glob('*.json'))
    payload = json.loads(record.read_text())
    payload['created_unix'] -= 7200
    record.write_text(json.dumps(payload))
    run_adapters(checkout, ['ruff'], ['a.py'],
                 sandbox_image=IMAGE, cache_dir=cache)
    assert calls == ['ruff', 'ruff']


def test_dirty_worktree_rejects_cache(checkout, tmp_path, monkeypatch):
    fake_docker_calls(monkeypatch)
    (checkout / 'a.py').write_text('x = 2\n')
    with pytest.raises(ValueError, match='clean Git checkout'):
        run_adapters(checkout, ['ruff'], ['a.py'], sandbox_image=IMAGE,
                     cache_dir=tmp_path / 'cache')


def test_inside_repo_cache_is_disallowed(checkout):
    with pytest.raises(ValueError, match='outside'):
        AdvisoryCache(checkout / '.cache', checkout, IMAGE)


def test_cache_requires_immutable_sandbox_identity(checkout, tmp_path):
    with pytest.raises(ValueError, match='docker-image'):
        run_adapters(checkout, ['ruff'], ['a.py'],
                     cache_dir=tmp_path / 'cache')


def test_test_runners_never_use_cache(checkout, tmp_path, monkeypatch):
    calls = fake_docker_calls(monkeypatch)
    cache = tmp_path / 'cache'
    run_adapters(checkout, ['pytest'], ['a.py'],
                 sandbox_image=IMAGE, cache_dir=cache)
    report = run_adapters(checkout, ['pytest'], ['a.py'],
                          sandbox_image=IMAGE, cache_dir=cache)
    assert calls == ['pytest', 'pytest']
    assert report['status'] == 'passed'
    assert report['cached_check_count'] == 0


def test_source_head_change_invalidates_previous_cache(
    checkout, tmp_path, monkeypatch,
):
    calls = fake_docker_calls(monkeypatch)
    cache = tmp_path / 'cache'
    run_adapters(checkout, ['ruff'], ['a.py'],
                 sandbox_image=IMAGE, cache_dir=cache)
    (checkout / 'a.py').write_text('x = 3\n')
    subprocess.run(('git', 'add', '-A'), cwd=checkout, check=True)
    subprocess.run(('git', 'commit', '-qm', 'change'), cwd=checkout, check=True)
    result = run_adapters(checkout, ['ruff'], ['a.py'],
                          sandbox_image=IMAGE, cache_dir=cache)
    assert result['status'] == 'passed'
    assert calls == ['ruff', 'ruff']
