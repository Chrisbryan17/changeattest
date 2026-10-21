"""Bounded, identity-checked Git object reads for immutable snapshots.

Batching replaces two Git subprocesses per file with one size query per
batch and one content query per bounded batch. No shell or path-based reads.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_MAX_BATCH_BYTES = 16 * 1024 * 1024
_MAX_BATCH_OBJECTS = 512
_OBJECT = re.compile(rb'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')


class GitObjectError(ValueError):
    pass


def _git(root: Path, *args: str, input_bytes: bytes) -> bytes:
    try:
        proc = subprocess.run(
            ('git', *args), cwd=root, input=input_bytes,
            capture_output=True, check=False, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitObjectError('Git object batch operation failed') from exc
    if proc.returncode:
        raise GitObjectError('Git object batch operation failed')
    return proc.stdout


def _chunks(items: list[str], amount: int):
    for offset in range(0, len(items), amount):
        yield items[offset:offset + amount]


def blob_sizes(root: Path, object_ids: list[str]) -> dict[str, int]:
    ordered = list(dict.fromkeys(object_ids))
    results: dict[str, int] = {}
    for batch in _chunks(ordered, _MAX_BATCH_OBJECTS):
        if any(not _OBJECT.fullmatch(x.encode('ascii')) for x in batch):
            raise GitObjectError('Invalid Git object identity')
        response = _git(
            root, 'cat-file',
            '--batch-check=%(objectname) %(objecttype) %(objectsize)',
            input_bytes=('\n'.join(batch) + '\n').encode('ascii'),
        )
        lines = response.splitlines()
        if len(lines) != len(batch):
            raise GitObjectError('Unexpected Git object metadata length')
        for oid, line in zip(batch, lines):
            parts = line.split(b' ')
            if len(parts) != 3 or parts[0] != oid.encode() or parts[1] != b'blob':
                raise GitObjectError('Git object type or identity mismatch')
            try:
                size = int(parts[2])
            except ValueError as exc:
                raise GitObjectError('Malformed Git object size') from exc
            if size < 0:
                raise GitObjectError('Negative Git object size')
            results[oid] = size
    return results


def _batch_objects(ordered: list[str], sizes: dict[str, int]):
    group: list[str] = []
    group_bytes = 0
    for oid in ordered:
        size = sizes[oid]
        if group and (len(group) >= _MAX_BATCH_OBJECTS or
                      group_bytes + size > _MAX_BATCH_BYTES):
            yield group
            group, group_bytes = [], 0
        group.append(oid)
        group_bytes += size
    if group:
        yield group


def blob_contents(root: Path, object_ids: list[str],
                  sizes: dict[str, int]) -> dict[str, bytes]:
    ordered = list(dict.fromkeys(object_ids))
    results: dict[str, bytes] = {}
    for batch in _batch_objects(ordered, sizes):
        raw = _git(
            root, 'cat-file', '--batch',
            input_bytes=('\n'.join(batch) + '\n').encode('ascii'),
        )
        offset = 0
        for oid in batch:
            end = raw.find(b'\n', offset)
            if end < 0:
                raise GitObjectError('Missing Git object header')
            header = raw[offset:end].split(b' ')
            if (
                len(header) != 3 or
                header[0] != oid.encode('ascii') or
                header[1] != b'blob' or
                header[2] != str(sizes[oid]).encode('ascii')
            ):
                raise GitObjectError('Unexpected Git object header')
            start = end + 1
            stop = start + sizes[oid]
            if stop >= len(raw) or raw[stop:stop + 1] != b'\n':
                raise GitObjectError('Truncated Git object content')
            results[oid] = raw[start:stop]
            offset = stop + 1
        if offset != len(raw):
            raise GitObjectError('Unexpected bytes after Git object batch')
    return results
