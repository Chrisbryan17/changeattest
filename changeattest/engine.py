"""Strict built-in check runner with deterministic, unsigned evidence records.

The report describes *observed execution*; its SHA-256 is an integrity checksum,
not a cryptographic signature, trusted attestation, or guarantee of completeness.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = 'changeattest.report.v1'


@dataclass(frozen=True)
class Check:
    name: str
    module: str
    extensions: tuple[str, ...] = ()
    text_only: bool = False
    args: tuple[str, ...] = ()


# Only explicitly vetted, non-mutating modules. Project config cannot supply
# arbitrary executable names, Python imports, shell snippets or arguments.
CHECKS: tuple[Check, ...] = (
    Check('json', 'pre_commit_hooks.check_json', ('.json',)),
    Check('toml', 'pre_commit_hooks.check_toml', ('.toml',)),
    Check('yaml', 'pre_commit_hooks.check_yaml', ('.yaml', '.yml')),
    Check('merge-conflict', 'pre_commit_hooks.check_merge_conflict',
          text_only=True, args=('--assume-in-merge',)),
    Check('private-key', 'pre_commit_hooks.detect_private_key'),
    Check('openpgp-secret-key', 'pre_commit_hooks.detect_openpgp_secret_key'),
)
DEFAULT_CHECKS = tuple(c.name for c in CHECKS)
DEFAULT_LIMIT = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 30


class ConfigurationError(ValueError):
    pass


def canonical(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def load_config(root: Path, explicit: str | None) -> dict[str, Any]:
    path = root / (explicit or '.changeattest.toml')
    if not path.is_file():
        if explicit is not None:
            raise ConfigurationError(f'Configuration does not exist: {explicit}')
        return {
            'checks': DEFAULT_CHECKS,
            'timeout_seconds': DEFAULT_TIMEOUT,
            'max_file_bytes': DEFAULT_LIMIT,
        }

    # A project-controlled file can only configure existing built-in checks.
    try:
        with path.open('rb') as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError('Unable to read valid TOML configuration') from exc
    if set(data) != {'changeattest'} or not isinstance(data['changeattest'], dict):
        raise ConfigurationError('Expected a [changeattest] TOML section')
    conf = data['changeattest']
    allowed = {'version', 'checks', 'timeout_seconds', 'max_file_bytes'}
    if set(conf) - allowed or conf.get('version') != 1:
        raise ConfigurationError('Unsupported ChangeAttest configuration version or key')

    checks = conf.get('checks', list(DEFAULT_CHECKS))
    if (not isinstance(checks, list) or any(not isinstance(x, str) for x in checks)
            or len(set(checks)) != len(checks)
            or any(x not in DEFAULT_CHECKS for x in checks)):
        raise ConfigurationError('Unknown or duplicate check identifier')
    timeout = conf.get('timeout_seconds', DEFAULT_TIMEOUT)
    limit = conf.get('max_file_bytes', DEFAULT_LIMIT)
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ConfigurationError('timeout_seconds must be an integer from 1 to 300')
    if type(limit) is not int or not 1 <= limit <= 256 * 1024 * 1024:
        raise ConfigurationError('max_file_bytes must be a positive integer <= 256 MiB')
    # Canonical registry order, independent of config array ordering.
    return {
        'checks': tuple(x for x in DEFAULT_CHECKS if x in checks),
        'timeout_seconds': timeout,
        'max_file_bytes': limit,
    }


def _git(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ('git', *args), cwd=root, capture_output=True, check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError('Git command could not run') from exc
    if result.returncode != 0:
        raise ConfigurationError('Git repository operation failed')
    return result.stdout


def _paths(raw: bytes) -> list[str]:
    # Git -z paths are platform-native filesystem bytes, not necessarily UTF-8.
    return sorted(set(os.fsdecode(s) for s in raw.split(b'\0') if s))


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(128 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _binary(path: Path) -> bool:
    with path.open('rb') as f:
        return b'\0' in f.read(8192)


def _run_check(
    check: Check, files: list[str], root: Path, timeout: int,
) -> dict[str, Any]:
    if not files:
        return {'id': check.name, 'status': 'skipped', 'file_count': 0,
                'exit_code': None, 'output_sha256': None}
    output = b''
    try:
        result = subprocess.run(
            (sys.executable, '-I', '-m', check.module, *check.args, *files),
            cwd=root, capture_output=True, timeout=timeout, check=False,
        )
        output = result.stdout + b'\0' + result.stderr
        if result.returncode == 0:
            status = 'passed'
        elif result.returncode == 1 and b'Traceback (most recent call last)' not in result.stderr:
            status = 'failed'
        else:
            status = 'error'
        code = result.returncode
    except subprocess.TimeoutExpired:
        status, code = 'error', None
    except OSError:
        status, code = 'error', None
    return {
        'id': check.name, 'status': status, 'file_count': len(files),
        'exit_code': code,
        # We deliberately do NOT persist command output: it may contain secrets.
        'output_sha256': hashlib.sha256(output).hexdigest() if output else None,
    }


def scan(root: Path, scope: str, config: dict[str, Any]) -> dict[str, Any]:
    root = Path(os.path.realpath(root))
    real_root = Path(os.fsdecode(_git(root, 'rev-parse', '--show-toplevel').strip()))
    if not real_root.is_dir():
        raise ConfigurationError('Git root is unavailable')

    if scope == 'staged':
        paths = _paths(_git(real_root, 'diff', '--cached', '--name-only', '-z',
                            '--diff-filter=ACMR', '--'))
        changed = set(_paths(_git(real_root, 'diff', '--name-only', '-z', '--')))
        # Do not claim to validate *staged* content using different worktree bytes.
        mismatch = sorted(set(paths) & changed)
    elif scope == 'tracked':
        paths = _paths(_git(real_root, 'ls-files', '--cached', '-z', '--'))
        mismatch = []
    else:
        raise ConfigurationError('Invalid scan scope')

    head = None
    try:
        head = _git(real_root, 'rev-parse', '--verify', 'HEAD').decode('ascii').strip()
    except ConfigurationError:
        pass

    problems: list[dict[str, str]] = [
        {'path': p, 'reason': 'staged-worktree-mismatch'} for p in mismatch
    ]
    usable: list[tuple[str, Path, int]] = []
    for name in paths:
        p = real_root / name
        try:
            # Disallow symlink traversal / escaping the repository and
            # avoid trusting a mutable external target.
            if p.is_symlink() or not p.resolve().is_relative_to(real_root):
                raise ValueError('unsafe-symlink-or-path')
            if not p.is_file():
                raise ValueError('missing-or-nonregular-file')
            size = p.stat().st_size
            if size > config['max_file_bytes']:
                raise ValueError('file-size-limit')
            usable.append((name, p, size))
        except (OSError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else 'unreadable-file'
            problems.append({'path': name, 'reason': reason})
    problems.sort(key=lambda e: (e['path'], e['reason']))

    scanned = [{'path': name, 'sha256': _hash_file(p)}
               for name, p, _ in usable if name not in mismatch]
    if mismatch:
        # Fail closed: no check is allowed to certify a staged snapshot whose
        # data diverges from the working tree.
        usable = []

    results: list[dict[str, Any]] = []
    for check in CHECKS:
        if check.name not in config['checks']:
            continue
        selected: list[str] = []
        for name, path, _ in usable:
            if check.extensions and path.suffix.lower() not in check.extensions:
                continue
            if check.text_only and _binary(path):
                continue
            selected.append(name)
        results.append(_run_check(check, selected, real_root, config['timeout_seconds']))

    statuses = {r['status'] for r in results}
    if problems or 'error' in statuses:
        overall = 'error'
    elif 'failed' in statuses:
        overall = 'failed'
    elif not scanned:
        overall = 'no-files'
    else:
        overall = 'passed'
    report: dict[str, Any] = {
        'schema': SCHEMA,
        'scope': scope,
        'head': head,
        'file_count': len(paths),
        'files': scanned,
        'problems': problems,
        'checks': results,
        'status': overall,
    }
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    return report
