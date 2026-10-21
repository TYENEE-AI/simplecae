"""Installed workers must not depend on a checkout or the caller's cwd."""
import os
import subprocess
import sys
from simplecae import __version__
from simplecae.paths import resource_root, worker_entry


def test_owned_entrypoint_works_from_unrelated_directory(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    process = subprocess.run(
        [sys.executable, worker_entry(), "--version"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20,
    )
    assert process.returncode == 0, process.stderr
    assert __version__ in process.stdout


def test_runtime_resources_cover_viewer_and_reproducible_example():
    root = resource_root()
    assert (root / "assets/workbench.js").is_file()
    assert (root / "examples/preview/examples.json").is_file()
