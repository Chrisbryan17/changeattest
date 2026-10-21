# Advisory Python test-impact planning

ChangeAttest can now derive a conservative Python import graph from immutable
Git commit objects and summarize which test files appear relevant to a proposed
change. This is **not a substitute for the complete test matrix**.

## CLI

```bash
changeattest impact \
  --root . \
  --base "$(git rev-parse HEAD~1)" \
  --head "$(git rev-parse HEAD)" \
  --report ./changeattest-impact.json
```

Supply **full** commit SHAs, not short Git references. The report includes
the base/head, changed paths, discovered test files, transitive affected
Python modules, selected test suggestions, fallback reasons, and an
explicit `mandatory_ci_recommendation=run-full-test-suite` decision.

Store advisory output outside the source checkout when using the separate
clean-tree Docker lint cache.

## Modes

- `targeted-advisory`: all changed paths are supported Python sources;
  the static graph finds at least one test importing them (possibly through
  multiple local module layers). It suggests tests for optional developer
  iteration. The result is not independently established full coverage.
- `full`: no trustworthy targeted selection was possible, so all
  discovered tests are suggested. A full fallback occurs if the change
  includes a non-Python file, deleted module, global `__init__.py` or
  `conftest.py`, dynamic/star import, unparseable Python source,
  ambiguous local module, no test match, or no diff.

The graph reads **Git commit tree bytes**, not current working-tree content.
It discovers `test_*.py` and `*_test.py` files, recognizes `import`
and `from ... import ...`, including relative imports, and follows
imports transitively to test files.

## Continuous integration

The `.github/workflows/impact-advisory.yml` workflow reports the
suggestion on pull requests using read-only permissions. It uploads a JSON
plan as an inspectable short-retention artifact.

The existing Linux/Windows full regression matrix and required
`verified-policy-gate` remain separate and unchanged. No PR is
allowed to claim validation merely because an impact plan was generated.

## Known limitations

Python imports can be computed at runtime, plugins can load files by path,
pytest configuration and fixtures can implicitly influence tests, and
extensions, code generation, package entry points, monkeypatching, and
reflection do not necessarily appear in a static graph. The current parser
does not claim soundness for arbitrary Python programs.

In particular, a `targeted-advisory` outcome is a *development hint*,
never an assurance that all affected tests have been found. No test
execution occurs in the impact command. A percentage reduction represents
theoretical test-file count reduction, **not measured runtime savings**.

This v1 capability is Python-specific; JavaScript, Rust, Go and other
languages require their own trustworthy dependency graphs and independent
validation before selective enforcement can be considered.
