"""Portable HTML, SARIF and JUnit exports from evidence reports.

The v1 scanner intentionally omits source diagnostics to avoid credential
leaks. These formats preserve check-level outcomes without inventing lines.
"""
from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from typing import Any

from changeattest.engine import canonical


def _checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    checks = report.get('checks', report.get('results', []))
    if not isinstance(checks, list) or not all(
        isinstance(x, dict) and isinstance(x.get('id'), str) for x in checks
    ):
        raise ValueError('Report does not contain valid check records')
    return checks


def render(report: dict[str, Any], fmt: str) -> bytes:
    checks = _checks(report)
    if fmt == 'sarif':
        rules = [{'id': r['id'], 'name': r['id']} for r in checks]
        results = [{
            'ruleId': r['id'],
            'level': 'error' if r.get('status') in ('failed', 'error', 'unavailable')
            else 'warning',
            'message': {'text': f"Check status: {r.get('status', 'unknown')}"},
        } for r in checks if r.get('status') not in ('passed', 'skipped')]
        return canonical({
            'version': '2.1.0',
            '$schema': 'https://json.schemastore.org/sarif-2.1.0.json',
            'runs': [{'tool': {'driver': {'name': 'ChangeAttest', 'rules': rules}},
                      'results': results}],
        })
    if fmt == 'junit':
        suite = ET.Element('testsuite', attrib={
            'name': 'ChangeAttest',
            'tests': str(len(checks)),
            'failures': str(sum(c.get('status') == 'failed' for c in checks)),
            'errors': str(sum(c.get('status') in ('error', 'unavailable')
                          for c in checks)),
            'skipped': str(sum(c.get('status') == 'skipped' for c in checks)),
        })
        for check in checks:
            case = ET.SubElement(suite, 'testcase', {
                'classname': 'changeattest',
                'name': check['id'],
            })
            status = check.get('status')
            if status == 'failed':
                ET.SubElement(case, 'failure', {'message': 'Check failed'})
            elif status in ('error', 'unavailable'):
                ET.SubElement(case, 'error', {'message': 'Check not completed'})
            elif status == 'skipped':
                ET.SubElement(case, 'skipped')
        return ET.tostring(suite, encoding='utf-8', xml_declaration=True)
    if fmt != 'html':
        raise ValueError('Unsupported format')

    cards = []
    for check in checks:
        name = html.escape(check['id'])
        status = html.escape(str(check.get('status', 'unknown')))
        count = html.escape(str(check.get('file_count', '-')))
        cards.append(
            f'<tr><td>{name}</td><td><span class="state">{status}</span></td>'
            f'<td>{count}</td></tr>'
        )
    status = html.escape(str(report.get('status', 'unknown')))
    digest = html.escape(str(report.get('report_sha256', 'n/a')))
    rows = ''.join(cards)
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>ChangeAttest evidence</title><style>
:root {{color-scheme:dark; font:16px system-ui, sans-serif;background:#0c111a;color:#eaf1fa}}
main {{max-width:850px;margin:5vh auto;padding:24px}}
header {{border-bottom:1px solid #364357;padding-bottom:20px}}
small {{color:#a9b5c6}}
table {{border-collapse:collapse;width:100%;margin:28px 0}}
th,td {{padding:13px;text-align:left;border-bottom:1px solid #2e3d52}}
.state {{font-weight:600}}h1 {{letter-spacing:-.04em}}
code {{overflow-wrap:anywhere}} footer {{font-size:13px;color:#a9b5c6}}
</style></head><body><main><header><small>VERIFICATION REPORT</small>
<h1>ChangeAttest</h1><p>Status: <strong>{status}</strong></p></header>
<table><thead><tr><th>Check</th><th>Outcome</th><th>Files</th></tr></thead>
<tbody>{rows}</tbody></table>
<footer>Evidence SHA-256: <code>{digest}</code><p>
A report hash alone does not authenticate its author or execution environment.</p>
</footer></main></body></html>'''
    return page.encode('utf-8')
