"""Check versioned delivery files without reading ignored runtime secrets.

Uses only the Python standard library. Reports paths and finding types, never
matching credential values. It does not remove files or rewrite Git history.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {'.py', '.ts', '.vue', '.mjs', '.js'}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {'.md', '.json', '.yml', '.yaml', '.toml'}
CREDENTIAL_PATTERNS = (
    rb'sk-[A-Za-z0-9_-]{24,}', rb'gh[pousr]_[A-Za-z0-9]{30,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
)


def tracked_paths() -> list[str]:
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached',
                             '--others', '--exclude-standard', '-z'],
                            check=True, capture_output=True)
    return sorted(set(filter(None, result.stdout.decode('utf-8').split('\0'))))


def inspect_repository() -> dict:
    issues, duplicates = [], defaultdict(list)
    names = [name for name in tracked_paths() if (ROOT / name).is_file()]
    for name in names:
        path = ROOT / name
        parts = set(Path(name).parts)
        if ((path.name == '.env' or path.name.startswith('.env.')) and path.name != '.env.example'
                or path.suffix in {'.db', '.sqlite', '.sqlite3', '.log'}
                or path.name.endswith(('.db-wal', '.db-shm', '.tsbuildinfo'))
                or parts.intersection({'node_modules', '__pycache__', '.venv', '.pytest_cache',
                                       '.playwright-cli', 'output', 'postgres-data'})):
            issues.append({'kind': 'runtime_file', 'path': name})
            continue
        if path.stat().st_size >= 95 * 1024 * 1024:
            issues.append({'kind': 'oversized_file', 'path': name})
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        body = path.read_bytes()
        if any(re.search(pattern, body) for pattern in CREDENTIAL_PATTERNS):
            issues.append({'kind': 'credential_pattern', 'path': name})
        if path.suffix in SOURCE_SUFFIXES and len(body.strip()) > 256:
            duplicates[sha256(body).hexdigest()].append(name)
        if path.suffix != '.md':
            continue
        prose = re.sub(r'```.*?```', '', body.decode('utf-8-sig'), flags=re.S)
        for raw in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', prose):
            target = raw.strip()
            target = target[1:target.find('>')] if target.startswith('<') else target.split(' "', 1)[0]
            if urlsplit(target).scheme or target.startswith('//'):
                continue
            target = unquote(target.split('#', 1)[0].split('?', 1)[0])
            if target and not (path.parent / target).exists():
                issues.append({'kind': 'broken_document_link', 'path': name, 'target': target})
    return {'files_checked': len(names), 'issues': issues,
            'identical_sources': [paths for paths in duplicates.values() if len(paths) > 1]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Emit a machine-readable report.')
    args = parser.parse_args()
    result = inspect_repository()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Checked {result['files_checked']} delivery files; {len(result['issues'])} issue(s).")
        for issue in result['issues']:
            print(issue['kind'], issue['path'], issue.get('target', ''))
        for paths in result['identical_sources']:
            print('identical_sources', ', '.join(paths))
    return bool(result['issues'])


if __name__ == '__main__':
    raise SystemExit(main())
