"""JUnit test-receipt extraction without executing or trusting test claims.

The report hashes externally generated test XML; only a trusted CI job that
actually ran the tests should sign the resulting receipt.
"""
from __future__ import annotations

import hashlib
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from changeattest.engine import canonical


def collect(root: Path, xml_files: list[str]) -> dict[str, Any]:
    if not xml_files or len(xml_files) != len(set(xml_files)):
        raise ValueError('Expected distinct JUnit XML paths')
    results = []
    for name in sorted(xml_files):
        source = Path(name)
        if not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Missing or overlarge JUnit report')
        raw = source.read_bytes()
        try:
            root_tag = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError('Invalid JUnit XML') from exc
        if root_tag.tag not in ('testsuite', 'testsuites'):
            raise ValueError('Expected JUnit testsuite document')
        cases = root_tag.findall('.//testcase')
        if not cases:
            raise ValueError('JUnit document contains no test cases')
        failures = sum(any(c.find(t) is not None for t in ('failure', 'error'))
                       for c in cases)
        skipped = sum(c.find('skipped') is not None for c in cases)
        passed = len(cases) - failures - skipped
        results.append({
            'id': f'test-suite:{source.name}', 'status': 'failed' if failures else 'passed',
            'file_count': len(cases), 'exit_code': 1 if failures else 0,
            'output_sha256': hashlib.sha256(raw).hexdigest(),
            'passed': passed, 'failed': failures, 'skipped': skipped,
        })
    proc = subprocess.run(('git', 'rev-parse', 'HEAD'), cwd=root,
                          capture_output=True, timeout=15, check=False)
    if proc.returncode:
        raise ValueError('Test receipt requires Git HEAD')
    head = proc.stdout.decode('ascii').strip()
    data: dict[str, Any] = {
        'schema': 'changeattest.tests.v1', 'head': head,
        'status': 'passed' if all(x['status'] == 'passed' for x in results) else 'failed',
        'checks': results,
        'test_cases': sum(x['file_count'] for x in results),
    }
    data['report_sha256'] = hashlib.sha256(canonical(data)).hexdigest()
    return data
