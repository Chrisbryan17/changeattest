# GitHub Actions supply-chain hardening

Status: action refs pinned to full upstream commit identities and checked
by the repository's regression tests.

The refs below were retrieved from GitHub's `refs/tags/<major>` API for
the upstream action repositories on 2026-10-21. They are fixed commits in
our workflow files, not floating tags.

| Action | Major | Pinned commit |
| --- | --- | --- |
| actions/checkout | v6 | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| actions/setup-python | v6 | `ece7cb06caefa5fff74198d8649806c4678c61a1` |
| actions/upload-artifact | v5 | `330a01c490aca151604b8cf639adc76d48f6c5d4` |
| actions/download-artifact | v5 | `634f93cb2916e3fdff6788551b99b062d0335ce0` |
| actions/attest | v4 | `1e69f48acb82d1966a394da916b4c1698aa569d6` |

Pin updates are treated as explicit security-reviewed dependency
changes. Retest the Python 3.11/3.13 Linux/Windows matrices, reusable
action, policy gate and release package verification after each upgrade.

## What pinning solves

A floating `@v4` reference may resolve to different upstream code on a
future run. A full Git object ID prevents an unreviewed upstream tag move
from silently changing what gets executed.

**A pinned action is not automatically secure.** The source repository
and commit still require review, and GitHub Actions, Python dependencies,
runner images and the CI workflow definition remain part of the trusted
computing base.

## Outstanding controls

- A PR can still change the required workflow definition itself under
  the current `pull_request` event. Enforce independent review of
  changes to sensitive workflow/policy paths using repository rules.
- Keep `GITHUB_TOKEN` permissions read-only for PRs, and do not share
  production secrets with untrusted code.
- Signed build provenance requires successful release-tag execution and
  consumer-side verification; configuring an attestation action is not
  evidence that a release was attested.
- Review upstream security advisories when deciding whether to re-pin to
  a newer major or patch revision.

See [workflow risk rules](WORKFLOW_AUDIT.md) and
[GitHub CI threat model](ADR-0001-TRUSTED-CI.md).
