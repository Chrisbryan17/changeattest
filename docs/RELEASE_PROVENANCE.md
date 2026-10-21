# Trusted release build provenance

ChangeAttest has a separate release packaging workflow at
`.github/workflows/build-release.yml`. It supports manual build verification,
and on a pushed version tag it can generate and verify a signed Sigstore-backed
GitHub Artifact Attestation for each wheel and source distribution.

**This is a workflow implementation, not evidence of an already published or
attested release.** No published release is claimed until the tag workflow
actually succeeds and external verification is reproduced.

## Release process

1. Merge and verify all regression tests on the protected default branch.
2. Review the release version in `setup.cfg`; the tag must match it exactly
   with a leading `v` (for example `v0.1.0.dev0`).
3. A maintainer creates the tag from the reviewed commit. Prefer an annotated
   and signed tag, with protected release tag rules.
4. The workflow builds the wheel and source archive with no repository write
   permission, checks package metadata, and preserves the build artifacts.
5. On tag pushes ONLY, a separate job with short-lived GitHub OIDC permission
   uses `actions/attest@v4` to generate build provenance. The job then runs
   `gh attestation verify` on every artifact, requiring the expected
   ChangeAttest release workflow signer identity.
6. Only artifacts which passed checks and attestation verification should be
   published by a separately reviewed release process. There is no
   automatic PyPI publication or GitHub release creation here.

## Verify a downloaded artifact

```bash
gh attestation verify ./dist/changeattest-VERSION-py3-none-any.whl \
  --repo Chrisbryan17/changeattest \
  --signer-workflow Chrisbryan17/changeattest/.github/workflows/build-release.yml
```

Replace the example filename with the *actual* downloaded wheel. Verify
source archives separately. Verify the expected source version and workflow
provenance, not merely a matching digest.

## Trust model

- Unlike locally signed arbitrary JSON, GitHub's attestation binds a build
  artifact digest to a CI workflow identity using the GitHub OIDC/Sigstore
  process. A consumer must still verify the attestation and decide whether
  the signer workflow was trustworthy.
- The tag workflow is not triggered by pull requests. The attestation job
  only executes on a `push` event for a version tag.
- The general build job runs without OIDC token or attestation permissions.
- Release tag authority and GitHub Actions workflow contents remain
  security-critical; protect tags and require careful reviews.
- Attestation proves recorded build provenance, NOT freedom from malware or
  that arbitrary tests were executed.
- Immutable GitHub release administration was NOT configured by this
  workflow and remains a separate repository setting.

Official references:
- https://github.com/actions/attest
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/increase-security-rating
