"""Validate GitHub synthetic merge commit ancestry without checkout.

Only Git commit object metadata is read. The caller must separately
authenticate the event-provided base/head SHA identities; this module
does not attest the remote who supplied the object.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from changeattest.engine import canonical

_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')
_MAX_COMMIT_MESSAGE_BYTES = 4 * 1024 * 1024


class MergeIdentityError(ValueError):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        response = subprocess.run(
            ('git', *args), cwd=root, capture_output=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MergeIdentityError('Could not read Git commit metadata') from exc
    if response.returncode:
        raise MergeIdentityError('Could not read Git commit metadata')
    return response.stdout


def verify_merge_identity(
    root: Path, base: str, head: str, merge: str,
) -> dict[str, Any]:
    """Compare exact Git object's ordered parents to event-provided SHA IDs."""
    if not all(
        type(obj) is str and _SHA.fullmatch(obj)
        for obj in (base, head, merge)
    ) or len({len(base), len(head), len(merge)}) != 1:
        raise MergeIdentityError('Expected complete SHA IDs of equal algorithm length')
    if merge in (base, head):
        raise MergeIdentityError('Merge commit must differ from both parents')
    root = root.resolve()
    kind = _git(root, 'cat-file', '-t', merge).strip()
    if kind != b'commit':
        raise MergeIdentityError('Merge object must be a commit')
    try:
        length = int(_git(root, 'cat-file', '-s', merge).strip())
    except ValueError as exc:
        raise MergeIdentityError('Invalid Git commit object size') from exc
    if length < 0 or length > _MAX_COMMIT_MESSAGE_BYTES:
        raise MergeIdentityError('Commit metadata exceeds size limit')
    raw = _git(root, 'cat-file', '-p', merge)
    if len(raw) != length:
        raise MergeIdentityError('Inconsistent Git commit object size')
    header = raw.split(b'\n\n', 1)[0].split(b'\n')
    parents = []
    for line in header:
        if line.startswith(b'parent '):
            oid = line[len(b'parent '):]
            try:
                parsed = oid.decode('ascii')
            except UnicodeDecodeError as exc:
                raise MergeIdentityError('Malformed Git parent identity') from exc
            if not _SHA.fullmatch(parsed):
                raise MergeIdentityError('Malformed Git parent identity')
            parents.append(parsed)
    status = 'verified' if parents == [base, head] else 'rejected'
    reasons = []
    if len(parents) != 2:
        reasons.append('merge-parent-count-mismatch')
    elif parents != [base, head]:
        reasons.append('merge-parent-identity-mismatch')
    result: dict[str, Any] = {
        'schema': 'changeattest.merge-identity.v1',
        'base': base, 'head': head, 'merge': merge,
        'parents': parents,
        'status': status, 'reasons': reasons,
    }
    result['report_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    return result
