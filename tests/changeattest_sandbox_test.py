from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from changeattest.adapters import ADAPTER_INDEX
from changeattest.adapters import run_adapters
from changeattest.sandbox import DockerSandbox
from changeattest.sandbox import build_argv
from changeattest.sandbox import run_in_docker

IMAGE = 'registry.example.invalid/changeattest/tools@sha256:' + 'a' * 64


@pytest.mark.parametrize('bad', (
    'ubuntu:latest',
    'ubuntu@sha256:deadbeef',
    'registry.example.invalid/tools:latest',
    'myimage@sha256:' + 'A' * 64,
    '',
    'foo;rm -rf /@sha256:' + 'a' * 64,
))
def test_docker_image_must_be_pinned_and_restricted(bad):
    with pytest.raises(ValueError, match='pinned'):
        DockerSandbox(bad)


def test_command_never_mounts_credentials_or_enables_network(tmp_path):
    root = tmp_path / 'my-repo'
    root.mkdir()
    argv = build_argv(
        ADAPTER_INDEX['ruff'], ['-inject.py', 'src/main.py'],
        root, DockerSandbox(IMAGE),
    )
    assert argv[:3] == ['docker', 'run', '--rm']
    assert '--network=none' in argv
    assert '--read-only' in argv
    assert '--cap-drop=ALL' in argv
    assert '--security-opt=no-new-privileges' in argv
    assert '--pull=never' in argv
    assert '--user' in argv
    assert argv[argv.index('--user') + 1] == '65534:65534'
    assert not any('--privileged' in value for value in argv)
    assert not any('docker.sock' in value for value in argv)
    assert argv[argv.index('--mount') + 1].endswith(
        ',target=/workspace,readonly',
    )
    assert argv[-2:] == ['./-inject.py', './src/main.py']
    assert '--env' in argv
    assert argv[argv.index('--tmpfs') + 1].startswith('/tmp:')


@pytest.mark.parametrize('name', ('../escape.py', '/tmp/x.py', 'dir/../../secret.py'))
def test_sandbox_rejects_filesystem_escape(tmp_path, name):
    with pytest.raises(ValueError, match='unsafe'):
        build_argv(ADAPTER_INDEX['ruff'], [name],
                   tmp_path, DockerSandbox(IMAGE))


def test_missing_image_or_docker_daemon_never_passes(tmp_path, monkeypatch):
    monkeypatch.setattr('changeattest.sandbox.shutil.which',
                        lambda name: None)
    result = run_in_docker(ADAPTER_INDEX['ruff'], ['a.py'],
                           tmp_path, 30, DockerSandbox(IMAGE))
    assert result['status'] == 'unavailable'
    assert result['execution_mode'] == 'docker-restricted'
    assert result['sandbox_image'] == IMAGE


def test_sandbox_reports_tool_failure_and_docker_failure(tmp_path, monkeypatch):
    monkeypatch.setattr('changeattest.sandbox.shutil.which',
                        lambda name: '/usr/bin/docker')
    def fail_tool(*args, **kwargs):
        assert isinstance(args[0], list)
        assert kwargs['capture_output']
        assert kwargs['timeout'] == 15
        return SimpleNamespace(returncode=1, stdout=b'lint failed', stderr=b'')
    monkeypatch.setattr('changeattest.sandbox.subprocess.run', fail_tool)
    failure = run_in_docker(ADAPTER_INDEX['ruff'], ['a.py'],
                            tmp_path, 15, DockerSandbox(IMAGE))
    assert failure['status'] == 'failed'
    assert failure['exit_code'] == 1
    assert len(failure['output_sha256']) == 64

    monkeypatch.setattr('changeattest.sandbox.subprocess.run',
                        lambda *a, **k: SimpleNamespace(
                            returncode=125, stdout=b'', stderr=b'docker error',
                        ))
    infra = run_in_docker(ADAPTER_INDEX['ruff'], ['a.py'],
                          tmp_path, 15, DockerSandbox(IMAGE))
    assert infra['status'] == 'error'


def test_timeout_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr('changeattest.sandbox.shutil.which',
                        lambda name: '/usr/bin/docker')
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('docker', 5)
    monkeypatch.setattr('changeattest.sandbox.subprocess.run', timeout)
    result = run_in_docker(ADAPTER_INDEX['ruff'], ['a.py'],
                           tmp_path, 5, DockerSandbox(IMAGE))
    assert result['status'] == 'error'


def test_pytest_container_uses_container_python_not_host_interpreter(tmp_path):
    command = build_argv(ADAPTER_INDEX['pytest'], ['.'],
                         tmp_path, DockerSandbox(IMAGE))
    assert command[command.index(IMAGE) + 1:] == [
        'python', '-I', '-m', 'pytest', '-q',
    ]


def test_parallel_registry_uses_sandbox_when_requested(tmp_path, monkeypatch):
    import changeattest.adapters as adapters
    observed = []

    def mock_run(adapter, selected, root, timeout, sandbox):
        observed.append((adapter.id, sandbox.image, selected))
        return {
            'id': adapter.id, 'status': 'passed', 'file_count': len(selected),
            'exit_code': 0, 'output_sha256': None, 'tool_sha256': None,
        }

    monkeypatch.setattr('changeattest.sandbox.run_in_docker', mock_run)
    monkeypatch.setattr(adapters.subprocess, 'run',
                        lambda *a, **k: SimpleNamespace(
                            returncode=0, stdout=b'a' * 40 + b'\n',
                        ))
    report = run_adapters(
        tmp_path, ['ruff'], ['test.py'], sandbox_image=IMAGE,
    )
    assert report['status'] == 'passed'
    assert report['execution_mode'] == 'docker-restricted'
    assert observed == [('ruff', IMAGE, ['test.py'])]
