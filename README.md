# ChangeAttest

**Check the change. Verify the evidence. Then merge.**

ChangeAttest is an independent, open-source developer preflight project. It begins with a battle-tested library of small Git hooks and is being developed into a change-aware quality, security, and test-evidence gate for human and AI-assisted software development.

> **Status:** Pre-release engineering project. The library, policy gate, immutable Git commit snapshots, optional tool adapters, Ed25519 evidence envelopes, agent scope contracts, exporters and local dashboard are implemented on `main`. **A hosted SaaS, cryptographically authenticated runner, fully isolated third-party execution, automatic agent integrations, and enterprise governance are not delivered.** Signing a self-asserted report does not establish independent execution.

## What works today

The repository includes the original Python hook collection for syntax checks, JSON/YAML validation, merge-conflict detection, whitespace cleanup, basic secret checks, and Git workflow hygiene.

Our foundation branch adds or fixes:

- **Staged executable checks outside Git** on POSIX, while retaining Git-index behavior inside repositories (tracked upstream as [#749](https://github.com/pre-commit/pre-commit-hooks/issues/749)).
- **pip index ordering** in requirements sorting (related to upstream [#612](https://github.com/pre-commit/pre-commit-hooks/issues/612)).
- **High-precision JSON formatting** using Decimal-aware `simplejson` (related to upstream [#780](https://github.com/pre-commit/pre-commit-hooks/issues/780)).
- **`check-lfs-attributes`**, a new check for staged LFS pointers mismatching staged `.gitattributes` (related to upstream [#1020](https://github.com/pre-commit/pre-commit-hooks/issues/1020)).
- **`detect-openpgp-secret-key`**, an opt-in, best-effort detector for recognizable binary OpenPGP secret-key packets at the start of files (related to upstream [#339](https://github.com/pre-commit/pre-commit-hooks/issues/339)). This is not a complete secret scanner.

See [the issue audit](docs/ISSUE_AUDIT.md) for scope and limitations.

## ChangeAttest CLI (first usable preflight engine)

The new CLI executes a fixed set of existing, non-mutating checks and emits a
machine-readable verification record. It is not a general command runner:
config files cannot inject shell commands, executable paths, or Python modules.

```bash
python -m pip install -e .
changeattest --version
changeattest check --scope tracked --report evidence.json
# For staged changes (the default):
changeattest check --scope staged --report staged-evidence.json
```

You can also run `python -m changeattest check`.

**Important semantics:** `staged` selects paths from the Git index, then
checks their working-tree bytes. If a staged file has additional unstaged
modifications, the scan **fails closed** instead of claiming to verify the
staged snapshot. `tracked` checks the current working tree, whether or not
those changes have been staged. Neither mode verifies untracked files.
Symlinks and over-limit files are reported as incomplete verification errors.

Exit codes: `0` = checks passed (or nothing selected), `1` = check failed,
`2` = verification incomplete or an operational/configuration error.
The report explicitly uses `status: "no-files"` when no files were selected.

The default check set is `json`, `toml`, `yaml`, `merge-conflict`,
`private-key`, and `openpgp-secret-key`. None automatically edits files.
The binary OpenPGP check is intentionally best-effort.

Optional configuration at the Git root:

```toml
[changeattest]
version = 1
checks = ["json", "toml", "yaml", "merge-conflict", "private-key", "openpgp-secret-key"]
timeout_seconds = 30
max_file_bytes = 8388608
```

The `checks` list can contain only built-in IDs. The JSON report includes
selected file SHA-256 digests, the Git HEAD, executed check IDs, outcomes,
exit codes, a digest of each check's output, and a digest of the overall
record. **Raw scanner output is deliberately withheld** to avoid disclosing
secrets via CI logs or report artifacts. A report checksum is **not** a
cryptographic signature or remote attestation, and a passed report is not
a substitute for independent CI enforcement.

See [CLI evidence specification](docs/EVIDENCE_V1.md) for the schema and
security boundaries.

## Policy gate (candidate release)

ChangeAttest also provides `changeattest gate` for **mandatory verification
with an explicit policy**. Unlike the ordinary `check` command, the gate
ignores the target checkout's `.changeattest.toml` and **fails** when no
files are selected, required checks are missing or skipped without permission,
a file cannot be verified, or the checked-out Git SHA differs.

```bash
changeattest gate --root . \
  --policy .github/changeattest-policy.toml \
  --expected-head "$(git rev-parse HEAD)" \
  --report evidence.json
```

For enforcement in CI, retrieve the gate implementation and policy from a
**trusted, protected revision**, run the checks again in CI, and configure
repository branch rules requiring the gate's successful status. A locally
generated checksum is not a signature or proof of provenance. The default
policy currently covers only `changeattest/` and `pre_commit_hooks/`.

Read the complete [policy and trust model](docs/POLICY_GATE.md).

### GitHub pull-request policy status

The [separate Policy Gate workflow](.github/workflows/policy-gate.yml)
runs on PRs targeting `main` and on pushes to `main`. It fetches the
**approved default-branch policy and code**, then checks the submitted
revision in a read-only CI job. Its stable status-check name is
`verified-policy-gate`.

**Active repository enforcement:** On October 21, 2026,
[GitHub ruleset #25567644](https://github.com/Chrisbryan17/changeattest/rules/25567644)
was enabled for the default branch. It requires `verified-policy-gate`
to succeed, so normal merges must satisfy the gate. The policy and CI
workflow should still be reviewed carefully: this ruleset enforces the
named check, but does not itself make the workflow files immutable or
require human approval of policy changes. Use pull requests for changes
to `main` and monitor repository administrators' ability to alter rules.

## Expanded platform interfaces

The tracked policy gate now runs against **temporary snapshots created from
immutable Git HEAD objects**, not live worktree bytes. It still does not
authenticate the runner or validate dependencies.

Optional verification commands (see [adoption instructions](docs/ADOPTION.md)):

```bash
# Optional language/test tools; toolchain code can execute project plugins
changeattest tools --adapter ruff --adapter pytest --report tools.json

# Record executed JUnit test output; this alone is an unsigned receipt
changeattest junit-evidence --junit results.xml --report tests.json

# Sign only with a separately controlled CI key, never an agent-owned key
changeattest sign --input tests.json --private-key ci-key.pem --output signed.json
changeattest verify-signature --input signed.json --public-key trusted-ci.pem

# Check a code agent's permitted scope against Git history
changeattest agent-review --contract contract.json \
  --base <BASE_SHA> --head <HEAD_SHA> --report agent-verdict.json

# Portable reports and a local-only evidence explorer
changeattest render --input evidence.json --format html --output evidence.html
changeattest store --input evidence.json --database evidence.sqlite
changeattest serve --database evidence.sqlite
```

See [implementation status](docs/IMPLEMENTATION_STATUS.md) for delivered vs
outstanding milestones and [security policy](SECURITY.md) for threat boundaries.
Organizational policy overlays are supported with `gate --overlay-policy`
and can only tighten mandatory checks, timeouts, size limits and coverage.

## Run hooks in a local development checkout

```bash
git clone https://github.com/Chrisbryan17/changeattest.git
cd changeattest
python -m pip install -e .
check-json example.json
check-lfs-attributes path/to/staged-file.bin
```

`check-lfs-attributes` examines the **Git index** and must be invoked inside a repository with staged content. These hooks are available on `main`; use a reviewed commit SHA when pinning them for production use.

ChangeAttest now uses its own Python distribution name `changeattest`, while retaining the legacy `pre_commit_hooks` import path and hook entry points for compatibility. The new `changeattest` CLI is implemented; policy-driven, signed verification and distributed orchestration remain future work.

### Use with the pre-commit framework

ChangeAttest's `.pre-commit-hooks.yaml` manifest remains compatible with the separately maintained [pre-commit framework](https://pre-commit.com/). When adopting in another repository, use this fork's URL and **pin a reviewed commit SHA** instead of a moving development branch. 

For the full inherited hook catalogue, see [Original hook catalogue](docs/ORIGINAL_HOOKS.md).

## Available hook identifiers

The following IDs are provided by this repository. Their current behavior and options are documented in the [inherited hook catalogue](docs/ORIGINAL_HOOKS.md) and in the hook manifest. Some legacy aliases intentionally report that a hook has been removed.

- `check-added-large-files`
- `check-ast`
- `check-byte-order-marker`
- `check-builtin-literals`
- `check-case-conflict`
- `check-docstring-first`
- `check-executables-have-shebangs`
- `check-illegal-windows-names`
- `check-json`
- `check-shebang-scripts-are-executable`
- `pretty-format-json`
- `check-lfs-attributes`
- `check-merge-conflict`
- `check-symlinks`
- `check-toml`
- `check-vcs-permalinks`
- `check-xml`
- `check-yaml`
- `debug-statements`
- `detect-openpgp-secret-key`
- `destroyed-symlinks`
- `detect-aws-credentials`
- `detect-private-key`
- `double-quote-string-fixer`
- `end-of-file-fixer`
- `file-contents-sorter`
- `fix-byte-order-marker`
- `fix-encoding-pragma`
- `forbid-new-submodules`
- `forbid-submodules`
- `mixed-line-ending`
- `name-tests-test`
- `no-commit-to-branch`
- `requirements-txt-fixer`
- `sort-simple-yaml`
- `trailing-whitespace`

## Continuous integration

The [in-repository CI workflow](.github/workflows/main.yml) runs the regression tests across supported Python versions on Linux and Windows. Test results are reported by GitHub Actions; no green status is claimed until the workflow actually completes.

## Direction

1. **Hardening:** correctness, cross-platform behavior, regression tests, and reliable Git checks.
2. **Execution:** change-aware check selection, caching, concurrency, timeout and tool adapters.
3. **Evidence:** machine-readable check results, verifiable command/tool identity, policy decisions.
4. **Integrations:** local CLI, protected CI status, pull requests, and optional agent workflows.

These are future milestones, not delivered capabilities.

## Provenance and license

ChangeAttest is derived from [pre-commit/pre-commit-hooks](https://github.com/pre-commit/pre-commit-hooks), originally developed by Anthony Sottile, Ken Struys, and contributors. The original MIT copyright and license notice remain in [LICENSE](LICENSE). The fork is independent, is not endorsed by its upstream maintainers, and does not require their approval for development under the MIT license. The GitHub repository is currently still marked as a fork.

The pre-commit framework and other external tools are separate projects. Respect their respective licenses. Do not copy upstream branding or imply affiliation.

## Responsible development

- Fixes must have regression cases and real test evidence.
- Never represent mock tests as proof of OS/hardware-specific behavior.
- Never claim that an AI suggestion was executed, tested, or reviewed unless there is evidence.
- Prevent leakage of secrets through logs, sample fixtures, or automated reports.
