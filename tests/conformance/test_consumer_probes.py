"""The consumer probes, run against the demo output, and the demo's input
fields checked against the document.

Each probe under `examples/consumers/` is a small program that reads the
emitted document and nothing else, run here the way a consumer would run it:
as a subprocess taking the document's path. If a probe cannot be written from
the emitted document alone, that is a schema bug, not a probe bug (SPEC.md
section 1).
"""

import json
import re
import subprocess
import sys

import jsonschema
import pytest

from .support import REPO_ROOT, export, work


PROBES = REPO_ROOT / "examples" / "consumers"
DEMO_CONFIG = "examples/demo/lab.yaml"
DEMO_BIB = REPO_ROOT / "examples" / "demo" / "bib"
CSL_SCHEMA = REPO_ROOT / "tests" / "vendor" / "csl-data.json"

# The demo article a citation must be complete for, as
# examples/demo/bib/journal.bib writes it.
ARTICLE = "brown2025tidy"
JOURNAL = "Transactions on Robot Learning"
VOLUME, NUMBER, PAGES = "4", "2", "112--131"
DOI = "10.5555/example.trl.2025.0412"


@pytest.fixture(scope="module")
def demo_document(tmp_path_factory):
    """(path, parsed) for the demo exported as JSON."""
    out = tmp_path_factory.mktemp("probes")
    run, data = export(REPO_ROOT, out, DEMO_CONFIG, "json")
    assert run.crash is None, run.crash
    assert run.code == 0, run.output
    return out / "lab.json", data


def run_probe(name, document):
    """Run one probe as a consumer would: a subprocess given the document."""
    result = subprocess.run(
        [sys.executable, str(PROBES / name), str(document)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8")


@pytest.fixture(scope="module")
def probe_output(demo_document):
    """{probe name: what it wrote}, one subprocess per probe."""
    path, _ = demo_document
    return {name: run_probe(name, path)
            for name in ("cv_tex.py", "csl_json.py", "graph.py")}


# A name's parts preserve whatever the input supplied -- a full given name or
# an initial -- so a probe must reproduce them as found, on every authorship.

def expected_name_from_parts(author):
    if author.get("literal"):
        return author["literal"]
    parts = [author.get(k) for k in ("given", "von", "family", "suffix")]
    return " ".join(p for p in parts if p)


def expected_csl_name(author):
    if author.get("literal"):
        return {"literal": author["literal"]}
    name = {}
    for csl_key, doc_key in (("given", "given"), ("family", "family"),
                             ("non-dropping-particle", "von"), ("suffix", "suffix")):
        if author.get(doc_key):
            name[csl_key] = author[doc_key]
    return name


# --- cv_tex.py ---------------------------------------------------------------

TEX_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
               "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
               "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex(text):
    return "".join(TEX_ESCAPES.get(c, c) for c in str(text))


def tex_entry(fragment, title):
    """The one `\\item` of a LaTeX fragment that carries ``title``."""
    found = [i for i in fragment.split(r"\item ") if tex(title) in i]
    assert len(found) == 1, "expected one entry for %r, found %d" % (title, len(found))
    return found[0]


def test_cv_tex_fragment_is_well_formed(probe_output, demo_document):
    """Grouped by year newest first, one entry per work, each entry opening
    with its authors' names as the document's parts have them."""
    _, doc = demo_document
    fragment = probe_output["cv_tex.py"]

    years = [int(y) for y in re.findall(r"\\section\*\{(\d+)\}", fragment)]
    assert years == sorted({p["year"] for p in doc["works"]}, reverse=True)
    assert fragment.count(r"\section*{") == fragment.count(r"\begin{enumerate}")
    assert fragment.count(r"\begin{enumerate}") == fragment.count(r"\end{enumerate}")
    assert fragment.count(r"\item ") == len(doc["works"])

    for pub in doc["works"]:
        lines = tex_entry(fragment, pub["title"]).splitlines()
        authors = ", ".join(expected_name_from_parts(a) for a in pub["authors"])
        assert lines[0] == tex(authors) + ".", pub["bib_id"]
        assert r"\newblock %s." % tex(pub["title"]) in lines, pub["bib_id"]
        # The year closes a block of its own; searching the whole entry would
        # be satisfied by a DOI that happens to contain the year.
        assert [l for l in lines if l.startswith(r"\newblock")
                and l.endswith("%s." % pub["year"])], pub["bib_id"]

    entry = tex_entry(fragment, work(doc, ARTICLE)["title"])
    assert r"\emph{%s}" % JOURNAL in entry
    assert "%s(%s)" % (VOLUME, NUMBER) in entry
    assert PAGES in entry


# --- csl_json.py -------------------------------------------------------------

# The CSL type for each entry type the demo contains, stated here rather than
# read from the probe; the test checks the demo contains exactly these.
CSL_TYPE = {"article": "article-journal", "inproceedings": "paper-conference",
            "phdthesis": "thesis", "mastersthesis": "thesis",
            "techreport": "report", "misc": "document",
            "incollection": "chapter", "inbook": "chapter",
            "book": "book", "manual": "report"}

# Where a work's own web page sits, in the order a citation processor should
# prefer: the page the entry named, then whatever else it can be reached at.
URL_KINDS = ("url", "pdf", "doi", "arxiv")


def first_link(pub, *kinds):
    """The first URL the document files under any of ``kinds``, or None."""
    for kind in kinds:
        for record in pub["links"].get(kind) or []:
            return record["url"]
    return None


def test_csl_json_export_is_schema_valid_and_citable(probe_output, demo_document):
    """Valid against the published CSL-JSON schema, every record carrying the
    fields the document can supply, and the article a complete reference."""
    _, doc = demo_document
    records = json.loads(probe_output["csl_json.py"])

    with open(CSL_SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    validator = validator_class(schema)
    assert [e.message for e in validator.iter_errors(records)] == []
    # An empty error list has to mean "looked and found none".
    assert not validator.is_valid([{"id": "x", "type": "not-a-csl-type"}])

    assert [r["id"] for r in records] == [p["bib_id"] for p in doc["works"]]
    assert {p["entry_type"] for p in doc["works"]} == set(CSL_TYPE)
    by_id = {r["id"]: r for r in records}
    for pub in doc["works"]:
        record = by_id[pub["bib_id"]]
        assert {k: record.get(k) for k in (
            "id", "type", "title", "author", "issued", "abstract", "note", "URL")} == {
            "id": pub["bib_id"],
            "type": CSL_TYPE[pub["entry_type"]],
            "title": pub["title"],
            "author": [expected_csl_name(a) for a in pub["authors"]],
            "issued": {"date-parts": [[pub["year"]]]},
            "abstract": pub["abstract"],
            "note": pub["note"],
            "URL": first_link(pub, *URL_KINDS),
        }, pub["bib_id"]

    record = by_id[ARTICLE]
    assert record.get("container-title") == JOURNAL
    assert record.get("volume") == VOLUME
    assert record.get("issue") == NUMBER
    assert record.get("page") == PAGES.replace("--", "-")
    assert record.get("DOI") == DOI


# --- graph.py ----------------------------------------------------------------

def read_graph(text):
    """(nodes, edges) from the probe's tab-separated records. An `authored`
    edge carries the authorship's position as a fourth field."""
    nodes, edges = {}, []
    for line in text.splitlines():
        record = line.split("\t")
        if record[0] == "node":
            nodes[record[1]] = record[2]
        else:
            edges.append(tuple(record[1:]))
    return nodes, edges


def expected_contributor(author):
    """The node one authorship implies: `person_id` for a lab member,
    `collaborator_key` for an authorship that matched nobody."""
    if author.get("person_id"):
        return "person:" + author["person_id"]
    if author.get("collaborator_key"):
        return "collaborator:" + author["collaborator_key"]
    return None


def expected_edges(doc):
    """Every edge the document implies, given the references it carries."""
    projects = {p["id"] for p in doc["projects"]}
    edges = []
    for pub in doc["works"]:
        target = "work:" + pub["bib_id"]
        for index, author in enumerate(pub["authors"], 1):
            node = expected_contributor(author)
            if node:
                edges.append(("authored", node, target,
                              str(author.get("position") or index)))
        edges += [("part_of", target, "project:" + i) for i in pub["project_ids"]
                  if i in projects]
    for project in doc["projects"]:
        edges += [("member_of", "person:" + i, "project:" + project["id"])
                  for i in project["people_ids"]]
    return edges


def test_graph_is_well_formed(probe_output, demo_document):
    """One node per work, project and contributor, and exactly the edges the
    document implies, every one resolving to a declared node."""
    _, doc = demo_document
    nodes, edges = read_graph(probe_output["graph.py"])

    assert [e for e in edges if e[0] == "authored"] != []
    for edge in edges:
        assert edge[1] in nodes and edge[2] in nodes, edge
    assert [e for e in edges if e[0] == "authored" and len(e) != 4] == []
    assert sorted(n for n in nodes if n.startswith("work:")) == sorted(
        "work:" + p["bib_id"] for p in doc["works"])
    assert sorted(n for n in nodes if n.startswith("project:")) == sorted(
        "project:" + p["id"] for p in doc["projects"])
    # A co-author the document could not resolve never arrives as a person.
    assert sorted(n for n in nodes if n.startswith("person:")) == sorted(
        "person:" + p["id"] for p in doc["people"])
    assert sorted(n for n in nodes if n.startswith("collaborator:")) == sorted(
        "collaborator:" + c["key"] for c in doc["collaborators"])
    # Complete tuples: a count would pass with two edges' endpoints swapped.
    assert sorted(edges) == sorted(expected_edges(doc))


# --- graph.py: who the co-authors are ----------------------------------------
#
# From examples/demo/bib/books.bib and conference.bib. Priya Patel is one
# external co-author on three works, written `Patel, Priya` twice and
# `Patel, P.` once; collaborators_file declares the alias that joins them.
# Pradeep Patel is a different person on a fourth work. The two `Lee, Lin`
# co-authors of `nolan2020stairs` are two different people written alike.
# A contributor is identified only by the works it authored, never by a label.

ONE_PERSON_WORKS = ("adams2022survey", "adams2023handbook", "ingram2019toolkit")
OTHER_PERSON_WORK = "hughes2021gaits"
SHARED_FAMILY = "Patel"
SAME_NAME_WORK = "nolan2020stairs"
SAME_NAME_FAMILY, SAME_NAME_GIVEN = "Lee", "Lin"


def authors_named(pub, family, given=None):
    return [a for a in pub["authors"] if a["family"] == family
            and (given is None or a["given"] == given)]


# Covers probe.identity_fixtures
def test_identity_fixtures_are_present(demo_document):
    """The document carries the scenarios the identity tests assert over, so
    those tests cannot pass because the works they are about have gone."""
    _, doc = demo_document
    spellings = {}
    for bib_id in ONE_PERSON_WORKS + (OTHER_PERSON_WORK,):
        found = authors_named(work(doc, bib_id), SHARED_FAMILY)
        assert len(found) == 1, bib_id
        assert found[0]["person_id"] is None, bib_id
        spellings.setdefault(found[0]["given"], []).append(bib_id)
    assert {given: sorted(works) for given, works in spellings.items()} == {
        "Priya": ["adams2022survey", "adams2023handbook"],
        "P.": ["ingram2019toolkit"],
        "Pradeep": ["hughes2021gaits"],
    }
    assert {a["name"] for bib_id in ONE_PERSON_WORKS + (OTHER_PERSON_WORK,)
            for a in authors_named(work(doc, bib_id), SHARED_FAMILY)} == {
        "Priya Patel", "P. Patel", "Pradeep Patel"}

    pub = work(doc, SAME_NAME_WORK)
    alike = authors_named(pub, SAME_NAME_FAMILY, SAME_NAME_GIVEN)
    assert len(alike) == 2
    assert [a for a in pub["authors"] if a["person_id"] is None] == alike
    assert [i for i, a in enumerate(pub["authors"], 1) if a in alike] == [2, 3]


def external_contributors(edges):
    """{node: the works it authored} for each `collaborator:` node."""
    authored = {}
    for edge in edges:
        if edge[0] == "authored" and edge[1].startswith("collaborator:"):
            authored.setdefault(edge[1], set()).add(edge[2].split(":", 1)[1])
    return authored


# Covers probe.identity_one_person
def test_graph_joins_one_co_author_written_two_ways(probe_output):
    """Exactly one external contributor touches any of the three works, and
    it holds exactly those three."""
    authored = external_contributors(read_graph(probe_output["graph.py"])[1])
    joined = [node for node, works in authored.items()
              if works & set(ONE_PERSON_WORKS)]
    assert len(joined) == 1, sorted(authored.items())
    assert authored[joined[0]] == set(ONE_PERSON_WORKS)


# Covers probe.identity_distinct_people
def test_graph_separates_co_authors_sharing_an_initial(probe_output):
    """The co-author sharing an initial and a family name is a separate
    contributor holding exactly their own work."""
    authored = external_contributors(read_graph(probe_output["graph.py"])[1])
    other = [node for node, works in authored.items() if OTHER_PERSON_WORK in works]
    assert len(other) == 1, sorted(authored.items())
    assert authored[other[0]] == {OTHER_PERSON_WORK}
    shared = [node for node, works in authored.items()
              if works & set(ONE_PERSON_WORKS)]
    assert shared != [] and set(shared) & set(other) == set()


# Covers probe.identity_authorship
def test_graph_keeps_two_authorships_written_alike_apart(probe_output, demo_document):
    """Two people written identically on one work are one grouping with two
    authorships, told apart by the positions the document declares."""
    _, doc = demo_document
    _, edges = read_graph(probe_output["graph.py"])
    declared = [a.get("position") for a in authors_named(
        work(doc, SAME_NAME_WORK), SAME_NAME_FAMILY, SAME_NAME_GIVEN)]
    assert None not in declared and len(set(declared)) == 2, declared

    alike = [edge for edge in edges if edge[0] == "authored"
             and edge[2] == "work:" + SAME_NAME_WORK
             and edge[1].startswith("collaborator:")]
    assert len(alike) == 2, alike
    assert len({edge[1] for edge in alike}) == 1, alike
    assert sorted(edge[3] for edge in alike) == sorted(str(p) for p in declared)


# --- Every input field of the demo reaches the document ----------------------
#
# Each field of each demo entry is read from the .bib files and looked up in
# the property the document gives it (SPEC.md section 5). `project` is
# sslabdata's own tag field and reaches `project_ids`, which `fields.project`
# covers. Every demo field is written one `name = {value}` per line, which is
# all the reader below handles.

ENTRY_RE = re.compile(r"^@(\w+)\{([^,]+),$(.*?)^\}", re.M | re.S)
FIELD_RE = re.compile(r"^\s*(\w+)\s*=\s*\{(.*)\},?$", re.M)


def demo_entries():
    """{citation key: (entry type, {field name: value})} for the demo input."""
    entries = {}
    for path in sorted(DEMO_BIB.glob("*.bib")):
        for kind, key, body in ENTRY_RE.findall(path.read_text(encoding="utf-8")):
            entries[key] = (kind.lower(), {name.lower(): value
                                           for name, value in FIELD_RE.findall(body)})
    return entries


DEMO_FIELDS = sorted({name for _, fields in demo_entries().values()
                      for name in fields} - {"project"})

CONTAINERS = ("journal", "booktitle", "school", "institution")
BIBLIOGRAPHIC_SCHEMES = ("doi", "isbn", "issn")
# A value the input wrote with LaTeX in it reaches the document converted, so
# only its presence is comparable, not its text.
LATEX = re.compile(r"[\\{}$~]")


def bibtex_names(people):
    """Parsed names joined back in BibTeX's own `von Last, Jr, First` order."""
    return " and ".join(", ".join(p for p in (
        " ".join(p for p in (n.get("von"), n.get("family")) if p),
        n.get("suffix"), n.get("given")) if p) for n in people)


def reached(pub, field, fields):
    """The value the work gives one input field, comparable with the input's."""
    if field in ("author", "editor"):
        return bibtex_names(pub[field + "s"])
    if field in CONTAINERS:
        return (pub["venue"] or {}).get("name")
    if field in BIBLIOGRAPHIC_SCHEMES:
        return ", ".join(pub["identifiers"].get(field, []))
    if field == "eprint":
        # Filed under the scheme `archivePrefix` names, lower-cased.
        return ", ".join(pub["identifiers"].get(fields["archiveprefix"].lower(), []))
    if field == "archiveprefix":
        schemes = [s for s in pub["identifiers"] if s not in BIBLIOGRAPHIC_SCHEMES]
        return schemes[0] if len(schemes) == 1 else None
    if field == "url":
        # Only a link the document says came from the input is the input's url.
        return next((r["url"] for kind in ("url", "video")
                     for r in pub["links"].get(kind) or []
                     if r.get("origin") == "input"), None)
    if field == "year":
        return str(pub["year"])
    if field == "award":
        # The awards joined back as the field lists them; a demo award has no
        # year prefix, so each takes the work's year.
        assert all(a["year"] == pub["year"] for a in pub["awards"]), pub["awards"]
        return " and ".join(a["name"] for a in pub["awards"])
    return pub[field]


# Covers fields.demo_entry_type, types.incollection, types.inbook, types.book,
# types.manual
def test_demo_entries_keep_their_key_and_type(demo_document):
    """One work per demo entry, keyed and typed as the input wrote it."""
    _, doc = demo_document
    assert {key: kind for key, (kind, _) in demo_entries().items()} == {
        p["bib_id"]: p["entry_type"] for p in doc["works"]}


# Covers fields.demo_every_field, fields.editor, fields.month, fields.chapter,
# fields.isbn, fields.organization, fields.issn, fields.howpublished,
# fields.address, fields.series, fields.edition
@pytest.mark.parametrize("field", DEMO_FIELDS)
def test_demo_field_reaches_the_document(demo_document, field):
    """Every demo entry that writes ``field`` has it in the field's property:
    with the input's own value where the input wrote plain text, and present
    at all where the value carried LaTeX."""
    _, doc = demo_document
    carriers = {key: fields for key, (_, fields) in demo_entries().items()
                if field in fields}
    assert carriers, field
    wrong = {}
    for key, fields in sorted(carriers.items()):
        value = fields[field]
        got = reached(work(doc, key), field, fields)
        expected = value.lower() if field == "archiveprefix" else value
        if not got or (not LATEX.search(value) and got != expected):
            wrong[key] = (value, got)
    assert wrong == {}, field
