"""Local-only evidence history and read-only dashboard.

This is a developer workstation feature, NOT a hosted SaaS or multi-tenant
audit server. It binds to loopback and never accepts HTTP writes.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from changeattest.attestation import validate_evidence
from changeattest.attestation import verify_evidence
from changeattest.engine import canonical

_SHA = re.compile(r'[a-f0-9]{64}\Z')


def _connection(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.execute('''CREATE TABLE IF NOT EXISTS evidence (
        digest TEXT PRIMARY KEY,
        recorded_utc TEXT NOT NULL,
        status TEXT NOT NULL,
        git_head TEXT,
        trust TEXT NOT NULL,
        payload TEXT NOT NULL
    )''')
    return con


def store(db: Path, document: dict[str, Any],
          trusted_public_key: bytes | None = None) -> str:
    if document.get('schema') == 'changeattest.attestation.v1':
        if trusted_public_key is None or not verify_evidence(
            document, trusted_public_key,
        ):
            raise ValueError('Signed evidence requires a matching trusted public key')
        report = document['evidence']
        trust = 'signature-verified'
    else:
        report = document
        if not validate_evidence(report):
            raise ValueError('Invalid report checksum')
        trust = 'unsigned'

    # Trust status means only checksum or signature verification.
    digest = report['report_sha256']
    status = str(report.get('status', 'unknown'))[:64]
    head = report.get('head')
    if head is not None and not isinstance(head, str):
        raise ValueError('Invalid head')
    if len(canonical(document)) > 32 * 1024 * 1024:
        raise ValueError('Evidence exceeds local storage limit')
    db.parent.mkdir(parents=True, exist_ok=True)
    with _connection(db) as con:
        con.execute(
            'INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?, ?, ?)',
            (digest, datetime.now(timezone.utc).isoformat(), status,
             head, trust, canonical(document).decode('utf-8')),
        )
    return digest


def list_reports(db: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not db.exists():
        return []
    with _connection(db) as con:
        rows = con.execute('''SELECT digest, recorded_utc, status, git_head, trust
                              FROM evidence ORDER BY recorded_utc DESC
                              LIMIT ?''', (min(max(int(limit), 1), 500),)).fetchall()
    return [
        dict(zip(('digest', 'recorded_utc', 'status', 'head', 'trust'), row))
        for row in rows
    ]


def get_report(db: Path, digest: str) -> dict[str, Any] | None:
    if not _SHA.fullmatch(digest) or not db.exists():
        return None
    with _connection(db) as con:
        row = con.execute(
            'SELECT payload FROM evidence WHERE digest=?', (digest,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def dashboard(rows: list[dict[str, Any]]) -> bytes:
    entries = ''.join(
        '<tr><td><a href="/api/reports/' + html.escape(row['digest']) + '">' +
        html.escape(row['digest'][:14]) + '</a></td><td>' +
        html.escape(row['status']) + '</td><td>' +
        html.escape(row['trust']) + '</td><td>' +
        html.escape((row['head'] or '')[:12]) + '</td></tr>'
        for row in rows
    )
    page = '''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ChangeAttest · Local evidence</title><style>
:root{color-scheme:dark;background:#0a121e;color:#e4eefa;font:16px system-ui}
main{max-width:960px;margin:48px auto;padding:16px}
table{width:100%;border-collapse:collapse}td,th{padding:14px;text-align:left;
border-bottom:1px solid #30415c}a{color:#9cd1ff}small{color:#aebed0}
h1{letter-spacing:-.04em}
</style></head><body><main><small>LOCAL WORKSTATION ONLY</small>
<h1>ChangeAttest evidence vault</h1><p>Stored reports, not a trusted
statement that software was verified.</p>
<table><thead><tr><th>Digest</th><th>Status</th><th>Trust</th><th>Git HEAD</th>
</tr></thead><tbody>''' + entries + '''</tbody></table>
<p><small>Unsigned = checksum only. Signature-verified = matching provided
public key, not an independently authenticated CI execution.</small></p>
</main></body></html>'''
    return page.encode('utf-8')


def serve(db: Path, port: int = 8765) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError('Port must be between 1024 and 65535')

    class ReadOnlyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == '/':
                data, content_type = dashboard(list_reports(db)), 'text/html; charset=utf-8'
            elif self.path == '/api/reports':
                data, content_type = canonical(list_reports(db)), 'application/json'
            elif self.path.startswith('/api/reports/'):
                obj = get_report(db, self.path[len('/api/reports/'):])
                if obj is None:
                    self.send_error(404)
                    return
                data, content_type = canonical(obj), 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            self.send_error(405, 'HTTP writes are not supported')

    # Loopback ONLY, not 0.0.0.0: a remote API would require auth,
    # TLS, tenancy boundaries, quotas, and operational controls.
    server = ThreadingHTTPServer(('127.0.0.1', port), ReadOnlyHandler)
    print(f'Local evidence dashboard: http://127.0.0.1:{port}/')
    try:
        server.serve_forever()
    finally:
        server.server_close()
