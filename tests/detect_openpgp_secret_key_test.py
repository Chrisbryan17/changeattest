from __future__ import annotations

import pytest

from pre_commit_hooks.detect_openpgp_secret_key import _secret_packet_at_start
from pre_commit_hooks.detect_openpgp_secret_key import main


def _packet(tag: int, *, version: int = 4, algorithm: int = 22) -> bytes:
    body = bytes((version, 0, 0, 0, 0, algorithm)) + b'key-material'
    return bytes((0xc0 | tag, len(body))) + body


@pytest.mark.parametrize('tag', (5, 7))
def test_detects_new_format_secret_packets(tag):
    packet = _packet(tag)
    assert _secret_packet_at_start(packet[:32], len(packet))


def test_detects_legacy_secret_packet():
    body = bytes((4, 0, 0, 0, 0, 1)) + b'key-material'
    packet = bytes((0x94, len(body))) + body
    assert _secret_packet_at_start(packet[:32], len(packet))


@pytest.mark.parametrize('tag', (6, 14, 1, 3))
def test_does_not_flag_public_keys_or_messages(tag):
    packet = _packet(tag)
    assert not _secret_packet_at_start(packet[:32], len(packet))


def test_rejects_truncated_and_invalid_packet_headers():
    packet = _packet(5)
    assert not _secret_packet_at_start(packet[:2], len(packet))
    assert not _secret_packet_at_start(packet[:32], 3)
    assert not _secret_packet_at_start(_packet(5, version=0), 20)


def test_binary_secret_key_hook(tmp_path, capsys):
    secret_path = tmp_path / 'secret.gpg'
    secret_path.write_bytes(_packet(5))
    ordinary_path = tmp_path / 'document.bin'
    ordinary_path.write_bytes(b'not a secret key')

    assert main([str(secret_path), str(ordinary_path)]) == 1
    assert str(secret_path) in capsys.readouterr().out
    assert main([str(ordinary_path)]) == 0
