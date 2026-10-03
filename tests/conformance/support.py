"""Helpers for the conformance tests (see tests/COVERAGE.md).

The conformance tests run sslabdata only through its public entry points,
``sslabdata.cli.main()`` and the assembler, and check sslabdata's own output and
messages. They never look at parser-library objects or messages, so the same
tests run whichever parser library sits behind the adapter.
"""

import contextlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pytest
import yaml

from sslabdata.cli import main


TESTS_DIR = Path(__file__).parent.parent
CORPUS = TESTS_DIR / "corpus"
VALID = CORPUS / "valid"
INVALID = CORPUS / "invalid"
EXPECTED = CORPUS / "expected"
REPO_ROOT = TESTS_DIR.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "v8" / "output.schema.json"

# The published schemas before v8. Each stays reachable byte for byte at its
# own path, so a consumer pinned to v3, v4, v5, v6 or v7 keeps a stable target
# (SPEC.md section 6).
PREVIOUS_SCHEMA_PATHS = {
    version: REPO_ROOT / "schema" / f"v{version}" / "output.schema.json"
    for version in (3, 4, 5, 6, 7)
}


def case(case_id, *values, marks=()):
    """One row of a parameter table: a case ID from tests/COVERAGE.md, then
    the test's values. The ID and the first two values name the row."""
    label = ":".join([case_id] + [str(v) for v in values[:2]])
    return pytest.param(case_id, *values, id=label, marks=marks)


# --- Running sslabdata ---------------------------------------------------------

@dataclass
class Run:
    """The result of one ``sslabdata`` command run in-process."""
    code: int
    stdout: str
    stderr: str
    crash: Optional[str] = None  # an uncaught exception, which is never OK

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@contextlib.contextmanager
def working_dir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run_sslabdata(args: List[str], cwd: Path) -> Run:
    """Run ``sslabdata <args>`` from ``cwd``, capturing its exit code and output."""
    out, err = io.StringIO(), io.StringIO()
    code, crash = 0, None
    with working_dir(cwd), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main([str(a) for a in args])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001 - a crash is a result to report
            crash = f"{type(e).__name__}: {e}"
    return Run(code=code, stdout=out.getvalue(), stderr=err.getvalue(), crash=crash)


def export(cwd: Path, out_dir: Path, config="lab.yaml", fmt="json"):
    """Run ``sslabdata --output`` from ``cwd`` and return (run, parsed output)."""
    out_path = Path(out_dir) / f"lab.{fmt}"
    run = run_sslabdata(["--config", config, "--format", fmt, "--output", out_path], cwd)
    data = None
    if run.crash is None and run.code == 0:
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f) if fmt == "json" else yaml.safe_load(f)
    return run, data


def write_atomically(path, text: str) -> None:
    """Replace ``path`` with ``text`` whole, or leave it as it was."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_variant(tmp_path: Path, **changes) -> Path:
    """Write valid/lab.yaml with some keys changed (None removes a key).

    The variant keeps the valid corpus's relative paths, so run it from VALID.
    """
    with open(VALID / "lab.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for key, value in changes.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    path = tmp_path / "variant.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return path


# --- Looking things up in the output ---------------------------------------

def work(data, bib_id):
    matches = [w for w in data["works"] if w["bib_id"] == bib_id]
    assert len(matches) == 1, f"expected one work {bib_id!r}, found {len(matches)}"
    return matches[0]


def item(data, section, key, value):
    matches = [x for x in data[section] if x[key] == value]
    assert len(matches) == 1, f"expected one {section} entry with {key}={value!r}"
    return matches[0]


def get_path(obj, path: str):
    """Follow a dotted path: ``authors.0.name``, ``authors.*.name``."""
    parts = path.split(".")
    for i, part in enumerate(parts):
        if part == "*":
            rest = ".".join(parts[i + 1:])
            return [get_path(x, rest) if rest else x for x in obj]
        if isinstance(obj, list):
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            raise KeyError(f"cannot follow {path!r} at {part!r}")
    return obj


# --- Expected values ---------------------------------------------------------

class Contains:
    """Expected: a string or list that contains every one of ``parts``."""
    def __init__(self, *parts):
        self.parts = parts

    def check(self, actual):
        return actual is not None and all(p in actual for p in self.parts)

    def __repr__(self):
        return f"Contains{self.parts!r}"


class Excludes:
    """Expected: a string or list that contains none of ``parts``."""
    def __init__(self, *parts):
        self.parts = parts

    def check(self, actual):
        return actual is not None and not any(p in actual for p in self.parts)

    def __repr__(self):
        return f"Excludes{self.parts!r}"


class AllOf:
    """Expected: every one of the given expectations."""
    def __init__(self, *expectations):
        self.expectations = expectations

    def check(self, actual):
        return all(matches(e, actual) for e in self.expectations)

    def __repr__(self):
        return f"AllOf{self.expectations!r}"


def matches(expected, actual):
    if hasattr(expected, "check"):
        return expected.check(actual)
    return actual == expected


def assert_field(obj, path, expected, where=""):
    actual = get_path(obj, path)
    assert matches(expected, actual), f"{where}{path}: expected {expected!r}, got {actual!r}"
