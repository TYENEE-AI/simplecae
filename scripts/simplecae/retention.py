"""Lossless, run-local compaction after analysis; no background cache or history purge."""
from pathlib import Path
import gzip
import hashlib
import os
import shutil
import stat
import uuid

from .case import sha256, write_json


def validate_storage(mode):
    if mode not in ('compact', 'full'):
        raise ValueError('storage must be compact or full')
    return mode


def _linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def compact_output(directory):
    """Keep every mesh, field, deck and diagnostic; gzip redundant native text.

    Only recognized native artifacts beside an owned deck/mesh are candidates.
    Verify the decompressed hash before unlinking the original. Results and
    Viewer bindings are never rewritten; failures/partial fields are retained.
    Call only after all solvers/readers using this output have stopped.
    """
    root = Path(directory)
    if _linked(root):
        raise ValueError('refusing a symlink output directory')
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('analysis output directory does not exist')
    candidates = []
    for base, dirs, names in os.walk(root, followlinks=False):
        parent = Path(base)
        dirs[:] = [name for name in dirs if not _linked(parent / name)]
        for name in names:
            path = parent / name
            native = path.suffix in ('.dat', '.frd') and path.with_suffix('.inp').is_file()
            mesh = name == 'mesh.msh' and (parent / 'mesh.npz').is_file()
            if (native or mesh) and not _linked(path):
                candidates.append(path)
    record_path = root / 'storage.json'
    if record_path.is_symlink():
        raise ValueError('refusing a symlink storage record')
    import json
    previous = json.loads(record_path.read_text(encoding='utf-8')) if record_path.is_file() else {}
    entries = {item['original']: item for item in previous.get('compressed', [])}
    errors = []
    for source in sorted(candidates):
        relative = source.relative_to(root).as_posix()
        target = source.with_name(source.name + '.gz')
        pending = source.with_name(source.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            if target.exists():
                raise ValueError('compressed target already exists; original retained')
            before = source.stat()
            expected = sha256(source)
            with source.open('rb') as src, pending.open('xb') as raw:
                with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=3, mtime=0) as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            digest = hashlib.sha256()
            with gzip.open(pending, 'rb') as check:
                for block in iter(lambda: check.read(1024 * 1024), b''):
                    digest.update(block)
            after = source.stat()
            if (digest.hexdigest() != expected or
                (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino)
                or sha256(source) != expected):
                raise RuntimeError('native evidence changed or compression verification failed')
            # Persist the recovery information before removing the original.
            pending.replace(target)
            entries[relative] = {'original': relative, 'gzip': relative + '.gz',
                'original_sha256': expected, 'gzip_sha256': sha256(target),
                'original_bytes': before.st_size, 'gzip_bytes': target.stat().st_size}
            write_json(record_path, {'schema_version': 'simplecae-storage-1', 'mode': 'compact',
                'lossless': True, 'compressed': list(entries.values()), 'errors': errors,
                'meaning': 'Native DAT/FRD/MSH text is losslessly compressed; all mesh levels, fields, decks, logs, decisions and failures remain. No other run or user source is deleted.'})
            source.unlink()
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append({'file': relative, 'error': f'{type(exc).__name__}: {exc}'})
        finally:
            if pending.exists():
                pending.unlink()
    record = {'schema_version': 'simplecae-storage-1', 'mode': 'compact', 'lossless': True,
        'compressed': list(entries.values()), 'errors': errors,
        'saved_bytes': sum(item['original_bytes'] - item['gzip_bytes'] for item in entries.values()
                           if not (root / item['original']).exists()),
        'meaning': 'Native DAT/FRD/MSH text is losslessly compressed; all mesh levels, fields, decks, logs, decisions and failures remain. No other run or user source is deleted.'}
    write_json(record_path, record)
    return record


def retain_output(directory, mode='compact'):
    validate_storage(mode)
    if mode == 'full':
        return {'mode': 'full', 'saved_bytes': 0}
    return compact_output(directory)
