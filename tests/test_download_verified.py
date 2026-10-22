"""Actual HTTP interruption/slow-stream recovery, without external network access."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from download_verified import download


@pytest.fixture
def server():
    payload = b'pinned-archive-fixture' * 4096
    started = threading.Event()
    disconnected = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/unavailable':
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            started.set()
            try:
                if self.path == '/slow':
                    for _ in range(400):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.05)
                else:
                    self.wfile.write(payload[:100] if self.path == '/interrupted' else payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                disconnected.set()

    service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    service.daemon_threads = True
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{service.server_port}', payload, started, disconnected
    service.shutdown()
    service.server_close()
    worker.join(timeout=5)


@pytest.mark.parametrize('failure', ['interrupted', 'unavailable', 'hash-mismatch'])
def test_failed_download_does_not_poison_retry_or_discard_evidence(server, tmp_path, failure):
    url, payload, _, _ = server
    target = tmp_path / 'archive.zip'
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(RuntimeError, match='retained'):
        download(url + '/' + failure, target, '0' * 64 if failure == 'hash-mismatch' else digest, 10)
    assert not target.exists()
    failed = list(tmp_path.glob('*.partial'))
    assert len(failed) == 1
    previous = failed[0].read_bytes()
    assert download(url + '/ok', target, digest, 10) == target
    assert target.read_bytes() == payload
    assert failed[0].read_bytes() == previous
    assert list(tmp_path.glob('*.partial')) == failed


def test_trickling_response_is_bounded_by_parent_and_worker_is_stopped(server, tmp_path):
    url, payload, started, disconnected = server
    target = tmp_path / 'archive.zip'
    before = time.monotonic()
    with pytest.raises(RuntimeError, match='timed out'):
        download(url + '/slow', target, hashlib.sha256(payload).hexdigest(), 2)
    assert time.monotonic() - before < 10
    assert started.is_set()
    assert disconnected.wait(4), 'Timed-out download worker retained its HTTP connection'
    assert not target.exists() and len(list(tmp_path.glob('*.partial'))) == 1


@pytest.mark.parametrize('corrupt', [False, True])
def test_existing_archive_is_verified_without_network_or_overwrite(tmp_path, corrupt):
    target = tmp_path / 'archive.zip'
    payload = b'verified archive'
    target.write_bytes(b'corrupt evidence' if corrupt else payload)
    digest = hashlib.sha256(payload).hexdigest()
    if corrupt:
        with pytest.raises(ValueError, match='Preserve and move'):
            download('http://127.0.0.1:1/must-not-connect', target, digest)
        assert target.read_bytes() == b'corrupt evidence'
    else:
        assert download('http://127.0.0.1:1/must-not-connect', target, digest) == target
    assert not list(tmp_path.glob('*.partial'))


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf')])
def test_invalid_deadline_does_not_start_download(tmp_path, timeout):
    with pytest.raises(ValueError, match='finite and positive'):
        download('http://127.0.0.1:1', tmp_path / 'archive', '0' * 64, timeout)
    assert not list(tmp_path.iterdir())
