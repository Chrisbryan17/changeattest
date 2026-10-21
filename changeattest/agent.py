"""Agent change-scope contract: deterministic repository diff authorization.

This verifies changed paths and optionally a trusted signed evidence bundle.
It does not establish agent identity, intent, correctness, or test execution
unless verified evidence from an independently controlled signer is required.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from changeattest.attestation import verify_evidence

_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')


@dataclass(frozen=True)
class Contract:
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_checks: tuple[str, ...]
    max_changed_files: int


def read_contract(filename: str) -> Contract:
    raw = Path(filename).read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError('Agent contract too large')
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) != {
        'version', 'allowed_paths', 'forbidden_paths', 'required_checks',
        'max_changed_files',
    } or type(obj['version']) is not int or obj['version'] != 1:
        raise ValueError('Invalid agent contract format')
    for field in ('allowed_paths', 'forbidden_paths', 'required_checks'):
        arr = obj[field]
        if type(arr) is not list or not all(
            type(s) is str and 0 < len(s) <= 512 for s in arr
        ) or len(arr) != len(set(arr)):
            raise ValueError(f'Invalid {field}')
    n = obj['max_changed_files']
    if type(n) is not int or not 1 <= n <= 100000:
        raise ValueError('Invalid maximum number of changed files')
    if not obj['allowed_paths']:
        raise ValueError('At least one allowed path pattern is required')
    return Contract(tuple(obj['allowed_paths']),
                    tuple(obj['forbidden_paths']),
                    tuple(obj['required_checks']), n)


def verify_agent_change(
    root: Path, contract: Contract, base: str, head: str,
    attestation: dict[str, Any] | None = None,
    trusted_public_key: bytes | None = None,
) -> dict[str, Any]:
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(head):
        raise ValueError('Base and head must be full Git commit SHAs')
    try:
        proc = subprocess.run(
            ('git', 'diff', '--no-renames', '--name-only', '-z',
             '--diff-filter=ACDMRTUXB', base, head, '--'),
            cwd=root, capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Unable to inspect Git change') from exc
    if proc.returncode:
        raise ValueError('Git diff failed')
    paths = sorted(set(x.decode('utf-8', errors='surrogateescape')
                       for x in proc.stdout.split(b'\0') if x))
    violations = []
    if not paths:
        violations.append('no-changes')
    if len(paths) > contract.max_changed_files:
        violations.append('change-count-exceeded')
    for path in paths:
        if any(fnmatch.fnmatchcase(path, p) for p in contract.forbidden_paths):
            violations.append(f'forbidden-path:{path}')
        elif not any(fnmatch.fnmatchcase(path, p) for p in contract.allowed_paths):
            violations.append(f'out-of-scope:{path}')

    evidence_status = 'not-required'
    if contract.required_checks:
        evidence_status = 'unverified'
        if (attestation is not None and trusted_public_key is not None and
                verify_evidence(attestation, trusted_public_key,
                                expected_head=head)):
            results = attestation['evidence'].get('checks', [])
            passed = {r.get('id') for r in results
                      if isinstance(r, dict) and r.get('status') == 'passed'
                      and r.get('exit_code') == 0}
            if set(contract.required_checks).issubset(passed) and (
                attestation['evidence'].get('status') == 'passed'
            ):
                evidence_status = 'verified'
        if evidence_status != 'verified':
            violations.append('missing-trusted-test-evidence')
    return {
        'schema': 'changeattest.agent.v1',
        'base': base, 'head': head, 'changed_files': paths,
        'evidence_status': evidence_status,
        'violations': sorted(set(violations)),
        'status': 'passed' if not violations else 'blocked',
    }
