"""Tests for the CLI."""

import shutil
import subprocess
import sys
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures"


def test_installed_command_smoke():
    """The installed `sslabdata` console script runs end to end.

    Every conformance test calls `main()` in-process, so only a subprocess
    catches a broken console-script entry point or an exit status the
    process does not carry out."""
    exe = shutil.which("sslabdata", path=str(Path(sys.executable).parent)) or shutil.which("sslabdata")
    assert exe, "sslabdata console script is not installed"
    result = subprocess.run(
        [exe, "--config", str(FIXTURES / "lab.yaml"), "--validate"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
