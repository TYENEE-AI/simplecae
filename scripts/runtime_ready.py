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
    return True


def main(root):
    # Only Python dependency/source problems justify pip. Native loader failures
    # require system libraries or an execution-environment repair, not reinstall.
    try:
        if not ready(root):
            print('Python runtime setup needed: incompatible dependency or source identity')
            return 1
    except (metadata.PackageNotFoundError, ModuleNotFoundError, StopIteration) as exc:
        print(f'Python runtime setup needed: {exc}')
        return 1
    except Exception as exc:
        print(f'Runtime inspection failed; repair metadata/configuration before retrying: {exc}')
        return 3
    try:
        from simplecae import gmsh_runtime
        gmsh_runtime.initialize()
        gmsh_runtime.finalize()
    except ModuleNotFoundError as exc:
        if exc.name == 'gmsh':
            print(f'Python runtime setup needed: {exc}')
            return 1
        print(f'Native runtime unavailable; repair shared libraries/runtime before retrying, not pip: {exc}')
        return 2
    except Exception as exc:
        print(f'Native runtime unavailable; repair shared libraries/runtime before retrying, not pip: {exc}')
        return 2
    print('Python dependencies, source identity and native loading are ready')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
