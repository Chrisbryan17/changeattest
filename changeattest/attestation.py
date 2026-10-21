"""Ed25519-signed evidence envelopes with explicit verifier trust roots.

A signature proves possession of the signing key, not that the checks ran.
Provision keys independently and sign ONLY results produced by controlled CI.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from changeattest.engine import canonical

SCHEMA = 'changeattest.attestation.v1'


def _load_crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:
        raise ValueError('Signing needs pip install changeattest[attest]') from exc
    return InvalidSignature, serialization, ed25519


def validate_evidence(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    digest = report.get('report_sha256')
    if not isinstance(digest, str) or len(digest) != 64:
        return False
    obj = dict(report)
    obj.pop('report_sha256', None)
    try:
        actual = hashlib.sha256(canonical(obj)).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return False
    return hmac.compare_digest(digest, actual)


def _key_id(public_key: Any, serialization: Any) -> str:
    encoded = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(encoded).hexdigest()


def sign_evidence(report: dict[str, Any], pem: bytes,
                  issuer: str = '') -> dict[str, Any]:
    _, serialization, ed25519 = _load_crypto()
    if not validate_evidence(report):
        raise ValueError('Evidence checksum mismatch')
    if not isinstance(issuer, str) or len(issuer) > 200:
        raise ValueError('Invalid issuer label')
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError('Signing requires an Ed25519 key')
    body = {
        'schema': SCHEMA, 'issuer_label': issuer,
        'key_sha256': _key_id(key.public_key(), serialization),
        'evidence': report,
    }
    signature = key.sign(canonical(body))
    return {**body, 'signature': base64.b64encode(signature).decode('ascii')}


def verify_evidence(envelope: Any, trusted_pem: bytes,
                    expected_head: str | None = None) -> bool:
    InvalidSignature, serialization, ed25519 = _load_crypto()
    if not isinstance(envelope, dict) or set(envelope) != {
        'schema', 'issuer_label', 'key_sha256', 'evidence', 'signature',
    } or envelope.get('schema') != SCHEMA:
        return False
    if not validate_evidence(envelope.get('evidence')):
        return False
    if expected_head is not None and envelope['evidence'].get('head') != expected_head:
        return False
    try:
        key = serialization.load_pem_public_key(trusted_pem)
        if not isinstance(key, ed25519.Ed25519PublicKey):
            return False
        if not hmac.compare_digest(envelope['key_sha256'],
                                   _key_id(key, serialization)):
            return False
        sig = base64.b64decode(envelope['signature'], validate=True)
        body = dict(envelope)
        del body['signature']
        key.verify(sig, canonical(body))
    except (ValueError, TypeError, KeyError, InvalidSignature):
        return False
    return True


def load_json_file(path: str) -> dict[str, Any]:
    source = Path(path)
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Evidence is too large')
    obj = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise ValueError('Expected a JSON object')
    return obj
