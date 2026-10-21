# ChangeAttest

**Check the change. Verify the evidence. Then merge.**

ChangeAttest is an independent, open-source developer preflight project. It begins with a battle-tested library of small Git hooks and is being developed into a change-aware quality, security, and test-evidence gate for human and AI-assisted software development.

> **Status:** Foundation development. The hook library runs today; the planned orchestration engine, attestations, dashboards, and agent integrations are **not implemented yet**. Do not treat a passing hook run as proof of security or production readiness.

## What works today

The repository includes the original Python hook collection for syntax checks, JSON/YAML validation, merge-conflict detection, whitespace cleanup, basic secret checks, and Git workflow hygiene.

Our foundation branch adds or fixes:

- **Staged executable checks outside Git** on POSIX, while retaining Git-index behavior inside repositories (tracked upstream as [#749](https://github.com/pre-commit/pre-commit-hooks/issues/749)).
- **pip index ordering** in requirements sorting (related to upstream [#612](https://github.com/pre-commit/pre-commit-hooks/issues/612)).
- **High-precision JSON formatting** using Decimal-aware `simplejson` (related to upstream [#780](https://github.com/pre-commit/pre-commit-hooks/issues/780)).
- **`check-lfs-attributes`**, a new check for staged LFS pointers mismatching staged `.gitattributes` (related to upstream [#1020](https://github.com/pre-commit/pre-commit-hooks/issues/1020)).
- **`detect-openpgp-secret-key`**, an opt-in, best-effort detector for recognizable binary OpenPGP secret-key packets at the start of files (related to upstream [#339](https://github.com/pre-commit/pre-commit-hooks/issues/339)). This is not a complete secret scanner.

See [the issue audit](docs/ISSUE_AUDIT.md) for scope and limitations.

## Run hooks in a local development checkout

```bash
git clone https://github.com/Chrisbryan17/changeattest.git
cd changeattest
python -m pip install -e .
check-json example.json
check-lfs-attributes path/to/staged-file.bin
```

`check-lfs-attributes` examines the **Git index** and must be invoked inside a repository with staged content. Some commands above require the foundation work to be merged into the default branch; until then, use the foundation branch.

ChangeAttest currently preserves the upstream Python package name `pre_commit_hooks` and CLI entry points for compatibility. A separate public `changeattest` CLI and the independent policy/evidence engine will be introduced without claiming they're already built.

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
