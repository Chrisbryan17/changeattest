"""A trusted-base PR workflow must never execute contributor checkout."""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

BASE = Path(__file__).resolve().parents[1]
WORKFLOW = BASE / '.github/workflows/baseline-pr-audit.yml'


def _workflow():
    return YAML(typ='safe').load(WORKFLOW.read_text(encoding='utf-8'))


def test_base_owned_workflow_only_uses_privileged_base_trigger():
    x = _workflow()
    assert set(x['on']) == {'pull_request_target'}
    assert x['on']['pull_request_target']['branches'] == ['main']
    assert x['permissions'] == {'contents': 'read'}
    assert set(x['jobs']) == {'baseline'}
    assert x['jobs']['baseline']['name'] == 'base-owned-source-verification-advisory'
    assert x['jobs']['baseline']['timeout-minutes'] <= 15


def test_workflow_does_not_checkout_untrusted_pr_or_share_secrets():
    x = _workflow()
    steps = x['jobs']['baseline']['steps']
    checkout = next(s for s in steps
                    if (s.get('uses') or '').startswith('actions/checkout@'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.base.sha }}'
    assert checkout['with']['persist-credentials'] is False
    assert len([s for s in steps if 'actions/checkout@' in (s.get('uses') or '')]) == 1
    assert all(not (s.get('uses') or '').startswith('docker://') for s in steps)
    assert all('secrets.' not in str(s) for s in steps)
    assert 'pull_request.head.sha' not in checkout['with']['ref']


def test_untrusted_code_is_only_fetched_as_git_data():
    x = _workflow()
    steps = x['jobs']['baseline']['steps']
    scripts = [s.get('run', '') for s in steps]
    all_scripts = '\n'.join(scripts)
    assert 'git fetch --no-tags --depth=1 origin "refs/pull/${PR_NUMBER}/head"' in all_scripts
    assert 'git rev-parse FETCH_HEAD^{commit}' in all_scripts
    assert 'git show "$BASE_SHA:.github/changeattest-policy.toml"' in all_scripts
    assert 'git+https://github.com/Chrisbryan17/changeattest.git@$TRUSTED_BASE_SHA' in all_scripts
    assert '--revision "$TARGET_PR_SHA"' in all_scripts
    assert '--expected-head "$TARGET_PR_SHA"' in all_scripts
    assert '--policy "$RUNNER_TEMP/baseline-policy.toml"' in all_scripts

    dangerous = (
        'git checkout "$PR_HEAD"',
        'git switch "$PR_HEAD"',
        'git reset --hard "$PR_HEAD"',
        'gh pr checkout',
        'make test',
        'npm test',
        'pytest ',
        'python setup.py',
        'pip install .',
    )
    assert not any(fragment in all_scripts for fragment in dangerous)


def test_base_owned_workflow_blocks_critical_paths_using_trusted_tool():
    x = _workflow()
    scripts = '\n'.join(s.get('run', '')
                        for s in x['jobs']['baseline']['steps'])
    assert 'changeattest sensitive-change' in scripts
    assert '--block-critical' in scripts
    assert '--base "$TRUSTED_BASE_SHA"' in scripts
    assert '--head "$TARGET_PR_SHA"' in scripts
    assert '--report "$RUNNER_TEMP/sensitive-review.json"' in scripts


def test_verified_merge_tree_is_fetched_as_objects_and_never_executed():
    x = _workflow()
    steps = x['jobs']['baseline']['steps']
    scripts = '\n'.join(step.get('run', '') for step in steps)
    assert 'git fetch --no-tags --depth=1 origin "refs/pull/${PR_NUMBER}/merge"' in scripts
    assert 'MERGE_SHA="$(git rev-parse FETCH_HEAD^{commit})"' in scripts
    assert 'TARGET_MERGE_SHA=' in scripts
    assert 'changeattest verify-merge' in scripts
    assert '--base "$TRUSTED_BASE_SHA"' in scripts
    assert '--head "$TARGET_PR_SHA"' in scripts
    assert '--merge "$TARGET_MERGE_SHA"' in scripts
    assert '--revision "$TARGET_PR_SHA"' in scripts
    assert '--revision "$TARGET_MERGE_SHA"' in scripts
    assert '--expected-head "$TARGET_MERGE_SHA"' in scripts
    assert '--report "$RUNNER_TEMP/merge-identity.json"' in scripts
    assert '--report "$RUNNER_TEMP/trusted-merge-evidence.json"' in scripts
    checkout = next(s for s in steps
                    if (s.get('uses') or '').startswith('actions/checkout@'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.base.sha }}'
    assert '${{ github.event.pull_request.head.sha }}' not in scripts
    assert '${{ github.event.pull_request.number }}' not in scripts
    for forbidden in ('git checkout "$TARGET_MERGE_SHA"',
                      'git switch "$TARGET_MERGE_SHA"',
                      'git reset --hard "$TARGET_MERGE_SHA"',
                      'git merge "$TARGET_PR_SHA"'):
        assert forbidden not in scripts
    archives = next(s for s in steps if 'actions/upload-artifact@' in
                    (s.get('uses') or ''))
    assert 'trusted-merge-evidence.json' in archives['with']['path']
    assert 'merge-identity.json' in archives['with']['path']


def test_untrusted_sha_flows_through_env_not_yaml_shell_expression():
    x = _workflow()
    scripts = '\n'.join(s.get('run', '') for s
                        in x['jobs']['baseline']['steps'])
    assert '${{ github.event.pull_request.head.sha }}' not in scripts
    assert '${{ github.event.pull_request.number }}' not in scripts
    assert '${{ github.event.pull_request.base.sha }}' not in scripts
    assert '[[ "$PR_HEAD" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]' in scripts
    assert 'test "$(git rev-parse HEAD)" = "$BASE_SHA"' in scripts
