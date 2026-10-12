#!/usr/bin/env python3
"""Toy state/context/artifact fixtures. No Miden contract, SDK, node or model runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit():
    with Path(os.environ['EVAL_ACTIVITY_PATH']).open('a') as stream:
        stream.write(json.dumps(dict(type='audit_complete', scope='worker_commands_and_human_interventions')) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=['fresh-contract', 'packaged-sdk-frontend',
                                            'full-stack-change', 'version-artifact-mismatch', 'unavailable-service'])
    parser.add_argument('phase', choices=['action', 'verify', 'preflight'])
    args = parser.parse_args()
    workspace = Path(os.environ['EVAL_WORKDIR'])
    result = {}
    if args.scenario == 'unavailable-service':
        # Bind our own unlistening socket; no existing daemon/port is contacted.
        with socket.socket() as reserved, socket.socket() as probe:
            reserved.bind(('127.0.0.1', 0))
            endpoint = reserved.getsockname()
            probe.settimeout(0.2)
            try:
                probe.connect(endpoint)
            except (ConnectionRefusedError, TimeoutError) as error:
                print('fixture service-unavailable: owned unlistening socket: ' + type(error).__name__, file=sys.stderr)
                audit()
                return 1
        raise RuntimeError('Expected refused or timed out connection')
    if args.phase == 'action':
        if args.scenario == 'fresh-contract':
            (workspace / 'counter.json').write_text(json.dumps(dict(count=1, fixture_only=True)))
        elif args.scenario == 'packaged-sdk-frontend':
            package = workspace / 'toy-sdk'
            package.mkdir()
            guide = b'Toy packaged API instructions, fixture only.\n'
            (package / 'AGENTS.md').write_bytes(guide)
            (workspace / 'consumed-context.md').write_bytes(guide)
        elif args.scenario == 'full-stack-change':
            package = json.dumps(dict(count=2, fixture_only=True)).encode()
            (workspace / 'contract-package.json').write_bytes(package)
            (workspace / 'frontend-package.json').write_bytes(package)
        elif args.scenario == 'version-artifact-mismatch':
            (workspace / 'artifact.json').write_text(json.dumps(dict(format=6, required_format=7)))
    elif args.phase == 'verify':
        if args.scenario == 'fresh-contract':
            result = json.loads((workspace / 'counter.json').read_text())
        elif args.scenario == 'packaged-sdk-frontend':
            result = dict(context_equal=(workspace / 'toy-sdk/AGENTS.md').read_bytes() ==
                          (workspace / 'consumed-context.md').read_bytes(), fixture_only=True)
        elif args.scenario == 'full-stack-change':
            result = dict(artifacts_equal=digest((workspace / 'contract-package.json').read_bytes()) ==
                          digest((workspace / 'frontend-package.json').read_bytes()),
                          count=json.loads((workspace / 'frontend-package.json').read_text())['count'], fixture_only=True)
        elif args.scenario == 'version-artifact-mismatch':
            artifact = json.loads((workspace / 'artifact.json').read_text())
            result = dict(version_equal=artifact['format'] == artifact['required_format'], fixture_only=True)
        audit()
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
