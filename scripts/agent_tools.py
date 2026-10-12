#!/usr/bin/env python3
"""Discover, validate and copy release-scoped Miden prompts. No network or SDK execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- miden-agent-tools:start -->'
END = '<!-- miden-agent-tools:end -->'
AGENTS = {'codex': '.agents', 'claude': '.claude', 'cursor': '.cursor'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def catalog():
    release = json.loads((ROOT / 'release.json').read_text())
    required = ('miden', 'toolchain', 'contract_sdk', 'compiler', 'protocol', 'rust_client', 'vm', 'package_format', 'knowledge_baseline', 'migration_source')
    if not isinstance(release, dict) or any(not isinstance(release.get(key), str) or not release[key].strip() for key in required):
        raise ValueError('Invalid release.json: required release versions and source identifiers must be nonempty strings.')
    entries = []
    for directory in sorted((ROOT / 'skills').iterdir()):
        if directory.is_symlink() or not directory.is_dir() or not (directory / 'SKILL.md').is_file():
            raise ValueError(f'Expected a real skill directory with SKILL.md: {directory}')
    for kind, pattern in [('skill', 'skills/*/SKILL.md'), ('command', 'commands/*.md')]:
        for path in sorted(ROOT.glob(pattern)):
            text = path.read_text()
            if not text.startswith('---\n') or '\n---\n' not in text[4:]:
                raise ValueError(f'Invalid frontmatter: {path.relative_to(ROOT)}')
            header, body = text[4:].split('\n---\n', 1)
            metadata = dict(line.split(': ', 1) for line in header.splitlines() if ': ' in line)
            name = path.parent.name if kind == 'skill' else path.stem
            if not re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', name):
                raise ValueError(f'Invalid name: {name}')
            if kind == 'skill' and (metadata.get('name') != name or not metadata.get('description')):
                raise ValueError(f'Skill name/description missing or mismatched: {path.relative_to(ROOT)}')
            if not body.strip():
                raise ValueError(f'Empty prompt: {path.relative_to(ROOT)}')
            files = [path] if kind == 'command' else sorted(p for p in path.parent.rglob('*') if p.is_file())
            for file in files:
                if file.is_symlink():
                    raise ValueError(f'Source symlink is unsupported: {file}')
            entries.append({'name': name, 'kind': kind, 'effect': 'prompt',
                            'description': metadata.get('description', body.strip().splitlines()[0]),
                            'path': path.relative_to(ROOT).as_posix(),
                            'files': {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in files}})
    if not entries:
        raise ValueError('No prompts found; use a complete agent-tools checkout.')
    return {'schema_version': 1, 'release': release, 'entries': entries}


def safe_path(project, path):
    # Resolve the user-selected project once, but never follow symlinks below it.
    for parent in [path, *path.parents]:
        if parent == project:
            break
        if parent.is_symlink():
            raise ValueError(f'Refusing symlink destination: {parent}. Choose a real project directory.')
        if parent.exists() and parent != path and not parent.is_dir():
            raise ValueError(f'Expected directory: {parent}. Move the conflicting file aside first.')
    if not path.is_relative_to(project):
        raise ValueError(f'Destination escapes project: {path}')


def selected(data, names, commands):
    available = {x['name'] for x in data['entries'] if x['kind'] == 'skill'}
    unknown = set(names) - available
    if unknown:
        raise ValueError(f'Unknown skill: {", ".join(sorted(unknown))}. Run list to see available skills.')
    return [x for x in data['entries'] if (x['kind'] == 'command' and commands) or
            (x['kind'] == 'skill' and (not names or x['name'] in names))]


def context(data, entries, agent):
    release = data['release']
    lines = [START, '## Miden agent context',
             f"Knowledge target: Miden {release['miden']}; guest SDK {release['contract_sdk']}; "
             f"compiler {release['compiler']}; protocol {release['protocol']}; Rust client {release['rust_client']}; VM {release['vm']}.",
             'Confirm Cargo.lock and installed tools match before using these APIs. Preserve lockfiles; rebuild incompatible artifacts.',
             'Read rust-sdk-source-guide for release sources, rust-sdk-pitfalls before contract edits, and rust-sdk-testing-patterns for MockChain tests.',
             'MockChain success does not verify RPC, proving services, submission, or inclusion. Use local-node-validation only with explicitly disposable test state.',
             'These are knowledge prompts, not executable tools or permission grants. Inspect requested effects; protect keys and stores; report tested and untested steps separately.',
             'Web/React context belongs to installed @miden-sdk packages; do not substitute these Rust/MASM skills for their API documentation.',
             'Installed skill index:']
    for item in entries:
        if item['kind'] == 'skill':
            path = f"{AGENTS[agent]}/skills/{item['name']}/SKILL.md"
            lines.append(f"- [{item['name']}]({path})")
    lines.append(END)
    return '\n'.join(lines) + '\n'


def merge_context(existing, block):
    if START not in existing and END not in existing:
        return existing + ('\n' if existing and not existing.endswith('\n\n') else '') + block
    if existing.count(START) != 1 or existing.count(END) != 1 or existing.index(END) < existing.index(START):
        raise ValueError('Malformed AGENTS.md markers. Repair the miden-agent-tools marker pair before retrying.')
    begin = existing.index(START)
    end = existing.index(END) + len(END)
    if existing[end:end + 1] == '\n':
        end += 1
    return existing[:begin] + block + existing[end:]


def plan_install(args, data):
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f'Project directory does not exist: {project}. Create it first.')
    if args.commands and args.agent != 'claude':
        raise ValueError('--commands requires --agent claude; other agents can read commands/*.md as prompts.')
    entries = selected(data, args.skill, args.commands)
    writes = {}
    for item in entries:
        for source in item['files']:
            relative = Path(source)
            target = project / AGENTS[args.agent] / relative
            writes[target] = (ROOT / source).read_bytes()
    # Reject different content anywhere in a selected skill, including unknown extra files.
    for item in entries:
        if item['kind'] != 'skill':
            continue
        directory = project / AGENTS[args.agent] / 'skills' / item['name']
        safe_path(project, directory)
        if directory.exists():
            if not directory.is_dir():
                raise ValueError(f'Install collision: {directory}. Move it aside and retry.')
            for path in directory.rglob('*'):
                safe_path(project, path)
                if path.is_file() and path not in writes:
                    raise ValueError(f'Install collision: extra file {path}. Preserve it outside the selected skill before retrying.')
    operations = []
    for path, content in writes.items():
        safe_path(project, path)
        if path.exists() and (not path.is_file() or path.read_bytes() != content):
            raise ValueError(f'Install collision: {path}. Preserve your copy, then move it aside before retrying. Nothing was written.')
        operations.append({'path': str(path), 'action': 'unchanged' if path.exists() else 'create', 'sha256': digest(content)})
    agents = project / 'AGENTS.md'
    safe_path(project, agents)
    original = agents.read_bytes() if agents.exists() else None
    merged = merge_context(original.decode('utf-8') if original is not None else '', context(data, entries, args.agent)).encode()
    operations.append({'path': str(agents), 'action': 'unchanged' if original == merged else ('update-context' if original is not None else 'create'), 'sha256': digest(merged)})
    writes[agents] = merged
    return project, writes, operations, agents, original


def apply_plan(project, writes, operations, agents, original):
    created_files, created_dirs = [], []
    temporary = None
    try:
        for op in operations:
            path = Path(op['path'])
            if op['action'] == 'unchanged':
                continue
            safe_path(project, path)
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
            if path == agents:
                # Recheck the original so a concurrent editor's changes are not overwritten.
                current = path.read_bytes() if path.exists() else None
                if current != original:
                    raise ValueError('AGENTS.md changed during installation. Retry after the other writer finishes.')
                with tempfile.NamedTemporaryFile(dir=project, prefix='.miden-context-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(writes[path])
                if path.exists():
                    os.chmod(temporary, path.stat().st_mode & 0o777)
                os.replace(temporary, path)
                temporary = None
            else:
                with path.open('xb') as stream:
                    created_files.append(path)
                    stream.write(writes[path])
    except (OSError, ValueError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        for path in reversed(created_files):
            path.unlink()
        for path in reversed(created_dirs):
            path.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='Read-only JSON catalog with release and file hashes')
    for command in ['install', 'check']:
        p = sub.add_parser(command)
        p.add_argument('--project', help='Existing project directory (required for install)')
        p.add_argument('--agent', choices=AGENTS, default='codex')
        p.add_argument('--skill', action='append', default=[], help='Repeat to select skills; default all')
        p.add_argument('--commands', action='store_true', help='Include Claude Code command prompts')
        if command == 'install':
            p.add_argument('--apply', action='store_true', help='Write the displayed plan; default is preview only')
    args = parser.parse_args()
    try:
        data = catalog()
        if args.command == 'list':
            result = data
        elif args.command == 'check' and not args.project:
            result = {'valid': True, 'release': data['release'], 'entries': len(data['entries']), 'scope': 'repository prompt metadata; no runtime verification'}
        else:
            if not args.project:
                parser.error('install requires --project')
            project, writes, operations, agents, original = plan_install(args, data)
            if args.command == 'check':
                missing = [op for op in operations if op['action'] != 'unchanged']
                if missing:
                    raise ValueError('Install missing or context differs: ' + ', '.join(op['path'] for op in missing) + '. Preview install with the same selection, then use --apply.')
                result = {'valid': True, 'release': data['release'], 'operations': operations}
            else:
                if args.apply:
                    apply_plan(project, writes, operations, agents, original)
                result = {'applied': args.apply, 'release': data['release'], 'operations': operations, 'effects': 'local prompt copies and marked AGENTS.md context only; no network, credentials, or SDK commands'}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f'agent-tools: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
