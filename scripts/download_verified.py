"""Download a pinned archive with a bounded worker and retained failure evidence."""
import argparse
import hashlib
import math
from pathlib import Path
import subprocess
import sys
import tempfile


WORKER = '''import shutil,sys,urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=60) as response:
    with open(sys.argv[2], "wb") as output:
        shutil.copyfileobj(response, output)
'''


def download(url, destination, expected_sha256, timeout=3000):
    destination = Path(destination).resolve()
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Download timeout must be finite and positive')
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256.lower()):
        raise ValueError('Expected SHA-256 must be a 64-character hexadecimal digest')
    def verified(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == expected_sha256.lower()
    if destination.exists():
        if not verified(destination):
            raise ValueError(f'SHA-256 mismatch: {destination}. Preserve and move this invalid archive aside before retrying; it was not extracted or overwritten.')
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=destination.name + '.', suffix='.partial', dir=destination.parent, delete=False) as stream:
        partial = Path(stream.name)
    try:
        # socket timeouts do not bound a trickling response. The parent bounds
        # this one owned Python worker; run() kills and waits for it on timeout.
        subprocess.run([sys.executable, '-c', WORKER, url, str(partial)],
                       capture_output=True, text=True, check=True, timeout=timeout)
        if not verified(partial):
            raise ValueError('Downloaded archive SHA-256 mismatch')
        partial.replace(destination)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise RuntimeError(f'Download failed; retained {partial}. Retry the same command after addressing the network or timeout. {detail}') from exc
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('destination')
    parser.add_argument('sha256')
    parser.add_argument('--timeout', type=float, default=3000)
    args = parser.parse_args()
    try:
        print(download(args.url, args.destination, args.sha256, args.timeout))
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
