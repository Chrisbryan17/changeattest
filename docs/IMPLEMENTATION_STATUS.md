# ChangeAttest platform implementation ledger

As of the platform-expansion branch started 2026-10-21.
**The status of this branch is subject to passing Linux and Windows CI and
merging its PR. The full original product roadmap is NOT yet complete.**

| Milestone | Concrete implemented scope | Not yet provided |
| --- | --- | --- |
| 4. Verification security | Immutable Git-commit blobs for the trusted tracked gate; fail-closed symlinks and size limits; mandatory GitHub status rule | Restricted approver governance, cryptographic CI identity, full policy protection |
| 5. Universal execution | Seven built-in validators; opt-in parallel tool adapters for Ruff, Biome, ESLint, tsc, go vet, cargo fmt, pytest | Adapter isolation, incremental test mapping, persistent content cache, custom trusted plugin SDK |
| 6. Evidence | SHA-256 JSON evidence, optional Ed25519 envelopes, JUnit result receipts | Sigstore/in-toto interoperability, secure signing service, attestations tied to external build artifacts |
| 7. AI agents | Diff scope contracts with forbidden paths and signed test receipt requirement | Agent authentication, bounded remediation agent, model provider plugins, code comprehension |
| 8. Developer experience | CLI, HTML/SARIF/JUnit exports, local evidence viewer | IDE plugins, TUI, per-line diagnostics without secret leakage |
| 9. CI ecosystem | Protected-baseline GitHub CI gate, reusable composite Action, agent scope contract | GitLab/Bitbucket, merge queues, third-party cross-org demos |
| 10. Governance | Explicit policy, monotonic organization-policy overlays, branch status ruleset | Organization policy registry, multi-tenant authorization, managed exception workflow |
| 11. Hosting | Local SQLite vault and loopback-only read-only HTTP dashboard | Hosted SaaS, secure tenancy, SSO, authenticated APIs, billing, production deployments |
| 12. OSS maturity | MIT attribution, CONTRIBUTING, SECURITY, CODEOWNERS, package-build CI | Published immutable release, independent GitHub fork detachment, adoption proof |
| 13. Validation | Python 3.11/3.13 Windows and Linux matrix; optional check adapters | Benchmark against incumbents, Aether/Handwired/Revenue OS verified integrations |

## Critical trust distinctions

- An Ed25519 signature proves that someone held the private key, not that
  a test actually executed.
- A trusted Git commit scanner verifies the HEAD tree bytes at scan time,
  but does not verify every dependency, generated artifact or runtime.
- Optional external test tools may execute project-local code; they are
  not a sandboxed or hard-isolated validator.
- The local dashboard provides no remote authentication or hosted SLA.
- GitHub required-status protection is active, but the project's current
  governance does not guarantee mandatory external human approval for
  workflow and policy modifications.

## Product completion criteria

A broad 'complete' claim requires external trust anchoring, authenticated
test execution, secure plugin isolation, immutable release packages,
managed organization policies, integrated IDE/CI support, production
backend controls, security review and deployment case studies. These are
not all in the present branch.
