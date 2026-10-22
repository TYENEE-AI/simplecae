"""CLI entrypoint for both ``python -m simplecae`` and owned worker processes."""
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplecae.process_lock import worker_guard
worker_guard()
from simplecae.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
