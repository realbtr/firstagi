"""Restore pinned historical data; never run a model, generator or network call."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'experiments/reports/ac0_debug/RAW_ARTIFACTS.json'
PREFIX = 'experiments/reports/ac0_debug/'
MAX_BYTES = 256 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def destination(root: Path, name: str) -> Path:
    parts = name.split('/')
    if (not name.startswith(PREFIX) or not name.endswith('.json')
            or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in parts)
            or PurePosixPath(name).is_absolute()):
        raise ValueError(f'unsafe artifact path: {name!r}')
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError('artifact escapes destination root')
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError('symlink in artifact destination')
        current = current.parent
    return target


def restore(archive: Path, manifest_path: Path, root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported artifact manifest')
    entries = manifest['files']
    names = [row['path'] for row in entries]
    if not names or len(set(names)) != len(names):
        raise ValueError('empty or duplicate manifest paths')
    targets = {name: destination(root, name) for name in names}
    if any(not isinstance(row['bytes'], int) or row['bytes'] <= 0 for row in entries):
        raise ValueError('invalid artifact size')
    total = sum(row['bytes'] for row in entries)
    if total != manifest['uncompressed_bytes'] or total > MAX_BYTES:
        raise ValueError('invalid uncompressed artifact budget')
    if archive.stat().st_size != manifest['archive_bytes'] or sha256(archive) != manifest['archive_sha256']:
        raise ValueError('archive size or SHA256 mismatch')
    data = {}
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if (len(members) != len(entries) or {m.name for m in members} != set(names)
                or any(not m.isfile() or m.issym() or m.islnk() for m in members)):
            raise ValueError('archive members differ from manifest or contain links')
        expected = {row['path']: row for row in entries}
        for member in members:
            row = expected[member.name]
            if member.size != row['bytes']:
                raise ValueError('member size mismatch')
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError('missing artifact payload')
            payload = stream.read(row['bytes'] + 1)
            if len(payload) != row['bytes'] or hashlib.sha256(payload).hexdigest() != row['sha256']:
                raise ValueError(f'member SHA256 mismatch: {member.name}')
            data[member.name] = payload
    # Validate every member and every existing destination before the first write.
    for row in entries:
        target = targets[row['path']]
        if target.exists() and (not target.is_file() or sha256(target) != row['sha256']):
            raise FileExistsError(f'will not overwrite existing artifact: {target}')
    written = 0
    for name, payload in data.items():
        target = targets[name]
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        destination(root, name)  # Recheck containment after directory creation.
        with target.open('xb') as stream:
            stream.write(payload)
        written += 1
    return {'verified': len(entries), 'written': written, 'bytes': total,
            'archive_sha256': manifest['archive_sha256']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(restore(args.archive, args.manifest, args.root), sort_keys=True))


if __name__ == '__main__':
    main()
