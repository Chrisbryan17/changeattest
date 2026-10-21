"""ChangeAttest command-line entry point."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from collections.abc import Sequence

from changeattest import __version__
from changeattest.engine import ConfigurationError
from changeattest.engine import canonical
from changeattest.engine import load_config
from changeattest.engine import scan


def _write_report(filename: str, payload: bytes) -> None:
    target = Path(filename).absolute()
    # Atomic replacement avoids partial reports if a process is interrupted.
    fd, tmp = tempfile.mkstemp(prefix='.changeattest-', suffix='.tmp',
                               dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='changeattest',
        description='Execute vetted checks and emit unsigned, reproducible evidence.',
    )
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='action', required=True)
    check = sub.add_parser('check', help='Run built-in preflight checks')
    check.add_argument('--root', default='.', help='Directory inside a Git repo')
    check.add_argument('--scope', choices=('staged', 'tracked'),
                       default='staged', help='File selection (default: staged)')
    check.add_argument('--config', help='TOML config relative to Git root')
    check.add_argument('--report', help='Write a deterministic JSON report')
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).resolve()
        # Resolve the actual Git top-level directory before looking for config.
        import subprocess
        proc = subprocess.run(
            ('git', 'rev-parse', '--show-toplevel'), cwd=root,
            capture_output=True, timeout=15, check=False,
        )
        if proc.returncode:
            raise ConfigurationError('Not inside a Git repository')
        git_root = Path(os.fsdecode(proc.stdout.strip()))
        config = load_config(git_root, args.config)
        result = scan(root, args.scope, config)
        if args.report:
            _write_report(args.report, canonical(result))
    except (ConfigurationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'changeattest: configuration or I/O error: {exc}', file=sys.stderr)
        return 2

    for finding in result['checks']:
        print(f"  {finding['id']}: {finding['status']} "
              f"({finding['file_count']} files)")
    for problem in result['problems']:
        print(f"  cannot verify {problem['path']}: {problem['reason']}")
    print(f"ChangeAttest: {result['status']} "
          f"({result['file_count']} files selected; "
          f"evidence sha256:{result['report_sha256'][:16]})")
    return 0 if result['status'] in ('passed', 'no-files') else (
        1 if result['status'] == 'failed' else 2
    )
