"""Warn about unignored analysis outputs without editing user Git settings."""
from pathlib import Path
import subprocess

_reported = set()


def output_warning(path):
    target = Path(path).resolve()
    base = target if target.is_dir() else target.parent
    while not base.exists() and base != base.parent:
        base = base.parent
    try:
        root = subprocess.run(['git', '-C', str(base), 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=5)
        if root.returncode: return None
        key = root.stdout.strip()
        if key in _reported: return None
        ignored = subprocess.run(['git', '-C', key, 'check-ignore', '--quiet', '--', str(target)],
                                 capture_output=True, timeout=5)
        if ignored.returncode == 1:
            _reported.add(key)
            return f'Output {target} is not ignored by Git. Prefer out/cae/ or .simplecae/ and add the selected output directory to .gitignore; no files were changed automatically.'
    except (OSError, subprocess.TimeoutExpired):
        return None
