"""Immutable Git-commit snapshot execution for the CI policy gate.

Reads bytes by object identity from HEAD; source files are never opened from
the mutable checkout. The isolated temporary tree contains no executable
checkout-supplied tooling. Only built-in audited validators are invoked.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from changeattest.engine import CHECKS
from changeattest.engine import ConfigurationError
from changeattest.engine import SCHEMA
from changeattest.engine import _run_check
from changeattest.engine import canonical
from changeattest.git_batch import GitObjectError
from changeattest.git_batch import blob_contents
from changeattest.git_batch import blob_sizes

_OBJECT = re.compile(rb'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        done = subprocess.run(
            ('git', *args), cwd=root, input=input_bytes, capture_output=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError('Unable to read Git snapshot') from exc
    if done.returncode:
        raise ConfigurationError('Unable to read Git snapshot')
    return done.stdout


def scan_commit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Scan exact Git HEAD tree bytes, with no live working-tree reads."""
    root = root.resolve()
    commit = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    tree = _git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD')
    prefix = tuple(config.get('include_prefixes', ()))
    files: list[dict[str, str]] = []
    problems: list[dict[str, str]] = []
    entries: list[tuple[str, str, str]] = []
    for line in tree.split(b'\0'):
        if not line:
            continue
        try:
            meta, raw_path = line.split(b'\t', 1)
            mode, kind, oid = meta.split()
        except ValueError as exc:
            raise ConfigurationError('Malformed Git tree entry') from exc
        if not _OBJECT.fullmatch(oid):
            raise ConfigurationError('Malformed Git object identity')
        path = os.fsdecode(raw_path)
        if prefix and not any(path.startswith(p) for p in prefix):
            continue
        entries.append((path, mode.decode('ascii'), oid.decode('ascii')))
    entries.sort(key=lambda a: a[0])

    # Reject unsafe paths and non-regular Git entries before invoking the
    # blob batch reader. A repeated blob OID is read once, then reused.
    candidates: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix='changeattest-snapshot-') as tmp:
        snap = Path(tmp).resolve()
        for name, mode, oid in entries:
            parts = Path(name).parts
            if (
                not parts or name.startswith(('/', '\\')) or
                any(x in ('.', '..') for x in parts) or
                not (snap / name).resolve().is_relative_to(snap)
            ):
                problems.append({'path': name, 'reason': 'unsafe-git-path'})
            elif mode not in ('100644', '100755'):
                problems.append({'path': name, 'reason': 'unsupported-git-object-type'})
            else:
                candidates.append((name, oid))

        try:
            sizes = blob_sizes(root, [oid for _, oid in candidates])
            selected = [(name, oid) for name, oid in candidates
                        if sizes[oid] <= config['max_file_bytes']]
            data = blob_contents(root, [oid for _, oid in selected], sizes)
        except (GitObjectError, KeyError) as exc:
            raise ConfigurationError('Git snapshot batch verification failed') from exc

        for name, oid in candidates:
            if sizes[oid] > config['max_file_bytes']:
                problems.append({'path': name, 'reason': 'file-size-limit'})

        allowed: list[str] = []
        for name, oid in selected:
            payload = data[oid]
            out = snap / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            allowed.append(name)
            files.append({
                'path': name, 'sha256': hashlib.sha256(payload).hexdigest(),
            })

        # Some legacy file checkers query Git metadata even when checking only
        # ordinary file content; an empty ephemeral repository satisfies them.
        _git(snap, 'init', '-q')
        results = []
        for check in CHECKS:
            if check.name not in config['checks']:
                continue
            selected = [
                name for name in allowed
                if (not check.extensions or Path(name).suffix.lower() in check.extensions)
                and (not check.text_only or b'\0' not in (snap / name).read_bytes()[:8192])
            ]
            results.append(_run_check(check, selected, snap, config['timeout_seconds']))

    problems.sort(key=lambda x: (x['path'], x['reason']))
    statuses = {x['status'] for x in results}
    status = (
        'error' if problems or 'error' in statuses else
        'failed' if 'failed' in statuses else
        'no-files' if not files else
        'passed'
    )
    report: dict[str, Any] = {
        'schema': SCHEMA, 'scope': 'tracked', 'head': commit,
        'file_count': len(entries), 'files': files, 'problems': problems,
        'checks': results, 'status': status, 'include_prefixes': list(prefix),
    }
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    return report
