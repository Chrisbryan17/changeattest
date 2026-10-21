"""ChangeAttest developer, evidence, and policy command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from changeattest import __version__
from changeattest.adapters import ADAPTER_INDEX
from changeattest.adapters import run_adapters
from changeattest.agent import read_contract
from changeattest.agent import verify_agent_change
from changeattest.attestation import load_json_file
from changeattest.attestation import sign_evidence
from changeattest.attestation import verify_evidence
from changeattest.engine import ConfigurationError
from changeattest.engine import canonical
from changeattest.engine import load_config
from changeattest.engine import scan
from changeattest.policy import evaluate
from changeattest.policy import load_policy
from changeattest.snapshot import scan_commit


def _write_report(filename: str, payload: bytes) -> None:
    target = Path(filename).absolute()
    fd, tmp = tempfile.mkstemp(prefix='.changeattest-', suffix='.tmp',
                               dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _root(root: str) -> Path:
    path = Path(root).resolve()
    result = subprocess.run(
        ('git', 'rev-parse', '--show-toplevel'), cwd=path,
        capture_output=True, timeout=15, check=False,
    )
    if result.returncode:
        raise ConfigurationError('Not inside a Git repository')
    return Path(os.fsdecode(result.stdout.strip()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='changeattest',
                                     description='Verify software changes with evidence.')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='action', required=True)

    check = sub.add_parser('check', help='Run allowlisted local preflight checks')
    check.add_argument('--root', default='.')
    check.add_argument('--scope', choices=('staged', 'tracked'), default='staged')
    check.add_argument('--config')
    check.add_argument('--report')

    gate = sub.add_parser('gate', help='Enforce trusted, mandatory check policy')
    gate.add_argument('--root', default='.')
    gate.add_argument('--policy', required=True)
    gate.add_argument('--report', required=True)
    gate.add_argument('--expected-head')

    tools = sub.add_parser('tools', help='Run optional cross-language tools (untrusted code risk)')
    tools.add_argument('--root', default='.')
    tools.add_argument('--adapter', action='append', required=True,
                       choices=tuple(ADAPTER_INDEX))
    tools.add_argument('--jobs', type=int, default=4)
    tools.add_argument('--timeout', type=int, default=120)
    tools.add_argument('--report', required=True)

    sign = sub.add_parser('sign', help='Sign existing evidence with an external Ed25519 key')
    sign.add_argument('--input', required=True)
    sign.add_argument('--private-key', required=True)
    sign.add_argument('--output', required=True)
    sign.add_argument('--issuer', default='')

    verify = sub.add_parser('verify-signature', help='Verify against explicit trusted Ed25519 public key')
    verify.add_argument('--input', required=True)
    verify.add_argument('--public-key', required=True)
    verify.add_argument('--expected-head')

    agent = sub.add_parser('agent-review', help='Enforce AI agent changed-path contracts')
    agent.add_argument('--root', default='.')
    agent.add_argument('--contract', required=True)
    agent.add_argument('--base', required=True)
    agent.add_argument('--head', required=True)
    agent.add_argument('--attestation')
    agent.add_argument('--trusted-key')
    agent.add_argument('--report', required=True)

    args = parser.parse_args(argv)

    try:
        if args.action == 'sign':
            envelope = sign_evidence(
                load_json_file(args.input),
                Path(args.private_key).read_bytes(), args.issuer,
            )
            _write_report(args.output, canonical(envelope))
            print('Signed evidence written; issuer_label is not authenticated identity.')
            return 0

        if args.action == 'verify-signature':
            good = verify_evidence(load_json_file(args.input),
                                   Path(args.public_key).read_bytes(),
                                   args.expected_head)
            print('Signature valid for explicitly trusted key' if good
                  else 'Signature or evidence invalid')
            return 0 if good else 1

        root = _root(args.root)

        if args.action == 'agent-review':
            contract = read_contract(args.contract)
            signed = load_json_file(args.attestation) if args.attestation else None
            pub = Path(args.trusted_key).read_bytes() if args.trusted_key else None
            decision = verify_agent_change(root, contract, args.base,
                                           args.head, signed, pub)
            _write_report(args.report, canonical(decision))
            print(f"Agent change scope: {decision['status']}")
            for violation in decision['violations']:
                print(f'  {violation}')
            return 0 if decision['status'] == 'passed' else 1

        if args.action == 'tools':
            names = subprocess.run(
                ('git', 'ls-files', '-z'), cwd=root, capture_output=True,
                timeout=15, check=False,
            )
            if names.returncode:
                raise ConfigurationError('Unable to enumerate Git files')
            paths = [os.fsdecode(x) for x in names.stdout.split(b'\0') if x]
            report = run_adapters(root, args.adapter, paths,
                                  timeout=args.timeout, jobs=args.jobs)
            _write_report(args.report, canonical(report))
            for result in report['results']:
                print(f"  {result['id']}: {result['status']}")
            return 0 if report['status'] == 'passed' else (
                1 if report['status'] == 'failed' else 2
            )

        if args.action == 'gate':
            policy = load_policy(Path(args.policy))
            result = (scan_commit(root, policy.runner_config())
                      if policy.scope == 'tracked' else
                      scan(root, policy.scope, policy.runner_config()))
            violations = evaluate(result, policy, args.expected_head)
            _write_report(args.report, canonical(result))
            for code in violations:
                print(f'  policy violation: {code}')
            print(f'ChangeAttest policy gate: {"BLOCK" if violations else "PASS"} '
                  f'(policy sha256:{policy.sha256[:16]}; '
                  f'evidence sha256:{result["report_sha256"][:16]})')
            return 1 if violations else 0

        config = load_config(root, args.config)
        result = scan(root, args.scope, config)
        if args.report:
            _write_report(args.report, canonical(result))
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
    except (ConfigurationError, OSError, subprocess.TimeoutExpired,
            ValueError, KeyError) as exc:
        print(f'changeattest: configuration or I/O error: {exc}', file=sys.stderr)
        return 2
