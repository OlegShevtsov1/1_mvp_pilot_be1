"""Runs bin/local-smoke: the whole API on a live local server, checked against the contract.

Deselected from the unit suite; run it with `uv run pytest -m smoke`. LOCAL_SMOKE_REF picks the
commit of origin to serve (bin/local-smoke's default, origin/main, when unset).
"""

import os
import signal
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
TIMEOUT = 300


@pytest.mark.smoke
def test_local_smoke_passes_and_stops_the_server():
    ref = os.environ.get("LOCAL_SMOKE_REF")
    args = [str(BIN / "local-smoke"), *(["--ref", ref] if ref else [])]

    # Its own process group, so a timeout can SIGTERM the script and its running step together:
    # bash then runs its EXIT trap, which stops the daemonized server. SIGKILL would skip the trap.
    smoke = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = smoke.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(smoke.pid, signal.SIGTERM)
        stdout, stderr = smoke.communicate(timeout=60)
        pytest.fail(f"bin/local-smoke timed out after {TIMEOUT} s\n{stdout}{stderr}")

    assert smoke.returncode == 0, stdout + stderr
    assert stdout.splitlines()[-1].startswith("smoke: ")
    assert subprocess.run([str(BIN / "local-check")], capture_output=True).returncode != 0, (
        "the server still answers on 127.0.0.1:8095 after bin/local-smoke"
    )
