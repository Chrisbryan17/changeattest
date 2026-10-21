from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml import YAML

PIN = re.compile(r'\A[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+@[a-f0-9]{40}\Z')


def test_every_remote_github_action_is_pinned_to_reviewed_full_commit():
    root = Path(__file__).resolve().parents[1]
    paths = list((root / '.github' / 'workflows').glob('*.yml'))
    paths += list((root / '.github' / 'actions').rglob('action.yml'))
    assert len(paths) >= 7
    scanned = []
    for path in paths:
        workflow = YAML(typ='safe').load(path.read_bytes())
        jobs = (workflow.get('jobs') or {}) if 'workflows' in path.parts else {
            'composite': workflow.get('runs') or {},
        }
        for spec in jobs.values():
            for step in spec.get('steps', []):
                used = step.get('uses', '')
                if not used or used.startswith(('./', 'docker://')):
                    continue
                scanned.append(used)
                assert PIN.fullmatch(used), (str(path), used)
    assert len(scanned) >= 15


def test_checkout_never_leaves_credentials_in_pr_workflows():
    root = Path(__file__).resolve().parents[1]
    for path in (root / '.github' / 'workflows').glob('*.yml'):
        workflow = YAML(typ='safe').load(path.read_bytes())
        events = workflow.get('on', [])
        if isinstance(events, dict):
            triggers = set(events)
        elif isinstance(events, str):
            triggers = {events}
        else:
            triggers = set(events)
        if 'pull_request' not in triggers:
            continue
        for job in (workflow.get('jobs') or {}).values():
            for step in job.get('steps', []):
                used = step.get('uses', '')
                if isinstance(used, str) and used.startswith('actions/checkout@'):
                    assert (step.get('with') or {}).get('persist-credentials') is False, str(path)


def test_trusted_gate_uses_pinned_actions_and_read_only_token():
    path = (Path(__file__).resolve().parents[1]
            / '.github/workflows/policy-gate.yml')
    data = YAML(typ='safe').load(path.read_bytes())
    assert data['permissions'] == {'contents': 'read'}
    job = data['jobs']['policy-gate']
    assert job['name'] == 'verified-policy-gate'
    assert all(
        PIN.fullmatch(step['uses'])
        for step in job['steps']
        if step.get('uses') and not step['uses'].startswith('./')
    )
