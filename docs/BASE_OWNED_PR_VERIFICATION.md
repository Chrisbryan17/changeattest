# Base-owned pull request verification experiment

**Status:** A live base-owned read-only workflow successfully verified
[PR #21](https://github.com/Chrisbryan17/changeattest/pull/21) in
[GitHub Actions run 39724039357](https://github.com/Chrisbryan17/changeattest/actions/runs/39724039357).
**It is not currently a required merge check.**

## Why it exists

The current required `pull_request` gate verifies the exact merge
commit using the baseline policy and evaluator, but GitHub may execute
the *workflow definition* from the proposed merge commit itself. A
contributor able to modify that workflow can therefore weaken the
required check unless repository-side review/governance prevents it.

The experimental
`.github/workflows/baseline-pr-audit.yml` uses
`pull_request_target`, for which GitHub loads the workflow from the
base branch. This event has elevated trust; it is not a safe default
for arbitrary testing of fork contributions.

## Hardened verification flow

1. Read only a controlled base revision, pinned through the base SHA
   from the signed GitHub event payload. `actions/checkout` must
   never use the PR head or merge ref.
2. Declare `permissions: contents: read` and `persist-credentials:
   false`; do not reference secrets or writable cache modes.
3. Validate that the PR number and both event-provided SHA strings
   match strictly defined formats.
4. Fetch `refs/pull/<PR-number>/head` into the local **Git object
   database only**, verify the resulting commit ID, and never check
   out or execute contributor files or build scripts.
5. Load the policy from the trusted base Git blob, and install
   ChangeAttest from that exact reviewed base commit SHA.
6. Run `sensitive-change --base <trusted-base-SHA> --head <PR-head-SHA>
   --block-critical`: critical changes to workflows, actions and
   protected policy trigger an advisory-job failure. High-risk
   verifier/dependency changes are logged for review without automatically
   failing this step.
7. Fetch GitHub's `refs/pull/<PR-number>/merge` into the Git object
   database only. Run `verify-merge` to require **exactly two ordered
   parents**, the event-provided trusted base SHA and PR head SHA.
   A missing/conflicted merge ref or mismatched parent IDs fails closed.
8. Run `gate --revision <PR-head-SHA>` and
   `gate --revision <synthetic-merge-SHA>` with independent matching
   `--expected-head` values. Both read immutable Git objects in
   temporary snapshots using trusted built-in validators. No checkout,
   package installation, build or execution of proposed source occurs.
9. Upload the sensitive-change report, merge-identity receipt and
   separate head/merge gate evidence, even on failure.

The workflow and its invariants have static regression tests.
In the first live run, trusted source was anchored to
`60f24fdb712d7b99be8e4dad66b5eac9aeb303f2`, and the requested PR
commit was `32a53544682da9795d6ac1a8908a888dbe8f37b8`. The job
reported `ChangeAttest policy gate: PASS`; GitHub attached
`base-owned-source-verification-advisory` to that proposed commit.

## Important deployment limitations

- `pull_request_target` executes in a privileged base context. Even
  with read-only token permission, careless future edits (running
  PR-controlled shell scripts, loading package metadata, mounting a
  writable Docker socket or importing PR modules) could turn it into
  a supply-chain compromise. Preserve the no-execution boundary.
- The job now verifies **both** the PR head and GitHub's synthetic
  merge tree, after matching the synthetic merge's ordered parent
  identities. A matching Git commit is not an independent attestation
  of GitHub's merge service or a guarantee that the merge ref will
  remain unchanged after the check. Re-run on base/head updates and
  retain the existing required merge-commit check.
- GitHub check association must be verified for each supported
  event/policy configuration. In the initial experiment GitHub
  attached the advisory check to the PR head, but it is NOT part of
  the active required-check ruleset and does not replace validation
  against the synthetic merge commit.
- GitHub's October 21, 2026 update moved default
  `pull_request_target` event-policy enforcement for affected public
  repositories to **December 2, 2026**. It is presently evaluated,
  not automatically denied for this cohort. Review the repository's
  policy insights before relying on the event; explicit, reviewed
  event policies are an administrator responsibility.
- Changes to the trusted workflow or policy still require
  independently enforced review. The existing active ruleset does
  not yet establish that level of governance.

## Acceptance criteria before any promotion

The base-owned workflow passed real PR #21. Negative controls
were subsequently verified: [draft PR #23](https://github.com/Chrisbryan17/changeattest/pull/23)
rejected a weakened policy, and
[draft PR #24](https://github.com/Chrisbryan17/changeattest/pull/24)
rejected invalid committed Python using both the traditional and
base-owned gates; both fixtures were closed without merging.

The synthetic-merge extension is implemented with regression tests,
but requires **a fresh live PR run after this workflow reaches
`main`**. Before promotion to required-check status, verify event
policy, enforced human review rules, trusted status-check source and
behavior on a stale or conflicted merge ref.

References:
- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/concepts/about-actions-policies
