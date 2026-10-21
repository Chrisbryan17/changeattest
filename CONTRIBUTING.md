# Contributing to ChangeAttest

This independent project retains the original hooks and MIT attribution.
Changes to inherited behavior should include regression cases that reproduce
the intended difference without relying on upstream approval.

## Developer setup

```bash
python -m pip install -e '.[attest]' -r requirements-dev.txt
python -m pytest -q tests
python -m changeattest --version
```

The CI matrix runs Python 3.11 and 3.13 on Ubuntu and Windows.
Do not claim OS or tooling coverage that CI did not execute.

## Review checklist

- No unsafe commands or imports from untrusted repository config.
- Provenance and policy statements accurately reflect what was verified.
- No private keys or secrets in source, tests, logs, or new evidence.
- CLI exit codes distinguish failures, errors, and empty coverage.
- Source content for protected gates is read from immutable Git objects.
- Cross-platform file names and Git behavior have regression cases.
- `changeattest tools` is never silently substituted for the trusted
  policy engine: external tools may run arbitrary project code.

## Sensitive paths

PRs modifying the gate, the security policy, dependencies, workflows,
signing logic or evidence semantics require increased scrutiny. CI status
checks alone do not replace human review.
