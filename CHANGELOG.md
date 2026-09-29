# Changelog

What changed, when, and what it replaced. [`SPEC.md`](SPEC.md) states the
current contract and nothing else; a behaviour that was superseded is
described here and not there.

Two version numbers move independently
([`SPEC.md` §6](SPEC.md#6-version-policy)): the document's `schema_version`,
whose releases are the git tags `schema-v4` and `schema-v5`, and the package
version, `sslabdata.__version__`. Entries are grouped by `schema_version`,
newest first, and the package release that ships them comes before all of
them. Numbers such as #101 are issue or pull request numbers in this repository.

## Package 3.1.0 (not yet released)

It emits `schema_version` 5, as 3.0.0 does.

- **A doubled spaced marker comes off.** `Brown\textsuperscript
  {*}\textsuperscript {*}, Bob` sets `equal_contribution` and reads `Bob
  Brown`, where it read `Bob Brown * *` with its stars split between the
  particle and the surname. A single spaced marker between a particle and
  the surname, `van\textsuperscript {*} Berg`, is joined the same way. Only
  `\textsuperscript` claims a `{*}` argument, as before (#53).
- **A command read from a `%` line is reported.** A well-formed `@article`,
  `@string` or `@preamble` on a line that starts with `%` between entries is
  still read, as BibTeX reads it, and now warns
  `BIB-COMMENTED-COMMAND-READ` with its line, so a user who meant to comment
  an entry out is told it was read. Under `--strict` the warning is an error.
  Prose on a `%` line still says nothing (#78).
- JSON Schemas for the input files, `lab.yaml`, `people.yaml`, `projects.yaml`
  and `collaborators.yaml`, at `schema/input/v1/`, versioned apart from the
  document ([`SPEC.md` §6](SPEC.md#6-version-policy)). The wheel installs them
  under `sslabdata/schema/input/v1/`, and an editor can name them to check
  and complete the files (#194).

## Package 3.0.0 (tag `v3.0.0`, 2026-09-28)

The first package release since `v2.0.0`, and the first on PyPI. It emits
`schema_version` 5 and carries the `schema_version` 4 and 5 changes and the
package changes below. The project is named `sslabdata`
(#82), and the Python API's `Publication` is `Work`. It requires Python 3.10 or
later. Its distribution metadata carries the README as the long description, an
MIT license expression and links to the specification, the changelog and the
issue tracker (#111). The wheel installs the current output schema, readable
as `sslabdata/schema/v5/output.schema.json` through `importlib.resources`; the
earlier schemas are not in the wheel, and their tagged URLs stay their access
path. The source distribution holds the package, `README.md`, `LICENSE`,
`SPEC.md` and every schema in `schema/`, and no tests (#112).

**Upgrading from 2.0.0.** Beyond the document's shape (`schema_version` 4 and
5 below), these changes can make a working 2.0.0 setup fail or behave
differently:

- **Names.** The distribution, the import package and the console command are
  `sslabdata`, not `labdata` (#84). `pip install sslabdata`, `import
  sslabdata`, and the command `sslabdata --config lab.yaml ...`.
- **Dependencies.** `bibtexparser` is replaced by `pybtex` and `pylatexenc`
  (#51). Several inputs 2.0.0 got wrong now convert correctly, among them
  `{\v c}`, `\&`, `---`, `Smith, Jr., John` and braced corporate names, so
  the emitted text of such works changes.
- **The Jekyll site is gone** (#73). sslabdata is the compiler only. The demo
  renderer is [sslabdata-site](https://github.com/siddhss5/sslabdata-site), and
  sslabdata ignores a `site:` section in `lab.yaml`.
- **Stricter input.** A configuration 2.0.0 accepted can now stop the run:
  - malformed input that ended in a traceback or was silently dropped is a
    coded, located diagnostic, and a `.bib` file that is not UTF-8 is fatal
    under `BIB-ENCODING-INVALID` (#94);
  - every configuration and record field has its YAML type checked, fatal at
    load under `CONFIG-TYPE-INVALID` in `lab.yaml` (#120);
  - a `bib_files` name that leaves `bib_dir`, by `..`, a drive or a symlink,
    is fatal under `CONFIG-BIB-FILE-OUTSIDE-BIB-DIR` (#122);
  - an unknown key in the people, projects or collaborators file is reported
    under `RECORD-KEY-UNKNOWN`, a warning that `--strict` makes an error (#103);
  - a value under `lab` that JSON cannot carry is fatal at load under
    `CONFIG-VALUE-NOT-JSON` (see below);
  - a key given twice in one YAML mapping, which 2.0.0 read as its last value,
    is fatal at load under `CONFIG-KEY-REPEATED` in `lab.yaml`, and fatal under
    `RECORD-KEY-REPEATED` in the people, projects or collaborators file (#145);
  - an empty `people_file`, `projects_file` or `collaborators_file`, which
    2.0.0 read as no file, is fatal under `CONFIG-FILE-NOT-FOUND`; only a key
    left out, or left with no value, means no file (#138);
  - a configured file path that is a directory or anything else that is not
    a regular file, or a `bib_dir` that is not a directory, is fatal under
    `CONFIG-PATH-WRONG-KIND` (#147).

  All three are under *Repeated YAML keys and configured paths* below.
- **New warnings.** Input that was read silently is now reported, and the run
  continues: a DOI that is only a resolver (`BIB-DOI-INVALID`), `and others`
  before the end of a name list (`BIB-OTHERS-NOT-LAST`), braces that merge or
  drop BibTeX fields (`BIB-BRACE-MISMATCH`) and control characters in any
  input (`TEXT-CONTROL-CHARACTER`). Each is a warning, and `--strict` makes it
  an error. `BIB-YEAR-INVALID` also covers years such as `-5` and `+2020`,
  which were read as numbers. They are described below.
- **Links.** A BibTeX `video` field is read as a video link (#105), and a `pdf`
  field as the work's PDF link, replacing the one guessed from `pdf_base_url`
  (#107). A `url` is a video link only when its parsed hostname is a video
  host or a subdomain of one, so `notyoutube.com` and `?next=youtube.com` are
  no longer videos (#123).
- **Author matching.** Run-together initials match like spaced ones: `S.S.
  Adams` and `S. S. Adams` are the same name (#83). How matching changed more
  broadly is under *Author matching reads the structured full name* below.
- **Output.** `--output` writes atomically: on any failure the file already
  there is left as it was, and no partial file is written (#124). A
  destination it cannot write is reported under `OUTPUT-WRITE-FAILED` (see
  *Values under `lab`* below). A missing `bib_dir` is reported once, under
  `CONFIG-FILE-NOT-FOUND` at `lab.yaml:bib_dir:`, and not once per `bib_files`
  name (#147).
- **`bibtex`.** Each field value in a work's `bibtex` is the value as it was
  read, byte for byte, so the record's text can differ from what 2.0.0 wrote
  (#154; see *`bibtex` holds each value as it was read* below).
- **Converted text is plain text.** `\url`, `\footnote`, citations, `\item`
  and similar commands no longer become Markdown or placeholder syntax, and
  the text argument of a formatting command such as `\texttt` is kept. See
  *Converter markup becomes plain text* and *Command arguments are kept*
  below.
- **Unicode.** Emitted text, including text converted from LaTeX, the
  citation keys and ids read from input, and every `collaborator_key` are in
  NFC, so input written with decomposed accents changes bytes, and it matches
  and groups as its precomposed spelling does. An initial whose mark has no
  precomposed form, `Q̇.`, is read as an initial (#185). A name in Hangul
  syllables keeps them in its `collaborator_key` rather than splitting them
  into conjoining jamo (#187).
- **Python API.** The elements of `AssemblyResult.diagnostics` and
  `AssemblyError.diagnostics` are `Diagnostic` dataclasses, not strings (see
  below).

## `schema_version` 5 (tag `schema-v5`, 2026-09-25)

Three changes, and nothing else in the document moves (#101):

1. **A project carries `image`.** `projects.yaml` accepts it, a URL or a site
   path, the same kind of value as a person's `photo`, and every project emits
   it, `null` when absent. It is plain text; deciding which URLs are safe to
   render is the renderer's job.
2. **`verification.checked_at` is removed.** Nothing produced it and it was
   always `null`. A link's `verification` is `{status}`.
3. **Counts that repeat the length of a list are removed:** `work_count` and
   `authorship_count` from collaborators, and `work_count` from people. A
   consumer reads `len(work_ids)` or `len(authorships)` instead.

A consumer that needs the v4 document pins `schema_version` 4 and the schema
at `schema/v4/output.schema.json`.

## `schema_version` 4 (tag `schema-v4`, 2026-09-21)

One consolidated breaking change (#56, #65, #71). Through commit `78570e6`,
the document's works were `publications`, the bibliography was one composed
`venue` string, links and identifiers were five flat `*_url` properties, and
an entry carrying `crossref` compiled with its parent's fields and none of its
own authors. From `schema_version` 4 the top level is `works`, the
bibliography is structured, `links` and `identifiers` are open registries,
`collaborators` is a declared grouping over unresolved authorships, and
`crossref` is rejected under `BIB-CROSSREF-UNSUPPORTED`. The package version
is 3.0.0, and `Publication` became `Work` in the Python API with it. A
consumer that needs the v3 document pins `schema_version` 3 and the schema at
`schema/v3/output.schema.json`.

**`collaborators` changed in four ways at once**, because the key changed: v3
grouped on the abbreviated display name, v4 on the normalised full name.

- Which authorships land together changed, and so did how many entries there
  are. The demo went from 7 to 9, one `P. Patel` group of four occurrences
  becoming `Priya Patel`, `Pradeep Patel` and `P. Patel`.
- The counts changed meaning as well as value: v3's `publication_count`
  counted occurrences, and v4 had both `work_count`, deduplicated per work,
  and `authorship_count` (v5 removed both).
- The displayed `name` expands, because it is the parts joined rather than the
  abbreviated form: `T. Turner` became `Trent Turner`.
- The order promised by [`SPEC.md` §3](SPEC.md#3-ordering) kept its rule,
  `last_year` descending, then work count descending, then `name`, with `key`
  appended after `name` because two keys can carry the same readable name.
  What moved in the list moved because the names and the groups moved.

**Every closed object declares every property it can carry.** Three
deviations from that existed through `schema_version` 3, each a bug against
the rule and not a second policy: `Person.to_dict()` omitted `photo`, `email`,
`co_advisor`, `start_year`, `publication_ids` and the alumni fields whenever
their value was falsy, and the alumni fields for anyone whose `status` was not
`alumni`; `Publication.to_dict()` omitted `bibtex` when the entry could not be
written back out as BibTeX; and `LabData.to_dict()` omitted top-level `lab`
when `lab.yaml` had no `lab` section, or an empty `lab: {}`, so a consumer
could not tell "no header" from "an empty header". In v4 every declared
property is present, `bibtex` is `null` when it could not be produced, and
`lab` is always emitted, `{}` when there is nothing in it. That changed the
schema's `required` lists and the nullability of the affected properties,
which is why it waited for the bump.

**`venue` is no longer composed.** Through `schema_version` 3, `format_venue()`
composed `venue` with Markdown emphasis, so an article in journal `J`
published in 2021 yielded `*J*, 2021`, the only place sslabdata generated
markup into a text field. v4 replaced it with a structured container and flat
bibliographic properties. #18 remains open for renderers: escaping,
attribute-safe escaping and the checks on rendered output.

**A work with no `year`** is `year: null` and sorts last, where it had been
`year: 0` at the same position. `null` is distinguishable from a genuine year
`0`, and the entry is reported under `BIB-YEAR-MISSING`.

**Consumer probes.** Under `schema_version` 3 none of the three consumer
probes in `examples/consumers/` could produce correct output. v4 closed every
gap but one: joining two spellings of one external co-author, which a grouping
keyed on a name cannot do by construction (#24). Until then the probe's
assertion for it was an `xfail(strict=True)` naming that issue. It passes
since `collaborators_file` can declare the alias.

## Package changes that did not change `schema_version`

A resolver correction, or a change to what a run reports, is a package-level
behaviour change and not a schema bump (see [what a schema version
freezes](SPEC.md#what-a-schema-version-freezes-and-what-it-does-not)). The
entries below are those.

### Author matching reads the structured full name (#24)

Through commit `eec03e6`, every author was abbreviated to initials before
matching (`match_form()`), so a full name could resolve to whoever declared
the abbreviation, and a near miss on string similarity was linked with
`method: fuzzy`. Since #24, matching reads the structured full name first and
the abbreviated form only where the input itself is abbreviated; a name that
fits more than one person gets `resolution.status: ambiguous` and no
`person_id`, a near miss is reported under `RESOLVE-SUGGESTION` and never
linked, and `collaborators_file` can join the spellings of one external
co-author, as `grouped_by: declared`. `schema_version` stayed 4: the shape,
namespace and meaning of `person_id` are unchanged, and `ambiguous` and
`declared` are new members of open strings.

In the valid corpus six `person_id` values moved:

- `name-kim-alan` from `akim` to `alankim`;
- `name-kim-initial` from `akim` to null;
- `id-full-name` from null to `ffischer`;
- three near misses that had been linked by fuzzy matching and now are not:
  `id-fuzzy` author 1 (`Davis, Dave M.`), `name-equal-normalized` author 4
  (`Davis{*}`) and `name-equal-escaped` author 2 (`Davis\^{*}`), each from
  `ddavis` to null.

That moved works from `akim` to `alankim` and away from `ddavis`, removed the
`Frank Fischer` collaborator, and added three: `A. Kim`, `Dave M. Davis`, and
one grouping the two starred Davis spellings, which normalise alike. In the
demo no `person_id` moved; it now declares `P. Patel` as an alias of `Priya
Patel` in `examples/demo/collaborators.yaml`, so `P. Patel` joins her grouping
and the `P. Patel` collaborator is gone. Exit codes were unchanged.

`RESOLVE-AMBIGUOUS-NAME` was narrowed at the same time (#26 decision 6): it
had also covered an unresolved authorship that fits a declared collaborator
and someone else, which is now `ID-GROUPING-AMBIGUOUS-DECLARED`. No release
carried the wider meaning.

### Diagnostic codes, `--strict` and JSON diagnostics (#26)

- Duplicate citation keys were invisible through commit `dd06e37`: the parser
  library kept the first entry, and a key repeated across two configured files
  passed `--validate` with exit `0`. Since #64, `parse_all_works()` reports
  each duplicate under `BIB-DUPLICATE-KEY`, `--validate` exits `1`, and the
  other modes emit the same diagnostic as a warning and continue. The code was
  introduced as `E-BIB-DUPLICATE-KEY` and renamed to drop the severity prefix
  before any release: severity is not part of a code.
- `--strict` and `--format json` with `--validate` or `--unresolved` were
  added (#79). The decision that an author who matched no lab member is never
  an error under `--strict` is #26 decision 10.

### `--unresolved` with no `people_file` (#22)

Through commit `cf9e055`, `--unresolved` printed `All authors resolved.` when
no `people_file` was configured, where nothing had been attempted. Since #61
it prints `Author resolution is not configured (no people_file).` and exits
`0`.

### A bare `%` in a field value is kept (#133)

Before 3.0.0 the LaTeX converter read a bare `%` inside a braced field value
as the start of a comment, so everything after it was silently dropped: `50%
faster robots` was emitted as `50`, and an abstract or a `\url` stopped at its
first `%`. A bare `%` is now a literal percent sign, as it is to BibTeX, and
`\%` is unchanged. Only works containing a bare `%` emit different text. In
math, a bare `%` is written back as `\%`, as a bare `&` already was.

### Converter markup becomes plain text (#18)

Some LaTeX commands were converted to syntax rather than text: `\url{u}` to
the autolink `<u>`, `\footnote{n}` to `[n]`, citations and cross-references
to `<cit.>` and `<ref>`, a list `\item` to a Markdown `* ` bullet,
`\includegraphics` and `\maketitle` to placeholder blocks, and
`\textfrac{a}{b}` to `%s/%s` followed by its arguments. Each now becomes
plain text or nothing, as [`SPEC.md` §2](SPEC.md#2-the-text-rule) lists:
`\url{u}` is `u` exactly as written (a `~` in it is no longer a no-break
space), a footnote is written in parentheses, `\item` starts a line
with `•`, `\textfrac{a}{b}` is `a/b`, and the rest are left out. Only works
whose converted fields use one of these commands emit different text.

### Command arguments are kept (#169, #174, #176)

Before 3.0.0 three kinds of command lost text that followed them:

- About 90 commands that pylatexenc parses with arguments but has no text rule
  for were reported under `LATEX-COMMAND-UNKNOWN` and dropped together with
  their arguments, so `\texttt{abc} d` read ` d`.
- `\newcommand`, `\renewcommand`, `\providecommand`, the environment
  definitions and `\DeclareMathOperator` read the text after them as their
  arguments, so part of it was lost: `\newcommand zqx Tidy Robots` read `x
  Tidy Robots`.
- `\title`, `\author` and `\date` dropped their argument with no diagnostic.

Each such command now falls into one of three groups, which
[`SPEC.md` §2](SPEC.md#what-sslabdata-converts-and-what-it-does-not) lists: a
formatting or box command, and `\title`, `\author` and `\date`, keep their
argument as text and are not reported; a citation, label, cross-reference or
setting such as `\color` is dropped with its arguments and not reported; and
any other command is reported under `LATEX-COMMAND-UNKNOWN`, dropped, and the
text after it, braced arguments included, is kept. Only works whose converted
fields use one of these commands emit different text.

### `bibtex` holds each value as it was read (#154)

The package's BibTeX writer encoded every field value as LaTeX again, so
`\%`, `\&`, `\_` and `\#` gained a second backslash and a bare `%`, `&`,
`_` or `#` gained one: the demo's `87\%` was emitted as `87\\%`. Each field
value in `bibtex` is now the value the entry was read with, byte for byte
([`SPEC.md` §5](SPEC.md#5-input-versus-derived)). Field order, quoting and
layout are unchanged, and `BIB-WRITE-BACK-FAILED` is reported as before.

### Years, DOIs, repositories and `and others` (#135, #136, #137, #146)

- **Year.** A `year` is read only from an unsigned run of the ASCII digits
  0-9. `-5`, `+2020`, `2_020` and full-width `２０２０` were read as numbers;
  each is now reported under `BIB-YEAR-INVALID` and emitted as `year: null`,
  as `in press` already was.
- **DOI.** A `doi` that is only a resolver, such as `https://doi.org/`, gave an
  empty DOI. It is now reported under the new `BIB-DOI-INVALID`, a warning, and
  the work gets no DOI identifier and no `doi` link. An empty `doi` is still
  read as absent and not reported.
- **Repository.** `eprinttype` is read as an alias of `archivePrefix`, which
  wins when both are written, and both are converted from LaTeX before they
  are matched. An `eprint` with `eprinttype = {hal}` had been filed under
  arXiv, and `archivePrefix = {{arXiv}}` now reads as `{arXiv}` does. arXiv
  is still the default when neither is written.
- **`and others`.** One anywhere but at the end of an `author` or `editor`
  list was read as an author named `others`. It is now dropped, as a trailing
  one is, and reported under the new `BIB-OTHERS-NOT-LAST`, a warning, once
  per list. A trailing `and others` is dropped with no diagnostic, as before.

### Control characters and brace mismatches (#165, #170)

- **Control characters.** A C0 control character other than tab, line feed
  and carriage return, or DEL, was kept in the text it was read with. It
  could make a field fall back under `LATEX-CONVERSION-FAILED` or a name fail
  to resolve. It is now removed where the input is read, from every `.bib`
  field value and every YAML scalar, and reported under the new
  `TEXT-CONTROL-CHARACTER`, a warning, once per value
  ([`SPEC.md` §2](SPEC.md#2-the-text-rule)).
- **Brace mismatches.** One opening brace too many reads the next field into a
  value, and one closing brace too many ends the entry early, so the fields
  after it are lost. Both happened silently. The entry is still read as
  BibTeX reads it, and is now reported under the new `BIB-BRACE-MISMATCH`, a
  warning, once per entry. An entry that already has a `BIB-SYNTAX-ERROR` is
  not checked.

### Values under `lab`, `--validate`, and output write failures (#121, #134, #142)

Before 3.0.0, `lab` was copied into the document unchanged, and three problems
followed from that:

- **Dates.** An unquoted date such as `founded: 2010-01-01` crashed JSON
  export with a traceback, even though `--validate --strict` had passed.
- **NaN.** `.nan` was written into JSON output as `NaN`, which is not JSON.
- **Other YAML types.** A set or binary value was written into YAML output
  with Python-specific tags.

Now every value under `lab` and `lab.links`, at any depth, follows one rule.
A date or timestamp is emitted as ISO 8601 text in both formats. NaN, the
infinities, sets, binary values, any other type JSON cannot carry, and a
mapping key that is not a string are refused, fatal at load under
`CONFIG-VALUE-NOT-JSON` and located at `lab.yaml:lab:<path>`. The last of
these can reject a `lab.yaml` that 2.0.0 exported, for example a year used as
a key.

`--validate` now builds the document in memory, in `--format`, with the same
code `--output` writes it with, so it cannot pass a document that `--output`
would refuse. A destination `--output` cannot write, such as a directory, a
path under a file, or a directory without permission, is reported under
`OUTPUT-WRITE-FAILED` with exit `1` instead of a traceback, and the file
already there is left as it was. `OUTPUT-WRITE-FAILED` is fatal.

### Repeated YAML keys and configured paths (#138, #145, #147)

- **Repeated keys.** YAML reads a key given twice in one mapping as its last
  value, and that is what sslabdata did, silently dropping the first. Every
  YAML file is now read with a loader that reports it. In `lab.yaml` it is
  fatal at load under `CONFIG-KEY-REPEATED`, and the first repeat is
  reported; in the people, projects or collaborators file it is fatal under
  `RECORD-KEY-REPEATED`, every repeat is reported, and the record is not
  loaded. A merge key (`<<`) is not a repeat.
- **Empty data-file paths.** An empty `people_file`, `projects_file` or
  `collaborators_file` was read as no file. It is now fatal under
  `CONFIG-FILE-NOT-FOUND`. A key left out, or YAML null, still means no file.
- **Paths of the wrong kind.** A configured file that was a directory was
  reported under `CONFIG-FILE-NOT-FOUND` as not existing. A `bib_files` name,
  `people_file`, `projects_file` or `collaborators_file` that is not a regular
  file, or a `bib_dir` that is not a directory, is now fatal under the new
  `CONFIG-PATH-WRONG-KIND`. A missing `bib_dir` is one `CONFIG-FILE-NOT-FOUND`
  at `lab.yaml:bib_dir:`, where it had been one per `bib_files` name.

Where each is located is in
[`SPEC.md`, *Diagnostic codes*](SPEC.md#diagnostic-codes).

### Diagnostics in the Python API are dataclasses (#141)

A diagnostic was a `str` subclass with its parts attached as attributes, so
a caller could use it as text. It is now a frozen dataclass with `code`,
`file`, `key`, `field` and `message` fields. `str()` of one gives exactly the
line the CLI prints, and a code missing from the registry is refused when the
diagnostic is built. A caller that tested a diagnostic as text, such as
`"BIB-" in d`, now reads `d.code` or `str(d)`. The CLI's text and JSON output
are unchanged.

### Rename to `sslabdata` (#82)

The project was called `labdata`. The v3 and v4 schema files were published
before the rename, so their `$id`s, titles and descriptions still say
`labdata`, and they are left byte for byte as published. v5 is the first
schema published under the new name.

## `schema_version` 3 and earlier

| `schema_version` | Change |
|---|---|
| 1 | The original document. |
| 2 | Authors carry their structured name parts (#23). Breaking: the object is closed, so a v1 consumer rejects the new keys. |
| 3 | Authors carry `equal_contribution` (#46). Breaking, for the same reason. |

Package `v2.0.0` (2026-02-15) is the last tag before the schema was versioned
in this repository.
