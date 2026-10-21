# ChangeAttest evidence v1

## Scope and non-goals

ChangeAttest v0.1-dev adds a deterministic, local **unsigned** verification
record for a fixed allowlist of non-mutating Python checks. It is not a
cryptographic attestation authority, execution sandbox, dependency scanner,
provenance proof, or independent CI service.

## Invocation

```sh
changeattest check --scope staged --report evidence.json
changeattest check --scope tracked --report evidence.json
```

The default scope is `staged`. Commands select files relative to the Git root,
not shell globs. The `tracked` scope uses the current working tree. The
`staged` scope uses paths from the index but runs checks on working-tree files;
it **refuses** to verify staged files whose worktree bytes diverge from the
index. This prevents a particularly common false claim, but is not a
transactional filesystem snapshot: concurrent changes during the scan are
not yet protected against.

Untracked files are not included. Symlinks, missing entries and files above
`max_file_bytes` cause incomplete verification (`exit 2`). Extensions are
used for JSON/TOML/YAML checks; generic checks run on applicable regular files.

## Report shape

Illustrative fields (the values below are examples, not actual test output):

```json
{
  "schema": "changeattest.report.v1",
  "scope": "staged",
  "head": null,
  "file_count": 1,
  "files": [
    {"path": "a.json", "sha256": "<sha256 of checked bytes>"}
  ],
  "checks": [
    {"id": "json", "status": "passed", "file_count": 1,
     "exit_code": 0, "output_sha256": "<sha256 of stdout, NUL, stderr>"}
  ],
  "problems": [],
  "status": "passed",
  "report_sha256": "<sha256 of canonical record without this field>"
}
```

**Canonical serialization:** `json.dumps(..., sort_keys=True,
ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\\n'`.
SHA-256 hashes the UTF-8 bytes of this serialization with
`report_sha256` removed. Report ordering and values are stable for the
same workspace and tool behavior. No wall clock timestamps are injected.

Statuses:

- `passed`: all selected checks completed successfully and no files were
  unverified.
- `failed`: at least one checker identified a problem (exit 1).
- `error`: a tool error, timeout, unsafe file, mismatched staged file,
  size limit, or inability to verify the selected snapshot.
- `no-files`: empty selection; **does not mean any code was verified**.

Checker statuses may also be `skipped` when no matching files were found.
The CLI returns 0/1/2 for passed/no-files, failed, and error respectively.
CLI configuration errors return 2 and are not claimed to have emitted reports.

## Security boundaries

- No shell invocation and no custom executable paths from project config.
- Only vetted built-in module IDs; strict TOML parser rejects unexpected
  keys and duplicate check IDs.
- File selection comes from NUL-delimited Git outputs.
- The runner does not read through symlinks, and detects staged/worktree
  mismatches rather than silently checking different content.
- Raw stdout and stderr are not saved in reports or printed by default,
  since validators may expose credentials.
- `output_sha256` is a fingerprint of observed output, not content.
- The report includes file names and hashes and therefore **may disclose
  repository metadata**. Secure it appropriately.
- A malicious developer can modify or remove their local hooks, config or
  reports. A checksum does not authenticate the runner, the environment,
  the producer, or the integrity of the reported file hashes.

For meaningful enforcement, use protected CI with pinned build dependencies,
restricted write permissions and independently executed checks. Signed
attestations, authenticated policy and race-free snapshotting are later work.
