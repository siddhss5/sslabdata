"""Output-format checks: the JSON Schema, YAML/JSON equality, and one small
comparison of the valid corpus's parsed output.

To regenerate tests/corpus/expected/valid.yaml after an intended change, run

    SSLABDATA_REGENERATE_EXPECTED=1 uv run pytest tests/conformance/test_output_format.py

and review the diff (git diff tests/corpus/expected/valid.yaml) before committing.
"""

import hashlib
import json
import os
import re

import jsonschema
import pytest
import yaml

from .support import (
    EXPECTED, INVALID, PREVIOUS_SCHEMA_PATHS, REPO_ROOT, SCHEMA_PATH, VALID, export,
    item,
)

DEMO_CONFIG = "examples/demo/lab.yaml"
EXPECTED_VALID = EXPECTED / "valid.yaml"


@pytest.fixture(scope="module")
def validator():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


@pytest.fixture(scope="module")
def demo_exports(tmp_path_factory):
    """The demo's output as (YAML, JSON), exported from the repo root."""
    out = tmp_path_factory.mktemp("demo")
    results = []
    for fmt in ("yaml", "json"):
        run, data = export(REPO_ROOT, out, DEMO_CONFIG, fmt)
        assert run.code == 0 and run.crash is None, run.output
        results.append(data)
    return results


def schema_errors(validator, data):
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in validator.iter_errors(data)]


def check_references(data):
    """Every ID the output refers to exists in the output, and the back-links
    on people and projects say what the works say."""
    people = {p["id"] for p in data["people"]}
    works = {w["bib_id"] for w in data["works"]}
    keys = {c["key"] for c in data["collaborators"]}
    for work in data["works"]:
        for author in work["authors"]:
            assert author["person_id"] in people | {None}, (work["bib_id"], author)
            assert author["collaborator_key"] in keys | {None}, (work["bib_id"], author)
            # Exactly one contributor, which is the `oneOf` the schema states
            # and which is checked here too so it holds of the document even
            # where nothing validates it.
            assert (author["person_id"] is None) != (author["collaborator_key"] is None), \
                (work["bib_id"], author)
        for editor in work["editors"]:
            assert editor["person_id"] in people | {None}, (work["bib_id"], editor)
    # Back-links are exactly what the works say, so a member or project that
    # authored or has works never ends up with an empty or partial list
    # (editing is not an authorship, so editors contribute nothing).
    for person in data["people"]:
        assert set(person["work_ids"]) <= works, person["id"]
        authored = [w["bib_id"] for w in data["works"]
                    if any(a["person_id"] == person["id"] for a in w["authors"])]
        assert sorted(person["work_ids"]) == sorted(authored), person["id"]
    for project in data["projects"]:
        assert set(project["work_ids"]) <= works, project["id"]
        assert set(project["people_ids"]) <= people, project["id"]
        having = [w for w in data["works"] if project["id"] in w["project_ids"]]
        assert sorted(project["work_ids"]) == sorted(w["bib_id"] for w in having), \
            project["id"]
        assert sorted(project["people_ids"]) == sorted(
            {a["person_id"] for w in having for a in w["authors"]} - {None}), project["id"]
    positions = {(w["bib_id"], a["position"]) for w in data["works"]
                 for a in w["authors"]}
    for collaborator in data["collaborators"]:
        grouped = [(a["work_id"], a["position"]) for a in collaborator["authorships"]]
        assert set(grouped) <= positions, collaborator["key"]
        assert collaborator["work_ids"] == sorted(
            {w for w, _ in grouped}, key=[w for w, _ in grouped].index)
    # Every unresolved authorship is grouped, and every grouping is used.
    referenced = {a["collaborator_key"] for w in data["works"] for a in w["authors"]
                  if a["collaborator_key"]}
    assert referenced == keys


# Covers output.schema
def test_valid_corpus_matches_schema(validator, valid_output):
    assert schema_errors(validator, valid_output) == []
    check_references(valid_output)


# Covers output.demo_schema
def test_demo_matches_schema(validator, demo_exports):
    for data in demo_exports:
        assert schema_errors(validator, data) == []
        check_references(data)


# Covers output.schema
def test_every_document_sslabdata_writes_matches_the_schema(validator, tmp_path):
    """Whatever input a run accepts, the document it writes is schema v5.

    Runs `sslabdata --format json --output` over the valid corpus, the demo
    and every invalid-corpus case. A case that exits non-zero writes nothing
    and is not checked; every other one must write a document the schema
    accepts, and none may crash. To reproduce, run

        pytest tests/conformance/test_output_format.py -k every_document --basetemp=DIR

    and read DIR/test_every_document*/schema-conformance.json (case -> exit
    status and schema errors) and the `<case>/lab.json` beside it, which can
    be validated against schema/v5/output.schema.json by any JSON Schema tool.
    """
    cases = {"valid": (VALID, "lab.yaml"), "demo": (REPO_ROOT, DEMO_CONFIG)}
    cases.update({f"invalid/{d.name}": (d, "lab.yaml")
                  for d in sorted(INVALID.iterdir()) if d.is_dir()})
    report = {}
    for name, (cwd, config) in cases.items():
        out = tmp_path / name
        run, data = export(cwd, out, config)
        assert run.crash is None, f"{name}: {run.crash}"
        report[name] = {"exit": run.code,
                        "schema_errors": [] if data is None
                        else schema_errors(validator, data)}
    (tmp_path / "schema-conformance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    assert {n: r["schema_errors"] for n, r in report.items()
            if r["schema_errors"]} == {}
    # Not vacuous: documents were written from all three kinds of input.
    assert report["valid"]["exit"] == report["demo"]["exit"] == 0
    assert report["invalid/invalid_person_role"]["exit"] == 0


def test_demo_header_and_equal_contribution_markers(demo_exports):
    """The demo's own header, and the `$^{*}$` it writes on two surnames: both
    are read as markers, and the marked authors still resolve."""
    for data in demo_exports:
        assert data["lab"]["name"] == "Example Lab"
        authors = item(data, "works", "bib_id", "brown2025tidy")["authors"]
        assert [(a["family"], a["person_id"], a["equal_contribution"])
                for a in authors] == [("Brown", "bbrown", True),
                                      ("Côté", "ccote", True),
                                      ("Adams", "aadams", False)]


# Covers output.schema
def test_schema_rejects_unknown_fields(validator, valid_output):
    """The schema is closed, so a new output field must be added to it."""
    data = json.loads(json.dumps(valid_output))
    data["works"][0]["surprise"] = True
    assert schema_errors(validator, data)


# Covers output.schema
def test_schema_rejects_an_authorship_with_two_references_or_none(validator,
                                                                  valid_output):
    """The `oneOf` on the contributor reference is enforced, both ways."""
    for change in ({"person_id": "aadams", "collaborator_key": "k-00000000"},
                   {"person_id": None, "collaborator_key": None}):
        data = json.loads(json.dumps(valid_output))
        data["works"][0]["authors"][0].update(change)
        assert schema_errors(validator, data), change


# The SHA-256 of each published schema, pinned byte for byte. "Unchanged" is
# a claim about bytes, and only bytes can make it: a check that a schema
# parses and states its version stays green while its title, its
# descriptions or any of its constraints are rewritten under a consumer that
# pinned it.
PREVIOUS_SCHEMA_SHA256 = {
    3: "97f85113822cffb47d36b415716563b50bfe4bf2bc30e892e4cc45b9e377aa92",
    4: "58baac01027d2f6b1a6451e395d6569bcb4318041ee204649aee8029adda24ba",
}

# The v5 `$id`, stated here as the literal a consumer would resolve. It is
# served from a tag created when this version ships and never moved (SPEC.md
# section 6), so changing this string is a contract change and has to be a
# deliberate edit in two places.
SCHEMA_ID = ("https://raw.githubusercontent.com/siddhss5/sslabdata/schema-v5"
             "/schema/v5/output.schema.json")


# Covers output.versioned_schema
def test_the_previous_schema_stays_reachable_unchanged(validator):
    """v3 and v4 are each at their own path, byte for byte, and v5 is at a
    third.

    A consumer pinned to an earlier version keeps a stable target only if
    nothing in the file moves, so the assertion is on the digest rather than
    on any property of the parsed document.
    """
    assert validator.schema["properties"]["schema_version"]["const"] == 5
    for version, path in PREVIOUS_SCHEMA_PATHS.items():
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == PREVIOUS_SCHEMA_SHA256[version]

        previous = json.loads(raw.decode("utf-8"))
        jsonschema.Draft202012Validator.check_schema(previous)
        assert previous["properties"]["schema_version"]["const"] == version
        # Different documents at different paths, not one file read twice.
        assert path != SCHEMA_PATH
        assert previous["$id"] != validator.schema["$id"]


# Covers output.versioned_schema
def test_the_published_id_is_the_string_consumers_resolve(validator):
    """The `$id` is the contract's address, so it is pinned as a literal.

    It names a dedicated tag rather than a branch: a branch URL moves under
    the consumers that resolved it, and `blob/main` serves an HTML page
    rather than the schema at all.
    """
    schema_id = validator.schema["$id"]
    assert schema_id == SCHEMA_ID
    assert "/schema-v5/" in schema_id, schema_id
    assert "/main/" not in schema_id and "/blob/" not in schema_id, schema_id


# --- The two properties the document must have as a whole -------------------

# Markdown emphasis, and an HTML tag. The emphasis pattern is deliberately
# narrow: a lone `*` is not emphasis, which matters because `Informed RRT*`
# and `BIT*` are real paper titles and `Davis*` is a real corpus name.
MARKDOWN_EMPHASIS = re.compile(r"\*[^*\s][^*]*\*")
HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")

# The properties whose value the input supplies verbatim. Markdown
# punctuation in one of these is text an author wrote, which SPEC.md section
# 2 says sslabdata neither escapes nor strips -- the corpus carries `not
# *emphasis*` in a title on purpose. Anywhere else it would be markup sslabdata
# generated, which is what composing `venue` used to do and what #56 removed.
INPUT_TEXT = {"title", "abstract", "note", "name", "given", "von", "family",
              "suffix", "literal", "name_variants", "description",
              "thesis_title", "current_position", "role", "status",
              "category", "key", "url"}


def markup_paths(data):
    """Every path outside the re-serialized export whose string carries markup.

    The export is skipped because it is the entry re-typeset and still holds
    LaTeX by design (SPEC.md section 5). Everything else is walked to any
    depth, and the path is returned rather than a count, so a failure says
    where the markup is.
    """
    found = []

    def walk(value, path):
        if isinstance(value, dict):
            for name, inner in value.items():
                if name != "bibtex":
                    walk(inner, path + "/" + str(name))
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                walk(inner, path + "/" + str(index))
        elif isinstance(value, str):
            if MARKDOWN_EMPHASIS.search(value) or HTML_TAG.search(value):
                found.append("%s = %r" % (path, value))

    walk(data, "")
    return sorted(found)


def leaf_property(path):
    """The property name a path ends at, skipping list indices."""
    parts = [part for part in path.split("/") if part and not part.isdigit()]
    return parts[-1] if parts else ""


# Covers output.no_markup
def test_the_demo_document_carries_no_markup(demo_exports):
    """Nothing sslabdata emits for the demo is Markdown or HTML.

    The demo's input is plain, so any markup in its output would be markup
    sslabdata generated. Under `schema_version` 3 `venue` was exactly that:
    `*Transactions on Robot Learning*, 4(2), 2025`.
    """
    for data in demo_exports:
        assert markup_paths(data) == []
    # An empty list has to mean "looked and found none": the venue string v3
    # composed must be rejected by the same scan.
    composed = {"works": [{"venue": "*Transactions on Robot Learning*, 4(2), 2025"}]}
    assert markup_paths(composed) != []
    assert markup_paths({"lab": {"name": "<b>Lab</b>"}}) != []


# Covers output.no_markup
def test_markup_in_the_corpus_is_only_text_the_input_wrote(valid_output):
    """Where the corpus does carry Markdown punctuation, it is input text.

    The corpus writes `[a link](x)`, `# heading` and `*emphasis*` into a
    title on purpose, and SPEC.md section 2 says those are text rather than
    markup. What must never happen is markup in a property sslabdata composes,
    and that is what this pins.
    """
    found = markup_paths(valid_output)
    assert found != [], "the corpus is supposed to exercise this"
    offenders = [path for path in found
                 if leaf_property(path.split(" = ")[0]) not in INPUT_TEXT]
    assert offenders == []


# Covers output.derived_is_empty
def test_every_derived_bag_is_empty(valid_output, demo_exports):
    """`derived` is sslabdata-owned and sslabdata puts nothing in it yet.

    Asserted so the region cannot quietly fill: a key appearing there is a
    change a reader of this test has to make on purpose.
    """
    def bags(data):
        found = []

        def walk(value, path):
            if isinstance(value, dict):
                if "derived" in value:
                    found.append((path + "/derived", value["derived"]))
                for name, inner in value.items():
                    walk(inner, path + "/" + str(name))
            elif isinstance(value, list):
                for index, inner in enumerate(value):
                    walk(inner, path + "/" + str(index))

        walk(data, "")
        return found

    for data in [valid_output] + list(demo_exports):
        filled = [path for path, bag in bags(data) if bag != {}]
        assert filled == [], filled
    # The walk has to have found the bags it is reporting on.
    assert len(bags(valid_output)) > 100, len(bags(valid_output))



def keys_anywhere(data):
    """Every key of every object in the document, at any depth."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            found.update(value)
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(data)
    return found


# Covers output.project.image
def test_a_project_image_is_emitted_or_null_and_never_reported(valid_output,
                                                               valid_validate):
    """`image` is read from `projects.yaml` like any other key: carried as
    written where a project has one, declared and null where it has none,
    and never reported as a key sslabdata does not read."""
    homebot = item(valid_output, "projects", "id", "homebot")
    sharedarm = item(valid_output, "projects", "id", "sharedarm")
    assert homebot["image"] == "images/projects/homebot.jpg"
    assert "image" in sharedarm and sharedarm["image"] is None
    assert valid_validate.code == 0 and valid_validate.crash is None
    assert "RECORD-KEY-UNKNOWN" not in valid_validate.output
    assert "image" not in valid_validate.output


# Covers output.link.verification
def test_a_link_verification_is_only_its_status(valid_output, demo_exports):
    """A build never fetches and records no time, so `verification` carries
    a status and nothing else."""
    for data in [valid_output] + list(demo_exports):
        verifications = [link["verification"] for w in data["works"]
                         for links in w["links"].values() for link in links]
        assert verifications, "the document is supposed to carry links"
        assert [v for v in verifications if set(v) != {"status"}] == []
        assert "checked_at" not in keys_anywhere(data)


# Covers output.no_duplicate_counts
def test_no_count_repeats_the_length_of_a_list(valid_output, demo_exports):
    """A person's and a collaborator's counts would only restate the length
    of `work_ids` or `authorships` beside them, so neither is emitted."""
    for data in [valid_output] + list(demo_exports):
        assert data["people"] and data["collaborators"]
        assert keys_anywhere(data) & {"work_count", "authorship_count"} == set()


# Covers output.yaml_json_same
def test_yaml_and_json_hold_the_same_data(tmp_path, valid_output, demo_exports):
    run, yaml_data = export(VALID, tmp_path, fmt="yaml")
    assert run.code == 0 and run.crash is None, run.output
    assert yaml_data == valid_output
    demo_yaml, demo_json = demo_exports
    assert demo_yaml == demo_json


# --- The snapshot ------------------------------------------------------------
# One small comparison of parsed output. It covers only cases whose values no
# open issue is expected to change: entries an xfailed test checks are left
# out on purpose. So fixing that issue turns its xfail green without anyone
# having to re-record this file, and the dedicated xfail tests stay the only
# place that behavior is stated.

SNAPSHOT = {
    "works": [
        "str-repeat",         # an expanded @string macro
        "type-article",       # journal, volume and number in the venue
        "type-phdthesis",     # a thesis venue
        "link-doi-bare",      # a DOI link
        "link-youtube",       # a video link
        "present",            # a PDF that exists
        "proj-multiple",      # two project tags, and a TeX-accented author
        "id-external-2023",   # a resolved author beside an unresolved one
    ],
    "people": ["ccote", "eevans", "vvandenberg"],
    "projects": ["homebot"],
    "collaborators": ["Quentin Quinn", "Rachel Ross"],
}
KEYS = {"works": "bib_id", "people": "id", "projects": "id", "collaborators": "name"}


def select(data):
    """The part of the output the snapshot owns, in the order SNAPSHOT lists."""
    chosen = {"schema_version": data["schema_version"],
              "generator": data["generator"], "lab": data["lab"]}
    for section, wanted in SNAPSHOT.items():
        chosen[section] = [item(data, section, KEYS[section], value) for value in wanted]
    return chosen


def diff_paths(expected, actual, path=""):
    """List the paths where two parsed outputs differ."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in sorted(set(expected) | set(actual), key=str):
            if key not in expected or key not in actual:
                out.append(f"{path}/{key}: only in {'actual' if key in actual else 'expected'}")
            else:
                out += diff_paths(expected[key], actual[key], f"{path}/{key}")
        return out
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            label = e.get("bib_id") or e.get("id") or e.get("name") if isinstance(e, dict) else i
            out += diff_paths(e, a, f"{path}/{label}")
        return out
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


# Covers output.full
def test_full_output(valid_output):
    """The snapshot, compared as parsed data rather than byte for byte."""
    chosen = select(valid_output)
    if os.environ.get("SSLABDATA_REGENERATE_EXPECTED"):
        with open(EXPECTED_VALID, "w", encoding="utf-8") as f:
            f.write("# Part of the output of tests/corpus/valid/, compared as parsed data by\n"
                    "# tests/conformance/test_output_format.py::test_full_output. The entries\n"
                    "# here are the ones no open issue is expected to change; SNAPSHOT in that\n"
                    "# file says which they are and why the rest is left out. Regenerate with\n"
                    "#   SSLABDATA_REGENERATE_EXPECTED=1 uv run pytest "
                    "tests/conformance/test_output_format.py\n"
                    "# and review the diff before committing.\n")
            yaml.safe_dump(chosen, f, allow_unicode=True, sort_keys=False, width=100)
        pytest.skip(f"regenerated {EXPECTED_VALID.name}; review the diff")
    with open(EXPECTED_VALID, encoding="utf-8") as f:
        expected = yaml.safe_load(f)
    differences = diff_paths(expected, chosen)
    assert not differences, "\n".join(differences[:40])
