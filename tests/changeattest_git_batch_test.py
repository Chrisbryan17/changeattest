from __future__ import annotations

import hashlib
import subprocess

import pytest

import changeattest.git_batch as batch
from changeattest.git_batch import GitObjectError
from changeattest.git_batch import blob_contents
from changeattest.git_batch import blob_sizes
from changeattest.snapshot import scan_commit


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(('git', 'init', '-q'), cwd=root, check=True)
    subprocess.run(('git', 'config', 'user.name', 'Test'), cwd=root, check=True)
    subprocess.run(('git', 'config', 'user.email', 'tests@example.invalid'),
                   cwd=root, check=True)
    subprocess.run(('git', 'config', 'core.autocrlf', 'false'), cwd=root, check=True)
    return root


def git(repo, *args):
    return subprocess.check_output(('git', *args), cwd=repo).strip().decode('ascii')


def test_round_trip_many_blobs_with_repeated_ids_and_binary_content(repo):
    expected = {}
    for n in range(64):
        contents = ((b'\x00binary\n' + bytes([n])) if n % 3 == 0
                    else (b'same-content' if n % 3 == 1
                          else f'number-{n}'.encode()))
        name = f'item-{n:03d}.bin'
        (repo / name).write_bytes(contents)
        expected[name] = contents
    subprocess.run(('git', 'add', '-A'), cwd=repo, check=True)
    objects = {name: git(repo, 'hash-object', name) for name in expected}
    ordered = list(objects.values()) + list(objects.values())[:3]
    sizes = blob_sizes(repo, ordered)
    blobs = blob_contents(repo, ordered, sizes)
    assert set(sizes) == set(objects.values())
    for name, oid in objects.items():
        assert blobs[oid] == expected[name]
        assert sizes[oid] == len(expected[name])


def test_empty_input_requires_no_git(repo, monkeypatch):
    monkeypatch.setattr(batch, '_git', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('git should not execute'),
    ))
    assert blob_sizes(repo, []) == {}
    assert blob_contents(repo, [], {}) == {}


def test_type_confusion_is_rejected(repo):
    (repo / 'item.py').write_text('pass\n')
    subprocess.run(('git', 'add', 'item.py'), cwd=repo, check=True)
    tree = git(repo, 'write-tree')
    with pytest.raises(GitObjectError):
        blob_sizes(repo, [tree])
    with pytest.raises(GitObjectError):
        blob_sizes(repo, ['not-a-commit'])


def test_forged_size_or_truncated_stream_fails_closed(repo):
    (repo / 'item.py').write_text('pass\n')
    oid = git(repo, 'hash-object', 'item.py')
    with pytest.raises(GitObjectError):
        blob_contents(repo, [oid], {oid: 9999})


def test_snapshot_uses_one_metadata_and_one_content_batch(repo, monkeypatch):
    for i in range(70):
        (repo / f'file-{i:03d}.py').write_text(f'x = {i}\n')
    subprocess.run(('git', 'add', '-A'), cwd=repo, check=True)
    subprocess.run(('git', 'commit', '-qm', 'lots of files'), cwd=repo, check=True)
    called = []
    original = batch._git

    def measured(*args, **kwargs):
        called.append(args[1:])
        return original(*args, **kwargs)

    monkeypatch.setattr(batch, '_git', measured)
    report = scan_commit(repo, {
        'checks': ('python-ast',), 'timeout_seconds': 30,
        'max_file_bytes': 8192, 'include_prefixes': (),
    })
    assert report['status'] == 'passed'
    assert report['file_count'] == 70
    assert len(report['files']) == 70
    assert sum('--batch-check' in ' '.join(c) for c in called) == 1
    assert sum('--batch' in ' '.join(c) and '--batch-check' not in ' '.join(c)
               for c in called) == 1


def test_snapshot_does_not_read_oversize_blobs(repo):
    (repo / 'large.py').write_bytes(b'a' * 1000)
    (repo / 'small.py').write_bytes(b'x = 1\n')
    subprocess.run(('git', 'add', '-A'), cwd=repo, check=True)
    subprocess.run(('git', 'commit', '-qm', 'sizes'), cwd=repo, check=True)
    report = scan_commit(repo, {
        'checks': ('python-ast',), 'timeout_seconds': 30,
        'max_file_bytes': 100, 'include_prefixes': (),
    })
    assert report['status'] == 'error'
    assert report['problems'] == [
        {'path': 'large.py', 'reason': 'file-size-limit'},
    ]
    assert len(report['files']) == 1
