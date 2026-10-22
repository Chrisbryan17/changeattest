# Base-owned pull request verification experiment

**Status:** Read-only, advisory workflow designed to verify a proposed
pull request's source objects without running or checking out PR code.
**Not a replacement for the existing required `verified-policy-gate`.**

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
6. Run `gate --revision <PR-head-SHA> --expected-head <same-SHA>`:
   allowlisted built-in validators read only the untrusted commit's
   blobs through a temporary snapshot. Third-party adapters, dynamic
   plugin loading and PR dependencies are excluded.
7. Upload unsigned evidence for inspection, with short retention.

The workflow and its invariants have static regression tests. The
Linux CI event itself must be exercised after the workflow exists on
the base branch; passing static tests does **not** prove a successful
live GitHub `pull_request_target` run.

## Important deployment limitations

- `pull_request_target` executes in a privileged base context. Even
  with read-only token permission, careless future edits (running
  PR-controlled shell scripts, loading package metadata, mounting a
  writable Docker socket or importing PR modules) could turn it into
  a supply-chain compromise. Preserve the no-execution boundary.
- As currently designed, the job verifies the proposed **PR head**
  rather than GitHub's synthetic merge commit. Merge correctness
  and the existing merge commit gate still require separate checks.
- GitHub status-check association differs by event: a
  `pull_request_target` run is associated with the base branch
  context, not automatically with the proposed head/merge check that
  branch protection requires. This workflow is **advisory**, not yet a
  separately enforceable merge decision.
- GitHub has announced default restrictions on
  `pull_request_target` events for public repositories beginning
  November 2, 2026. Organization/repository Actions policy must be
  checked before relying on this event. Do not bypass a protective
  platform policy solely to enable this experiment.
- Changes to the trusted workflow or policy still require
  independently enforced review. The existing active ruleset does
  not yet establish that level of governance.

## Acceptance criteria before any promotion

Demonstrate that the trusted workflow really runs from the base
branch for a fresh PR and rejects invalid Python in a disposable
target revision, while leaving source files unexecuted. Confirm the
event/check association and repository Actions policy. Obtain
enforced review and trusted check-source controls through GitHub
administration (possibly organization-level required workflows).

References:
- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/concepts/about-actions-policies
