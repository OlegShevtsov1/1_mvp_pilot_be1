import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "pr-conventions.sh"


@pytest.mark.parametrize(
    ("title", "body", "exit_code"),
    [
        ("BE1-1: x", "Type: feat", 0),
        ("BE1-12-3: x", "Type: fix", 0),
        ("BE1-1: x", "Type: feat\r\n", 0),
        ("BE1-1 x", "Type: feat", 1),
        ("ABC-1: x", "Type: feat", 1),
        ("BE1-1: x", "no type line", 1),
        ("BE1-1: x", "Type: feat\nType: fix", 1),
        ("BE1-1: x", "Type: feature", 1),
    ],
)
def test_pr_conventions(title, body, exit_code):
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "PR_TITLE": title, "PR_BODY": body},
        capture_output=True,
        text=True,
    )

    assert result.returncode == exit_code, result.stdout + result.stderr
