"""Detect mismatches between Git LFS attributes and staged blob content."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Sequence

_LFS_POINTER = re.compile(
    rb'\Aversion https://git-lfs\.github\.com/spec/v1\r?\n'
    rb'(?:ext-[^\r\n]+\r?\n)*'
    rb'oid sha256:[0-9a-f]{64}\r?\n'
    rb'size [0-9]+\r?\n?\Z',
)
_MAX_POINTER_BYTES = 65536


def _is_staged_lfs_pointer(path: str) -> bool:
    blob = f':{path}'
    size = int(subprocess.check_output(('git', 'cat-file', '-s', blob)))
    if size > _MAX_POINTER_BYTES or size < 100:
        return False
    contents = subprocess.check_output(('git', 'cat-file', 'blob', blob))
    return _LFS_POINTER.fullmatch(contents) is not None


def check_lfs_attributes(paths: Sequence[str]) -> int:
    if not paths:
        return 0
    tracked = subprocess.check_output(('git', 'ls-files', '-z', '--cached', '--', *paths))
    names = [os.fsdecode(name) for name in tracked.split(b'\0') if name]
    if not names:
        return 0

    attrs = subprocess.run(
        ('git', 'check-attr', '--cached', '-z', '--stdin', 'filter'),
        input=b''.join(os.fsencode(name) + b'\0' for name in names),
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    if not attrs.endswith(b'\0'):
        raise ValueError('Unexpected git check-attr response')
    fields = attrs[:-1].split(b'\0')
    if len(fields) != 3 * len(names):
        raise ValueError('Unexpected git check-attr response')

    failed = False
    for i in range(0, len(fields), 3):
        path = os.fsdecode(fields[i])
        is_tracked_lfs = fields[i + 2] == b'lfs'
        is_pointer = _is_staged_lfs_pointer(path)
        if is_tracked_lfs and not is_pointer:
            print(f'{path}: has filter=lfs but is staged as a regular blob')
            failed = True
        elif is_pointer and not is_tracked_lfs:
            print(f'{path}: is staged as an LFS pointer but lacks filter=lfs')
            failed = True
    return int(failed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('filenames', nargs='*')
    args = parser.parse_args(argv)
    return check_lfs_attributes(args.filenames)


if __name__ == '__main__':
    raise SystemExit(main())
