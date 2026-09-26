"""The invalid corpus (tests/corpus/invalid/<dir>/): one complete outcome per fixture.

tests/corpus/expected/diagnostics.yaml holds, for each fixture, what a user
can observe: the exit status, every diagnostic with its code, severity and
location, and the works and values the document keeps. Each fixture is run once
per mode and once through the Python API, and the observations are compared
with that entry in `test_outcome`. Checks use codes, severities, locations and
the values that are wrong, never the wording of a message.

The same runs are the conformance-results artifact. To write it, set
SSLABDATA_CONFORMANCE_RESULTS to a path (see tests/COVERAGE.md); its content
does not depend on the host, the working directory or the time.

Below that are the few tests that need a tree the corpus does not hold: names
that leave `bib_dir` through a symlink, a file with no permissions, and the
text-mode streams of a fatal-at-load code.
"""

import contextlib
import io
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import pytest
import yaml

from sslabdata import (
    AssemblyError, ConfigurationError, LabDataConfig, assemble,
)

from .support import (
    EXPECTED, INVALID, REPO_ROOT, AllOf, Contains, Excludes, assert_field,
    export, item, run_sslabdata, working_dir, write_atomically,
)

with open(EXPECTED / "diagnostics.yaml", encoding="utf-8") as f:
    DIAGNOSTICS = yaml.safe_load(f)

RESULTS_ENV = "SSLABDATA_CONFORMANCE_RESULTS"

# Reported by every fixture that declares no lab name; test_config_cli.py owns it.
INCIDENTAL = {"CONFIG-LAB-NAME-MISSING"}

SUBJECT = {"work": ("works", "bib_id"), "person": ("people", "id"),
           "project": ("projects", "id")}
# A diagnostic on standard error: `Warning: ` before a warning, and either
# nothing or an `Error...: ` prefix before an error (SPEC.md, Streams).
LINE = re.compile(r"^(Warning: |Error: |Error loading configuration: )?"
                  r"([A-Z]+(?:-[A-Z]+)+) ")


def printed(line):
    """`<severity> <code> <location>` of one line of standard error, whose
    location runs to the first `: `; `uncoded` for a line that carries no code."""
    found = LINE.match(line)
    if not found:
        return "uncoded"
    severity = "warning" if found.group(1) == "Warning: " else "error"
    return f"{severity} {found.group(2)} {line[found.end():].split(': ', 1)[0]}"


def stream(want):
    """The `printed()` form of an expected diagnostic."""
    return (f"{want['severity']} {want['code']} "
            f"{want.get('file') or ''}:{want.get('key') or ''}:{want.get('field') or ''}")


def place(record):
    """The (code, severity, file, key, field) of a record or an expected entry."""
    return tuple(record.get(name) for name in
                 ("code", "severity", "file", "key", "field"))


# --- Running a fixture in every mode ---------------------------------------------

@dataclass
class Observed:
    """What one fixture did. `entry` is the deterministic part, and the whole of
    the case's share of the results artifact."""
    entry: dict
    records: dict     # the JSON records of `--validate` and `--unresolved`
    stderr: list      # the lines `--output` printed
    data: Optional[dict]
    problems: list = field(default_factory=list)


def observe(spec, work_dir):
    folder = INVALID / spec["dir"]
    entry, problems = {"fixture": spec["dir"]}, []

    def note(mode, run):
        if run.crash is not None:
            problems.append(f"{mode} crashed: {run.crash}")

    records = {}
    for mode in ("--validate", "--unresolved"):
        run = run_sslabdata(["--config", "lab.yaml", mode, "--format", "json"], folder)
        note(mode, run)
        try:
            found = json.loads(run.stdout)
        except ValueError:
            found = []
            problems.append(f"{mode} did not print JSON: {run.output}")
        entry[mode.lstrip("-")] = {
            "exit": run.code,
            "diagnostics": [dict(zip(("code", "severity", "file", "key", "field"),
                                     place(r))) for r in found]}
        records[mode.lstrip("-")] = found

    out = work_dir / f"{spec['dir']}.json"
    run = run_sslabdata(["--config", "lab.yaml", "--format", "json", "--output", out],
                        folder)
    note("--output", run)
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    stderr = run.stderr.splitlines()
    entry["output"] = {
        "exit": run.code,
        "written": data is not None,
        "works": [w["bib_id"] for w in data["works"]] if data else [],
        "stderr": sorted(printed(line) for line in stderr)}

    with working_dir(folder), contextlib.redirect_stderr(io.StringIO()):
        try:
            entry["api"] = type(assemble(LabDataConfig.from_yaml("lab.yaml"),
                                         diagnostics=False)).__name__
        except (ConfigurationError, AssemblyError) as e:
            entry["api"] = type(e).__name__
        except Exception as e:  # noqa: BLE001 - a defect is this case's outcome, not the harness's
            entry["api"] = f"crashed: {type(e).__name__}"
    return Observed(entry, records, stderr, data, problems)


def render(observed):
    """The conformance-results artifact: every case's entry, in a stable order."""
    return json.dumps({"format": 1, "cases": {c: o.entry for c, o in observed.items()}},
                      indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    work_dir = tmp_path_factory.mktemp("invalid")
    seen = {case_id: observe(spec, work_dir) for case_id, spec in DIAGNOSTICS.items()}
    if os.environ.get(RESULTS_ENV):
        write_atomically(os.environ[RESULTS_ENV], render(seen))
    return seen


# --- One test per fixture ----------------------------------------------------------

def exactly(mode, got, want):
    """`got` and `want` hold the same items, each the same number of times: an
    extra, a repeated or a missing diagnostic or work fails."""
    got, want = Counter(got), Counter(want)
    assert got == want, (f"{mode}: unexpected {sorted((got - want).elements(), key=str)}, "
                         f"missing {sorted((want - got).elements(), key=str)}")


def carries(mode, wants, found):
    """Every expected `values` token is in a message reported at that place.
    `found` is [(place, message)]."""
    for want in wants:
        messages = [m for where, m in found if where == place(want)]
        assert any(all(v in m for v in want.get("values", ())) for m in messages), (
            f"{mode}: no {want['code']} message carries {want.get('values')}: {messages}")


@pytest.mark.parametrize("case_id", DIAGNOSTICS)
def test_outcome(observed, case_id):
    """Everything a user can observe of one fixture, exactly, in every mode:
    the exit status, the diagnostics (code, severity, location, values) and the
    works the document keeps. An extra or repeated diagnostic or work fails."""
    spec, seen = DIAGNOSTICS[case_id], observed[case_id]
    entry, fatal = seen.entry, spec.get("fatal")
    assert not seen.problems, seen.problems
    expected = spec["diagnostics"]
    # Outside `--validate` only a fatal diagnostic is still an error.
    elsewhere = [{**w, "severity": w["severity"] if fatal else "warning"} for w in expected]

    # `--validate`.
    assert entry["validate"]["exit"] == spec["exit"], entry["validate"]
    reported = [r for r in seen.records["validate"] if r["code"] not in INCIDENTAL]
    exactly("--validate", map(place, reported), map(place, expected))
    carries("--validate", expected, [(place(r), r["message"]) for r in reported])

    # `--unresolved`: the same diagnostics, and the names it alone lists.
    unresolved = entry["unresolved"]
    assert unresolved["exit"] == (1 if fatal else 0), unresolved
    listed = [r for r in seen.records["unresolved"] if r["code"] not in INCIDENTAL]
    wanted = elsewhere + spec.get("unresolved_only", [])
    exactly("--unresolved", map(place, listed), map(place, wanted))
    carries("--unresolved", wanted, [(place(r), r["message"]) for r in listed])

    # `--output`: a fatal diagnostic writes nothing; anything else writes a
    # document with exactly the works `kept` lists, and each diagnostic once
    # on standard error.
    output = entry["output"]
    assert (output["exit"], output["written"]) == ((1, False) if fatal else (0, True)), output
    exactly("--output works", output["works"], spec.get("kept", ()))
    printed_lines = [line for line in output["stderr"]
                     if line.split(" ")[1] not in INCIDENTAL]
    exactly("--output stderr", printed_lines, map(stream, elsewhere))
    for want in elsewhere:
        lines = [l for l in seen.stderr if printed(l) == stream(want)]
        assert any(all(v in l for v in want.get("values", ())) for l in lines), (
            f"--output: no {want['code']} line carries {want.get('values')}: {lines}")
    for subject in spec.get("emits", ()):
        (kind,) = subject.keys() & SUBJECT
        section, key = SUBJECT[kind]
        found = item(seen.data, section, key, subject[kind])
        for path, value in subject["expect"].items():
            if isinstance(value, dict):
                value = AllOf(Contains(*value.get("contains", ())),
                              Excludes(*value.get("excludes", ())))
            assert_field(found, path, value, f"{kind} {subject[kind]}: ")
    text = json.dumps(seen.data)
    assert not [t for t in spec.get("not_emitted", ()) if t in text]

    # The Python API: the same fatality, as an exception.
    assert entry["api"] == {"load": "ConfigurationError", "assembly": "AssemblyError",
                            None: "LabData"}[fatal], entry["api"]


def test_the_python_api_prints_diagnostics_only_when_asked_to(capsys):
    """`diagnostics` decides printing, never compiling: with False every
    diagnostic, the fatal one included, is printed before the error is raised;
    with True nothing is printed and the error is raised all the same."""
    for diagnostics in (False, True):
        with working_dir(INVALID / "crossref_entry"):
            with pytest.raises(AssemblyError) as raised:
                assemble(LabDataConfig.from_yaml("lab.yaml"), diagnostics=diagnostics)
        printed = "".join(f"Warning: {line}\n" for line in raised.value.diagnostics)
        assert capsys.readouterr().err == ("" if diagnostics else printed)


def test_the_results_artifact_holds_no_host_data(observed, tmp_path):
    """A path, a user name or a temporary directory in the artifact would make
    it differ between hosts. It is rendered here and compared with what a run
    on this host could leak."""
    text = render(observed)
    assert json.loads(text)["cases"].keys() == DIAGNOSTICS.keys()
    for leak in (str(REPO_ROOT), str(tmp_path.parent), os.path.expanduser("~")):
        assert leak not in text


def test_spec_is_well_formed():
    """A typo in the expected outcomes must fail here rather than be ignored."""
    keys = {"dir", "exit", "fatal", "diagnostics", "unresolved_only", "kept", "emits",
            "not_emitted"}
    places = {"code", "severity", "file", "key", "field", "values"}
    dirs = [spec["dir"] for spec in DIAGNOSTICS.values()]
    assert len(dirs) == len(set(dirs)), "a fixture has more than one entry"
    assert set(dirs) == {d.name for d in INVALID.iterdir() if d.is_dir()}
    for case_id, spec in DIAGNOSTICS.items():
        assert (INVALID / spec["dir"] / "lab.yaml").is_file(), case_id
        assert set(spec) <= keys and {"dir", "exit", "diagnostics"} <= set(spec), case_id
        assert spec["exit"] in (0, 1) and spec.get("fatal") in (None, "load", "assembly"), case_id
        assert spec["exit"] == 1 or not spec.get("fatal"), case_id
        for d in [*spec["diagnostics"], *spec.get("unresolved_only", ())]:
            assert {"code", "severity"} <= set(d) and set(d) <= places, (case_id, d)
            assert d["severity"] in ("error", "warning"), (case_id, d)
            assert all(isinstance(d.get(n), (str, type(None))) for n in places - {"values"}), (case_id, d)
        for subject in spec.get("emits", ()):
            assert len(subject.keys() & SUBJECT) == 1 and set(subject) <= {*SUBJECT, "expect"}, case_id


# --- Trees the corpus does not hold ---------------------------------------------------

# Covers config.bib_files.name_absolute
def test_a_fatal_at_load_code_goes_to_standard_error_in_every_mode(tmp_path):
    """The one shape that carries a code inside another one.

    Nothing is assembled, so there is no `--validate` report to gather the
    diagnostic into and it cannot be on standard output the way an
    assembly-time code is. It is on standard error, after the
    `Error loading configuration: ` prefix, in every mode -- which is why
    SPEC.md tells a consumer to search a line for a code rather than anchor
    at its start. The consolidated outcomes above read JSON, which cannot
    show the text streams.
    """
    where = INVALID / DIAGNOSTICS["config.bib_files.name_absolute"]["dir"]
    out = tmp_path / "lab.json"
    for args in (["--validate"],
                 ["--unresolved"],
                 ["--format", "json", "--output", out]):
        run = run_sslabdata(["--config", "lab.yaml", *args], where)
        assert run.crash is None, (args, run.crash)
        assert run.code == 1, (args, run.output)
        assert "CONFIG-BIB-FILE-ABSOLUTE" in run.stderr, (args, run.output)
        assert "CONFIG-BIB-FILE-ABSOLUTE" not in run.stdout, (args, run.output)
        assert run.stderr.startswith("Error loading configuration: "), run.stderr
    assert not out.exists(), "a document was written despite a fatal diagnostic"


OUTSIDE = INVALID / "config_bib_file_outside"

# Names that leave bib_dir by their spelling alone. The backslash and drive
# forms are rejected on every host, so Linux CI exercises the Windows syntax
# rules (not the Windows filesystem).
LEAVING_BY_SPELLING = ["../outside.bib", "../../outside.bib", "sub/../../outside.bib",
                       "..\\outside.bib", "sub\\..\\..\\outside.bib", "C:outside.bib"]
# Names that are spelt inside bib_dir and leave it through a symlink there:
# to a file, to a sibling directory whose name begins with "bib", to nothing,
# and to the directory above.
SYMLINKS = {"link.bib": "../outside.bib", "lookalike.bib": "../bib_evil/x.bib",
            "dangling.bib": "../missing.bib", "up": ".."}
LEAVING_BY_SYMLINK = ["link.bib", "lookalike.bib", "dangling.bib", "up/outside.bib"]


def outside_tree(tmp_path, names):
    """The outside-bib_dir fixture, copied, with `crossref.bib` then `names`
    listed as its bib_files and the symlinks above made in bib_dir."""
    where = tmp_path / "case"
    shutil.copytree(OUTSIDE, where)
    config = yaml.safe_load((where / "lab.yaml").read_text(encoding="utf-8"))
    config["bib_files"] = [{"name": n, "category": "Papers"}
                           for n in ["crossref.bib", *names]]
    (where / "lab.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    for link, target in SYMLINKS.items():
        try:
            (where / "bib" / link).symlink_to(target, target_is_directory=link == "up")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks cannot be created here")
    return where


# Covers config.bib_files.name_outside_bib_dir
@pytest.mark.parametrize("name", LEAVING_BY_SPELLING + LEAVING_BY_SYMLINK)
def test_a_name_outside_bib_dir_is_rejected_before_anything_is_parsed(tmp_path, name):
    """A name that leaves bib_dir is a coded error, in every mode, with nothing written.

    `crossref.bib`, listed first, is fatal if it is read: the error being the
    only one reported shows the whole configuration was checked before any
    file was parsed. To reproduce one case, run `sslabdata --config lab.yaml
    --validate` in tests/corpus/invalid/config_bib_file_outside (`../outside.bib`).
    """
    where = outside_tree(tmp_path, [name])
    out = tmp_path / "written" / "lab.json"
    out.parent.mkdir()
    for args in (["--validate"], ["--format", "json", "--output", out]):
        run = run_sslabdata(["--config", "lab.yaml", *args], where)
        assert run.crash is None, (args, run.crash)
        assert run.code == 1 and run.stdout == "", (args, run.output)
        assert run.stderr.startswith("Error loading configuration: "), run.stderr
        assert "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR lab.yaml:bib_files:name: " in run.stderr
        assert f"'{name}'" in run.stderr
        assert "BIB-CROSSREF-UNSUPPORTED" not in run.output, "a file was parsed"
    assert list(out.parent.iterdir()) == [], "something was written despite the error"


# Covers config.bib_files.name_outside_bib_dir
def test_a_name_is_checked_where_the_reader_opens_it_when_bib_dir_is_empty(tmp_path):
    """With `bib_dir: ""` the reader opens `/<name>`, not `<cwd>/<name>`, so a
    name that is under the working directory as written still leaves it."""
    where = outside_tree(tmp_path, [])
    outside = (where / "outside.bib").resolve()
    name = outside.relative_to(outside.anchor).as_posix()
    (where / "lab.yaml").write_text(yaml.safe_dump(
        {"bib_dir": "", "bib_files": [{"name": name, "category": "Papers"}]}),
        encoding="utf-8")
    run = run_sslabdata(["--config", "../lab.yaml", "--validate"], where / "bib")
    assert run.crash is None and run.code == 1, run.output
    assert f"CONFIG-BIB-FILE-OUTSIDE-BIB-DIR ../lab.yaml:bib_files:name: '{name}'" in run.stderr


# Covers config.bib_files.name_outside_bib_dir
def test_a_nested_name_under_bib_dir_is_accepted_and_emitted_as_written(tmp_path):
    """The document is the artifact: `works[].source.file` is `conference/2026.bib`.
    To reproduce, list that name in the fixture's lab.yaml and run
    `sslabdata --config lab.yaml --output lab.json`."""
    where = outside_tree(tmp_path, [])
    config = yaml.safe_load((where / "lab.yaml").read_text(encoding="utf-8"))
    config["bib_files"] = [{"name": "conference/2026.bib", "category": "Papers"}]
    (where / "lab.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    run, data = export(where, tmp_path)
    assert run.code == 0 and run.crash is None, run.output
    assert [w["source"]["file"] for w in data["works"]] == ["conference/2026.bib"]


def test_an_input_file_the_system_will_not_open_is_coded_not_a_traceback(tmp_path):
    """The one read failure the loaders leave to the CLI: a people file that
    exists but cannot be opened. Coded `CONFIG-UNREADABLE`, naming the file
    in the system's words, exit 1, nothing written.
    """
    where = tmp_path / "case"
    shutil.copytree(INVALID / "record_unknown_key", where)
    people = where / "people.yaml"
    people.chmod(0)
    try:
        people.read_bytes()
    except OSError:
        pass
    else:
        pytest.skip("this account can read a file with no permissions")
    try:
        out = tmp_path / "lab.json"
        run = run_sslabdata(["--config", "lab.yaml", "--output", out], where)
    finally:
        people.chmod(0o644)
    assert run.crash is None and run.code == 1, run.output
    assert run.stderr.startswith("Error loading configuration: CONFIG-UNREADABLE lab.yaml::: "), run.stderr
    assert "people.yaml" in run.stderr
    assert not out.exists()
