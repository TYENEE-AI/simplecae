"""Timeout cleanup must include native descendants of a campaign worker."""
from pathlib import Path
import subprocess
import sys
import time
import pytest
from simplecae.execution import run_owned_worker


def test_campaign_timeout_stops_descendant(tmp_path):
    marker = tmp_path / "orphan.txt"
    child = f"import time,pathlib;time.sleep(3);pathlib.Path({str(marker)!r}).write_text('orphan')"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned_worker([sys.executable, "-c", parent], timeout=1)
    time.sleep(3.1)
    assert not marker.exists()


def test_worker_exit_code_is_not_replaced_by_success():
    result = run_owned_worker([sys.executable, "-c", "raise SystemExit(7)"], timeout=10)
    assert result.returncode == 7
