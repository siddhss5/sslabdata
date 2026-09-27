# sslabdata

sslabdata compiles BibTeX and a little YAML into one schema-specified document —
works, people, projects and the links between them — that any website, CV or
script can read.

Most academics already keep good BibTeX. What they do not have is that
bibliography as *data*: authors linked to the people in the group, papers
linked to the projects they belong to, names normalised, LaTeX resolved to
plain Unicode text. sslabdata does that one job and writes the result to a
single YAML or JSON file, specified by a published JSON Schema you can check
it against.

```bash
sslabdata --config lab.yaml --output lab.yml
```

- [`SPEC.md`](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md) — the normative contract: what the strings are, what
  order the lists are in, which fields are derived, when the version changes.
- [`CHANGELOG.md`](https://github.com/siddhss5/sslabdata/blob/main/CHANGELOG.md) — what changed at each release, and what it
  replaced.
- [`schema/v5/output.schema.json`](https://github.com/siddhss5/sslabdata/blob/main/schema/v5/output.schema.json) — the
  document's JSON Schema. Published versions are immutable and live at their
  own paths; [`schema/v3/`](https://github.com/siddhss5/sslabdata/blob/main/schema/v3/output.schema.json) and
  [`schema/v4/`](https://github.com/siddhss5/sslabdata/blob/main/schema/v4/output.schema.json) are still there.
- [`tests/COVERAGE.md`](https://github.com/siddhss5/sslabdata/blob/main/tests/COVERAGE.md) — every input case sslabdata
  supports, and every case it does not, with the fixture and test for each.

## What sslabdata is not

**sslabdata is not a CMS and not a site generator.** It does not build a
website, own your pages or manage your content. News, openings, teaching
pages, press and galleries are prose with no shared structure to compile, and
they belong in your site repository. [`SPEC.md` §8](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#8-the-entity-boundary-and-the-evidence-for-it) gives the
evidence for that boundary and the destination for each content type it
leaves out.

sslabdata emits data. Rendering it is your renderer's job.

## Install

```bash
pip install sslabdata
```

To work on sslabdata itself, install from a clone instead:

```bash
git clone https://github.com/siddhss5/sslabdata.git
cd sslabdata
pip install -e ".[test]"
pytest
```

The `test` extra installs `pytest` and `jsonschema`, which the tests need.

## Write `lab.yaml`

```yaml
lab:
  name: "My Lab"
  description: "What our lab does"
  university: "University Name"
  website: "https://mylab.example.org"

bib_dir: "data/bib"
bib_files:
  - name: "journal.bib"
    category: "Journal Papers"
  - name: "conference.bib"
    category: "Conference Papers"

pdf_base_url: "https://mylab.example.org/pdfs"
people_file: "data/people.yaml"       # optional
projects_file: "data/projects.yaml"   # optional
collaborators_file: "data/collaborators.yaml"  # optional
```

Each `bib_files` entry's `name` is a name under `bib_dir`: it is emitted as
the work's `source.file`, so it may be neither absolute nor leave `bib_dir`,
and sslabdata rejects such a name rather than rewriting it
([`SPEC.md` §5](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#5-input-versus-derived)).

Paths are relative to the directory you run `sslabdata` from.
[`examples/demo/lab.yaml`](https://github.com/siddhss5/sslabdata/blob/main/examples/demo/lab.yaml) is a complete example,
built from the fictional Example Lab in [`examples/demo/`](https://github.com/siddhss5/sslabdata/tree/main/examples/demo/).

Then compile it:

```bash
sslabdata --config lab.yaml --validate            # report counts and problems
sslabdata --config lab.yaml --unresolved          # list unmatched author names
sslabdata --config lab.yaml --output lab.yml      # write the document
sslabdata --config lab.yaml --format json --output lab.json
sslabdata --config lab.yaml --validate --strict   # fail on every problem
sslabdata --config lab.yaml --validate --format json   # problems as JSON
```

`--validate` exits `0` when it finds no errors and `1` when it does, or when
the run fails outright. An author who matched nobody is reported but is not an
error; most are external collaborators. It checks the configuration, the
people and projects files and every entry, not the output against the JSON
Schema. Every problem is reported under a stable code.

`--strict` turns every coded problem into an error, except those about
authors who matched no lab member and redefined `@string` macros; an error
exits `1` and an export then writes nothing. With `--validate` or
`--unresolved`, `--format json` prints the problems as one JSON array on
standard output. [`SPEC.md` §1](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#1-contract-hierarchy) owns the flags,
exit codes, streams and precedence when you pass more than one mode, the
[diagnostic codes](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#diagnostic-codes) with their classes, and the
[JSON shape](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#diagnostics-as-json).

## Inputs

### BibTeX (required)

Standard `.bib` files. These are the fields sslabdata interprets. A field not
listed here is carried through in `bibtex` but is not interpreted and affects
nothing else:

| Field | Becomes |
|-------|---------|
| `title` | `title`, LaTeX converted to plain Unicode text; `$...$` math kept as TeX |
| `author` | `authors`, one authorship per name, each with its `position`, a readable `name`, its `given` / `von` / `family` / `suffix` parts (or `literal` for a brace-protected name), `equal_contribution`, a `resolution` record, and exactly one of `person_id` and `collaborator_key` |
| `editor` | `editors`, read by the same machinery. Editing a volume is not an authorship: editors are in nobody's `work_ids` and produce no collaborator |
| `year` | `year`, and the sort order of the works list. `null`, with a diagnostic, when the entry has none |
| `journal` / `booktitle` / `school` / `institution` | `venue`, as `{kind, name}` — the one place sslabdata normalises across entry types. `null` when the entry names no container |
| `volume`, `number`, `pages`, `series`, `edition`, `publisher`, `address`, `organization`, `chapter`, `month`, `howpublished`, `type` | Properties of the work, under BibTeX's own names and with BibTeX's own meanings |
| `doi`, `isbn`, `issn`, `eprint` + `archivePrefix` (or `eprinttype`) | `identifiers`, an open map from scheme to a list of identifiers, plus the links built from them. An `eprint`'s scheme is the repository `archivePrefix` or `eprinttype` named, lower-cased, so that field needs no property of its own — and an `eprint` in a repository other than arXiv gets no arXiv link |
| `abstract` | `abstract` |
| `note` | `note` |
| `url` | A link of kind `video` when its host is YouTube or Vimeo (or a subdomain of either), otherwise of kind `url` |
| `video` | A link of kind `video`, whatever its host, so `url` can hold the work's website |
| `pdf` | The work's one link of kind `pdf`. An entry without it gets `pdf_base_url` plus its citation key, when `pdf_base_url` is set |
| `project` | `project_ids` (see below) |
| `crossref` | **An error**: the field is rejected, not resolved, and the run fails. Write the fields out on the entry itself |

The entry is also re-serialized into a `bibtex` field, so fields sslabdata does
not interpret are still carried. It is a re-serialization, not a copy
([`SPEC.md` §5](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#5-input-versus-derived)).

### The `project` tag

sslabdata adds one custom BibTeX field, `project`, to link a paper to a research
project:

```bibtex
@inproceedings{cote2024pantry,
  title     = {Where Does This Go? Object Placement in Unfamiliar Kitchens},
  author    = {C{\^o}t{\'e}, Carol and Davis, Dave and Adams, Alice},
  booktitle = {Proceedings of the Conference on Robot Learning Systems},
  year      = {2024},
  eprint    = {2406.99812},
  archivePrefix = {arXiv},
  project   = {homebot}
}
```

Several projects go in one field, comma-separated:
`project = {homebot, sharedcontrol}`. Each project in the document then
back-links the works tagged with it, and the people who wrote them.

### People (optional, `data/people.yaml`)

A list of lab members and alumni. `aliases` tells sslabdata how to match BibTeX
author names to people:

```yaml
- id: "bbrown"
  name: "Bob Brown"
  aliases: ["B. Brown"]
  role: "phd_student"
  status: "current"
  website: "https://example.org/people/bbrown"
  co_advisor: "Peggy Park"
  start_year: 2021

- id: "iingram"
  name: "Ivan Ingram"
  aliases: ["I. Ingram"]
  role: "phd_student"
  status: "alumni"
  start_year: 2016
  end_year: 2022
  degree: "PhD"
  thesis_title: "Learning Grasp Affordances from Play"
  current_position: "Research Scientist, Example Robotics Inc."
```

`id` and `name` are required. `role` is any non-empty string, so any lab's
roles fit; `status` is `current` (the default) or `alumni`.

### External co-authors (optional, `data/collaborators.yaml`)

A list of co-authors outside the lab whose spellings you want grouped
together. It only decides which authorships share one `collaborators`
entry; it never makes anyone a lab member and never produces a `person_id`:

```yaml
- name: "Priya Patel"
  aliases: ["P. Patel"]
```

`Patel, Priya` and `Patel, P.` are then one collaborator, with
`grouped_by: declared`. A different `Patel, Pradeep` is not joined, because
nothing declares him. A name or alias that a lab member already declares is
reported under `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER` and left to the member.

### Projects (optional, `data/projects.yaml`)

```yaml
- id: "homebot"
  title: "Household Manipulation"
  description: "Robots that tidy up, fetch things and put them away in real homes."
  website: "https://example.org/projects/homebot"
  image: "images/projects/homebot.jpg"
  status: "active"
```

`id` and `title` are required; `status` is `active` (the default) or
`completed`. `image` is a URL or a site path, the same kind of value as a
person's `photo`, and is `null` when absent. It is carried as plain text:
deciding which URLs are safe to render is the renderer's job.

## How author matching works

sslabdata matches the structured parts of each BibTeX author name (given, von,
family, suffix) to lab members: first on the full name against each person's
`name` and any alias written in full, then, only when the name is itself
abbreviated, on a declared alias. Nothing is guessed. A name that fits more
than one person gets no `person_id` and is reported under
`RESOLVE-AMBIGUOUS-NAME`; a near miss is never linked and is reported under
`RESOLVE-SUGGESTION` with the ids it might be. Both are warnings, so
`--validate` lists them and still exits `0`. To resolve one, add the spelling
to that person's `aliases`. [`SPEC.md`](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#how-a-name-is-matched) gives
the normalisation and the order the match decides in.

A name that matches nobody keeps `person_id: null` and its authorship
references a `collaborators` entry instead, by `collaborator_key`.
`sslabdata --config lab.yaml --unresolved` lists those names so you can add
aliases — or, if you have configured no `people_file`, tells you resolution
was never attempted.

`collaborators` is a grouping over unresolved authorships, not a list of
humans, and its `key` is a lookup key, not an identity. The grouping can be
wrong in both directions, so sslabdata reports a key that spans more than one
spelling and an initials-only key that could be any of several fuller ones,
and `collaborators_file` lets you join spellings yourself. What the grouping
does and does not promise is in
[`SPEC.md` §5](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#5-input-versus-derived).

## Reading the document

The output is one YAML or JSON file. Strings in it that are meant for display
are plain Unicode text: not HTML, not Markdown, not escaped. They are
untrusted, and a title really may contain `<`, `&`, `"` or `*`, so **escape
them when you render them**. Math is the one markup exception and stays
delimited by `$…$`. `bibtex`, identifiers and URLs are not display text.

sslabdata enforces that rule only where it converts LaTeX from BibTeX. Strings
you supply directly in YAML, and everything under `lab`, are copied through as
written and never checked, so keeping them plain is on you.
[`SPEC.md` §2](https://github.com/siddhss5/sslabdata/blob/main/SPEC.md#2-the-text-rule) draws the line precisely.

Validate a document against the schema with any JSON Schema tool. sslabdata
does not do this for you, and does not depend on a validator — `jsonschema`
is a test-only dependency, so install it first. The installed package carries
the current schema:

```bash
pip install jsonschema
python -c "
import json, yaml, jsonschema
from importlib.resources import files
schema = json.loads(files('sslabdata.schema').joinpath('v5/output.schema.json').read_text())
jsonschema.Draft202012Validator(schema).validate(yaml.safe_load(open('lab.yml')))
print('valid')
"
```

## Python API

The CLI is the reference compiler. The Python API is a convenience wrapper
over the same pipeline:

```python
from sslabdata import LabDataConfig, assemble, export_to_yaml

config = LabDataConfig.from_yaml("lab.yaml")
data = assemble(config)

export_to_yaml(data, "lab.yml")

for work in data.works:
    authors = ", ".join(a.name for a in work.authors)
    print(f"{work.title} ({authors})")
```

Public: the names exported from `sslabdata/__init__.py`. Everything else —
`sslabdata.parsers`, `sslabdata.loaders`, `sslabdata.resolver` — is private and may
change without a version bump.

## The demo renderer

[sslabdata-site](https://github.com/siddhss5/sslabdata-site) renders the Example
Lab document as a website ([what it looks like](https://siddhss5.github.io/sslabdata-site/)).
It is an **optional downstream consumer**, not part of sslabdata and not part of
what sslabdata promises; it installs sslabdata from a pinned tag or commit and keeps its own
copy of the demo. sslabdata ignores a `site:` section in `lab.yaml`, so a
renderer can keep its own settings there.

### Before a release (maintainers)

These steps are run from a clone: `tools/` is not in the published package.
Before publishing a sslabdata release, build sslabdata-site against the candidate:
run its **Release gate** workflow with the candidate's git ref as
`sslabdata_ref`. It builds without deploying, and keeps the renderer's toolchain
out of this repository's CI.

Also run the smoke check over real, messy bibliographies. It compiles each
`.bib` file under a directory on its own. It must report no crashes and no
uncoded lines. Review any LaTeX remnants it lists. A local TeX Live installation
has a directory of such files. Nothing is fetched, and nothing from it is
committed. It is not in CI because it needs TeX:

```bash
uv run python tools/smoke.py /usr/local/texlive/2025/texmf-dist/bibtex/bib
```

## Dependencies

- **pybtex** — BibTeX parsing
- **pylatexenc** — LaTeX to Unicode text
- **pyyaml** — YAML I/O

No network calls. All processing is local and offline.

## License

MIT License. Copyright (c) 2024 Personal Robotics Laboratory, University of Washington.
