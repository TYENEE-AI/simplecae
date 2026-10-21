"""Storage is lossless and must never change an analysis or delete foreign files."""
import gzip
import hashlib
import json
from pathlib import Path
import pytest
from simplecae.retention import compact_output, validate_storage


def fixture_output(root):
    level = root / 'level-01'
    level.mkdir(parents=True)
    (root / 'result.json').write_text('{"status":"indeterminate"}')
    for name, data in {'job.inp': b'*NODE\n', 'job.dat': b'raw peak 999.9\n' * 1000,
                       'job.frd': b'native field\n' * 1000, 'mesh.msh': b'mesh\n' * 1000,
                       'mesh.npz': b'untouched mesh', 'fields.npz': b'uncropped fields',
                       'job.solver.log': b'failed diagnostic', 'job.sta': b'stages',
                       'user.dat': b'not a solver artifact'}.items():
        (level / name).write_bytes(data)
    return level


def test_compaction_preserves_exact_raw_evidence_decision_and_fields(tmp_path):
    level = fixture_output(tmp_path)
    originals = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    receipt = compact_output(tmp_path)
    assert not receipt['errors'] and receipt['saved_bytes'] > 0
    assert {Path(e['original']).name for e in receipt['compressed']} == {'job.dat','job.frd','mesh.msh'}
    for relative, data in originals.items():
        target = tmp_path / relative
        if target.exists():
            assert target.read_bytes() == data
        else:
            assert gzip.decompress(Path(str(target) + '.gz').read_bytes()) == data
    for item in receipt['compressed']:
        assert hashlib.sha256(originals[item['original']]).hexdigest() == item['original_sha256']
    assert not (level / 'job.dat').exists()
    assert compact_output(tmp_path)['saved_bytes'] == receipt['saved_bytes']


def test_partial_failed_native_job_keeps_every_byte_and_log(tmp_path):
    (tmp_path / 'job.inp').write_text('*HEADING\n')
    (tmp_path / 'job.dat').write_bytes(b'partial failed fields\n' * 100)
    (tmp_path / 'job.solver.log').write_text('TIMEOUT\n')
    compact_output(tmp_path)
    assert gzip.decompress((tmp_path / 'job.dat.gz').read_bytes()) == b'partial failed fields\n' * 100
    assert (tmp_path / 'job.solver.log').read_text() == 'TIMEOUT\n'
    assert not (tmp_path / 'result.json').exists()


def test_existing_gzip_and_failed_compression_do_not_remove_original(tmp_path, monkeypatch):
    fixture_output(tmp_path)
    (tmp_path / 'level-01/job.dat.gz').write_bytes(b'user-owned-existing-file')
    monkeypatch.setattr('simplecae.retention.shutil.copyfileobj', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    receipt = compact_output(tmp_path)
    assert len(receipt['errors']) == 3
    assert (tmp_path / 'level-01/job.dat').is_file()
    assert (tmp_path / 'level-01/job.dat.gz').read_bytes() == b'user-owned-existing-file'
    assert (tmp_path / 'level-01/job.frd').is_file()
    assert not list(tmp_path.rglob('*.tmp'))


@pytest.mark.parametrize('mode', ['compact','full'])
def test_supported_storage_modes(mode):
    assert validate_storage(mode) == mode


def test_invalid_storage_is_rejected():
    with pytest.raises(ValueError):
        validate_storage('delete-evidence')


def test_directory_links_are_not_traversed(tmp_path, monkeypatch):
    owned = tmp_path / 'owned'
    foreign = tmp_path / 'foreign'
    fixture_output(owned)
    fixture_output(foreign)
    # Portable equivalent of the Windows reparse-point guard. An actual link
    # is not required to exercise traversal rejection under restricted hosts.
    import simplecae.retention as module
    original = module._linked
    monkeypatch.setattr(module, '_linked', lambda p: p == owned / 'level-01' or original(p))
    assert not compact_output(owned)['compressed']
    assert (owned / 'level-01/job.dat').is_file()
    assert (foreign / 'level-01/job.dat').is_file()
