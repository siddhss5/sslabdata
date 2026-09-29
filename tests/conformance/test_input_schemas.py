"""The input schemas accept what the loaders accept, and reject what the
loaders reject for a type or shape reason.

The schemas are read as an installed user reads them, through
importlib.resources from `sslabdata.schema`. Each input file is read the way
an editor's YAML language server reads it: a date is text and every key is
text, since JSON has no other kind.

The oracle is the loaders' own verdict. tests/corpus/expected/diagnostics.yaml
records every diagnostic of every invalid fixture, located at its file. An
input file that carries a code in `SHAPE` must fail its schema; every other
input file must validate. Every code the registry locates at an input file is
in `SHAPE` or in `NOT_SHAPE`, which says why a schema does not check it, so a
new code cannot be left unclassified.

A failure names the fixture and the file; rerun with `-k <fixture>` and
validate that file by hand to inspect it.
"""

import json
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest
import yaml

from .support import EXPECTED, INVALID, REPO_ROOT, VALID, case

SCHEMAS = ("lab", "people", "projects", "collaborators")

# The key in lab.yaml that names each data file.
DATA_FILE_KEYS = {"people_file": "people", "projects_file": "projects",
                  "collaborators_file": "collaborators"}

# The codes that say a value has the wrong type or shape, a required key is
# missing, or a value is outside its enumeration.
SHAPE = {
    "CONFIG-NOT-A-MAPPING", "CONFIG-KEY-MISSING", "CONFIG-TYPE-INVALID",
    "PEOPLE-NOT-A-LIST", "PROJECTS-NOT-A-LIST", "COLLABORATORS-NOT-A-LIST",
    "PEOPLE-FIELD-MISSING", "PROJECTS-FIELD-MISSING",
    "COLLABORATORS-FIELD-MISSING", "RECORD-TYPE-INVALID",
    "PEOPLE-ROLE-INVALID", "PEOPLE-STATUS-INVALID", "PROJECTS-STATUS-INVALID",
}

# The deliberate exceptions: codes located at an input file that its schema
# does not check, and why. A file carrying only these validates.
NOT_SHAPE = {
    # The loaders reject these, and a schema cannot see them.
    "CONFIG-KEY-REPEATED": "a repeated key is a fact of the YAML text; the "
                           "data a schema sees holds one value per key",
    "RECORD-KEY-REPEATED": "as CONFIG-KEY-REPEATED",
    "CONFIG-VALUE-NOT-JSON": "NaN, infinity, a set, binary and a non-string "
                             "key are YAML values that the JSON data a schema "
                             "sees has no form for",
    "CONFIG-BIB-FILE-ABSOLUTE": "a path rule about bib_dir, checked by both "
                                "Windows and POSIX path rules, not a type",
    "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR": "resolved against bib_dir on the "
                                       "filesystem, symlinks included",
    "CONFIG-FILE-NOT-FOUND": "a fact of the filesystem",
    "CONFIG-PATH-WRONG-KIND": "a fact of the filesystem",
    "PEOPLE-ID-DUPLICATE": "compares records with each other",
    "PROJECTS-ID-DUPLICATE": "compares records with each other",
    "PEOPLE-ALIAS-AMBIGUOUS": "compares records with each other",
    "PEOPLE-YAML-INVALID": "the file is not YAML, so there is no data to "
                           "validate",
    "PROJECTS-YAML-INVALID": "as PEOPLE-YAML-INVALID",
    "COLLABORATORS-YAML-INVALID": "as PEOPLE-YAML-INVALID",
    # The loaders accept these, with a warning.
    "CONFIG-KEY-UNKNOWN": "an unknown key is reported and ignored, not "
                          "rejected, so the schemas allow it",
    "RECORD-KEY-UNKNOWN": "as CONFIG-KEY-UNKNOWN",
    "CONFIG-BIB-FILES-MISSING": "no bib_files can be meant; the key is "
                                "optional",
    "CONFIG-LAB-NAME-MISSING": "a lab with no name is loaded, and a name is "
                               "optional",
    "TEXT-CONTROL-CHARACTER": "about the characters inside text, which are "
                              "removed and the rest kept",
}

with open(EXPECTED / "diagnostics.yaml", encoding="utf-8") as f:
    DIAGNOSTICS = yaml.safe_load(f)


def load_schema(name):
    text = (files("sslabdata.schema") / "input" / "v1"
            / f"{name}.schema.json").read_text(encoding="utf-8")
    schema = json.loads(text)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


VALIDATORS = {name: load_schema(name) for name in SCHEMAS}


class EditorLoader(yaml.SafeLoader):
    """YAML with no timestamp type: a date is read as its text."""


EditorLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers
            if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def as_json(value):
    if isinstance(value, dict):
        return {str(k): as_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [as_json(v) for v in value]
    return value


def read(path):
    """The file's data as JSON sees it, or None when it is not YAML."""
    try:
        with open(path, encoding="utf-8") as f:
            return as_json(yaml.load(f, Loader=EditorLoader))
    except (yaml.YAMLError, UnicodeDecodeError):
        return None


def errors(schema, path):
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in VALIDATORS[schema].iter_errors(read(path))]


# --- Valid inputs ----------------------------------------------------------------

VALID_INPUTS = [
    *[(p, p.stem) for p in sorted(VALID.glob("*.yaml"))],
    *[(p, p.stem) for p in sorted((REPO_ROOT / "examples" / "demo").glob("*.yaml"))],
    (REPO_ROOT / "examples" / "config.yaml", "lab"),
    *[(p, p.stem) for p in sorted((REPO_ROOT / "tests" / "fixtures").glob("*.yaml"))],
]


@pytest.mark.parametrize(
    "path, schema", [pytest.param(p, s, id=p.relative_to(REPO_ROOT).as_posix())
                     for p, s in VALID_INPUTS])
def test_valid_inputs_validate(path, schema):
    """input.schema_valid: every input file of the valid corpus, the demo and
    the examples validates against its schema."""
    assert schema in SCHEMAS
    assert errors(schema, path) == []


# --- The invalid corpus ----------------------------------------------------------

def inputs(fixture):
    """{name as diagnostics locate it: (path, schema)} for each input file a
    fixture's lab.yaml reaches. Paths are relative to the fixture directory,
    which is where the corpus runs sslabdata from."""
    directory = INVALID / fixture
    found = {"lab.yaml": (directory / "lab.yaml", "lab")}
    config = read(directory / "lab.yaml")
    for key, schema in DATA_FILE_KEYS.items():
        name = config.get(key) if isinstance(config, dict) else None
        if isinstance(name, str) and name and (directory / name).is_file():
            found[name] = (directory / name, schema)
    return found


INVALID_CASES = [case(case_id, entry["dir"])
                 for case_id, entry in DIAGNOSTICS.items()]


def places(schema, data):
    """Where the schema finds each error, as diagnostics locate it: (keys,
    field), where ``keys`` holds each value the diagnostic's key may take.

    In lab.yaml the key is the top-level key. In a data file it names the
    record: by its first required field, or by its id or nothing when that
    field is what is wrong. A missing or extra property is placed at the
    property.
    """
    found = []
    for error in VALIDATORS[schema].iter_errors(data):
        path = list(error.absolute_path)
        if error.validator == "required":
            extra = [p for p in error.validator_value if p not in error.instance]
        elif error.validator == "additionalProperties":
            extra = [p for p in error.instance if p not in error.schema["properties"]]
        else:
            extra = [None]
        for name in extra:
            steps = path + ([name] if name is not None else [])
            if schema == "lab":
                named = [s for s in steps if isinstance(s, str)]
                found.append(({named[0] if named else None},
                              named[1] if len(named) > 1 else None))
                continue
            record = data[steps[0]] if steps else None
            keys = {None}
            if isinstance(record, dict):
                keys |= {record.get("id"),
                         record.get("name" if schema == "collaborators" else "id")}
            named = [s for s in steps[1:] if isinstance(s, str)]
            found.append((keys, named[0] if named else None))
    return found


@pytest.mark.parametrize("case_id, fixture", INVALID_CASES)
def test_invalid_corpus_agrees_with_the_loaders(case_id, fixture):
    """input.schema_invalid: the schema finds an error at the place of each
    type or shape problem the loaders report, and a file in which they report
    none validates."""
    diagnostics = DIAGNOSTICS[case_id]["diagnostics"]
    problems = []
    for name, (path, schema) in inputs(fixture).items():
        at_file = [d for d in diagnostics if d.get("file") == name]
        codes = {d["code"] for d in at_file}
        data = read(path)
        if data is None:
            assert codes & {"PEOPLE-YAML-INVALID", "PROJECTS-YAML-INVALID",
                            "COLLABORATORS-YAML-INVALID"}, name
            continue
        found = places(schema, data)
        for d in at_file:
            if d["code"] in SHAPE and not any(
                    d.get("key") in keys and d.get("field") in (None, field)
                    for keys, field in found):
                problems.append(f"{name}: the loaders report {d['code']} at "
                                f"{d.get('key')}:{d.get('field')}, and the "
                                "schema finds nothing there")
        if found and not codes & SHAPE:
            problems.append(f"{name}: the loaders report no type or shape "
                            f"problem ({sorted(codes)}), but "
                            f"{errors(schema, path)}")
    assert problems == []


def test_every_code_at_an_input_file_is_classified():
    """A code the registry locates at an input file is either checked by the
    schemas or listed, with its reason, as not checked."""
    unclassified = set()
    for entry in DIAGNOSTICS.values():
        names = inputs(entry["dir"])
        unclassified |= {d["code"] for d in entry["diagnostics"]
                         if d.get("file") in names}
    assert unclassified - SHAPE - set(NOT_SHAPE) == set()
    assert SHAPE.isdisjoint(NOT_SHAPE)
