# Security policy

ChangeAttest is pre-release software. Do not treat a passing check as
proof that a code change is safe, that tests ran in a trusted environment,
or that a release artifact was authenticated.

## Reporting suspected vulnerabilities

Use GitHub's private vulnerability-reporting or security advisory workflow
if available for this repository. Do not post secrets or exploit details in
public issues. If private reporting is unavailable, request a private
contact channel without including exploit details.

## Security invariants

- The mandatory CI gate must load its policy and evaluator from a protected
  baseline, never from the unreviewed PR working tree.
- No untrusted executable/plugins in the trusted gate; external tool
  adapters are optional and may execute arbitrary project-local code.
- Source assertions are bound to immutable committed Git object bytes.
- Signed envelopes are trustworthy only when the verifier independently
  trusts the signing public key **and** the signer controls execution.
- The dashboard is restricted to localhost and is not an authenticated
  network service.
- No test receipt proves test execution unless a controlled runner signs
  it and the signature is checked against its public key.

## Known non-goals

No cryptographic runner identity, sandboxing of third-party test code,
hardware-based remote attestation, guaranteed secret scanning coverage,
or enterprise multi-tenant isolation is currently provided.
