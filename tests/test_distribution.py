"""The built distributions carry what users install and rely on.

The sdist and the wheel are built in-process with the build backend, offline,
and the wheel is built from the extracted sdist, as an installer would. The
distributions are the artifact: set SSLABDATA_DIST_DIR to keep them, then
inspect with `tar tzf` and `unzip -l`.

    SSLABDATA_DIST_DIR=/tmp/dist pytest tests/test_distribution.py
    tar tzf /tmp/dist/sslabdata-*.tar.gz
    unzip -l /tmp/dist/sslabdata-*.whl

Tests are not distributed (clone the repository for them). The current output
schema is wheel data, read through importlib.resources.
"""

import os
import tarfile
import zipfile
from pathlib import Path

from setuptools import build_meta

REPO_ROOT = Path(__file__).parent.parent
# The current schema is the newest one in schema/, so a new version that
# pyproject.toml does not ship fails here instead of shipping a stale schema.
CURRENT = max((REPO_ROOT / "schema").glob("v*"), key=lambda p: int(p.name[1:]))
SCHEMA = f"{CURRENT.name}/output.schema.json"


def test_distributions_carry_the_public_resources(tmp_path, monkeypatch):
    dist = Path(os.environ.get("SSLABDATA_DIST_DIR") or tmp_path / "dist")
    dist.mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(REPO_ROOT)
    sdist = dist / build_meta.build_sdist(str(dist))
    with tarfile.open(sdist) as tar:
        tar.extractall(tmp_path / "src", filter="data")
        sdist_files = {m.name.split("/", 1)[1] for m in tar.getmembers() if m.isfile()}

    monkeypatch.chdir(next((tmp_path / "src").iterdir()))
    wheel = dist / build_meta.build_wheel(str(dist))
    with zipfile.ZipFile(wheel) as zf:
        wheel_files = set(zf.namelist())
        packaged_schema = zf.read(f"sslabdata/schema/{SCHEMA}")

    modules = {p.relative_to(REPO_ROOT).as_posix()
               for p in (REPO_ROOT / "sslabdata").rglob("*.py")}
    assert {"README.md", "LICENSE", "SPEC.md", f"schema/{SCHEMA}"} | modules <= sdist_files
    assert {f"sslabdata/schema/{SCHEMA}"} | modules <= wheel_files
    # One canonical schema: the packaged copy is the repository file.
    assert packaged_schema == (REPO_ROOT / "schema" / SCHEMA).read_bytes()
    for files in (sdist_files, wheel_files):
        assert not any("tests" in Path(f).parts for f in files)
