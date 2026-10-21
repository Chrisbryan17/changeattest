# Legacy issue audit

Date: 2026-10-21

This document tracks defects and limitations inherited from the MIT-licensed hook collection. These are independent ChangeAttest implementations. No changes or requests are being submitted to the upstream organization.

| Original issue | ChangeAttest status | Scope / limitations |
| --- | --- | --- |
| [#749](https://github.com/pre-commit/pre-commit-hooks/issues/749) | Implemented on foundation branch | POSIX filesystem fallback outside Git repositories; index remains authoritative in Git. Native POSIX regression environment still required. |
| [#612](https://github.com/pre-commit/pre-commit-hooks/issues/612) | Implemented on foundation branch | Ensure pip's primary `--index-url` (including `-i` and assignment syntax) precedes `--extra-index-url` in sorted files. Does not make extra package indexes secure; dependency confusion is a separate risk. |
| [#780](https://github.com/pre-commit/pre-commit-hooks/issues/780) | Implemented on foundation branch | Decimal-aware JSON number handling using `simplejson`; regression cases check long decimal literals and nested arrays. Numeric notation may still be normalized. |
| [#1020](https://github.com/pre-commit/pre-commit-hooks/issues/1020) | New opt-in hook on foundation branch | `check-lfs-attributes` compares staged filter attributes with staged Git blob content. Recognizes canonical LFS pointer files up to 64 KiB; does not require git-lfs. |
| [#339](https://github.com/pre-commit/pre-commit-hooks/issues/339) | New opt-in hook on foundation branch | `detect-openpgp-secret-key` checks recognizable OpenPGP secret-key packet headers at file start without libmagic. Best-effort only: it does not parse every possible OpenPGP representation, find keys embedded later in arbitrary binary streams, or replace secret scanning. |
| [#1218](https://github.com/pre-commit/pre-commit-hooks/issues/1218) | Requires repository administration | GitHub immutable release setting is not a source-code patch. Until separately verified, users should pin reviewed commit SHAs. |

## Verification policy

"Implemented" here means code and test cases exist in the foundation branch. It does **not** by itself mean the combined test suite or all operating-system matrix checks have passed. Merge only after CI and review. The existing fork retains its history and MIT copyright notices.

## Historical status

Previously closed upstream proposals have also been considered as evidence, but upstream PR state is not a determination that a ChangeAttest change is correct or incorrect. We test and own our behavior independently.

## Backlog after the issue pass

1. Complete CI validation on Linux and Windows where feasible.
2. Document per-hook failure behavior, complexity, and platform constraints.
3. Establish immutable releases and versioning independent of upstream.
4. Introduce a distinct `changeattest` package and CLI without silently breaking legacy hook consumers.
5. Build deterministic evidence reports, then policy evaluation and change-aware orchestration.
