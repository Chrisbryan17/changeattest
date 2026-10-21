# Adopting ChangeAttest

## Stable local experience

For now install from a **reviewed full Git commit SHA** and use a
disposable environment:

```bash
python -m pip install 'changeattest[attest] @ git+https://github.com/Chrisbryan17/changeattest.git@<REVIEWED_SHA>'
changeattest --version
changeattest check --scope tracked --report evidence.json
changeattest render --input evidence.json --format html --output evidence.html
```

Pin GitHub Actions and third-party tools to trusted commits where possible.
Never use unverified AI-generated release claims as proof a test was run.

## CI

Use the composite `./.github/actions/verify` with `engine-ref` set to
a reviewed full commit SHA and `policy` supplied from the protected default
branch. In a third-party repository you may reference the action as
`Chrisbryan17/changeattest/.github/actions/verify@<REVIEWED_SHA>` after checking
out the target revision. Require its gate status through a repository rule.

**Untrusted PRs:** workflows that execute user-supplied tests/plugins must run
without secrets or write credentials, in disposable environments. The
`changeattest tools` command does not sandbox custom toolchain code.

## Reports and local dashboard

```bash
changeattest render --input evidence.json --format sarif --output findings.sarif
changeattest render --input evidence.json --format junit --output checks.xml
changeattest store --input evidence.json --database ~/.changeattest/history.sqlite
changeattest serve --database ~/.changeattest/history.sqlite --port 8765
```

The dashboard serves *read-only* content at `http://127.0.0.1:8765`.
It is not a secure network/enterprise service.

## External test verification

```bash
pytest -q --junitxml=results.xml
changeattest junit-evidence --junit results.xml --report test-evidence.json
```

Only a controlled CI runner should sign the receipt. A local signature
without a trusted key and trusted test execution conveys no test provenance.

## Product maturity

This project is still pre-release. There is no published GitHub release,
supported SaaS, managed remote test sandbox or proven performance advantage
over existing commercial validation products.
