"""Allowlisted developer-tool adapters and bounded parallel execution.

External tools and their project-local configuration may execute arbitrary
code. This command is deliberately OUTSIDE ChangeAttest's trusted CI gate.
Run on disposable, non-secret CI workers for untrusted repositories.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from changeattest.engine import canonical


@dataclass(frozen=True)
class Adapter:
    id: str
    binary: str
    command: tuple[str, ...]
    suffixes: tuple[str, ...] = ()
    project_files: tuple[str, ...] = ()
    explicit_risk: str = 'Reads untrusted project files and configuration'


ADAPTERS = (
    Adapter(
        'python-ast-stdlib', sys.executable,
        ('-I', '-B', '-c',
         'import ast,sys\\n'
         'for name in sys.argv[1:]:\\n'
         '    with open(name, "rb") as stream:\\n'
         '        ast.parse(stream.read(), filename=name)\\n'),
        ('.py',),
        explicit_risk='Syntax-only check using the Python stdlib, no project import',
    ),
    Adapter('ruff', 'ruff', ('check', '--no-cache', '--output-format', 'concise'),
            ('.py',)),
    Adapter('biome', 'biome', ('ci',), ('.js', '.jsx', '.ts', '.tsx', '.json')),
    Adapter('eslint', 'eslint', ('--no-fix',), ('.js', '.jsx', '.ts', '.tsx'),
            explicit_risk='ESLint project plugins may execute arbitrary code'),
    Adapter('tsc', 'tsc', ('--noEmit', '--project', 'tsconfig.json'),
            project_files=('tsconfig.json',)),
    Adapter('go-vet', 'go', ('vet', './...'), project_files=('go.mod',)),
    Adapter('cargo-fmt', 'cargo', ('fmt', '--all', '--', '--check'),
            project_files=('Cargo.toml',)),
    Adapter('pytest', sys.executable, ('-I', '-m', 'pytest', '-q'),
            project_files=('pytest.ini', 'pyproject.toml', 'setup.cfg'),
            explicit_risk='Pytest executes arbitrary test and fixture code'),
)
ADAPTER_INDEX = {adapter.id: adapter for adapter in ADAPTERS}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _select(adapter: Adapter, root: Path, files: list[str]) -> list[str]:
    if adapter.project_files:
        return [] if not any((root / p).is_file() for p in adapter.project_files) else ['.']
    return [p for p in files if Path(p).suffix.lower() in adapter.suffixes]


def _run(adapter: Adapter, root: Path, selected: list[str],
         timeout: int) -> dict[str, Any]:
    if not selected:
        return {'id': adapter.id, 'status': 'skipped', 'file_count': 0,
                'exit_code': None, 'output_sha256': None, 'tool_sha256': None}
    program = shutil.which(adapter.binary)
    if not program:
        return {'id': adapter.id, 'status': 'unavailable',
                'file_count': len(selected), 'exit_code': None,
                'output_sha256': None, 'tool_sha256': None}
    argv = [program, *adapter.command]
    if not adapter.project_files:
        argv.extend(selected)
    try:
        proc = subprocess.run(argv, cwd=root, capture_output=True,
                              timeout=timeout, check=False)
        status = 'passed' if proc.returncode == 0 else 'failed'
        code = proc.returncode
        out = proc.stdout + b'\0' + proc.stderr
        fingerprint = hashlib.sha256(out).hexdigest()
    except (OSError, subprocess.TimeoutExpired):
        status, code, fingerprint = 'error', None, None
    return {'id': adapter.id, 'status': status,
            'file_count': len(selected), 'exit_code': code,
            'output_sha256': fingerprint,
            'tool_sha256': _hash_file(Path(program)) if Path(program).is_file() else None}


def run_adapters(root: Path, selected_ids: list[str], files: list[str],
                 timeout: int = 120, jobs: int = 4,
                 sandbox_image: str | None = None,
                 cache_dir: Path | None = None) -> dict[str, Any]:
    if (
        any(x not in ADAPTER_INDEX for x in selected_ids) or
        len(selected_ids) != len(set(selected_ids)) or
        not 1 <= timeout <= 3600 or not 1 <= jobs <= 16
    ):
        raise ValueError('Invalid tool selection or execution limit')
    root = root.resolve()
    tasks = [(ADAPTER_INDEX[x], _select(ADAPTER_INDEX[x], root, files))
             for x in sorted(selected_ids)]
    if cache_dir is not None and sandbox_image is None:
        raise ValueError('Advisory cache requires --docker-image')
    if sandbox_image is not None:
        # Lazy imports avoid a registry/sandbox/cache import cycle.
        from changeattest.sandbox import DockerSandbox
        from changeattest.sandbox import run_in_docker
        sandbox = DockerSandbox(sandbox_image)
        advisory = None
        if cache_dir is not None:
            from changeattest.cache import AdvisoryCache
            advisory = AdvisoryCache(Path(cache_dir), root, sandbox.image)

        def runner(task):
            adapter, selected = task
            if advisory is not None:
                cached = advisory.get(adapter, selected)
                if cached is not None:
                    return cached
            result = run_in_docker(adapter, selected, root, timeout, sandbox)
            if advisory is not None:
                advisory.put(adapter, selected, result)
            return result
    else:
        runner = lambda task: _run(task[0], root, task[1], timeout)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(runner, tasks))
    states = {r['status'] for r in results}
    status = ('error' if 'error' in states or 'unavailable' in states else
              'failed' if 'failed' in states else
              'no-files' if not any(r['file_count'] for r in results) else
              'passed-with-cache' if 'cached-passed' in states else 'passed')
    report: dict[str, Any] = {
        'schema': 'changeattest.tools.v1', 'status': status,
        'results': results, 'selected_tools': sorted(selected_ids),
        'root_git_head': None,
        'execution_mode': 'docker-restricted' if sandbox_image else 'local-unrestricted',
        'sandbox_image': sandbox_image,
        'advisory_cache': cache_dir is not None,
        'cached_check_count': sum(r['status'] == 'cached-passed' for r in results),
    }
    try:
        commit = subprocess.run(('git', 'rev-parse', 'HEAD'), cwd=root,
                                capture_output=True, timeout=10, check=False)
        if commit.returncode == 0:
            report['root_git_head'] = commit.stdout.decode('ascii').strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    report['report_sha256'] = hashlib.sha256(canonical(report)).hexdigest()
    return report
