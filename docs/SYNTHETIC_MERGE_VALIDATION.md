# Synthetic merge trust verification: acceptance and incident playbook

This document is also a harmless PR fixture for confirming that the
default-branch-owned verification workflow works with GitHub's real
`refs/pull/<number>/merge` object. It changes no executable code,
repository configuration or required CI status.

## Verification invariants

1. The workflow is loaded from the protected **base** revision.
2. The only checked-out revision is the event's **base** commit.
3. The PR head and synthetic merge are fetched into the local Git object
   database; no contributor code is checked out or executed.
4. The synthetic merge commit is authenticated by matching its **two
   ordered parents** to the event's exact base and PR-head SHA.
5. Any absent merge ref, unexpected parent, checkout mismatch or
   missing trusted policy blocks the advisory check.
6. The base-owned evaluator scans both immutable head and merge Git
   trees. A clean head does not excuse an invalid merged tree.
7. The source revision and baseline policy are explicit in the reports.
8. This remains an advisory source-verification signal until GitHub
   administrator-enforced protections and event policy are confirmed.

## How to review a result

Open the `ChangeAttest Base-Owned PR Verification` workflow for this PR.
Inspect the job `base-owned-source-verification-advisory`.
On success, confirm these artifacts were produced:

- `sensitive-review.json`
- `merge-identity.json`
- `trusted-pr-evidence.json`
- `trusted-merge-evidence.json`

A clean outcome has `merge-identity.status = verified`, ordered
`parents = [trusted_base_sha, proposed_head_sha]`, and two passing
policy scans with independent `head` fields.

A failure in this workflow should not be overwritten or represented
as success. For merge conflicts or obsolete PR merge refs, rebase or
update the PR, then wait for GitHub to regenerate the merge ref and
re-run validation on the new exact commit identities.

## Security posture

A passing result proves only that **these allowlisted validators**
accepted the fetched Git objects in this runner. It cannot by itself
prove safe code execution, safe dependencies, authentic release
provenance or code-review approval. The system deliberately does not
run third-party test scripts in its privileged base-owned workflow.

For event restrictions, consult GitHub's up-to-date
`pull_request_target` security and Actions event-policy documents.
The October 21, 2026 GitHub changelog revised the default public
repository enforcement date to December 2, 2026; an administrator
should review policy insights and approved exceptions before that date.
