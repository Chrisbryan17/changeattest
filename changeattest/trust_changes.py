"""Deterministic, immutable security-sensitive change classifier.

The decision is advisory unless --block-sensitive is explicitly used by a
trusted workflow. Code running from a PR-controlled checkout is NOT by itself
an independent reviewer or an enforceable branch protection rule.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from changeattest.engine import canonical

_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')
_MAX_CHANGED_PATHS = 50000

_CRITICAL_PREFIXES = (
    '.github/workflows/',
    '.github/actions/',
)
_CRITICAL_FILES = frozenset((
    '.github/changeattest-policy.toml',
    '.github/changeattest-agent-contract.json',
    '.github/CODEOWNERS',
))
_HIGH_PREFIXES = ('changeattest/',)
_HIGH_FILES = frozenset((
    'setup.cfg', 'setup.py', 'pyproject.toml', 'requirements.txt',
    'requirements-dev.txt', 'SECURITY.md', 'LICENSE',
    'tests/changeattest_base_owned_workflow_test.py',
    'tests/changeattest_policy_test.py',
    'tests/changeattest_release_workflow_test.py',
))


class SensitiveChangeError(ValueError):
    pass


def classify_path(path: str) -> tuple[str, str] | None:
    if any(path.startswith(p) for p in _CRITICAL_PREFIXES):
        return 'critical', 'ci-workflow-or-action'
    if path in _CRITICAL_FILES:
        return 'critical', 'policy-or-review-governance'
    if path in _HIGH_FILES or path.startswith('requirements-'):
        return 'high', 'package-security-or-policy-tests'
    if any(path.startswith(p) for p in _HIGH_PREFIXES):
        return 'high', 'verification-implementation'
    return None


def classify_commit_change(root: Path, base: str, head: str) -> dict[str, Any]:
    """Inspect committed changes only, with no checkout or source execution."""
    if not (
        isinstance(base, str) and isinstance(head, str)
        and _SHA.fullmatch(base) and _SHA.fullmatch(head)
    ):
        raise SensitiveChangeError('Both revisions must be full Git object identities')
    root = root.resolve()
    try:
        response = subprocess.run(
            ('git', 'diff', '--no-renames', '--name-only', '-z',
             '--diff-filter=ACDMRTUXB', base, head, '--'),
            cwd=root, capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SensitiveChangeError('Unable to inspect Git commit change') from exc
    if response.returncode:
        raise SensitiveChangeError('Unable to inspect Git commit change')

    names = sorted(set(os.fsdecode(raw)
                       for raw in response.stdout.split(b'\0') if raw))
    if len(names) > _MAX_CHANGED_PATHS:
        raise SensitiveChangeError('Change exceeds security review path limit')
    findings = []
    for name in names:
        kind = classify_path(name)
        if kind is not None:
            severity, reason = kind
            findings.append({
                'path': name, 'severity': severity, 'reason': reason,
            })
    counts = {
        level: sum(item['severity'] == level for item in findings)
        for level in ('critical', 'high')
    }
    status = ('review-required' if findings else
              'no-sensitive-changes' if names else 'no-changes')
    result: dict[str, Any] = {
        'schema': 'changeattest.sensitive-change.v1',
        'base': base, 'head': head, 'status': status,
        'changed_paths': names, 'findings': findings,
        'counts': counts,
        'enforcement_note': (
            'Only a separately reviewed workflow and independently '
            'enforced GitHub rules can make a required approval binding.'
        ),
    }
    result['report_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    return result
