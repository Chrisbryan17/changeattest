"""Conservative advisory impact graph derived from immutable Git objects.

This module NEVER gates a release or asserts that unselected tests are safe
to omit. It produces transparent change-to-test suggestions, falling back
to the full suite whenever a supported assumption is violated.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from changeattest.engine import canonical
from changeattest.git_batch import GitObjectError
from changeattest.git_batch import blob_contents
from changeattest.git_batch import blob_sizes

_SHA = re.compile(r'[a-f0-9]{40}(?:[a-f0-9]{24})?\Z')
_MAX_PY_FILES = 6000
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_SOURCE = 64 * 1024 * 1024


class ImpactError(ValueError):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        cmd = subprocess.run(
            ('git', *args), cwd=root, capture_output=True, timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImpactError('Unable to inspect Git history') from exc
    if cmd.returncode:
        raise ImpactError('Unable to inspect Git history')
    return cmd.stdout


def _test(path: str) -> bool:
    p = Path(path)
    return (
        p.suffix == '.py'
        and ('tests' in p.parts or p.name.startswith('test_'))
        and (p.name.startswith('test_') or p.name.endswith('_test.py'))
    )


def _module(path: str) -> str:
    parts = list(Path(path).with_suffix('').parts)
    if parts and parts[0] == 'src':
        parts.pop(0)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def _resolve_import(name: str, modules: dict[str, str]) -> set[str]:
    """A package import can expose both a module and its __init__.py."""
    found: set[str] = set()
    bits = name.split('.')
    while bits:
        candidate = '.'.join(bits)
        if candidate in modules:
            found.add(modules[candidate])
        bits.pop()
    return found


def _imports(tree: ast.AST, source: str,
             modules: dict[str, str]) -> tuple[set[str], bool]:
    found: set[str] = set()
    dangerous = False
    name = _module(source)
    path = Path(source)
    package = name if path.name == '__init__.py' else name.rpartition('.')[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(_resolve_import(alias.name, modules))
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == '*' for a in node.names):
                # Star exports and module __getattr__ are not statically safe.
                dangerous = True
            if node.level:
                chunks = package.split('.') if package else []
                if node.level > len(chunks):
                    dangerous = True
                    continue
                base = '.'.join(chunks[:len(chunks) - node.level + 1])
                if node.module:
                    base = '.'.join(x for x in (base, node.module) if x)
            else:
                base = node.module or ''
            if base:
                found.update(_resolve_import(base, modules))
            for alias in node.names:
                submodule = '.'.join(x for x in (base, alias.name) if x)
                found.update(_resolve_import(submodule, modules))
        elif isinstance(node, ast.Call):
            call = node.func
            if (isinstance(call, ast.Name) and call.id in ('__import__', 'import_module', 'reload')) or (
                isinstance(call, ast.Attribute)
                and call.attr in ('import_module', 'reload')
            ):
                dangerous = True
    found.discard(source)
    return found, dangerous


def _py_files_from_commit(root: Path, head: str) -> dict[str, bytes]:
    output = _git(root, 'ls-tree', '-rz', '--full-tree', head)
    entries: dict[str, str] = {}
    for line in output.split(b'\0'):
        if not line:
            continue
        try:
            meta, raw_path = line.split(b'\t', 1)
            mode, kind, oid = meta.split()
        except ValueError as exc:
            raise ImpactError('Invalid Git tree listing') from exc
        path = os.fsdecode(raw_path)
        if not path.endswith('.py'):
            continue
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise ImpactError('Unsupported Python source Git object')
        if path.startswith('/') or '..' in Path(path).parts:
            raise ImpactError('Invalid Python source path')
        entries[path] = oid.decode('ascii')
        if len(entries) > _MAX_PY_FILES:
            raise ImpactError('Too many Python files for advisory analysis')
    try:
        sizes = blob_sizes(root, list(entries.values()))
        if any(sizes[oid] > _MAX_SOURCE_BYTES for oid in entries.values()):
            raise ImpactError('Oversized Python source: fall back to full suite')
        if sum(sizes[oid] for oid in entries.values()) > _MAX_TOTAL_SOURCE:
            raise ImpactError('Python source exceeds analysis memory budget')
        data = blob_contents(root, list(entries.values()), sizes)
    except (GitObjectError, KeyError) as exc:
        raise ImpactError('Unable to read Git Python object bytes') from exc
    return {path: data[oid] for path, oid in entries.items()}


def _changed(root: Path, base: str, head: str) -> list[str]:
    raw = _git(
        root, 'diff', '--no-renames', '--name-only', '-z',
        '--diff-filter=ACDMRTUXB', base, head, '--',
    )
    return sorted(set(os.fsdecode(x) for x in raw.split(b'\0') if x))


def plan_impact(root: Path, base: str, head: str) -> dict[str, Any]:
    """Compute advisory test suggestions, with explained full-suite fallback."""
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(head):
        raise ImpactError('Both base and head must be full Git commit SHA values')
    root = root.resolve()
    files = _changed(root, base, head)
    sources = _py_files_from_commit(root, head)
    tests = sorted(name for name in sources if _test(name))
    reasons: set[str] = set()
    selected: set[str] = set()
    affected: set[str] = set()
    if not files:
        reasons.add('no-diff')
    if not tests:
        reasons.add('no-discovered-tests')
    if any(not name.endswith('.py') for name in files):
        reasons.add('non-python-change')
    if any(name not in sources for name in files if name.endswith('.py')):
        reasons.add('deleted-or-unreadable-python')
    if any(Path(name).name in ('conftest.py', '__init__.py') for name in files):
        reasons.add('global-import-or-fixture-change')

    modules: dict[str, str] = {}
    for path in sorted(sources):
        key = _module(path)
        if not key or key in modules:
            reasons.add('ambiguous-python-module')
        else:
            modules[key] = path

    reverse: dict[str, set[str]] = defaultdict(set)
    for path, content in sorted(sources.items()):
        try:
            tree = ast.parse(content, filename=path)
        except (SyntaxError, UnicodeError, ValueError):
            reasons.add('source-parse-error')
            continue
        imports, dynamic = _imports(tree, path, modules)
        if dynamic:
            reasons.add('dynamic-or-star-import')
        for imported in imports:
            reverse[imported].add(path)

    changed_py = set(path for path in files if path in sources)
    selected.update(path for path in changed_py if _test(path))
    queue = deque(sorted(changed_py))
    seen = set(queue)
    while queue:
        path = queue.popleft()
        affected.add(path)
        for importer in sorted(reverse.get(path, ())):
            if importer not in seen:
                seen.add(importer)
                queue.append(importer)
                if _test(importer):
                    selected.add(importer)
    if changed_py and not selected:
        reasons.add('no-test-dependency-match')

    decision = 'full' if reasons else 'targeted-advisory'
    planned = tests if decision == 'full' else sorted(selected)
    report: dict[str, Any] = {
        'schema': 'changeattest.impact.v1',
        'base': base, 'head': head, 'status': 'advisory-only',
        'decision': decision,
        'fallback_reasons': sorted(reasons),
        'changed_files': files, 'affected_python_files': sorted(affected),
        'all_tests': tests, 'suggested_tests': planned,
        'selected_count': len(planned), 'total_count': len(tests),
        'potential_test_reduction_percent': (
            round(100 * (1 - len(planned) / len(tests)), 2) if tests else 0.0
        ),
        'mandatory_ci_recommendation': 'run-full-test-suite',
        'limitations': (
            'Static imports cannot prove complete runtime dependency '
            'coverage. Never treat this advisory plan as merge-gate evidence.'
        ),
    }
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    return report
