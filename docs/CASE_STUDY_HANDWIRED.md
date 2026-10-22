# Field validation: Handwired WebGPU repository

**Date:** 2026-10-21
**Target:** [Chrisbryan17/handwired](https://github.com/Chrisbryan17/handwired)
**Trial PR:** [Handwired #18](https://github.com/Chrisbryan17/handwired/pull/18)
**Observed evidence:** [read-only ChangeAttest CI run](https://github.com/Chrisbryan17/handwired/actions/runs/39693589872)
**Result:** `ChangeAttest policy gate: PASS`

This is a real cross-repository execution of the published ChangeAttest
source revision, not a generated screenshot, simulation or hypothetical
installation.

## Repository context

Handwired is an open-source JavaScript/TypeScript/WebGPU engineering
repository with source, experimental labs and GPU/CPU test systems.
The installation was deliberately scoped to source and configuration
verification; it does NOT attempt to replace Handwired's GPU tests,
WebGPU hardware validation, TypeScript checking, or Visual Lab deployment.

## Exact experiment

- A separate branch added only a scoped TOML policy and advisory CI workflow.
- CI installed a reviewed, full commit SHA of ChangeAttest:
  `33196ef146498243e457cee1f1ef9ccbf5e224f3`.
- The policy inspected Git HEAD objects under `src/`, `lab/`,
  and `.github/workflows/`. At trial preparation, GitHub's source tree
  reported 1,129 tracked files under `src/` and `lab/`; workflow files
  add a small number more.
- Mandatory checks: YAML syntax, unresolved merge conflicts, and
  recognizable private-key patterns.
- Checks ran in a read-only GitHub-hosted Ubuntu job with no production
  secrets and `contents: read` token permissions.
- The exact `git rev-parse HEAD` was supplied as expected commit identity.
- JSON evidence was uploaded as a short-retention job artifact.

The [GitHub Actions job log](https://github.com/Chrisbryan17/handwired/actions/runs/39693589872)
reported:

```text
ChangeAttest policy gate: PASS
```

This establishes that the selected checks completed successfully on the
submitted revision. It does NOT establish absence of vulnerabilities,
malicious source code, false negatives, or correct WebGPU behavior.

## Reproduce locally

From a Handwired checkout at the tested revision, with Python 3.13 and
Git installed:

```bash
python -m pip install "git+https://github.com/Chrisbryan17/changeattest.git@33196ef146498243e457cee1f1ef9ccbf5e224f3"
python -I -m changeattest gate --root . \
  --policy .github/changeattest-policy.toml \
  --expected-head "$(git rev-parse HEAD)" \
  --report changeattest-evidence.json
```

The report above is an **unsigned checksum-backed receipt**. Its output
file is advisory evidence, not a signature or an independent CI identity
attestation.

## What the experiment does NOT prove

- Handwired's code was modified or its existing tests were replaced.
- The trial policy is independently protected: it currently resides inside
  the candidate PR checkout and is advisory only. It is not enforced by a
  Handwired main-branch ruleset.
- ChangeAttest can typecheck TypeScript or execute GPU kernels in its
  trusted built-in gate.
- Container sandbox-escape resistance, unattended release approval, or
  end-to-end software supply-chain security.
- Numeric speedup compared with Handwired's existing CI; none was measured.

## Follow-on validation

For credible benchmarks, record wall-clock overhead, use targeted error
injections on disposable branches, assess false positive/negative cases,
and measure actual overlap with Handwired's existing CPU/TypeScript/visual
tests. Do not claim unique coverage without such experiments.
