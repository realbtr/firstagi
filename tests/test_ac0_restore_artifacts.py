"""Storage boundary tests on tiny archives; no saved experiment is executed."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from experiments.diagnostics.ac0_restore_artifacts import restore

NAME = 'experiments/reports/ac0_debug/fixture/data.json'


def archive_fixture(tmp_path, names=(NAME,), link=False, bad_member_hash=False):
    archive = tmp_path / 'fixture.tar.gz'
    payload = b'{"fixture": true}\n'
    entries = []
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in names:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            if link:
                member.type = tarfile.SYMTYPE
                member.linkname = '/outside'
            bundle.addfile(member, None if link else io.BytesIO(payload))
            entries.append({'path': name, 'bytes': len(payload),
                            'sha256': '0'*64 if bad_member_hash else hashlib.sha256(payload).hexdigest()})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'files': entries,
        'uncompressed_bytes': sum(row['bytes'] for row in entries),
        'archive_bytes': archive.stat().st_size,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}), encoding='utf-8')
    return archive, manifest, tmp_path / 'repo', payload


def test_verified_restore_and_idempotent_reuse(tmp_path):
    archive, manifest, root, payload = archive_fixture(tmp_path)
    assert restore(archive, manifest, root)['written'] == 1
    assert (root / NAME).read_bytes() == payload
    assert restore(archive, manifest, root)['written'] == 0


def test_corrupt_archive_rejected_before_writes(tmp_path):
    archive, manifest, root, _ = archive_fixture(tmp_path)
    archive.write_bytes(archive.read_bytes() + b'tamper')
    with pytest.raises(ValueError, match='archive size or SHA256'):
        restore(archive, manifest, root)
    assert not root.exists()


def test_bad_member_hash_rejected_before_writes(tmp_path):
    archive, manifest, root, _ = archive_fixture(tmp_path, bad_member_hash=True)
    with pytest.raises(ValueError, match='member SHA256'):
        restore(archive, manifest, root)
    assert not root.exists()


@pytest.mark.parametrize('name', [
    '../outside.json', '/absolute.json',
    'experiments/reports/ac0_debug/../outside.json',
    'experiments/reports/ac0_debug/C:evil.json',
    'experiments/reports/ac0_debug/back\\slash.json',
])
def test_unsafe_names_rejected(tmp_path, name):
    archive, manifest, root, _ = archive_fixture(tmp_path, names=(name,))
    with pytest.raises(ValueError, match='unsafe artifact path'):
        restore(archive, manifest, root)
    assert not root.exists()


def test_archive_link_rejected(tmp_path):
    archive, manifest, root, _ = archive_fixture(tmp_path, link=True)
    with pytest.raises(ValueError, match='members'):
        restore(archive, manifest, root)
    assert not root.exists()


def test_existing_different_file_preserved(tmp_path):
    archive, manifest, root, _ = archive_fixture(tmp_path)
    target = root / NAME
    target.parent.mkdir(parents=True)
    target.write_bytes(b'owner data')
    with pytest.raises(FileExistsError, match='will not overwrite'):
        restore(archive, manifest, root)
    assert target.read_bytes() == b'owner data'


def test_duplicate_manifest_paths_rejected(tmp_path):
    archive, manifest, root, _ = archive_fixture(tmp_path, names=(NAME, NAME))
    with pytest.raises(ValueError, match='duplicate'):
        restore(archive, manifest, root)
    assert not root.exists()
