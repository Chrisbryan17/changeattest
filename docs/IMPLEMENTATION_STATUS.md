# ChangeAttest implementation ledger

Last reviewed: 2026-10-21, after merged PRs #1–#12.
GitHub repository: https://github.com/Chrisbryan17/changeattest

**Pre-release. Working software, not a finished universal trust platform.**
The current CLI, build, GitHub CI policy gate and expanded modules passed
Python 3.11/3.13 tests on Linux and Windows. Tag signing and unrestricted
third-party-code isolation have different verification requirements.

| Workstream | Implemented on `main` | Still open |
| --- | --- | --- |
| Source integrity | Immutable Git HEAD tree validation, SHA-256 file hashes, path/symlink/size rejection, **bounded Git batch object reads** (#10) | Merkle evidence across generated artifacts and external dependencies, quantified large-scale performance benchmarks |
| Local and CI quality | Legacy MIT hook catalogue, standalone `changeattest` CLI, explicit policy requirements, strict Git commit matching, required GitHub status gate | Expand protected policy coverage and workflow tamper governance, protected human reviews |
| Parallel tool execution | Ruff, Biome, ESLint, TypeScript, Go, Cargo, pytest adapters | Build/test impact graphs, general plugin SDK, memory-safe scalable scheduling |
| Restricted third-party tools | **Opt-in Docker backend** (#9), digest-pinned images, read-only workspace, disabled network, dropped capabilities, non-root process and resource limits | Container runtime integration tests on real supported hosts, hardened VM/microVM isolation, independent security assessment |
| Execution performance | Batched Git-object reads (#10), bounded parallel adapters, **opt-in advisory Ruff result cache** (#11) | Cross-tool incremental scheduling and cache invalidation proofs, persistent distributed cache, benchmarked speedup |
| Evidence | Deterministic unsigned JSON, Ed25519 verification with trusted keys, JUnit test receipts, HTML/SARIF/JUnit exports | Independently authenticated CI runner, signed executed-test provenance, Sigstore/in-toto integration with policy evidence |
| Release provenance | **Tag-only GitHub OIDC/Sigstore artifact attestation workflow** (#12), version/tag consistency validation and `gh attestation verify` step | Run a reviewed version tag and validate generated attestations; immutable GitHub release setting; trusted publication workflow |
| AI-agent control | Git diff scope contracts, denied paths, signed evidence option, advisory GitHub agent scope workflow | Agent identity/authentication, isolated remediation loop, IDE/agent framework integration, risk analysis |
| CI and repository rules | Reviewed default-branch source for policy/evaluator, read-only CI runner, required `verified-policy-gate`, CI matrix, wheel/sdist smoke verification | Rules requiring security reviews for workflow/policy edits; GitLab/Bitbucket integrations and self-hosted hardened runners |
| Local reporting | SQLite history, read-only localhost evidence viewer, machine-readable reports | Authenticated multi-user API, team dashboard, retained audit policy, hosted storage |
| Organization policy | Strict TOML policies, monotonic policy overlays | Central authorization, approval queues, exception expiry, SSO/OIDC account service |
| OSS and commercial | MIT attribution, README, SECURITY.md, CONTRIBUTING.md, CODEOWNERS, reproducible source code and regression suites | Stable version, published package/release, comprehensive docs site, pricing and SaaS deployment |
| External validation | Cross-platform CI, static security regressions, package-build smoke tests | Demonstrations on Aether, Handwired, Revenue OS; actual attack simulations and independent security review |

## Verified test checkpoint

PR #12 ran **531 tests passed** per Linux Python version and **514 tests
passed, 15 skipped, 2 expected failures** per Windows Python version.
The independent gate, agent scope check and package smoke also succeeded.
The post-merge default-branch matrix should be reviewed separately on GitHub
before treating the latest commit as verified.

## Trust boundaries that must remain explicit

1. `gate` reads Git objects and independently runs allowlisted checks.
   It must never accept advisory cache hits as a substitute for execution.
2. `tools --docker-image` is an **opt-in restricted container**, not proof
   of perfect malicious-code isolation. Actual Docker/host isolation has not
   been penetration tested on each platform.
3. `tools --cache-dir` reuses Ruff successes only for a clean checkout and
   digest-pinned image, clearly labeled `cached-passed` and advisory. It
   is outside required policy verification.
4. An Ed25519 signature authenticates key possession, not test execution.
5. A GitHub tag attestation workflow now exists, but **no tag-triggered
   attestation run is claimed completed** without real signed artifacts.
6. A required GitHub check is active, but changes to the check workflow
   and sensitive policy files still need enforced independent review; see
   [ADR 0001](ADR-0001-TRUSTED-CI.md).
7. GitHub release immutability is a distinct administrative setting and
   remains unverified/not enabled by this repository's source code.
8. Hosting, enterprise governance and comprehensive coverage remain
   future work. There is no production SaaS or secure multitenant service.

## Near-term implementation priorities

- Harden protected workflow/policy governance through GitHub rules and
  independent review; test simulated workflow-bypass attempts.
- Verify Docker restrictions against actual Linux and Windows Docker
  engines and pin reviewed third-party tool images.
- Build deterministic source-to-test dependency graphs and measure incremental
  execution savings against full execution.
- Validate a tagged test release's GitHub-generated Sigstore provenance and
  implement a release publication process with immutable releases.
- Run ChangeAttest on real repositories and publish measured comparisons.
- Only after these controls: expand enterprise identity, central policy,
  protected remote execution and hosted evidence services.

New milestones must include regression tests and execution evidence; do not
mark a workstream complete merely because a module or workflow exists.

## Additional verified work (PRs #14–#17, 2026-10-21)

- **#14: Python change-impact intelligence.** Reads exact Git revision
  objects, builds a transitive Python import graph and suggests relevant
  tests. Automatically recommends the full suite when analysis is
  ambiguous. Reports are explicitly advisory; mandatory CI still executes
  the full matrix.
- **#15: GitHub Actions static security audit.** Inspect committed
  workflow definitions for privileged PR execution, risky permissions,
  shell injection patterns and non-pinned actions. The first live
  repository audit found 0 critical, 0 high and 20 medium findings.
- **#16: GitHub Actions dependency pinning.** Upgraded reviewed actions,
  pinned every remote action to a full upstream commit SHA, disabled
  PR-checkout credential persistence and added regression enforcement.
  The next self-audit reported 0 critical, 0 high and 0 medium findings.
- **#17: Real Linux Docker sandbox smoke.** Added a standard-library
  Python AST adapter and a live GitHub Actions job that passed valid
  Python and rejected invalid Python inside a restricted container.
  Windows Docker execution and hostile-host security remain unverified.
- **External project validation:** Tested the ChangeAttest policy
  gate against the real
  [Handwired WebGPU repository](CASE_STUDY_HANDWIRED.md),
  not just synthetic test fixtures. The advisory CI job returned PASS.

### Outstanding verification milestones

Enforce trusted workflow approval through repository/organization governance;
test adversarial PR workflow modifications; validate signed, tagged release
provenance and immutable publication; extend typed language/test coverage;
measure actual runtime performance improvements and false-negative rates;
and implement secure tenant isolation before promising any hosted service.

