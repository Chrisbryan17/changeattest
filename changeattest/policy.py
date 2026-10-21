"""Strict local policy semantics for ChangeAttest's CI gate.

A valid report checksum is NOT proof of provenance. Only a runner which
executes the checks itself, under a separately protected policy, can enforce
this verdict. Rules intentionally cannot execute custom programs.
"""
from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from changeattest.engine import ConfigurationError
from changeattest.engine import DEFAULT_CHECKS
from changeattest.engine import SCHEMA
from changeattest.engine import canonical

_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_GIT_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')


@dataclass(frozen=True)
class Policy:
    scope: str
    required_checks: tuple[str, ...]
    allow_skipped_checks: frozenset[str]
    min_files: int
    include_prefixes: tuple[str, ...]
    timeout_seconds: int
    max_file_bytes: int
    sha256: str

    def runner_config(self) -> dict[str, Any]:
        # No .changeattest.toml from the target checkout is loaded in gate
        # mode: this policy alone dictates the checks and execution bounds.
        return {
            'checks': self.required_checks,
            'timeout_seconds': self.timeout_seconds,
            'max_file_bytes': self.max_file_bytes,
            'include_prefixes': self.include_prefixes,
        }


def load_policy(path: Path) -> Policy:
    try:
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode('utf-8'))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError('Unable to read a valid policy TOML file') from exc

    if set(data) != {'policy'} or not isinstance(data['policy'], dict):
        raise ConfigurationError('A policy file must contain only [policy]')
    cfg = data['policy']
    allowed = {
        'version', 'scope', 'required_checks', 'allow_skipped_checks',
        'min_files', 'timeout_seconds', 'max_file_bytes',
        'include_prefixes',
    }
    if set(cfg) - allowed or type(cfg.get('version')) is not int or cfg['version'] != 1:
        raise ConfigurationError('Unsupported policy version or property')
    scope = cfg.get('scope', 'tracked')
    if scope not in ('tracked', 'staged'):
        raise ConfigurationError('Policy scope must be tracked or staged')

    def names(key: str, fallback: list[str]) -> tuple[str, ...]:
        values = cfg.get(key, fallback)
        if (
            type(values) is not list or
            any(type(x) is not str or x not in DEFAULT_CHECKS for x in values) or
            len(set(values)) != len(values)
        ):
            raise ConfigurationError(f'Unknown or duplicate {key} entries')
        return tuple(values)

    required = names('required_checks', list(DEFAULT_CHECKS))
    skipped = names('allow_skipped_checks', [])
    if not required or not set(skipped).issubset(required):
        raise ConfigurationError('Required checks cannot be empty, and skips must be a subset')
    prefixes = cfg.get('include_prefixes', [])
    if (
        type(prefixes) is not list or
        len(set(x for x in prefixes if type(x) is str)) != len(prefixes) or
        any(type(x) is not str or not re.fullmatch(r'[A-Za-z0-9_.\-/]+/', x)
            or x.startswith(('/', './', '../')) or '/./' in x or '/../' in x
            for x in prefixes)
    ):
        raise ConfigurationError('include_prefixes must be distinct safe directory prefixes')
    count = cfg.get('min_files', 1)
    timeout = cfg.get('timeout_seconds', 30)
    max_bytes = cfg.get('max_file_bytes', 8 * 1024 * 1024)
    if type(count) is not int or not 1 <= count <= 1_000_000:
        raise ConfigurationError('min_files must be an integer in 1..1000000')
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ConfigurationError('timeout_seconds must be an integer in 1..300')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 256 * 1024 * 1024:
        raise ConfigurationError('max_file_bytes must be an integer in 1..256 MiB')
    # Canonical registry order: policy key order cannot change execution order.
    checks = tuple(n for n in DEFAULT_CHECKS if n in required)
    return Policy(
        scope=scope,
        required_checks=checks,
        allow_skipped_checks=frozenset(skipped),
        min_files=count,
        include_prefixes=tuple(sorted(prefixes)),
        timeout_seconds=timeout,
        max_file_bytes=max_bytes,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def evaluate(report: dict[str, Any], policy: Policy,
             expected_head: str | None = None) -> tuple[str, ...]:
    """Return sorted failure codes, never a trusted/non-trusted assertion."""
    errors: set[str] = set()
    if not isinstance(report, dict):
        return ('malformed-report',)
    checksum = report.get('report_sha256')
    unsealed = dict(report)
    unsealed.pop('report_sha256', None)
    try:
        digest_matches = (
            type(checksum) is str and _SHA256.fullmatch(checksum) is not None
            and hashlib.sha256(canonical(unsealed)).hexdigest() == checksum
        )
    except (TypeError, ValueError, OverflowError):
        digest_matches = False
    if not digest_matches:
        errors.add('invalid-report-checksum')

    if set(report) != {
        'schema', 'scope', 'head', 'file_count', 'files', 'problems',
        'checks', 'status', 'report_sha256', 'include_prefixes',
    }:
        errors.add('unexpected-report-shape')
    if report.get('schema') != SCHEMA or report.get('scope') != policy.scope:
        errors.add('schema-or-scope-mismatch')
    if report.get('include_prefixes') != list(policy.include_prefixes):
        errors.add('selection-mismatch')
    if expected_head is not None:
        if not _GIT_SHA.fullmatch(expected_head):
            raise ConfigurationError('Expected head must be a full Git SHA')
        if report.get('head') != expected_head:
            errors.add('git-head-mismatch')
    head = report.get('head')
    if head is not None and (type(head) is not str or not _GIT_SHA.fullmatch(head)):
        errors.add('invalid-git-head')

    count = report.get('file_count')
    files = report.get('files')
    problems = report.get('problems')
    if type(count) is not int or count < policy.min_files:
        errors.add('insufficient-files')
    if type(files) is not list or type(problems) is not list:
        errors.add('invalid-files')
    else:
        names: set[str] = set()
        for f in files:
            if not isinstance(f, dict) or set(f) != {'path', 'sha256'}:
                errors.add('invalid-files')
                continue
            name, digest = f['path'], f['sha256']
            if (
                type(name) is not str or not name or name in names or
                type(digest) is not str or not _SHA256.fullmatch(digest)
            ):
                errors.add('invalid-files')
            else:
                names.add(name)
        if problems:
            errors.add('incomplete-file-verification')
        if type(count) is int and count != len(files) + len(problems):
            errors.add('file-count-mismatch')
        if problems and any(
            not isinstance(p, dict) or set(p) != {'path', 'reason'} or
            type(p['path']) is not str or type(p['reason']) is not str
            for p in problems
        ):
            errors.add('invalid-files')

    if report.get('status') != 'passed':
        errors.add('report-not-passed')
    results = report.get('checks')
    if type(results) is not list:
        errors.add('invalid-checks')
    else:
        seen: set[str] = set()
        for result in results:
            if not isinstance(result, dict) or set(result) != {
                'id', 'status', 'file_count', 'exit_code', 'output_sha256',
            }:
                errors.add('invalid-checks')
                continue
            name = result['id']
            if type(name) is not str or name in seen or name not in policy.required_checks:
                errors.add('unexpected-or-duplicate-check')
                continue
            seen.add(name)
            status = result['status']
            selected = result['file_count']
            code = result['exit_code']
            output = result['output_sha256']
            if (type(selected) is not int or selected < 0 or
                    type(count) is not int or selected > count):
                errors.add('invalid-checks')
                continue
            if status == 'passed':
                if code != 0 or selected == 0:
                    errors.add('inconsistent-check-result')
            elif status == 'skipped':
                if name not in policy.allow_skipped_checks:
                    errors.add('required-check-skipped')
                if code is not None or selected != 0:
                    errors.add('inconsistent-check-result')
            else:
                errors.add('required-check-not-passed')
            if output is not None and (
                type(output) is not str or not _SHA256.fullmatch(output)
            ):
                errors.add('invalid-checks')
        if seen != set(policy.required_checks):
            errors.add('missing-required-check')
    return tuple(sorted(errors))
