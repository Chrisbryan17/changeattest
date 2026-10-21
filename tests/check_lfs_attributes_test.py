from __future__ import annotations

import subprocess

import pytest

from pre_commit_hooks.check_lfs_attributes import main


def _git(*args: str) -> None:
    subprocess.run(('git', *args), check=True, capture_output=True)


def _stage(*filenames: str) -> None:
    # Keep tests independent of whether git-lfs is installed on the host.
    _git(
        '-c', 'filter.lfs.clean=',
        '-c', 'filter.lfs.required=false',
        'add', '--', *filenames,
    )


@pytest.fixture
def lfs_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _git('init', '-q')
    return tmp_path


def _pointer() -> bytes:
    return (
        b'version https://git-lfs.github.com/spec/v1\n'
        b'oid sha256:' + b'a' * 64 + b'\n'
        b'size 123\n'
    )


def test_staged_regular_blob_has_lfs_attribute(lfs_repo, capsys):
    (lfs_repo / '.gitattributes').write_text('*.bin filter=lfs\n')
    (lfs_repo / 'data.bin').write_bytes(b'regular bytes')
    _stage('.gitattributes', 'data.bin')

    assert main(['data.bin']) == 1
    assert 'has filter=lfs but is staged as a regular blob' in capsys.readouterr().out


def test_staged_lfs_pointer_without_lfs_attribute(lfs_repo, capsys):
    (lfs_repo / 'data.txt').write_bytes(_pointer())
    _stage('data.txt')

    assert main(['data.txt']) == 1
    assert 'is staged as an LFS pointer but lacks filter=lfs' in capsys.readouterr().out


def test_matching_pointer_and_attribute_pass(lfs_repo):
    (lfs_repo / '.gitattributes').write_text('*.bin filter=lfs\n')
    (lfs_repo / 'data.bin').write_bytes(_pointer())
    _stage('.gitattributes', 'data.bin')

    assert main(['data.bin']) == 0


def test_checks_index_not_unstaged_worktree(lfs_repo):
    (lfs_repo / '.gitattributes').write_text('*.bin filter=lfs\n')
    (lfs_repo / 'data.bin').write_bytes(_pointer())
    _stage('.gitattributes', 'data.bin')

    (lfs_repo / '.gitattributes').write_text('')
    (lfs_repo / 'data.bin').write_bytes(b'changed in worktree')

    assert main(['data.bin']) == 0


def test_handles_unicode_file_names(lfs_repo):
    (lfs_repo / 'mañana.txt').write_bytes(_pointer())
    _stage('mañana.txt')

    assert main(['mañana.txt']) == 1


def test_no_paths_is_noop(lfs_repo):
    assert main([]) == 0
