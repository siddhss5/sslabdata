"""The code classes, and the codes and paths only a fault can reach."""

import re

import pytest

from sslabdata.diagnostics import CLASSES, NEVER_AN_ERROR, diagnostic

from ..conformance.support import REPO_ROOT, run_sslabdata
from ..test_strict_json import (
    CODE, json_run, spec_classes, spec_never_an_error, spec_registry, write_lab,
)


def test_the_code_classes_are_the_ones_spec_states():
    """SPEC.md is the registry: a code added, reclassified or exempted from
    `--strict` in one place only would change every user's exit status, and
    no fixture exercises the codes that a fault alone reaches."""
    assert spec_registry() == set(CLASSES)
    assert spec_classes() == CLASSES
    assert spec_never_an_error() == NEVER_AN_ERROR
    assert NEVER_AN_ERROR <= set(CLASSES)


def test_every_code_the_source_names_is_classified():
    """A code the source emits but `CLASSES` lacks is rejected when the
    diagnostic is built, on the run that first reports it, which only a
    fixture that reaches that code would otherwise reveal."""
    named = set()
    for path in (REPO_ROOT / "sslabdata").rglob("*.py"):
        named |= set(re.findall(rf'"({CODE})"', path.read_text(encoding="utf-8")))
    assert named and named - set(CLASSES) == set()
    with pytest.raises(ValueError, match="NO-SUCH-CODE"):
        diagnostic("NO-SUCH-CODE", "w.bib", "e", "title", "never reported")


def test_a_field_whose_latex_cannot_be_read_is_located(tmp_path, monkeypatch):
    """`LATEX-CONVERSION-FAILED` is located at its field and fails `--strict`.
    The converter fails only on a fault, so no corpus input can reach it;
    the failure is injected."""
    import sslabdata.parsers.bibtex as bibtex

    def unreadable(value):
        if "Broken" in value:
            raise ValueError("cannot read")
        return value
    monkeypatch.setattr(bibtex, "latex_to_text", unreadable)
    write_lab(tmp_path, "@article{e, title = {Broken {Title}}, journal = {J},"
                        " year = 2024}\n")
    run, [record] = json_run(tmp_path, "--validate", "--strict")
    assert (record["code"], record["file"], record["key"], record["field"]) == (
        "LATEX-CONVERSION-FAILED", "./w.bib", "e", "title")
    assert record["severity"] == "error" and run.code == 1


def test_an_entry_that_cannot_be_written_back_is_located(tmp_path, monkeypatch):
    """`BIB-WRITE-BACK-FAILED` is located at its entry and stays a warning.
    Serializing a parsed entry fails only on a fault, so it is injected."""
    def refuse(self, *args, **kwargs):
        raise ValueError("cannot write")
    monkeypatch.setattr("sslabdata.parsers.bibtex.Entry.to_string", refuse)
    write_lab(tmp_path, "@article{e, title = {T}, journal = {J}, year = 2024}\n")
    run, [record] = json_run(tmp_path, "--validate")
    assert (record["code"], record["file"], record["key"], record["field"]) == (
        "BIB-WRITE-BACK-FAILED", "./w.bib", "e", "bibtex")
    assert run.code == 0


# Covers cli.validate.agrees_with_output
@pytest.mark.parametrize("fmt", ["yaml", "json"])
def test_validate_fails_on_what_serializing_refuses(tmp_path, monkeypatch, fmt):
    """`--validate` fails on what serializing the document refuses, not only
    on what loading caught. Loading refuses a NaN under `lab` before
    serializing is reached, so one is put into the assembled document:
    `--validate` in `fmt` reports it coded, located at the configuration,
    and exits 1; `--output` in `fmt` reports the same and writes nothing."""
    import sslabdata.cli as cli

    def assemble_with_nan(config, assemble_result=cli.assemble_result):
        result = assemble_result(config)
        result.data.lab["ratio"] = float("nan")
        return result
    monkeypatch.setattr(cli, "assemble_result", assemble_with_nan)
    write_lab(tmp_path, "@article{e, title = {T}, journal = {J}, year = 2024}\n")
    where = "CONFIG-VALUE-NOT-JSON lab.yaml:lab:ratio: "

    if fmt == "json":
        run, [record] = json_run(tmp_path, "--validate")
        assert (record["code"], record["severity"], record["file"], record["key"],
                record["field"]) == ("CONFIG-VALUE-NOT-JSON", "error", "lab.yaml",
                                     "lab", "ratio")
    else:
        run = run_sslabdata(["--config", "lab.yaml", "--validate"], tmp_path)
        assert run.crash is None and where in run.stdout, run.output
    assert run.code == 1

    run = run_sslabdata(["--config", "lab.yaml", "--format", fmt, "--output",
                         "out"], tmp_path)
    assert run.crash is None and run.code == 1, run.output
    assert run.stderr.startswith(where), run.stderr
    assert not (tmp_path / "out").exists()
