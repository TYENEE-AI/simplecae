"""Bundle runtime resources without duplicating them in the source tree."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithResources(build_py):
    def run(self):
        super().run()
        source = Path(__file__).resolve().parent
        build_root = Path(self.build_lib).resolve()
        target = build_root / "simplecae" / "_data"
        # setuptools can reuse build/lib; removed resources must not leak into
        # a later wheel. Delete only this generated, contained resource tree.
        if target.is_symlink() or not target.resolve().is_relative_to(build_root):
            raise ValueError("Generated resource directory escapes the build root")
        if target.exists():
            shutil.rmtree(target)
        for directory in ("assets", "examples"):
            for path in sorted((source / directory).rglob("*")):
                if not path.is_file() or any(
                    part in {"__pycache__", "__marimo__"} for part in path.parts
                ) or path.suffix in {".pyc", ".pyo"}:
                    continue
                destination = target / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                self.copy_file(str(path), str(destination))


setup(cmdclass={"build_py": BuildWithResources})
