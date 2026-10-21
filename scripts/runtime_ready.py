"""Cheap bootstrap reuse check; no source hashes, solver run or network access."""
from pathlib import Path
import importlib.metadata as metadata
import json
import sys
import sysconfig
import tomllib
from urllib.parse import urlsplit
from urllib.request import url2pathname


def ready(root):
    # pip ships packaging even in a fresh venv; this adds no runtime dependency.
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf8'))['project']
    if not SpecifierSet(project['requires-python']).contains('.'.join(map(str, sys.version_info[:3]))):
        return False
    for text in project['dependencies']:
        req = Requirement(text)
        if req.marker is not None and not req.marker.evaluate():
            continue
        if not req.specifier.contains(metadata.version(req.name)):
            return False
    import simplecae
    if Path(simplecae.__file__).resolve() != (root / 'scripts/simplecae/__init__.py').resolve():
        return False
    # Editable source reports its own version. Stale dist-info alone does not
    # justify downloading/rebuilding an otherwise compatible working runtime.
    # A checkout's scripts/*.egg-info may shadow venv metadata on sys.path.
    installed = next(d for d in metadata.distributions(path=[sysconfig.get_path('purelib')])
                     if d.metadata.get('Name', '').replace('_', '-').lower() == project['name'].replace('_', '-').lower())
    origin = json.loads(installed.read_text('direct_url.json') or '{}')
    url = urlsplit(origin.get('url', ''))
    if not origin.get('dir_info', {}).get('editable') or url.scheme != 'file':
        return False
    if Path(url2pathname(url.path)).resolve() != root.resolve():
        return False
    import gmsh
    gmsh.initialize()
    gmsh.finalize()
    return True


if __name__ == '__main__':
    try:
        ok = ready(Path(__file__).resolve().parents[1])
    except Exception as exc:
        print(f'Runtime setup needed: {exc}')
        ok = False
    raise SystemExit(0 if ok else 1)
