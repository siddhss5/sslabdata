"""Config keys and CLI flags, run on the valid corpus and variants of its lab.yaml.

Wrong-typed and otherwise invalid config lives in tests/corpus/invalid/ and is
checked by test_invalid_corpus.py.
"""

import json
import os
from datetime import date, datetime, timezone

import jsonschema
import pytest
import yaml

from .support import (
    SCHEMA_PATH, VALID, case, export, item, run_sslabdata, work, write_variant,
)


# --- Config keys: present ----------------------------------------------------

# Covers config.lab.present, config.bib_dir.present, config.bib_files.present,
# config.site
def test_config_present(valid_output):
    assert valid_output["lab"]["name"] == "Corpus Lab"
    categories = {w["category"] for w in valid_output["works"]}
    assert categories == {"Strings", "Names", "LaTeX", "Structure", "Encoding", "Links",
                          "Projects"}
    # site is for downstream renderers; sslabdata accepts it and does not
    # copy it into the output.
    assert "site" not in valid_output


# Covers config.pdf_base_url.present
def test_config_pdf_base_url_present(valid_output):
    assert "present.pdf" in work(valid_output, "present")["links"]["pdf"][0]["url"]


# Covers config.people_file.present
def test_config_people_file_present(valid_output):
    assert len(valid_output["people"]) == 18
    assert work(valid_output, "name-last-first")["authors"][0]["person_id"] == "aadams"


# Covers config.projects_file.present
def test_config_projects_file_present(valid_output):
    assert [p["id"] for p in valid_output["projects"]] == ["homebot", "sharedarm"]


QUINN_WORKS = ["id-external-2023", "id-external-2019", "id-grouping"]


def person_ids(data):
    return [(w["bib_id"], a["position"], a["person_id"])
            for w in data["works"] for a in w["authors"] + w["editors"]]


# Covers config.collaborators_file.present, identity.collaborator_alias
def test_config_collaborators_file_present(tmp_path, valid_output):
    """A declared alias joins `Quinn, Quentin` and `Quinn, Q.` into one
    grouping, and changes no `person_id` anywhere."""
    run, data = export(VALID, tmp_path,
                       write_variant(tmp_path, collaborators_file="collaborators.yaml"))
    assert run.code == 0 and run.crash is None, run.output
    quinn = [c for c in data["collaborators"] if c["family"] == "Quinn"]
    assert len(quinn) == 1, quinn
    assert quinn[0]["grouped_by"] == "declared"
    assert quinn[0]["work_ids"] == QUINN_WORKS
    assert quinn[0]["name_variants"] == ["Q. Quinn", "Quentin Quinn"]
    # Only this key moved: without the file, the two spellings are two keys.
    assert len([c for c in valid_output["collaborators"]
                if c["family"] == "Quinn"]) == 2
    assert {c["grouped_by"] for c in valid_output["collaborators"]} == {"normalized_name"}
    assert person_ids(data) == person_ids(valid_output)


# Covers identity.collaborator_alias_is_member
def test_collaborator_alias_that_is_a_member_is_reported(tmp_path, valid_output):
    """`A. Adams` is also a member's alias: reported as a warning in both
    reporting modes, neither exit code moves, and the member keeps it."""
    variant = write_variant(tmp_path, collaborators_file="collaborators.yaml")
    validate = run_sslabdata(["--config", variant, "--validate"], VALID)
    unresolved = run_sslabdata(["--config", variant, "--unresolved"], VALID)
    # Under --validate the report is on stdout, beneath `Warnings`; in the
    # other modes a warning is on stderr with the `Warning: ` prefix.
    for run, stream, prefix in ((validate, validate.stdout, "  - "),
                                (unresolved, unresolved.stderr, "Warning: ")):
        assert run.code == 0 and run.crash is None, run.output
        [line] = [line for line in stream.splitlines()
                  if "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER" in line]
        assert line.startswith(prefix + "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER"), line
        assert "collaborators.yaml:Amy Adams:aliases" in line
        assert "A. Adams" in line and "aadams" in line
    report = validate.stdout
    assert report.index("RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER") > report.index("Warnings (")
    assert "Bibliography errors" not in report
    _, data = export(VALID, tmp_path,
                     write_variant(tmp_path, collaborators_file="collaborators.yaml"))
    assert [c for c in data["collaborators"] if c["name"] == "Amy Adams"] == []
    assert person_ids(data) == person_ids(valid_output)


# --- Config keys: missing (optional keys) ------------------------------------

# Covers config.lab.missing
def test_config_lab_missing(tmp_path):
    """The header is always emitted, so `lab: {}` is what no header looks like.

    A consumer can tell "no header" from "an empty header": the key is there
    and the header is empty.
    """
    run, data = export(VALID, tmp_path, write_variant(tmp_path, lab=None))
    assert run.code == 0 and run.crash is None, run.output
    assert data["lab"] == {}
    # And an explicitly empty header is the same document, not a different one.
    run, empty = export(VALID, tmp_path, write_variant(tmp_path, lab={}))
    assert run.code == 0 and run.crash is None, run.output
    assert empty["lab"] == {}


# Covers config.lab.date
def test_config_lab_dates_are_emitted_as_iso_text(tmp_path):
    """A date or a timestamp under `lab`, at any depth, is its ISO 8601 text:
    `--validate --strict` in each format passes, both exports succeed, parse
    to the same document and validate against the schema. Read back as YAML,
    a date the export left unquoted would be a date again, and the two
    documents would differ.

    To reproduce, add `founded: 2010-01-01` under `lab` in
    tests/corpus/valid/lab.yaml and export it with `--format json`.
    """
    lab = {"name": "Corpus Lab", "founded": date(2010, 1, 1),
           "links": {"cv": datetime(2024, 5, 1, 9, 30, tzinfo=timezone.utc)}}
    variant = write_variant(tmp_path, lab=lab, bib_files=[
        {"name": "encoding.bib", "category": "E"}])
    documents = []
    for fmt in ("yaml", "json"):
        run = run_sslabdata(["--config", variant, "--validate", "--strict",
                             "--format", fmt], VALID)
        assert run.code == 0 and run.crash is None, run.output
        run, data = export(VALID, tmp_path, variant, fmt)
        assert run.code == 0 and run.crash is None, run.output
        documents.append(data)
    assert documents[0] == documents[1]
    assert documents[0]["lab"] == {"name": "Corpus Lab", "founded": "2010-01-01",
                                   "links": {"cv": "2024-05-01T09:30:00+00:00"}}
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        jsonschema.validate(documents[1], json.load(f),
                            cls=jsonschema.Draft202012Validator)


# Covers config.pdf_base_url.missing
def test_config_pdf_base_url_missing(tmp_path):
    """No base configured is a third answer, distinct from `missing`: a work
    without its own `pdf` field has no PDF link at all rather than one
    labelled as absent."""
    run, data = export(VALID, tmp_path, write_variant(tmp_path, pdf_base_url=None))
    assert run.code == 0 and run.crash is None, run.output
    # Only a PDF the entry names itself (`origin: input`) is left.
    assert [w["bib_id"] for w in data["works"]
            if any(link["origin"] != "input" for link in w["links"].get("pdf", []))] == []
    # With a base, there is one, so the emptiness above is the config's doing.
    assert "pdf" in work(valid_pdf_base(tmp_path), "present")["links"]


# Covers config.people_file.missing
def test_config_people_file_missing(tmp_path):
    run, data = export(VALID, tmp_path, write_variant(tmp_path, people_file=None))
    assert run.code == 0 and run.crash is None, run.output
    assert data["people"] == []
    assert {a["person_id"] for w in data["works"] for a in w["authors"]} == {None}
    # Every authorship still references exactly one contributor, so nothing
    # falls out of the graph when there is nobody to resolve against.
    assert [a for w in data["works"] for a in w["authors"]
            if not a["collaborator_key"]] == []
    assert len(item(data, "collaborators", "name", "Alice Adams")["work_ids"]) > 1


# Covers config.people_file.missing
def test_unresolved_without_people_file(tmp_path):
    """--unresolved says author resolution is not configured, naming people_file,
    and --validate lists no author as unresolved when there was nobody to
    resolve against."""
    variant = write_variant(tmp_path, people_file=None)
    run = run_sslabdata(["--config", variant, "--unresolved"], VALID)
    assert "people_file" in run.output
    assert "All authors resolved" not in run.stdout, run.stdout
    validate = run_sslabdata(["--config", variant, "--validate"], VALID)
    assert "Quentin Quinn" not in validate.stdout, validate.stdout


# Covers config.projects_file.missing
def test_config_projects_file_missing(tmp_path):
    run, data = export(VALID, tmp_path, write_variant(tmp_path, projects_file=None))
    assert run.code == 0 and run.crash is None, run.output
    assert data["projects"] == []
    # Project tags on works are kept.
    assert work(data, "proj-multiple")["project_ids"] == ["homebot", "sharedarm"]


# --- Links that depend on config --------------------------------------------

def valid_pdf_base(tmp_path):
    """The valid corpus exported with its ordinary local `pdf_base_url`."""
    run, data = export(VALID, tmp_path / "with-base")
    assert run.code == 0 and run.crash is None, run.output
    return data


# Covers links.pdf.remote_guess
def test_remote_pdf_base_url_guess_is_unchecked(tmp_path):
    """A remote pdf_base_url gives every work without its own `pdf` field a
    guessed link, `derived` and `unchecked`: a build never fetches, so nothing
    says whether the file is there. It is not checked against local files
    either, so `present`, whose PDF the corpus holds, is `unchecked` too. An
    entry's own `pdf` still replaces the guess, and nothing is reported.
    """
    variant = write_variant(tmp_path, pdf_base_url="https://example.org/pdfs/",
                            bib_files=[{"name": "links.bib", "category": "Links"}])
    run, data = export(VALID, tmp_path, variant)
    assert run.code == 0 and run.crash is None, run.output
    for key in ("present", "missing"):
        assert work(data, key)["links"]["pdf"] == [
            {"url": f"https://example.org/pdfs/{key}.pdf", "label": None,
             "origin": "derived", "verification": {"status": "unchecked"}}]
    assert work(data, "link-pdf-field")["links"]["pdf"] == [
        {"url": "https://example.org/papers/link-pdf-field.pdf", "label": None,
         "origin": "input", "verification": {"status": "unchecked"}}]
    report = run_sslabdata(["--config", variant, "--validate", "--strict",
                            "--format", "json"], VALID)
    assert report.code == 0 and report.crash is None, report.output
    assert json.loads(report.stdout) == []


# --- CLI flags and output formats --------------------------------------------

# Covers cli.config
def test_cli_config_required():
    run = run_sslabdata(["--validate"], VALID)
    assert run.crash is None
    assert run.code == 2
    assert "--config" in run.stderr


# Covers cli.config_not_found, diag.config_not_found
def test_cli_config_not_found():
    run = run_sslabdata(["--config", "no-such-lab.yaml", "--validate"], VALID)
    assert run.crash is None
    assert run.code == 1
    assert "no-such-lab.yaml" in run.stderr


# Covers cli.mode.required, diag.mode_required
def test_cli_mode_required():
    run = run_sslabdata(["--config", "lab.yaml"], VALID)
    assert run.crash is None
    assert run.code == 2
    for flag in ("--output", "--validate", "--unresolved"):
        assert flag in run.stderr


# Covers cli.help
def test_cli_help():
    run = run_sslabdata(["--help"], VALID)
    assert run.code == 0
    for flag in ("--config", "--format", "--output", "--validate", "--unresolved"):
        assert flag in run.stdout


FORMATS = [
    case("cli.format.yaml", ["--format", "yaml"], yaml.safe_load),
    case("cli.format.yaml", [], yaml.safe_load),  # the default
    case("cli.format.json", ["--format", "json"], json.loads),
]


@pytest.mark.parametrize("case_id, args, parse", FORMATS)
def test_cli_format(tmp_path, valid_output, case_id, args, parse):
    out = tmp_path / "lab.out"
    run = run_sslabdata(["--config", "lab.yaml", *args, "--output", out], VALID)
    assert run.code == 0 and run.crash is None, run.output
    assert parse(out.read_text(encoding="utf-8")) == valid_output


# Covers cli.format.invalid, diag.format_invalid
def test_cli_format_invalid(tmp_path):
    run = run_sslabdata(["--config", "lab.yaml", "--format", "xml", "--output",
                       tmp_path / "lab.xml"], VALID)
    assert run.code == 2
    assert "xml" in run.stderr
    assert not (tmp_path / "lab.xml").exists()


# Covers cli.output, diag.wrote
def test_cli_output_creates_parent_dirs(tmp_path, valid_output):
    out = tmp_path / "out" / "nested" / "lab.yml"
    run = run_sslabdata(["--config", "lab.yaml", "--output", out], VALID)
    assert run.code == 0 and run.crash is None, run.output
    assert out.exists()
    assert str(out) in run.stdout
    assert str(len(valid_output["works"])) in run.stdout


# Covers cli.validate, diag.unresolved_authors
def test_cli_validate(valid_validate, valid_output):
    assert valid_validate.crash is None
    assert valid_validate.code == 0, valid_validate.output
    # Counts, and unresolved external authors, which are not errors.
    for section in ("works", "people", "projects"):
        assert str(len(valid_output[section])) in valid_validate.stdout
    assert "Quentin Quinn" in valid_validate.stdout


# Covers diag.validation_passed
def test_cli_validate_closes_with_a_summary_line(valid_validate, valid_output):
    """A passing --validate ends with a line of its own, after the counts.

    Checked by shape rather than by wording: the closing line is not indented
    like a listed name, and is not one of the count lines.
    """
    assert valid_validate.code == 0, valid_validate.output
    lines = [line for line in valid_validate.stdout.splitlines() if line.strip()]
    counts = {str(len(valid_output[s])) for s in ("works", "people", "projects")}
    closing = lines[-1]
    assert not closing.startswith(" "), closing
    assert not any(count in closing for count in counts), closing
    assert closing not in lines[:-1], closing


# Covers cli.unresolved, diag.unresolved_authors
def test_cli_unresolved(valid_unresolved, valid_output):
    assert valid_unresolved.crash is None
    assert valid_unresolved.code == 0
    listed = {c["name"] for c in valid_output["collaborators"]}
    for name in listed:
        assert name in valid_unresolved.stdout
    assert "A. Adams" not in valid_unresolved.stdout


# Covers cli.unresolved_none, diag.all_resolved
def test_cli_unresolved_none(tmp_path):
    """Every author resolves: sslabdata says so in one line and lists nobody."""
    variant = write_variant(tmp_path, bib_files=[{"name": "encoding.bib", "category": "E"}])
    run = run_sslabdata(["--config", variant, "--unresolved"], VALID)
    assert run.code == 0 and run.crash is None, run.output
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, run.stdout
    assert not lines[0].startswith(" "), run.stdout
    for name in ("Adams", "Côté"):
        assert name not in run.stdout



def snapshot(root):
    """Every path under `root` with its bytes, or None for a directory."""
    return {p.relative_to(root): None if p.is_dir() else p.read_bytes()
            for p in sorted(root.rglob("*"))}


OLD = b"the document from the last good run\n"

WRITE_FAILURES = [
    case("cli.output.write_failed", "directory"),
    case("cli.output.write_failed", "parent_is_a_file"),
    case("cli.output.write_failed", "permission_denied"),
]


# Covers cli.output.write_failed
@pytest.mark.parametrize("case_id, failure", WRITE_FAILURES)
def test_a_failed_write_is_coded_and_changes_nothing(tmp_path, case_id, failure):
    """`--output` naming a directory, a path under a file, or a file in a
    directory that cannot be written to: `OUTPUT-WRITE-FAILED` located at the
    destination on standard error, exit 1, no traceback and no `Wrote` line.
    The tree is compared byte for byte before and after, so the old document
    is kept and no temporary file is left behind.

    To reproduce, run `sslabdata --config lab.yaml --output .` in
    tests/corpus/valid.
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "lab.yml").write_bytes(OLD)
    if failure == "directory":
        destination = tree / "lab.yml.d"
        destination.mkdir()
    elif failure == "parent_is_a_file":
        destination = tree / "lab.yml" / "lab.yml"
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root can write to a read-only directory")
        destination = tree / "lab.yml"
        tree.chmod(0o555)
        if os.access(tree, os.W_OK):
            tree.chmod(0o755)
            pytest.skip("permission bits do not stop this account writing")
    before = snapshot(tree)
    try:
        run = run_sslabdata(["--config", "lab.yaml", "--output", destination], VALID)
    finally:
        tree.chmod(0o755)
    assert run.crash is None and run.code == 1, run.output
    coded = [line for line in run.stderr.splitlines() if "OUTPUT-WRITE-FAILED" in line]
    assert len(coded) == 1, run.stderr
    assert coded[0].startswith(f"OUTPUT-WRITE-FAILED {destination}::: "), coded
    assert "Wrote" not in run.stdout, run.stdout
    assert snapshot(tree) == before
