"""Opt-in Docker execution boundary for third-party developer tools.

This is defense in depth, NOT a guarantee that a malicious container
cannot escape. Use a patched rootless/container runtime on disposable,
non-secret hosts. Repository files are mounted read-only, networking is
disabled and the container is launched without additional capabilities.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from changeattest.adapters import Adapter

_DIGEST_IMAGE = re.compile(
    r'\A[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[a-f0-9]{64}\Z',
)
_MAX_OUTPUT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class DockerSandbox:
    image: str
    memory: str = '1g'
    cpus: str = '2'
    pids_limit: int = 128

    def __post_init__(self) -> None:
        if not _DIGEST_IMAGE.fullmatch(self.image):
            raise ValueError('Docker image must be pinned to a full sha256 digest')
        if self.memory not in ('256m', '512m', '1g', '2g', '4g'):
            raise ValueError('Invalid sandbox memory limit')
        if self.cpus not in ('1', '2', '4'):
            raise ValueError('Invalid sandbox CPU allocation')
        if type(self.pids_limit) is not int or not 16 <= self.pids_limit <= 512:
            raise ValueError('Invalid sandbox process limit')


def _container_executable(adapter: Adapter) -> str:
    # sys.executable is a host path, so map it to the container's Python.
    return 'python' if adapter.id == 'pytest' else adapter.binary


def build_argv(
    adapter: Adapter, selected: list[str], root: Path,
    sandbox: DockerSandbox,
) -> list[str]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Repository root must be a directory')
    # Docker --mount uses comma-separated fields. Never interpolate a root
    # containing delimiters that could inject new mount or security options.
    if any(ch in str(root) for ch in (',', '\n', '\r', '\x00')):
        raise ValueError('Unsafe character in repository mount path')

    for name in selected:
        if name == '.' and adapter.project_files:
            continue
        if (
            not name or os.path.isabs(name) or
            any(part in ('', '.', '..') for part in Path(name).parts) or
            not (root / name).resolve().is_relative_to(root)
        ):
            raise ValueError('Adapter selected an unsafe path')
    # No host shell, no Docker daemon/socket mount, no extra host mounts,
    # no writable project files, no credentials, and no Docker network.
    command = [
        'docker', 'run', '--rm', '--pull=never',
        '--network=none', '--read-only', '--cap-drop=ALL',
        '--security-opt=no-new-privileges',
        '--pids-limit', str(sandbox.pids_limit),
        '--memory', sandbox.memory, '--cpus', sandbox.cpus,
        '--user', '65534:65534',
        '--mount', f'type=bind,source={root},target=/workspace,readonly',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
        '--workdir', '/workspace',
        '--env', 'HOME=/tmp',
        '--env', 'TMPDIR=/tmp',
        '--env', 'PYTHONDONTWRITEBYTECODE=1',
        sandbox.image,
        _container_executable(adapter), *adapter.command,
    ]
    if not adapter.project_files:
        # ./ prevents Git filenames beginning with a dash from becoming flags,
        # even for linters that do not support a literal '--' delimiter.
        command.extend(f'./{name}' for name in selected)
    return command


def run_in_docker(
    adapter: Adapter, selected: list[str], root: Path,
    timeout: int, sandbox: DockerSandbox,
) -> dict[str, Any]:
    fields = {
        'id': adapter.id, 'file_count': len(selected),
        'tool_sha256': None,
        'sandbox_image': sandbox.image,
        'execution_mode': 'docker-restricted',
    }
    if not selected:
        return {**fields, 'status': 'skipped', 'exit_code': None,
                'output_sha256': None}
    if not shutil.which('docker'):
        return {**fields, 'status': 'unavailable', 'exit_code': None,
                'output_sha256': None}
    argv = build_argv(adapter, selected, root, sandbox)
    try:
        proc = subprocess.run(argv, cwd=root, capture_output=True,
                              timeout=timeout, check=False)
        code = proc.returncode
        # Docker failures (e.g. image unavailable, daemon error) cannot be
        # mistaken for a lint failure. 125-127 are Docker CLI error codes.
        status = ('error' if code in (125, 126, 127) else
                  'passed' if code == 0 else 'failed')
        output = proc.stdout[:_MAX_OUTPUT_BYTES] + b'\0' + proc.stderr[:_MAX_OUTPUT_BYTES]
        fingerprint = hashlib.sha256(output).hexdigest()
    except (OSError, subprocess.TimeoutExpired):
        status, code, fingerprint = 'error', None, None
    return {**fields, 'status': status, 'exit_code': code,
            'output_sha256': fingerprint}
