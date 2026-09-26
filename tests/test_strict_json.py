"""`--strict`, diagnostics as JSON, and every message carrying a code (#26).

The classes and the JSON shape are the ones SPEC.md states; these tests read
SPEC.md for both, so the document and the code cannot drift apart.
"""

import json
import re

import jsonschema
import pytest
import yaml

from .conformance.support import INVALID, REPO_ROOT, VALID, run_sslabdata

SPEC = (REPO_ROOT / "SPEC.md").read_text(encoding="utf-8")
CODE = r"[A-Z]+(?:-[A-Z]+)+"


def spec_schema():
    """The JSON Schema block SPEC.md gives under *Diagnostics as JSON*."""
    after = SPEC.split("<!-- diagnostics-json-schema -->", 1)[1]
    return json.loads(after.split("```json", 1)[1].split("```", 1)[0])


def spec_registry():
    """The codes SPEC.md registers under *Codes in use*."""
    table = SPEC.split("Codes in use:", 1)[1].split("\n\n", 2)[1]
    codes = set()
    for row in table.splitlines()[2:]:
        codes |= set(re.findall(rf"`({CODE})`", row.split("|")[1]))
    return codes


def spec_classes():
    """{code: class} from the class table under *Diagnostic codes*."""
    classes = {}
    for name in ("Fatal at load", "Fatal", "Validation error", "Warning"):
        [row] = [line for line in SPEC.splitlines()
                 if line.strip().startswith(f"| **{name}** |")]
        for code in re.findall(rf"`({CODE})`", row.split("|")[-2]):
            classes[code] = name.lower()
    return classes


def spec_never_an_error():
    table = SPEC.split("**Under `--strict`**", 1)[1].split("\n\n", 2)[1]
    return {code for row in table.splitlines()[2:]
            for code in re.findall(rf"`({CODE})`", row.split("|")[1])}


REGISTERED = spec_registry()


# --- No uncoded line, in any mode --------------------------------------------

def corpus_folders():
    folders = [(REPO_ROOT, "examples/demo/lab.yaml"), (VALID, "lab.yaml")]
    folders += [(d, "lab.yaml") for d in sorted(INVALID.iterdir()) if d.is_dir()]
    return [pytest.param(cwd, config, id="demo" if cwd == REPO_ROOT else cwd.name)
            for cwd, config in folders]


MODES = [(mode, strict, fmt)
         for mode in ("--validate", "--unresolved", "--output")
         for strict in ((), ("--strict",))
         for fmt in ("yaml", "json")]

LINE = re.compile(rf"^(?:Warning: |Error: |Error loading configuration: )?({CODE}) ")


def uncoded(tmp_path, cwd, config, mode, strict, fmt):
    """What one run does wrong, one message each; empty when it keeps the rule."""
    out = tmp_path / f"{'strict' if strict else 'plain'}.{fmt}"
    args = ["--config", config, "--format", fmt, *strict]
    args += [mode, out] if mode == "--output" else [mode]
    run = run_sslabdata(args, cwd)
    if run.crash is not None:
        return [f"crashed: {run.crash}"]
    problems = []
    for line in run.stderr.splitlines():
        found = LINE.match(line)
        if not (found and found.group(1) in REGISTERED):
            problems.append(f"uncoded line: {line!r}")

    if fmt == "json" and mode != "--output":
        if run.stderr:
            problems.append("standard error is not empty")
        try:
            records = json.loads(run.stdout)
            jsonschema.validate(records, spec_schema())
        except (ValueError, jsonschema.ValidationError) as e:
            return problems + [f"not a diagnostics array: {e}"]
        unregistered = {r["code"] for r in records} - REGISTERED
        if unregistered:
            problems.append(f"unregistered codes: {sorted(unregistered)}")
        errors = [r for r in records if r["severity"] == "error"]
        if run.code != (1 if errors else 0):
            problems.append(f"exit {run.code} with {len(errors)} error record(s)")
    return problems


@pytest.mark.parametrize("cwd, config", corpus_folders())
def test_every_line_on_standard_error_carries_a_code(tmp_path, cwd, config):
    """Every mode is run and every failure reported, so one bad mode cannot
    hide another in the same folder."""
    failures = []
    for mode, strict, fmt in MODES:
        label = " ".join([mode, "--format", fmt, *strict])
        failures += [f"{config} {label}: {problem}"
                     for problem in uncoded(tmp_path, cwd, config, mode, strict, fmt)]
    assert not failures, f"in {cwd}:\n" + "\n".join(failures)


# --- --strict ----------------------------------------------------------------

def strict_run(folder, *mode):
    return run_sslabdata(["--config", "lab.yaml", "--strict", *mode], INVALID / folder)


@pytest.mark.parametrize("folder, code", [
    ("config_bib_dir_missing", "CONFIG-KEY-MISSING"),     # fatal at load
    ("people_missing_name", "PEOPLE-FIELD-MISSING"),      # fatal
    ("undefined_project", "RESOLVE-PROJECT-UNKNOWN"),     # validation error
    ("year_not_number", "BIB-YEAR-INVALID"),              # warning
    ("ambiguous_alias", "RESOLVE-AMBIGUOUS-NAME"),        # warning, lab members
])
def test_strict_fails_every_mode_on_each_error_class(tmp_path, folder, code):
    out = tmp_path / "lab.json"
    for mode in (["--validate"], ["--unresolved"], ["--format", "json", "--output", out]):
        run = strict_run(folder, *mode)
        assert run.crash is None and run.code == 1, (mode, run.output)
        assert code in run.output, (mode, run.output)
    assert not out.exists()


def test_the_demo_passes_every_mode_under_strict(tmp_path):
    for mode in (["--validate"], ["--unresolved"], ["--output", tmp_path / "d.yaml"]):
        run = run_sslabdata(["--config", "examples/demo/lab.yaml", "--strict", *mode],
                          REPO_ROOT)
        assert run.code == 0 and run.crash is None, (mode, run.output)


def write_lab(tmp_path, bib, people=None, collaborators=None):
    (tmp_path / "w.bib").write_text(bib, encoding="utf-8")
    config = {"lab": {"name": "L"}, "bib_dir": ".",
              "bib_files": [{"name": "w.bib", "category": "C"}]}
    for key, records in (("people_file", people),
                         ("collaborators_file", collaborators)):
        if records is not None:
            (tmp_path / f"{key}.yaml").write_text(yaml.safe_dump(records),
                                                  encoding="utf-8")
            config[key] = f"{key}.yaml"
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def strict_codes(tmp_path):
    """The codes of a --validate --strict run as JSON, and each mode's exit."""
    run = run_sslabdata(["--config", "lab.yaml", "--validate", "--strict",
                       "--format", "json"], tmp_path)
    records = json.loads(run.stdout)
    exits = {run.code}
    for mode in (["--validate"], ["--unresolved"], ["--output", tmp_path / "o.yaml"]):
        exits.add(run_sslabdata(["--config", "lab.yaml", "--strict", *mode],
                              tmp_path).code)
    return records, exits


MEMBERS = [{"id": "aadams", "name": "Alice Adams", "role": "pi"}]
NOT_MATCHING = {"RESOLVE-SUGGESTION", "RESOLVE-AMBIGUOUS-NAME",
                "ID-GROUPING-AMBIGUOUS-DECLARED", "ID-GROUPING-INITIALS-AMBIGUOUS"}


def test_strict_passes_when_only_outside_co_authors_are_unresolved(tmp_path):
    """Outside co-authors close to no member's name, and a redefined @string
    macro, leave --strict at exit 0 in every mode."""
    write_lab(tmp_path,
              '@string{v = "Old"}\n@string{v = "Venue"}\n'
              "@article{a, title = {T}, journal = v, year = 2024, author = "
              "{Adams, Alice and Ross, Rachel and Zhou, Zelda}}\n"
              "@article{b, title = {T}, journal = {J}, year = 2023, author = "
              "{ROSS, RACHEL and Adams, Alice}}\n",
              people=MEMBERS)
    records, exits = strict_codes(tmp_path)
    codes = {r["code"] for r in records}
    assert not codes & NOT_MATCHING, records
    assert codes == {"BIB-STRING-REDEFINED", "ID-GROUPING-SPANS-SPELLINGS"}
    assert {r["severity"] for r in records} == {"warning"}
    assert exits == {0}
    assert (tmp_path / "o.yaml").exists()


def test_a_suggestion_alone_leaves_strict_at_exit_0(tmp_path):
    """Decision 10: an author who matched no lab member is never an error
    under --strict, even when the name is close to a member's."""
    write_lab(tmp_path,
              "@article{a, title = {T}, journal = {J}, year = 2024, author = "
              "{Davis, Dave M.}}\n",
              people=[{"id": "ddavis", "name": "Dave Davis", "role": "student"}])
    records, exits = strict_codes(tmp_path)
    assert [(r["code"], r["severity"]) for r in records] == [
        ("RESOLVE-SUGGESTION", "warning")]
    assert exits == {0}


def test_an_initials_only_grouping_alone_leaves_strict_at_exit_0(tmp_path):
    write_lab(tmp_path,
              "@article{a, title = {T}, journal = {J}, year = 2024, author = "
              "{Quinn, Q. and Quinn, Quentin}}\n", people=MEMBERS)
    records, exits = strict_codes(tmp_path)
    assert [r["code"] for r in records] == ["ID-GROUPING-INITIALS-AMBIGUOUS"]
    assert exits == {0}


# The boundary of ID-GROUPING-AMBIGUOUS-DECLARED (#26 decisions 6 and 10).

def test_a_name_fitting_two_collaborator_entries_is_a_grouping_warning(tmp_path):
    write_lab(tmp_path,
              "@article{a, title = {T}, journal = {J}, year = 2024, author = "
              "{Patel, P.}}\n", people=MEMBERS,
              collaborators=[{"name": "Priya Patel", "aliases": ["P. Patel"]},
                             {"name": "Pradeep Patel", "aliases": ["P. Patel"]}])
    records, exits = strict_codes(tmp_path)
    assert [(r["code"], r["severity"]) for r in records] == [
        ("ID-GROUPING-AMBIGUOUS-DECLARED", "warning")]
    assert exits == {0}


def boundary_runs(tmp_path):
    """Every record, and every exit, of one boundary case.

    ``records[(mode, strict)]`` is the ordered ``[(code, severity)]`` of the
    JSON array; ``text[strict]`` the codes `--validate` lists as text, under
    ``Warnings`` and under ``Bibliography errors``; ``exits`` the exit code of
    every mode with ``--strict``, JSON and text.
    """
    records, text, exits = {}, {}, set()
    for strict in ((), ("--strict",)):
        for mode in ("--validate", "--unresolved"):
            run = run_sslabdata(["--config", "lab.yaml", mode, "--format", "json",
                               *strict], tmp_path)
            records[(mode, bool(strict))] = [
                (r["code"], r["severity"]) for r in json.loads(run.stdout)]
            if strict:
                exits.add(run.code)
        run = run_sslabdata(["--config", "lab.yaml", "--validate", *strict], tmp_path)
        sections = {}
        for heading in ("Warnings", "Bibliography errors"):
            part = run.stdout.split(f"\n{heading} (", 1)
            listed = part[1].split("\n\n", 1)[0].splitlines()[1:] if len(part) > 1 else []
            sections[heading] = [line.split()[1] for line in listed]
        text[bool(strict)] = sections
        if strict:
            exits.add(run.code)
    for mode in (["--unresolved"], ["--output", tmp_path / "o.yaml"]):
        exits.add(run_sslabdata(["--config", "lab.yaml", "--strict", *mode],
                              tmp_path).code)
    return records, text, exits


def test_a_name_fitting_an_entry_and_one_member_is_two_warnings(tmp_path):
    """`Patel, P.` fits the entry that declares `P. Patel` and member Paul
    Patel, who declares no alias: one entry and one member.

    The resolver reports its initials fitting the member as
    RESOLVE-SUGGESTION, and grouping reports the entry and the member as
    ID-GROUPING-AMBIGUOUS-DECLARED. Both are warnings under decision 10, so
    --strict passes; RESOLVE-AMBIGUOUS-NAME is not reported.
    """
    write_lab(tmp_path,
              "@article{a, title = {T}, journal = {J}, year = 2024, author = "
              "{Patel, P.}}\n",
              people=[{"id": "ppatel", "name": "Paul Patel", "role": "student"}],
              collaborators=[{"name": "Priya Patel", "aliases": ["P. Patel"]}])
    records, text, exits = boundary_runs(tmp_path)
    both = [("RESOLVE-SUGGESTION", "warning"),
            ("ID-GROUPING-AMBIGUOUS-DECLARED", "warning")]
    for strict in (False, True):
        assert records[("--validate", strict)] == both
        assert records[("--unresolved", strict)] == both + [
            ("RESOLVE-UNRESOLVED-NAME", "warning")]
        assert text[strict] == {
            "Warnings": ["RESOLVE-SUGGESTION", "ID-GROUPING-AMBIGUOUS-DECLARED"],
            "Bibliography errors": []}
    assert exits == {0}


def test_a_name_fitting_an_entry_and_two_members_fails_strict(tmp_path):
    """One entry and two members: the members' ambiguity is
    RESOLVE-AMBIGUOUS-NAME (decision 6), an error under --strict, and the
    grouping warning names the entry as well. No RESOLVE-SUGGESTION: a name
    the resolver finds ambiguous is not also offered as a suggestion."""
    write_lab(tmp_path,
              "@article{a, title = {T}, journal = {J}, year = 2024, author = "
              "{Kim, A.}}\n",
              people=[{"id": "akim", "name": "Alex Kim", "role": "student"},
                      {"id": "alankim", "name": "Alan Kim", "role": "student"}],
              collaborators=[{"name": "Amy Kim"}])
    records, text, exits = boundary_runs(tmp_path)
    for strict, level in ((False, "warning"), (True, "error")):
        both = [("RESOLVE-AMBIGUOUS-NAME", level),
                ("ID-GROUPING-AMBIGUOUS-DECLARED", "warning")]
        assert records[("--validate", strict)] == both
        assert records[("--unresolved", strict)] == both + [
            ("RESOLVE-UNRESOLVED-NAME", "warning")]
    assert text[False] == {
        "Warnings": ["RESOLVE-AMBIGUOUS-NAME", "ID-GROUPING-AMBIGUOUS-DECLARED"],
        "Bibliography errors": []}
    assert text[True] == {"Warnings": ["ID-GROUPING-AMBIGUOUS-DECLARED"],
                          "Bibliography errors": ["RESOLVE-AMBIGUOUS-NAME"]}
    assert exits == {1}


def test_a_failing_strict_export_writes_nothing_and_keeps_an_existing_file(tmp_path):
    absent = tmp_path / "absent.json"
    run = strict_run("year_not_number", "--format", "json", "--output", absent)
    assert run.code == 1 and not absent.exists()

    existing = tmp_path / "existing.json"
    existing.write_bytes(b'{"kept": "as it was"}\n')
    before = existing.read_bytes()
    run = strict_run("year_not_number", "--format", "json", "--output", existing)
    assert run.code == 1
    assert existing.read_bytes() == before


def test_strict_validate_lists_promoted_codes_as_errors():
    run = strict_run("year_not_number", "--validate")
    errors = run.stdout.split("\nBibliography errors (", 1)[1]
    assert "  - BIB-YEAR-INVALID ./badyear.bib:bad-year:year: " in errors
    assert run.code == 1


# --- JSON ----------------------------------------------------------------------

def json_run(cwd, *mode, config="lab.yaml"):
    run = run_sslabdata(["--config", config, "--format", "json", *mode], cwd)
    assert run.crash is None and run.stderr == "", run.output
    records = json.loads(run.stdout)
    jsonschema.validate(records, spec_schema())
    return run, records


def test_unresolved_names_are_records_only_under_unresolved_json():
    run, records = json_run(REPO_ROOT, "--unresolved",
                            config="examples/demo/lab.yaml")
    names = [r for r in records if r["code"] == "RESOLVE-UNRESOLVED-NAME"]
    text = run_sslabdata(["--config", "examples/demo/lab.yaml", "--unresolved"],
                       REPO_ROOT)
    listed = [line.strip() for line in text.stdout.splitlines()[1:]]
    assert [r["message"] for r in names] == listed
    assert {r["severity"] for r in names} == {"warning"}
    lin = next(r for r in names if r["message"] == "Lin Lee")
    assert (lin["file"], lin["key"], lin["field"]) == (
        "examples/demo/bib/conference.bib", "nolan2020stairs", "author")

    _, validate = json_run(REPO_ROOT, "--validate", config="examples/demo/lab.yaml")
    assert validate == []


def test_a_configuration_that_does_not_load_is_still_one_array(tmp_path):
    run, records = json_run(tmp_path, "--validate", config="missing.yaml")
    assert run.code == 1
    [record] = records
    assert {k: v for k, v in record.items() if k != "message"} == {
        "code": "CONFIG-NOT-FOUND", "severity": "error",
        "file": "missing.yaml", "key": None, "field": None}

    (tmp_path / "bad.yaml").write_text("lab: {name: L\n", encoding="utf-8")
    run, [record] = json_run(tmp_path, "--unresolved", config="bad.yaml")
    assert run.code == 1
    assert (record["code"], record["file"]) == ("CONFIG-UNREADABLE", "bad.yaml")


# --- The five codes that were uncoded -------------------------------------------

def test_a_missing_or_unreadable_configuration_is_coded_as_text(tmp_path):
    run = run_sslabdata(["--config", "missing.yaml", "--validate"], tmp_path)
    assert run.code == 1
    [line] = run.stderr.splitlines()
    assert line.startswith("Error: CONFIG-NOT-FOUND missing.yaml::: ")
    (tmp_path / "bad.yaml").write_text("lab: {name: L\n", encoding="utf-8")
    run = run_sslabdata(["--config", "bad.yaml", "--validate"], tmp_path)
    assert run.code == 1
    [line] = run.stderr.splitlines()
    assert line.startswith("Error loading configuration: CONFIG-UNREADABLE bad.yaml::: ")


def test_a_parser_library_message_is_coded_and_located_at_its_entry(tmp_path):
    write_lab(tmp_path, "@article{e, title = {A}, title = {B}, journal = {J},"
                        " year = 2024}\n")
    run = run_sslabdata(["--config", "lab.yaml", "--output", tmp_path / "o.yaml"],
                      tmp_path)
    [line] = run.stderr.splitlines()
    assert line.startswith("Warning: BIB-PARSER-MESSAGE ./w.bib:e:: ")
    assert line.split(":: ", 1)[1].strip(), "the library's message is kept after the code"
