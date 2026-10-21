from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

from changeattest.attestation import sign_evidence
from changeattest.engine import canonical
from changeattest.history import dashboard
from changeattest.history import get_report
from changeattest.history import list_reports
from changeattest.history import store
from changeattest.reports import render


@pytest.fixture
def report():
    data = {
        'schema': 'changeattest.report.v1',
        'status': 'failed',
        'head': 'b' * 40,
        'checks': [
            {'id': 'json', 'status': 'passed', 'file_count': 1},
            {'id': '<script>alert(1)</script>', 'status': 'failed',
             'file_count': 1},
        ],
    }
    data['report_sha256'] = hashlib.sha256(canonical(data)).hexdigest()
    return data


def test_export_renderers_escape_html_and_use_valid_sarif_junit(report):
    raw = render(report, 'html').decode()
    assert '<script>alert(1)</script>' not in raw
    assert '&lt;script&gt;' in raw
    assert 'Content-Security-Policy' in raw

    sarif = json.loads(render(report, 'sarif'))
    assert sarif['version'] == '2.1.0'
    assert sarif['runs'][0]['results'][0]['level'] == 'error'
    xml = ET.fromstring(render(report, 'junit'))
    assert xml.tag == 'testsuite'
    assert xml.attrib['failures'] == '1'
    with pytest.raises(ValueError):
        render(report, 'unknown')


def test_history_stores_unsigned_reports_with_explicit_trust_label(report, tmp_path):
    db = tmp_path / 'evidence.sqlite'
    digest = store(db, report)
    assert digest == report['report_sha256']
    assert store(db, report) == digest  # idempotent
    entries = list_reports(db)
    assert len(entries) == 1
    assert entries[0]['trust'] == 'unsigned'
    assert get_report(db, digest) == report
    assert get_report(db, 'not-a-checksum') is None
    assert b'<!doctype html>' in dashboard(entries)


def test_history_rejects_tampered_and_unsigned_fake_signatures(report, tmp_path):
    report['head'] = 'c' * 40
    with pytest.raises(ValueError):
        store(tmp_path / 'no.sqlite', report)
    assert not (tmp_path / 'no.sqlite').exists()


def test_history_signed_records_need_explicit_trusted_key(report, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    envelope = sign_evidence(report, private)
    db = tmp_path / 'evidence.sqlite'
    with pytest.raises(ValueError):
        store(db, envelope)
    store(db, envelope, public)
    assert list_reports(db)[0]['trust'] == 'signature-verified'


def test_dashboard_does_not_interpret_stored_values_as_html():
    rows = [{'digest': '0' * 64, 'status': '<iframe>',
             'trust': '<img>', 'head': '<script>'}]
    data = dashboard(rows).decode()
    assert '<iframe>' not in data
    assert '<img>' not in data
    assert '&lt;iframe&gt;' in data
