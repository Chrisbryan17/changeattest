from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML


def test_release_workflow_uses_tag_only_oidc_attestation():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/build-release.yml'
    workflow = YAML(typ='safe').load(path.read_text(encoding='utf-8'))

    assert 'pull_request' not in workflow['on']
    assert workflow['on']['push']['tags'] == ['v*']
    assert workflow['permissions'] == {'contents': 'read'}

    build = workflow['jobs']['wheel-and-sdist']
    signer = workflow['jobs']['release-attestation']
    assert build['permissions'] == {'contents': 'read'}
    assert signer['needs'] == 'wheel-and-sdist'
    assert signer['if'] == (
        "github.event_name == 'push' && "
        "startsWith(github.ref, 'refs/tags/v')"
    )
    assert signer['permissions'] == {
        'contents': 'read',
        'id-token': 'write',
        'attestations': 'write',
        'artifact-metadata': 'write',
    }
    assert any('Check tagged distribution version' == step.get('name')
               for step in build['steps'])

    actions = [step.get('uses') for step in signer['steps']]
    assert 'actions/attest@v4' in actions
    attest = next(step for step in signer['steps']
                  if step.get('uses') == 'actions/attest@v4')
    assert attest['with']['subject-path'] == 'dist/*'
    assert any('gh attestation verify' in step.get('run', '')
               for step in signer['steps'])
    assert not any('actions/checkout' in (step.get('uses') or '')
                   for step in signer['steps'])
