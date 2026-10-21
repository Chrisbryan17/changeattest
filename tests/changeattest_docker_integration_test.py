from __future__ import annotations

import subprocess
import sys

from changeattest.adapters import ADAPTER_INDEX
from changeattest.sandbox import DockerSandbox
from changeattest.sandbox import build_argv

IMAGE = 'python@sha256:' + 'a' * 64


def test_stdlib_ast_adapter_checks_valid_and_invalid_code(tmp_path):
    adapter = ADAPTER_INDEX['python-ast-stdlib']
    good = tmp_path / 'good.py'
    bad = tmp_path / 'bad.py'
    good.write_text('answer = 42\n', encoding='utf-8')
    bad.write_text('def broken(:\n', encoding='utf-8')
    success = subprocess.run(
        (sys.executable, *adapter.command, str(good)),
        cwd=tmp_path, capture_output=True, check=False,
    )
    failure = subprocess.run(
        (sys.executable, *adapter.command, str(bad)),
        cwd=tmp_path, capture_output=True, check=False,
    )
    assert success.returncode == 0
    assert failure.returncode != 0


def test_container_command_uses_container_python_and_no_project_execution(tmp_path):
    adapter = ADAPTER_INDEX['python-ast-stdlib']
    command = build_argv(adapter, ['good.py'], tmp_path, DockerSandbox(IMAGE))
    position = command.index(IMAGE)
    assert command[position + 1] == 'python'
    assert command[position + 2:position + 5] == ['-I', '-B', '-c']
    assert 'ast.parse' in command[position + 5]
    assert command[-1] == './good.py'
    assert '--network=none' in command
    assert '--read-only' in command
