# ADR 0001 — Trust boundary for mandatory GitHub checks

Status: **Implemented baseline; additional governance required**
Decision date: 2026-10-21

## Existing mechanism

- A GitHub ruleset requires the `verified-policy-gate` context on `main`.
- That job installs ChangeAttest from the default-branch commit and fetches
  its required policy from that same baseline.
- The validator reads Git object bytes from the exact commit and does not
  run arbitrary tools specified by a PR.
- Tests, package-smoke and optional agent-scope workflows run separately.
- `CODEOWNERS` declares review owners of policy and workflow code.

## Residual attack and mandatory next control

The current job is triggered by `pull_request`, whose workflow definition
can originate from the proposed merge commit. A contributor changing the
workflow definition can potentially remove or weaken its verification steps,
while still emitting an identically named success context.

**The required status check by itself does not prove that the reviewed
workflow definition was the one executed.** CODEOWNERS names do not
automatically mandate human approval without a branch ruleset requiring
appropriate reviews.

A repository administrator should add appropriate rules requiring review of
sensitive workflow/policy modifications, consider authorized status-check
sources or organization-level required workflows, and test bypass attempts
before claiming tamper resistance. Administrative bypass authority remains
a separate part of the threat model.

## Why not blindly switch to pull_request_target?

GitHub documents `pull_request_target` as running a workflow from the
trusted base branch, but it comes with a privileged execution context.
Checking out and executing contributor code can become a "pwn request".
GitHub also documents a public-repository default event restriction
scheduled for November 2, 2026. A migration would require a deliberate
read-only threat model and confirmation that the repository's event policy
allows the workflow.

References:
- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks

## Defined safe boundaries

- Third-party adapter commands are opt-in and NOT trusted-gate validators.
- Private signing keys must stay outside source control and untrusted CI.
- Local SQLite evidence history is neither a proof authority nor SaaS.
- Signed reports authenticate signatures, not executions.
- Workflow, action, policy and signing-code reviews must remain security
  critical changes.
