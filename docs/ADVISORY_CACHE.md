# Advisory result caching

`changeattest tools` can reuse certain *local advisory* lint results.
The protected `changeattest gate` never consumes this cache. A cache hit
does **not** establish that verification was executed in the current run.

## Usage

Choose a reviewed image pinned to a full registry `sha256` digest.
Store the cache **outside** the target repository:

```bash
changeattest tools --adapter ruff \
  --docker-image 'registry.example.invalid/tools@sha256:<reviewed-image-digest>' \
  --cache-dir "$HOME/.cache/changeattest" \
  --report "$HOME/.cache/changeattest-tools.json"
```

Store generated reports **outside** the checkout too. A report created as an
untracked file inside the checkout deliberately disables later cache hits.

A valid cache hit produces check status `cached-passed` and overall status
`passed-with-cache`. Those statuses explicitly distinguish reused local
results from fresh runs. The CLI returns success for this *advisory* mode,
but neither cached status is accepted by the mandatory policy evaluator.

## Conservative eligibility

Only the **Ruff file-level static check** is cacheable for now.
Pytest, TypeScript project builds, Cargo, Go vet, Biome and ESLint always
execute afresh. The cache requires:

- A clean Git tracked and untracked working tree.
- An unchanged full Git commit and tree identity.
- The same explicitly reviewed, digest-pinned local Docker image.
- The same adapter command and selected file paths.
- A positive prior result not older than 3600 seconds.
- A cache folder outside the repository checkout.

A missing, stale, malformed or inconsistent cache entry results in a fresh
execution, not a pass by default. No local cache data is added to an
unsigned report as if it were independently trusted.

## Limitations and security

The cache is a **performance hint**, not a tamper-proof evidence source.
Cache files are intentionally local and unsigned. An attacker with local
filesystem write access can change them; nothing from this store belongs
in release verification or CI governance. This feature does not turn
third-party tools into a trusted sandboxed execution service.

Clean Git status does not include every ignored filesystem artifact, and
external tools may be affected by dynamic/runtime inputs. Consequently,
the cache is not a correctness guarantee. Do not use advisory caching in
regulated or security-sensitive release gates. Prefer CI fresh execution.
