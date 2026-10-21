# GitHub Actions workflow risk audit

`changeattest workflow-audit` examines workflow definitions directly from
immutable committed Git objects without running their scripts or project tools.

```bash
changeattest workflow-audit --root . --report workflow-risks.json
```

Default behavior is advisory: reports findings without blocking the
command. Add `--fail-on-high` to return nonzero when a critical or high
finding occurs, after the rules have been reviewed for false positives.

## What v1 detects

- `pull_request_target` / `workflow_run` elevated-trust triggers.
- Privileged checkout of PR head refs, and later shell execution of that
  checkout in the same job.
- Broad or explicitly write-capable tokens in PR-triggered workflows.
- Direct interpolation of certain untrusted PR, issue or comment fields
  into shell commands.
- Remote action references that are not pinned to full commit SHAs.
- Checkout steps which retain credentials by default in PR workflows.
- Obvious network-download-to-shell patterns.
- Malformed, oversized, nonregular or unsupported workflow definitions.

The immutable Git source and inspection results are bound to a SHA-256
JSON report. A separate read-only GitHub Actions job uploads the advisory
report on pull requests. The actual protected verification gate is
unchanged.

## Risk and limitations

This is **heuristic static analysis**, not a complete security audit or
proof that a workflow was run from a protected revision. Scripts can invoke
other scripts and dependencies, expressions may be indirectly unsafe, and
workflow features may evolve faster than these heuristics. Medium findings
include legitimate uses of moving action tags. False negatives are possible.

GitHub cautions that `pull_request_target` runs with elevated base
repository privileges. Executing PR-controlled code in that context can
lead to repository compromise. The scanner detects some common paths, but
does not try to rewrite workflows automatically.

Critically, the existing `verified-policy-gate` is triggered by
`pull_request`, and the workflow file can be altered in a PR. This
advisory audit does not solve that trust boundary. Use enforced
administrative workflow review policies and/or organization-managed
required workflows where available before claiming tamper resistance.
GitHub CODEOWNERS without enforced reviews is not sufficient.

## Official references

- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
