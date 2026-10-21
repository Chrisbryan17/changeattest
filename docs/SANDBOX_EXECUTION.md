# Restricted Docker tool adapters

**Status:** opt-in restricted Docker execution with tested command
construction on Linux and Windows. A dedicated GitHub Actions job now
executes the standard-library AST checker in a real Linux Docker container
and requires a valid Python file to pass and an invalid file to fail. This
does not establish Windows Docker runtime coverage or hostile-container
escape resistance.

`changeattest tools` historically launches external linters and test runners
directly on the developer's computer. Those programs, config plugins, and tests
can execute arbitrary repository-controlled code. The trusted built-in
`changeattest gate` deliberately DOES NOT use them.

## Restrict optional external tools

Build or obtain a reviewed image containing the exact tools needed. Pull the
image locally and record its full immutable `sha256` digest, then run:

```bash
changeattest tools \
  --root . --adapter ruff --adapter pytest \
  --docker-image 'example.invalid/ci-tools@sha256:<64-hex-digest>' \
  --jobs 2 --timeout 120 --report tools.json
```

The image reference **must have a full digest**, not a moving tag.
`--pull=never` prevents a hidden registry download during the check. A
missing Docker daemon, local image, required executable, or image runtime
causes the tool check to fail/incomplete; it will not silently fall back
to host execution.

The container is started without shell interpolation, without network
access, as UID/GID 65534, with read-only project bind mount and read-only
root filesystem, no Linux capabilities, no-new-privileges, bounded CPU,
memory and process count, and a limited writable `/tmp` filesystem.
No Docker socket, SSH key, cloud token, host home directory or project
write permissions are intentionally forwarded. Project paths are validated
for escapes before being supplied to the container.

Some tools require writable caches, package registries or dependencies:
configure the image in advance. A read-only source mount prevents in-place
autofixes. The `pytest` adapter runs project code; this is an intentionally
*untrusted* evaluation mode, so use disposable and unprivileged workers.

## Runtime smoke test

The `docker-restrictions-linux-smoke` job in
`.github/workflows/main.yml` pulls the official Python 3.13 slim image on
a disposable Linux runner, resolves its actual OCI sha256 digest, and passes
that digest into `changeattest tools --adapter python-ast-stdlib`. The
image is selected by a moving tag **only for the smoke test**; real
production execution should pin an independently approved full digest.

The first check parses a valid committed Python file under the restricted
container and must pass. The second presents invalid Python syntax and must
fail with nonzero exit code. The check uses Python's standard `ast.parse`;
it doesn't install or execute project-controlled plugins.

This proves basic command/runtime integration when the job succeeds, not
that the Docker host is protected against container escapes, side channels
or kernel vulnerabilities.

## Limitations

- Docker is not a security boundary equivalent to a hardened microVM or VM.
  Run an up-to-date Docker engine on disposable hosts without valuable
  host credentials. Prefer rootless/user-namespace and mandatory-access
  controls where operationally possible.
- Image approval, software bill of materials, vulnerability scanning,
  signature verification and provenance are NOT automated by this command.
- The image may include malicious software even if a digest is pinned.
  Digest pinning proves content identity, not software trust.
- Docker runtime capabilities differ between Windows, macOS and Linux;
  not all limits are equally enforced on Docker Desktop.
- The default `changeattest tools` execution without `--docker-image`
  remains unrestricted host execution and prints a warning.
- Scanner output is hashed but not reproduced verbatim in evidence by
  default; this reduces secret exposure, but repository paths and metadata
  may still be sensitive.
- No remote distributed workers, eviction-safe cache, or build graph
  scheduler is included yet.

See [ADR 0001](ADR-0001-TRUSTED-CI.md) for the separate security model of
required GitHub status checks.
