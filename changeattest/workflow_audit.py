"""Read-only, immutable GitHub Actions workflow security heuristics.

Not a proof of CI integrity: the scanner highlights common dangerous
shapes, particularly privileged PR-context execution and untrusted inputs.
A scanner running in PR-controlled CI is not itself a trusted merge gate.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from changeattest.engine import canonical
from changeattest.git_batch import GitObjectError
from changeattest.git_batch import blob_contents
from changeattest.git_batch import blob_sizes

_WORKFLOW = re.compile(r'\A\.github/workflows/[^/]+\.(yml|yaml)\Z')
_ACTION_PIN = re.compile(r'@[0-9a-f]{40}\Z')
_BAD_EXPR = re.compile(
    r'\$\{\{\s*(?:github\.head_ref|github\.event\.(?:'
    r'pull_request\.(?:title|body|head\.ref)|'
    r'issue\.(?:title|body)|comment\.body|'
    r'pull_request_review\.body))\b',
    re.IGNORECASE,
)
_HEAD_REF = re.compile(
    r'github\.(?:head_ref|event\.pull_request\.head\.sha|'
    r'event\.pull_request\.head\.ref)|refs/pull/',
    re.IGNORECASE,
)
_SHELL_PIPE = re.compile(r'\b(?:curl|wget)\b[^;\n|]*\|\s*(?:sh|bash)\b')
_MAX_WORKFLOW_BYTES = 1024 * 1024
_MAX_WORKFLOWS = 150


class WorkflowAuditError(ValueError):
    pass


def _events(obj: Any) -> set[str]:
    if isinstance(obj, str):
        return {obj}
    if isinstance(obj, list):
        return {item for item in obj if isinstance(item, str)}
    if isinstance(obj, dict):
        return {name for name in obj if isinstance(name, str)}
    return set()


def _writes(perms: Any) -> bool:
    if perms == 'write-all':
        return True
    return isinstance(perms, dict) and any(
        value == 'write' for value in perms.values()
    )


def inspect_workflow(path: str, data: bytes) -> list[dict[str, str]]:
    """Return stable rule findings without executing any workflow content."""
    found: list[dict[str, str]] = []

    def add(rule: str, severity: str, job: str = '', detail: str = '') -> None:
        found.append({
            'path': path, 'rule': rule, 'severity': severity,
            'job': job, 'detail': detail,
        })

    if len(data) > _MAX_WORKFLOW_BYTES:
        add('oversized-workflow', 'high')
        return found
    try:
        parsed = YAML(typ='safe').load(data)
    except Exception:
        add('invalid-workflow-yaml', 'high')
        return found
    if not isinstance(parsed, dict):
        add('invalid-workflow-shape', 'high')
        return found

    events = _events(parsed.get('on', parsed.get(True)))
    privileged = bool(events & {'pull_request_target', 'workflow_run'})
    pr_trigger = privileged or 'pull_request' in events
    if privileged:
        add('privileged-pr-trigger', 'info', detail=','.join(sorted(events)))

    if pr_trigger and _writes(parsed.get('permissions')):
        add('write-token-for-pr-event', 'high')
    if pr_trigger and parsed.get('permissions') is None:
        add('unspecified-workflow-token-permissions', 'medium')

    jobs = parsed.get('jobs')
    if not isinstance(jobs, dict):
        add('missing-jobs', 'high')
        return found
    for job, spec in sorted(jobs.items(), key=lambda kv: str(kv[0])):
        if not isinstance(spec, dict):
            add('invalid-job-shape', 'high', str(job))
            continue
        jobname = str(job)
        if pr_trigger and _writes(spec.get('permissions')):
            add('write-token-for-pr-event', 'high', jobname)
        steps = spec.get('steps', [])
        if not isinstance(steps, list):
            add('invalid-step-list', 'high', jobname)
            continue
        checkout_untrusted = False
        for step in steps:
            if not isinstance(step, dict):
                add('invalid-step-shape', 'medium', jobname)
                continue
            uses = step.get('uses', '')
            if not isinstance(uses, str):
                uses = ''
            with_args = step.get('with')
            if not isinstance(with_args, dict):
                with_args = {}
            if uses and not uses.startswith('./') and not uses.startswith('docker://'):
                if not _ACTION_PIN.search(uses):
                    add('unpinned-action-reference', 'medium', jobname, uses[:180])
            if uses.startswith('actions/checkout@'):
                ref = str(with_args.get('ref', ''))
                if (
                    privileged and (
                        _HEAD_REF.search(ref) or
                        with_args.get('allow-unsafe-pr-checkout') in (True, 'true')
                    )
                ):
                    checkout_untrusted = True
                    add('privileged-checkout-of-pr-code', 'high', jobname)
                if pr_trigger and with_args.get('persist-credentials') is not False:
                    add('checkout-keeps-credentials', 'medium', jobname)
            run = step.get('run', '')
            if isinstance(run, str) and run:
                if pr_trigger and _BAD_EXPR.search(run):
                    add('untrusted-expression-in-shell', 'high', jobname)
                if privileged and checkout_untrusted:
                    # A shell step following an unsafe checkout can execute
                    # scripts/config/plugins from the untrusted working tree.
                    add('privileged-run-after-pr-checkout', 'critical', jobname)
                if _SHELL_PIPE.search(run):
                    add('download-piped-to-shell', 'medium', jobname)
    return sorted(found, key=lambda x: (
        x['path'], x['job'], x['rule'], x['severity'], x['detail'],
    ))


def _git(root: Path, *args: str) -> bytes:
    try:
        p = subprocess.run(('git', *args), cwd=root, capture_output=True,
                           check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkflowAuditError('Unable to inspect Git commit') from exc
    if p.returncode:
        raise WorkflowAuditError('Unable to inspect Git commit')
    return p.stdout


def audit_commit(root: Path) -> dict[str, Any]:
    """Inspect workflow blobs in HEAD, not uncommitted workflow edits."""
    root = root.resolve()
    head = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}').strip().decode()
    raw = _git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD', '.github/workflows/')
    ids: dict[str, str] = {}
    findings: list[dict[str, str]] = []
    for line in raw.split(b'\0'):
        if not line:
            continue
        try:
            meta, raw_name = line.split(b'\t', 1)
            mode, kind, oid = meta.split()
        except ValueError as exc:
            raise WorkflowAuditError('Malformed Git workflow tree') from exc
        name = os.fsdecode(raw_name)
        if not _WORKFLOW.fullmatch(name):
            continue
        if mode not in (b'100644', b'100755') or kind != b'blob':
            findings.append({
                'path': name, 'rule': 'nonregular-workflow',
                'severity': 'high', 'job': '', 'detail': '',
            })
            continue
        ids[name] = oid.decode('ascii')
        if len(ids) > _MAX_WORKFLOWS:
            raise WorkflowAuditError('Workflow count exceeds scan limit')
    try:
        sizes = blob_sizes(root, list(ids.values()))
        eligible = {path: oid for path, oid in ids.items()
                    if sizes[oid] <= _MAX_WORKFLOW_BYTES}
        content = blob_contents(root, list(eligible.values()), sizes)
    except (GitObjectError, KeyError) as exc:
        raise WorkflowAuditError('Could not verify Git workflow blobs') from exc
    for path, oid in sorted(ids.items()):
        if path not in eligible:
            findings.append({
                'path': path, 'rule': 'oversized-workflow',
                'severity': 'high', 'job': '', 'detail': '',
            })
        else:
            findings.extend(inspect_workflow(path, content[oid]))
    findings.sort(key=lambda x: (x['path'], x['job'], x['rule'], x['detail']))
    counts = {level: sum(x['severity'] == level for x in findings)
              for level in ('critical', 'high', 'medium', 'info')}
    report: dict[str, Any] = {
        'schema': 'changeattest.workflow-audit.v1',
        'head': head, 'status': 'advisory-only',
        'workflows_scanned': len(ids),
        'finding_counts': counts, 'findings': findings,
        'trust_note': (
            'Heuristic workflow inspection. Not a guarantee of secure CI '
            'or proof that a required check used a reviewed workflow.'
        ),
    }
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    return report
