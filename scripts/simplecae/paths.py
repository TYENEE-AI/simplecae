"""Read-only bundled resources in a source checkout or an installed wheel."""
from pathlib import Path


def resource_root():
    package = Path(__file__).resolve().parent
    bundled = package / "_data"
    if bundled.is_dir():
        return bundled
    checkout = package.parent.parent
    if (checkout / "assets").is_dir() and (checkout / "examples").is_dir():
        return checkout
    raise FileNotFoundError(
        "SimpleCAE resources are missing. Reinstall the complete simplecae-toolkit "
        "package or use the complete skill checkout."
    )


def worker_entry():
    """Absolute executable entrypoint, independent of cwd and editable installs."""
    return str(Path(__file__).resolve().with_name("__main__.py"))
