# AI-agent change contracts

Any coding agent may emit changes, but ChangeAttest does not identify or
authenticate the agent. The `agent-review` command verifies a Git commit
diff against a version-controlled allow/deny contract. A signing key is an
optional separate trust anchor for independent test execution.

## Contract

```json
{
  "version": 1,
  "allowed_paths": ["src/*", "tests/*"],
  "forbidden_paths": [".github/workflows/*", "secrets/*"],
  "required_checks": ["test-suite:unit-results.xml"],
  "max_changed_files": 100
}
```

If `required_checks` is nonempty, an agent MUST supply evidence signed
by a trusted verification key. The key should belong to controlled CI and
not to the coding agent. No key means missing evidence and a blocked verdict.

```bash
changeattest agent-review --root . \
  --contract contract.json --base <BASE_SHA> --head <HEAD_SHA> \
  --attestation signed-ci-tests.json \
  --trusted-key trusted-ci-ed25519-public.pem \
  --report agent-verdict.json
```

The sample GitHub `agent-change-scope` workflow is advisory and currently
checks change scope only. It has no agent identity provider or trusted
signing key, and does not guarantee that an AI claim is true. Required
checks and signed execution evidence can be layered in as a CI operator
introduces a real trusted signing service.

The default repo contract denies changes to the trusted policy and license.
It is not required by the current branch ruleset; legitimate changes may
need maintainer approval when a stronger rule is introduced.

## Threat boundary

Path patterns are deterministic and checked against Git history, not
untracked files. Use non-secret CI runners and never grant agent-origin
change verification a token that can modify protected branches.
