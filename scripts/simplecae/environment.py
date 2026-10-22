"""Read-only diagnostics for isolated CAD/CAE runtimes."""
import importlib.metadata
import platform
import os
from pathlib import Path


def runtime_copies(active_root, compare_roots=()):
    """Inspect known skill roots and explicitly supplied copies, never scan disks."""
    from .case import sha256
    active=Path(active_root).resolve()
    configured=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'skills/simplecae'
    candidates={active,configured.resolve(),*(Path(p).expanduser().resolve() for p in compare_roots)}
    for path in compare_roots:
        if not (Path(path).expanduser()/'SKILL.md').is_file():raise ValueError('Compared runtime root needs SKILL.md: '+str(path))
    copies=[]
    for candidate in sorted(candidates,key=str):
        if (candidate/'SKILL.md').is_file():
            copies.append({'root':str(candidate),'active_resources':candidate==active,
                           'skill_sha256':sha256(candidate/'SKILL.md'),
                           'entrypoint':str(candidate/'scripts/simplecae_cli.py') if (candidate/'scripts/simplecae_cli.py').is_file() else None})
    return {'active_resource_root':str(active),'known_copies':copies,
            'multiple_copies_detected':len(copies)>1,
            'search_scope':'Active resources, configured Codex skill, and explicit --compare-root values only; not a whole-disk inventory.'}


def environment_warnings():
    installed = {}
    for name in ('cadquery-ocp', 'cadquery-ocp-novtk', 'simplecadapi', 'cadgen'):
        try: installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    warnings = []
    if 'cadquery-ocp' in installed and 'cadquery-ocp-novtk' in installed:
        warnings.append('cadquery-ocp and cadquery-ocp-novtk share the OCP namespace. '
                        'Recreate separate SimpleCADAPI, cadgen and SimpleCAE environments; '
                        'uninstalling one overlapping distribution can break the other.')
    if 'simplecadapi' in installed and tuple(map(int, platform.python_version_tuple()[:2])) >= (3,14):
        warnings.append('The validated SimpleCADAPI 2.2.6.post2 runtime requires Python <3.14; use its own Python 3.13 environment.')
    return warnings


def solver_install_hint():
    system = platform.system()
    instruction = ('scripts/bootstrap.ps1' if system == 'Windows' else
                   'scripts/bootstrap.sh; for a no-sudo runtime see references/platform-installation.md')
    return f'{system}: run {instruction} or set SIMPLECAE_CCX / --ccx to a native executable'
