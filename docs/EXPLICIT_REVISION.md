# Immutable explicit-commit verification

ChangeAttest's `gate` command can verify an exact Git commit that is
present in the local Git object database **without checking out that
commit** or importing its Python modules.

```bash
python -I -m changeattest gate \
  --root /path/to/reviewed-tool-checkout \
  --revision 0123456789abcdef0123456789abcdef01234567 \
  --expected-head 0123456789abcdef0123456789abcdef01234567 \
  --policy /path/to/trusted-baseline-policy.toml \
  --report /tmp/verification.json
```

Replace both example SHA values with the actual same full target
commit ID. The target commit must already exist in the repository's
local object database (e.g. after a read-only `git fetch`).

The `--revision` option rejects symbolic refs, shortened Git hashes
and other Git revision syntax, requires a tracked immutable policy scope,
and requires `--expected-head` to establish an explicit binding.
It scans the target Git tree/blob contents rather than the current HEAD
or mutable worktree. The installed evaluator and policy still need to
be supplied independently from a trusted source.

## CI integration design

The existing `pull_request` required workflow continues operating
unchanged. This primitive enables a **separate** base-branch controlled
workflow in which the evaluator and policy are taken from the protected
branch, the PR head SHA is fetched as Git *data only*, and no contributor
checkout is executed.

Whether a check can be required for a particular pull request depends
on GitHub's event/check association and repository Actions policy.
This command itself does not repair any GitHub branch protection,
required workflow, review, or status-identity configuration.

`pull_request_target` is a privileged event: NEVER run untrusted PR
scripts/dependencies/test runners in that event, and never pass a
write-capable token or secrets. See:

- https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
