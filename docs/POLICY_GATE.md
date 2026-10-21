# ChangeAttest policy gate v1

**This is a local policy evaluator. It is not cryptographic attestation.**
A report can be manufactured and rehashed; the CI job must execute the
validators itself using a trusted runner implementation and trusted rules.

## CLI

```bash
changeattest gate \
  --root . \
  --policy /trusted/path/policy.toml \
  --expected-head "$(git rev-parse HEAD)" \
  --report /tmp/changeattest-evidence.json
```

The `--policy` path must be provided explicitly. In a GitHub PR check,
fetch it from the protected default branch or a separately controlled
repository—not from the proposed PR changes. The gate intentionally ignores
the target repository's `.changeattest.toml`.

Exit codes: 0 if every policy condition is satisfied, 1 for violations
(including checker failures, skipped mandatory checks, incomplete file
verification, zero files, or Git commit mismatch), 2 for configuration,
repository, or report-writing errors. Both nonzero codes must block CI.

The gate runs only the built-in, non-mutating Python validator allowlist.
It cannot run arbitrary commands supplied by the target checkout.

## Versioned policy

```toml
[policy]
version = 1
scope = "tracked"
include_prefixes = ["changeattest/", "pre_commit_hooks/"]
required_checks = ["python-ast", "merge-conflict"]
allow_skipped_checks = []
min_files = 1
timeout_seconds = 45
max_file_bytes = 8388608
```

`include_prefixes` deliberately narrows the directory coverage.
The starter policy does **not** cover test fixtures, documentation,
lockfiles, or external dependencies. Expand it with explicit test evidence;
a passing gate means only the specified checks ran against the selected
files. The evidence records the selected prefixes.

`required_checks` must be a nonempty subset of supported check IDs.
Each required check must appear **exactly once** in the evidence record.
By default a skipped mandatory check blocks the run, even when no file
matches that validator. Set `allow_skipped_checks` for validators that may
legitimately have no relevant files. A skipped check must have zero selected
files; it is not evidence of execution.

`min_files` defaults to one. An empty selection does **not** silently pass.
A non-matching or excluded file contributes no coverage. No `allow-empty`
switch is provided in the gate.

`--expected-head` must be a full Git SHA; the gate rejects a mismatch.
A report checksum prevents accidental alteration after generation; it
does not authenticate a producer. On a PR, compare with the exact checked
out synthetic merge commit or PR commit, as appropriate.

## CI security model

A meaningful GitHub check should:

1. Check out the PR or target revision in a job with `contents: read`
   permissions and **no production secrets**.
2. Fetch the policy and gate implementation from a protected, reviewed
   revision of the default branch, and run the CLI using `python -I`.
3. Run `changeattest gate` **inside that CI job**, not on a supplied report.
4. Use the actual Git HEAD as `--expected-head`, save the evidence under
   `RUNNER_TEMP`, and propagate nonzero exit codes.
5. Configure repository branch rules requiring the **specific gate job's
   successful check** before merging. A green optional workflow alone
   does not prevent merges.
6. Protect modifications to the CI workflow, the trusted default branch,
   and the policy. A PR author can modify workflow files in their branch,
   so requiring a trusted status context is essential.

CI systems and public untrusted PRs have additional runner and supply-chain
risks; this gate does not sandbox arbitrary code. Never execute
untrusted build scripts with write tokens or privileged runner secrets.

### Limitations remaining

- The scanner currently hashes worktree bytes and checks for staged/worktree
  mismatch, but does not provide an immutable filesystem snapshot against
  concurrent mutation. Use disposable CI runners.
- File selection by trusted prefixes is intentionally incomplete.
- No signed provenance, cryptographic runner identity, or automatic branch
  protection administration is implemented.
- Python environment/runtime and installed packages remain part of the
  trusted computing base.

See [evidence v1](EVIDENCE_V1.md) for the unsigned report schema.
