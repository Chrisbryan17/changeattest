# Sensitive change classification

The `changeattest sensitive-change` command identifies changes to the
repository's security-critical source and configuration files from an
**immutable Git diff**. It never executes the changed files.

```bash
changeattest sensitive-change \
  --base <reviewed-base-full-SHA> \
  --head <proposed-commit-full-SHA> \
  --report sensitive-change-evidence.json
```

The default is advisory: a machine-readable report lists changed paths,
their reasons and the number of critical/high review items.

For a verifier installed and executed from a **trusted independent
baseline**, append `--block-sensitive` to return nonzero when
security-sensitive files were changed.

## Classification

Critical: GitHub Actions workflow and composite-action definitions,
mandatory ChangeAttest policy, agent scope contract, and CODEOWNERS.

High: verification-engine source under `changeattest/`, package
dependencies/build metadata, security and licensing notices, and core
security regression tests.

The classifier treats deletions and renames conservatively by using Git
diffs with rename detection disabled. It compares exact full Git commit
identifiers; untracked and mutable worktree files cannot affect results.

## What classification does not prove

A passing classification means none of the **currently configured
sensitive path patterns** matched. It is not proof of code safety,
workflow execution integrity, or review approval.

An attacker with control over the version of ChangeAttest executing the
classifier can modify its results. For meaningful enforcement, use the
classifier only when the binary and policy come from a separately
protected baseline and when GitHub rules actually require the
corresponding check.

Likewise, failing a sensitive change does not mean a developer is
malicious. It indicates that independent maintainer review is required.
A robust review-exception mechanism and enforcement rules are distinct
features, not provided by this CLI.

The base-owned PR verifier provides an experimental read-only
environment but its status-check association and event policy still
need empirical verification. See
[base-owned PR verification](BASE_OWNED_PR_VERIFICATION.md).
