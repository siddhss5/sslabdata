"""`sslabdata init`, run through `cli.main()` as a new lab would run it.

The artifact is the tree `init` writes and the document compiled from it,
both under pytest's temporary directory. To keep and inspect them:

    pytest --no-cov --basetemp=/tmp/init-run tests/conformance/test_init.py
    ls -R /tmp/init-run/test_init_writes_a_lab_that_pa0/new-lab

`new-lab/lab.json` is the document; it validates against schema v7, and each
YAML file beside it against its input schema.
"""

import json
import os
import shlex
import stat

import jsonschema
import pytest

from .support import SCHEMA_PATH, run_sslabdata
from .test_input_schemas import errors

WRITTEN = {"lab.yaml": "lab", "people.yaml": "people",
           "projects.yaml": "projects", "collaborators.yaml": "collaborators"}
FILES = [*WRITTEN, os.path.join("bib", "publications.bib")]


def tree(root):
    """Every file under ``root`` with its bytes, and every directory."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            found[os.path.relpath(os.path.join(dirpath, name), root)] = None
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                found[os.path.relpath(path, root)] = f.read()
    return found


def next_command(run, cwd):
    """Run the command `init` printed last, as a user would paste it."""
    command = run.stdout.strip().splitlines()[-1].strip()
    if " && " in command:
        cd, command = command.split(" && ", 1)
        cwd = cwd / shlex.split(cd)[1]
    words = shlex.split(command)
    assert words[0] == "sslabdata"
    return run_sslabdata(words[1:], cwd)


# Covers cli.init
def test_init_writes_a_lab_that_passes_strict_validation(tmp_path):
    """Into a directory that does not exist yet: every file is written, the
    printed next command (`--validate --strict`) passes, `--output` writes a
    document that matches schema v7, and each written YAML file matches its
    input schema."""
    run = run_sslabdata(["init", "new-lab"], tmp_path)
    assert run.code == 0 and run.crash is None, run.output
    lab = tmp_path / "new-lab"
    assert sorted(p for p, data in tree(lab).items() if data) == sorted(FILES)
    for name in FILES:
        assert os.path.join("new-lab", name) in run.stdout

    check = next_command(run, tmp_path)
    assert check.code == 0 and check.crash is None, check.output
    assert "Works: 1\nPeople: 1\nProjects: 1\n" in check.stdout

    out = run_sslabdata(["--config", "lab.yaml", "--strict", "--format", "json",
                         "--output", "lab.json"], lab)
    assert out.code == 0 and out.crash is None, out.output
    document = json.loads((lab / "lab.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)
    [work] = document["works"]
    assert work["authors"][0]["person_id"] == "aadams"
    assert work["project_ids"] == ["homebot"]

    for name, schema_name in WRITTEN.items():
        assert errors(schema_name, lab / name) == [], name


# Covers cli.init
def test_init_defaults_to_the_current_directory(tmp_path):
    run = run_sslabdata(["init"], tmp_path)
    assert run.code == 0 and run.crash is None, run.output
    assert " && " not in run.stdout.strip().splitlines()[-1]
    check = next_command(run, tmp_path)
    assert check.code == 0, check.output


# Covers cli.init.refuses_overwrite, cli.init.force
def test_init_never_overwrites_without_force(tmp_path):
    """Two files already there: each is named, and nothing at all is written.
    With --force, exactly the files init writes are replaced, and a file of
    the user's beside them is left alone."""
    (tmp_path / "bib").mkdir()
    (tmp_path / "people.yaml").write_text("- id: mine\n", encoding="utf-8")
    (tmp_path / "bib" / "publications.bib").write_text("% mine\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep\n", encoding="utf-8")
    before = tree(tmp_path)

    run = run_sslabdata(["init"], tmp_path)
    assert run.code == 1 and run.crash is None, run.output
    refused = [line for line in run.stderr.splitlines() if line]
    assert [line.split()[:2] for line in refused] == [
        ["INIT-FILE-EXISTS", os.path.join("bib", "publications.bib") + ":::"],
        ["INIT-FILE-EXISTS", "people.yaml:::"],
    ]
    assert run.stdout == ""
    assert tree(tmp_path) == before

    run = run_sslabdata(["init", ".", "--force"], tmp_path)
    assert run.code == 0 and run.crash is None, run.output
    after = tree(tmp_path)
    assert after["notes.txt"] == b"keep\n"
    assert set(after) == set(before) | set(FILES)
    assert b"aadams" in after["people.yaml"]
    assert next_command(run, tmp_path).code == 0


# Covers cli.init.wrong_kind
def test_init_refuses_what_is_not_a_file_or_directory(tmp_path):
    """DIR that is a file, and a path init writes that is a directory, are
    refused, the second even with --force, and nothing changes."""
    (tmp_path / "taken").write_text("x\n", encoding="utf-8")
    run = run_sslabdata(["init", "taken"], tmp_path)
    assert (run.code, run.crash) == (1, None)
    assert run.stderr.startswith("INIT-PATH-WRONG-KIND taken:::")
    assert (tmp_path / "taken").read_text(encoding="utf-8") == "x\n"

    lab = tmp_path / "lab"
    (lab / "people.yaml").mkdir(parents=True)
    before = tree(lab)
    run = run_sslabdata(["init", "lab", "--force"], tmp_path)
    assert (run.code, run.crash) == (1, None)
    assert run.stderr.startswith(
        f"INIT-PATH-WRONG-KIND {os.path.join('lab', 'people.yaml')}:::")
    assert tree(lab) == before


# Covers cli.init.outside_dir
def test_init_refuses_a_bib_directory_that_leads_outside(tmp_path):
    """A bib/ symlinked to a directory outside DIR is refused, even with
    --force, and nothing is written on either side of the link."""
    outside = tmp_path / "outside"
    outside.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "bib").symlink_to(outside, target_is_directory=True)
    run = run_sslabdata(["init", "lab", "--force"], tmp_path)
    assert (run.code, run.crash) == (1, None)
    assert run.stderr.split()[:2] == [
        "INIT-PATH-OUTSIDE-DIR",
        os.path.join("lab", "bib", "publications.bib") + ":::"]
    assert tree(outside) == {}
    assert sorted(os.listdir(lab)) == ["bib"]


# Covers cli.init.write_failed
@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                    reason="needs POSIX permissions that bind the user")
def test_a_failed_forced_write_keeps_the_old_file(tmp_path):
    """--force into a directory the user cannot write: coded, exit 1, and
    the file already there is as it was, with no temporary file left."""
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "lab.yaml").write_text("mine\n", encoding="utf-8")
    lab.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        before = tree(lab)
        run = run_sslabdata(["init", "lab", "--force"], tmp_path)
        after = tree(lab)
    finally:
        lab.chmod(stat.S_IRWXU)
    assert (run.code, run.crash) == (1, None)
    assert run.stderr.startswith(
        f"INIT-WRITE-FAILED {os.path.join('lab', 'lab.yaml')}:::")
    assert after == before
