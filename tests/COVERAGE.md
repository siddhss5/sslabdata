# Supported cases

Every case sslabdata supports, and every case it does not, with the fixture that
holds the input and the test that checks the behavior. The corpus is fictional
throughout (`tests/corpus/`); no real lab data is used anywhere.

## How to read this table

| Column | Meaning |
|---|---|
| Case | A stable ID. Fixtures mark it with `% CASE <id>` in a `.bib` file, or `# CASE <id>` in a YAML file. |
| Input | The input form, as it appears in the fixture. |
| Expected | What sslabdata is expected to do with it. |
| Fixture | The file holding the input. |
| Test | The assertion. `tests/conformance/` runs sslabdata only through `cli.main()` and the assembler. |
| Status | `pass` today, or `xfail #N` when the row describes behavior that issue #N still has to deliver. |

Input sslabdata does not support has a row too, and its expected behavior is a
warning or an error. Silently ignoring an input is never correct.

This table is kept by review. The one automatic check,
`test_coverage_table.py`, fails if a case ID appears twice, if a row's ID is
missing from the fixture it names (a fixture outside `tests/corpus/` only has
to exist), if a test named in the Test column is not defined in that file, or
if the ID appears in no test file and not in
`tests/corpus/expected/diagnostics.yaml`. Whether the test really checks what
the row claims, and whether the status column is current, is for review to
judge. `xfail` markers are `strict=True` and name their issue in the reason,
so a case turns red once the issue is fixed and the marker is stale.

## Conformance results

Each fixture in `tests/corpus/invalid/` has one entry in
`tests/corpus/expected/diagnostics.yaml` (its header defines the fields): the
exit status, every diagnostic with its code, severity and location, and every
work the document keeps. `test_invalid_corpus.py::test_outcome` runs the
fixture once per mode (`--validate`, `--unresolved`, `--output`) and once
through the Python API and compares all of it with that entry exactly in each
mode: an extra, repeated or missing diagnostic or work fails.

Those runs are also written out as the conformance-results artifact, a JSON
file with one entry per case, in a stable order and free of timestamps, paths
and host data. To reproduce it, from the repository root:

```
SSLABDATA_CONFORMANCE_RESULTS=conformance-results.json \
  uv run --frozen --extra test pytest --no-cov tests/conformance/test_invalid_corpus.py
```

`pytest` is in the optional `test` extra, so a bare `uv run pytest` fails in a
clean environment. `--no-cov` is needed too: the repository always enables
coverage with a 92% floor, which this one file does not reach, so without it
the command exits 1 although every test passes and the artifact is written.

The file is replaced atomically, only once every case has run, and it is the
same on every host, so `sha256sum` of two runs is the way to compare them. CI
gets it by setting the variable on its pytest step. A reviewer reads the
observed outcome of a case under its ID, and compares it with the expected
entry of the same ID.

Cases that fail today are not fixed here (that is the linked issue's job):
#20 (verifying a remote link), #27 (explicit link and award fields), #28
(`keywords` project tags).

## Generated inputs

The rows below pin the cases someone thought of.
`tests/conformance/test_generated_inputs.py` explores the values nobody wrote
down. From a fixed seed it generates `.bib` entries and `lab.yaml`, people,
projects and collaborators files: every special character (`% & # _ $ ~ ^ \
{ }`), escaped and bare, unbalanced braces, known and unknown LaTeX commands,
`\url` and `\href`, math, Unicode with combining marks, right-to-left and
zero-width characters, empty and whitespace-only values, malformed years,
DOI and URL shapes, `eprint` with `archivePrefix` and `eprinttype`, author
lists with `and others` anywhere, `{literal}` names, `Jr.` and von parts,
repeated citation keys, `lab` values YAML types JSON cannot carry, and
repeated YAML keys. About a third of the cases draw every configuration
value from that range. The rest keep the configuration well formed, so that
the run writes a document and the `.bib` values can be checked in it.

Each input runs through `cli.main()` in four modes: `--validate` and
`--output`, each in YAML and in JSON. Every input must keep these
invariants:

1. No run raises an uncaught exception.
2. A run that exits 0 writes a document that validates against
   `schema/v5/output.schema.json`, and the YAML and JSON documents hold the
   same data.
3. A run that exits 1 reports at least one coded error.
4. `--validate` exits 0 only where `--output` in the same format writes.
5. No text is lost silently. A sentinel word follows the special characters
   in each generated value, and some values hold one as the braced argument
   of a LaTeX command: a formatting command such as `\texttt` or `\mbox`, a
   command whose arguments are not text such as `\label`, `\color` or
   `\setcounter`, or a generated unknown name. Every word must reach the
   work's `bibtex`, and `bibtex` must carry each field value as it was
   written. Every word must reach the value's place in the document too,
   except one inside a command that §2 of SPEC.md turns into nothing: a
   citation, label or cross-reference, a setting, or `\includegraphics`.
   The test writes these out as `DROPS_ARGUMENT`, with the number of
   arguments each takes, rather than importing them, so that the list
   checks the code. An unknown command keeps its braced argument as text
   (`LATEX-COMMAND-UNKNOWN`). A URL inside `\url` or `\href` must reach the
   text unchanged. A value can lose text only with a coded diagnostic that
   explains the loss at its entry, or a syntax error in its file.
6. No input is silently read as something else. A year that is not an
   unsigned run of ASCII digits is never a number. An `eprint` is filed
   under the repository its entry names, and arXiv only when it names none.
   `others` is never an author. An empty `*_file` path, a repeated YAML key
   and a path that is a directory are each reported. LaTeX conversion does
   not add `<`, `>`, `[` or `]` that the source did not have.

A failure is grouped by the invariant and the kind of value that broke it.
Each group is then reduced: parts of the input are removed one at a time
while the failure persists. When one group has several causes, each one is
reduced separately, up to six per group. The reduced input is small enough
to become a corpus fixture.

To reproduce, from the repository root:

```
SSLABDATA_GENERATED_FAILURES=generated-failures.json \
  uv run --frozen --extra test pytest --no-cov tests/conformance/test_generated_inputs.py
```

The default is 1000 inputs and runs in well under a minute.
`SSLABDATA_GENERATED_CASES=3000` runs a longer search. The first 1000 of
those inputs are the default ones, because each input is seeded by its
index. The artifact is a JSON file. Each entry of its `failures` gives:

- the class;
- the index of the first input that showed the failure;
- a detail line;
- the reduced `input`, as file paths and their text, beside the
  `directories` every case also has;
- each mode's exit status, crash and coded lines;
- the `--validate --format json` diagnostics.

The artifact is written atomically, holds no paths or times, and is the
same on every host, so two runs can be compared with `sha256sum`. To turn a
failure into a fixture, write each `input` file into a directory under
`tests/corpus/invalid/`, create the listed directories, and give the case
an entry in `tests/corpus/expected/diagnostics.yaml`.

The test is expected to fail until the issues it finds are fixed. It is not
marked `xfail`, because a failure names the bug, and the reduced input is
the fixture for its fix.

## `@string` macros and BibTeX structure
Rule: when a macro is defined more than once, **the last definition wins**, as
in BibTeX itself. `strings.bib` defines `rss`, `cfx` and `jfx` twice each, and
the second definition is the one that reaches the output.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `strings.macro` | `booktitle = rss`, with `@string{rss = ...}` | The macro is expanded into the venue | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_strings` | pass |
| `strings.repeat_last_wins` | `rss` defined twice | The last definition is used; the first never appears in the output | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_strings` | pass |
| `strings.redefined_report` | Three macros redefined in one file | One summary message names all three | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_redefined_strings_reported_once` | pass |
| `strings.defined_once` | A macro defined exactly once | Expanded like any other; no message mentions it | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_macro_defined_once_is_not_reported` | pass |
| `strings.concat` | `"Joined " # "Title"` and `"Proceedings of the " # cfx` | The parts are concatenated, macros expanded | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_strings` | pass |
| `strings.macro_journal` | `journal = jfx # " Letters"` | The journal is the expanded macro plus the literal suffix | `tests/corpus/valid/strings.bib` | `test_valid_corpus.py::test_strings` | pass |
| `strings.undefined` | `booktitle = nosuchmacro`, which no `@string` defines | Warning naming the file, key, field and macro; the entry and its neighbours are kept | `tests/corpus/invalid/undefined_string/macro.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.comment_lines` | A `%` comment line between entries | Ignored; the entries around it are read | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_comments_and_preamble_are_not_works` | pass |
| `structure.comment_entry` | `@comment{...}` wrapping something that looks like an entry | Not a publication; the entries around it are read | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_comments_and_preamble_are_not_works` | pass |
| `structure.preamble` | `@preamble{"..."}` | Not a publication; the entries around it are read | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_comments_and_preamble_are_not_works` | pass |
| `structure.comment_mentions_command` | A `%` comment line whose prose contains `@comment{` | Ignored; it is not read as a command, and the entry after it is read | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_comments_and_preamble_are_not_works` | pass |
| `structure.comment_mentions_unclosed_group` | A `%` comment line whose prose contains `@comment{` and then a `{` that never closes | Not a comment group: the entry after it is read, and nothing is reported | `tests/corpus/invalid/comment_prose_unclosed_brace/prose.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.uppercase` | `@ARTICLE` with `TITLE`, `AUTHOR`, `JOURNAL`, `YEAR` | Read exactly as the lower-case spelling is | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.value_quoted` | Field values in `"quotes"` | Read like braced values | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.value_braced` | Field values in `{braces}`, including a doubly braced title | Read; the braces themselves never reach the output | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.value_numeric` | Unquoted numeric `year`, `volume`, `number` | Read like quoted values | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.proceedings` | An ordinary `@proceedings` entry that nothing cross-refers to | Read like any other entry: its own year, author and booktitle | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.crossref` | An entry carrying a `crossref` field | Error: stable `BIB-CROSSREF-UNSUPPORTED` names the file, the citation key and the parent key, and the run exits non-zero in every mode. The entry is not emitted | `tests/corpus/invalid/crossref_entry/crossref.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.crossref_undefined_parent` | A `crossref` naming an entry that does not exist | The same error, not a milder one | `tests/corpus/invalid/crossref_undefined_parent/crossref.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.crossref_no_parent` | A `crossref` field with no parent key in it, written empty and written as whitespace | The same error: the field is rejected on its presence, not on its value, and the diagnostic says the entry names no parent rather than quoting a blank one | `tests/corpus/invalid/crossref_no_parent/crossref.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.not_utf8` | A `.bib` file saved as Latin-1 | Error `BIB-ENCODING-INVALID` naming the file and the line of the first byte that is not UTF-8, no traceback; no encoding is guessed; fatal, nothing written | `tests/corpus/invalid/bib_not_utf8/latin1.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.bom_crlf` | A file with a UTF-8 BOM and CRLF line endings | Read normally; the BOM is not part of the first key, accents still decode | `tests/corpus/valid/encoding.bib` | `test_valid_corpus.py::test_structure` | pass |
| `structure.brace_mismatch` | `organization = {{{…}},` before `abstract`, `title = {…}},` before `note`, `howpublished = {Online}} and more,`, and `title = {\} # w},` before `url`, where `\}` counts as a brace and `w` is an undefined @string: braces that BibTeX matches with no syntax error | Each entry is read as BibTeX reads it, and warns `BIB-BRACE-MISMATCH` at the first field whose text did not arrive: `abstract`, read into `organization`; `note`, lost when the entry ended; `howpublished`, whose ` and more` is lost; `url`, lost when the entry ended, beside `BIB-STRING-UNDEFINED` for `w`. The entry after them is read as written | `tests/corpus/invalid/brace_mismatch/braces.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.unclosed_brace` | An entry whose `title` brace is never closed | Warning naming the file, key and `title`; the entries before and after it are still read | `tests/corpus/invalid/unclosed_brace/broken.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.duplicate_key_file` | The same citation key twice in one file | Stable `BIB-DUPLICATE-KEY` error names the file, key and `citation_key` field | `tests/corpus/invalid/duplicate_key_same_file/dup.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.duplicate_key_across` | The same citation key in two files | Stable `BIB-DUPLICATE-KEY` error names both files, keys and `citation_key` field | `tests/corpus/invalid/duplicate_key_across_files/first.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.missing_year` | An entry with no `year` | Stable `BIB-YEAR-MISSING` warning names the file, key and `year`; the work is emitted with `year: null` and sorts last | `tests/corpus/invalid/missing_year/noyear.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.year_not_number` | `year = {in press}` | Warning naming the file, key and field; the entry and its neighbours are kept | `tests/corpus/invalid/year_not_number/badyear.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.year_not_digits` | `year = {-5}`, `{+2020}`, `{2_020}` and full-width `{２０２０}`, each of which `int()` reads as a number | The same `BIB-YEAR-INVALID` warning, naming the file, key, field and value, and `year: null`: a year is an unsigned run of ASCII digits, and the schema's `minimum: 0` is never broken; the plain year beside them is read | `tests/corpus/invalid/year_not_digits/digits.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.missing_journal` | An `@article` with no `journal` | Warning naming the file, key and field; the entry is kept | `tests/corpus/invalid/missing_journal/nojournal.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `structure.missing_booktitle` | An `@inproceedings` with no `booktitle` | Warning naming the file, key and field; the entry is kept | `tests/corpus/invalid/missing_booktitle/nobooktitle.bib` | `test_invalid_corpus.py::test_outcome` | pass |

## Entry types
Every type sslabdata has a venue rule for, plus one it does not.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `types.article` | `@article` with `journal`, `volume`, `number` | Venue `{kind: journal, name: <journal>}`; `volume` and `number` are properties of the work | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.inproceedings` | `@inproceedings` with `booktitle` | Venue `{kind: conference, name: <booktitle>}` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.phdthesis` | `@phdthesis` with `school` | Venue `{kind: institution, name: <school>}` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.mastersthesis` | `@mastersthesis` with `school` | Venue `{kind: institution, name: <school>}` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.techreport` | `@techreport` with `type`, `number`, `institution` | Venue `{kind: institution, name: <institution>}`; `type` and `number` are properties of the work, with BibTeX's meanings | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.techreport_default` | `@techreport` with only `institution` | The same venue; `type` is null rather than a label sslabdata invented | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.misc_arxiv` | `@misc` with `eprint` | Venue `{kind: repository, name: arXiv}`; the identifier is `identifiers.arxiv` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.misc` | `@misc` with no venue fields | Venue is null: nothing names a container, so the work declares none | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `types.unsupported` | `@unpublished`, a type sslabdata has no venue rule for | Warning naming the file, key and type; the entry is kept | `tests/corpus/invalid/unsupported_entry_type/entry.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `types.incollection` | `@incollection` with `booktitle`, `editor`, `chapter`, `pages`, `publisher`, `series`, `isbn` and `month` | Kept as an `incollection` work; the `booktitle` naming the collection is the venue's name | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_entries_keep_their_key_and_type`, `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `types.inbook` | `@inbook` with `chapter`, `pages`, `publisher`, `address`, `edition` and `isbn` | Kept as an `inbook` work; the `publisher` of the book is a property of the work | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_entries_keep_their_key_and_type`, `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `types.book` | `@book` with `publisher`, `address`, `series`, `edition` and `isbn` | Kept as a `book` work; the `publisher` is a property of the work | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_entries_keep_their_key_and_type`, `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `types.manual` | `@manual` with `organization`, `address`, `edition` and `month` | Kept as a `manual` work; the issuing `organization` is a property of the work | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_entries_keep_their_key_and_type`, `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |

## Fields read
Every BibTeX field sslabdata reads. A field it emits no property for is still
preserved in the copyable `bibtex` output field.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `fields.journal` | `journal` | The venue's name, with `kind: journal` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.volume` | `volume` | The `volume` property, as written | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.number` | `number` | The `number` property, keeping BibTeX's name and BibTeX's meaning | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.pages` | `pages` | The `pages` property, as written | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.publisher` | `publisher` | The `publisher` property, converted from LaTeX | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.address` | `address` on an `@incollection` | The `address` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.series` | `series` on an `@incollection` | The `series` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.edition` | `edition` on a `@book` | The `edition` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.booktitle` | `booktitle` | The venue's name, with a `kind` the entry type decides | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.school` | `school` | The venue's name, with `kind: institution` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.institution` | `institution` | The venue's name, with `kind: institution` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.type` | `type` | The `type` property: a report's own label, distinct from `entry_type` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.eprint` | `eprint` | An identifier under the scheme `archivePrefix` names | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.archiveprefix` | `archivePrefix = {arXiv}`, and `archivePrefix = {HAL}` on another entry | Becomes the identifier's scheme, lower-cased, and the venue's name for a preprint, so it needs no property of its own. The entry naming another repository is what pins it: a compiler that assumed arXiv would satisfy the arXiv row and lose the field | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.eprinttype` | `eprinttype = {hal}` and `eprinttype = {pubmed}`, biblatex's name for the field, with no `archivePrefix` | Read as `archivePrefix` is: the identifier is filed under `hal` or `pubmed`, the venue is that repository, and no arXiv link is built | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.archiveprefix_latex` | `archivePrefix = {{arXiv}}` | Converted from LaTeX before it is read, so it behaves as `{arXiv}` does: scheme `arxiv`, venue `arXiv` and an arXiv link | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.doi` | `doi`, bare or written as a resolver URL | `identifiers.doi`, with the resolver prefix off | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.url` | `url` | A link of kind `video` for a known video host, otherwise `url`, with `origin: input` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.project` | `project = {homebot}` | Becomes `project_ids` | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_structure` | pass |
| `fields.unread` | `keywords`, which sslabdata emits no property for | Not dropped: it stays in the `bibtex` field | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_structure` | pass |

## Fields the demo carries, and the property each reaches
Every field of every demo entry is read from the `.bib` files and looked up
in the one property SPEC.md §5 gives it: a flat property, `venue.name`,
`identifiers[scheme]`, the parsed `editors`, or a link whose `origin` is
`input`. The value must equal the input's wherever the input wrote plain
text; a value written with LaTeX is converted on the way in, so for those
only presence is compared. Every value here is also preserved in the
`bibtex` record, as `fields.unread` says.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `fields.demo_entry_type` | Every entry of the demo, across its four `.bib` files | One work per entry, with the entry's citation key and entry type | `examples/demo/lab.yaml` | `test_consumer_probes.py::test_demo_entries_keep_their_key_and_type` | pass |
| `fields.demo_every_field` | Every field of every demo entry except `project`, which `fields.project` covers | Reaches its property, equal to the input's value where the input wrote plain text and present where the value carries LaTeX; `eprint` under the scheme `archivePrefix` names, lower-cased; `url` as a link with `origin: input` | `examples/demo/lab.yaml` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.editor` | `editor = {Quinn, Quentin and Silva, Sofia}` on an `@incollection` | Parsed into `editors` beside the authors, name parts and all, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.month` | `month = {March}` | The `month` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.chapter` | `chapter = {9}` on an `@inbook` | The `chapter` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.isbn` | `isbn` on a `@book` | `identifiers.isbn`, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.organization` | `organization` on a `@manual` | Converted from LaTeX into the `organization` property, with the input's value | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.issn` | `issn` on an `@article` | `identifiers.issn`, with the input's value | `examples/demo/bib/journal.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |
| `fields.howpublished` | `howpublished` on a `@misc` | The `howpublished` property, with the input's value | `examples/demo/bib/other.bib` | `test_consumer_probes.py::test_demo_field_reaches_the_document` | pass |

## Name forms
Author names as they appear in `.bib` files. `name` below is the `authors[].name`
field of the output.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `names.last_first` | `Adams, Alice` | Name `Alice Adams`, resolved to the person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.first_last` | `Bob Brown` | Name `Bob Brown`, resolved to the person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.particle_last_first` | `van den Berg, Victor` | The particle stays with the surname: `Victor van den Berg` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.particle_first_last` | `Rupert de la Cruz` | The particle stays with the surname: `Rupert de la Cruz` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.suffix` | `Smith, Jr., John` | The suffix is kept and is not mistaken for a given name | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.corporate` | `{Example Robotics Consortium}` | Kept as one name, without its braces, and not abbreviated | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.corporate_escaped` | `{AT\&T Research}` | Kept as one name, with `\&` decoded to `&` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.hyphenated` | `Green, Grace-Ann` | The given name is kept whole, not abbreviated: `Grace-Ann Green` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.structured` | Any author or editor name | The parts BibTeX split it into — given, von, family, suffix, or literal for a brace-protected name — reach the output, and `name` is those parts joined in reading order, abbreviating nothing | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_name_parts` | pass |
| `names.accent_tex` | `C{\^o}t{\'e}, Carol` | Name `Carol Côté`, resolved to the person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.accent_utf8` | `Côté, Carol` in raw UTF-8 | Same output as the TeX spelling, resolved to the same person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.others` | `... and others` | The real authors are resolved; `others` is not emitted as an author | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.others_mid_list` | `Adams, Alice and Brown, Bob and others and Cee, Cy`, and an editor list starting `others and ...` | Warning `BIB-OTHERS-NOT-LAST` naming the file, key and `author` or `editor`; `others` is dropped and no author or editor is named `others`, the other names keep their order and positions count only them. A terminal `and others` beside them draws no warning | `tests/corpus/invalid/others_mid_list/others.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `names.equal_contribution` | Each of `$^{*}$`, `^{*}`, `\textsuperscript{*}` and a trailing `*`, written in turn on the given name, the surname, the particle and the suffix — sixteen combinations | The marker is taken off that part: the readable name and the structured parts read as they would without it, and the name resolves to the same person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_equal_contribution` | pass |
| `names.equal_contribution_marker` | The same sixteen combinations, and every other author name in the corpus | `equal_contribution` is true for each of the sixteen marked authors and false for every other author in the valid corpus | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_equal_contribution` | pass |
| `names.equal_contribution_normalized` | `Brown$^{*}$*` (the marker twice), `Kim{$^{*}$}` (in a brace group of its own), `Green\textsuperscript {*}` (a space before the argument, which BibTeX splits into two name parts, also written with a second marker after it) and `Davis{*}` (a brace group holding only a star) | The first three come off whole: nothing is left in the name and those authors are marked and resolve. The last is another command's argument rather than a marker, so it stays in the name and marks nobody | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_equal_contribution` | pass |
| `names.equal_contribution_escaped` | `Brown\*`, `Davis\^{*}`, `Green\$^{*}$` and `Evans\\textsuperscript {*}` — a star, caret, dollar or backslash written with a backslash in front of it | Not a marker: `equal_contribution` stays false for all four, and the name parts keep their own boundaries. What each escaped spelling becomes is the ordinary LaTeX conversion's doing — the star survives in `Davis\^{*}` and `Green\$^{*}$` and is consumed with `\*` in `Brown\*` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_equal_contribution` | pass |
| `names.same_initial_alex` | `Kim, Alex`, who declares the alias `A. Kim` | Resolves to `akim` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.same_initial_alan` | `Kim, Alan`, who declares no alias | Resolves to `alankim`, not to the other Kim | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_ambiguous` | `Kim, A.`, which fits both Kims | Not resolved to either; listed for a human to resolve | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_run_together` | `Ivers, S.S.`, whose person declares the alias `S. S. Ivers` | Resolves to `sivers`: initials written together are one initial per letter, so `S.S.`, `S.S`, `S S` and `S. S.` match alike. The readable name and the given part stay `S.S.` as written | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_run_together_alias` | `Lark, T. R.`, whose person declares the alias `T.R. Lark` | Resolves to `tlark`: the declared side is read the same way | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_run_together_three` | `Moss, U.A.K.`, whose person declares the alias `U. A. K. Moss` | Resolves to `umoss` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_run_together_unmatched` | `Ivers, S.T.`, which no one declares, and `Quill, E.D.` beside the member `Ed Quill` | Neither resolves: `S. T. Ivers` is not `S. S. Ivers` or `Stella Sky Ivers`, and `E.D.` is the two initials `E. D.`, not the given name `Ed` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_multiletter_whole` | `Nash, Jo` beside the alias `J. O. Nash`, and `Lark, TR` beside the alias `T.R. Lark` | Neither resolves: a part with no period inside it is a name and is never split into initials | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `names.initials_hyphenated` | `Wren, J.-P.` and `Wren, J.P.`, whose person declares the alias `J.-P. Wren` | `J.-P.` resolves to `jwren`; `J.P.` does not. Hyphenated initials are left as written: periods are still removed, so `J.-P.` equals `J-P`, but not `J.P.`, `J. P.` or `JP` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |

## Identity resolution
Every way an author name can be matched to a person, and what happens when it
cannot be.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `identity.alias` | A name matching a declared `aliases` entry | Resolved to that person | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_names` | pass |
| `identity.full_name` | A full name matching `name`, with no aliases declared | Resolved to that person | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `identity.normalized` | `DAVIS, D` — different case and punctuation | Resolved: matching ignores case, accents and periods | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `identity.fuzzy` | `Davis, Dave M.`, close to a person's name but not equal | Not auto-linked; reported as a suggestion for a human | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `identity.ambiguous_reported` | `Kim, A.`, which fits both Kims | A `RESOLVE-AMBIGUOUS-NAME` warning naming the file, the key, the author position and both ids, under `--validate` and `--unresolved`; neither exit code changes | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_ambiguous_name_reported_as_a_located_warning` | pass |
| `identity.suggestion_reported` | `Davis, Dave M.`, close to a person's name but not equal | A `RESOLVE-SUGGESTION` warning naming the file, the key, the author position and the suggested id, under `--validate` and `--unresolved`; the authorship stays a collaborator | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_near_miss_reported_as_a_suggestion` | pass |
| `identity.collaborator_alias` | `collaborators_file` declaring `Quentin Quinn` with the alias `Q. Quinn` | `Quinn, Quentin` and `Quinn, Q.` are one collaborator, `grouped_by: declared`; no `person_id` changes anywhere | `tests/corpus/valid/collaborators.yaml` | `test_config_cli.py::test_config_collaborators_file_present` | pass |
| `identity.collaborator_alias_is_member` | A `collaborators_file` alias, `A. Adams`, that a lab member also declares | A `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER` warning naming the file, the collaborator and the alias, under `--validate` and `--unresolved`; neither exit code changes, and the member keeps the spelling | `tests/corpus/valid/collaborators.yaml` | `test_config_cli.py::test_collaborator_alias_that_is_a_member_is_reported` | pass |
| `identity.external` | A co-author who is in no people file | Left unresolved, grouped into a collaborator, and the authorship references that grouping's key | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_names` | pass |
| `identity.alike_authorships` | Two different people listed on one work under one written name | One grouping key, two authorships at two positions; `work_ids` has one entry and `authorships` two, so the occurrences survive the grouping | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_two_authorships_written_alike_stay_apart` | pass |
| `identity.grouping_distinct` | Five names each differing from an initials-only name above in exactly one of the things the check compares: the particle, the family name, the second initial, the second half of a hyphenated given name, and a lineage suffix that disagrees | None of them is reported as a name an initials-only key could be. The set of pairs the corpus produces is asserted whole, so a check comparing one thing less adds a pair and one comparing more drops one | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_the_initials_warnings_are_exactly_these_pairs` | pass |
| `identity.grouping_spellings` | One external name written `Ross, Rachel` on one entry and `ROSS, RACHEL` on another | One key with two `name_variants`, and a `ID-GROUPING-SPANS-SPELLINGS` warning naming the key. Not an error | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_grouping_risks_are_reported` | pass |
| `identity.grouping_suffix` | `Tate, Jr., T.` beside `Tate, Jr., Tobias` and `Tate, Sr., Tobias`, and `Vance, V.` beside `Vance, Jr., Victor` | The pair whose suffixes agree is reported and so is the pair where only one side writes one, because an entry that omits a suffix has said nothing. The pair whose suffixes disagree is not: two lineage suffixes that disagree are two people | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_an_initials_only_key_that_could_be_a_fuller_one_is_reported` | pass |
| `identity.grouping_initials` | `Quinn, Q.` beside `Quinn, Quentin`, and six more pairs: a surname particle, two initials, a hyphenated family name, a name outside ASCII, a lineage suffix that agrees, and a lineage suffix on one side only | Two keys each, which differ — the instability is intended, not a merge — and an `ID-GROUPING-INITIALS-AMBIGUOUS` warning naming both. Decided on the structured parts — the initials, the family name, the particles and the suffix — so none of those shapes is missed. Not an error | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_an_initials_only_key_that_could_be_a_fuller_one_is_reported` | pass |
| `identity.ambiguous_alias` | Two people declaring the same alias | Warning naming both ids and the alias; the name resolves to neither | `tests/corpus/invalid/ambiguous_alias/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `identity.declared_suffix_not_spaced` | Two people declaring `T.T. Ivers, S.S.` and `T.T. Ivers, S. S.` | Two spellings, not one: text after the comma is never spaced, so no `PEOPLE-ALIAS-AMBIGUOUS` warning | `tests/corpus/invalid/declared_suffix_not_spaced/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `identity.collaborator_whole_initials` | A `collaborators_file` entry `S.S. Quinn`, with `Quinn, SS` on one entry and `Quinn, S.S.` on another | Two collaborators: the entry is keyed with its initials spaced, and `SS` is a name that is never split, so no key spans the two spellings and no `ID-GROUPING-SPANS-SPELLINGS` warning | `tests/corpus/invalid/collaborator_whole_initials/collaborators.yaml` | `test_invalid_corpus.py::test_outcome` | pass |

## LaTeX and text
Titles, abstracts and notes are meant to reach the site as plain Unicode text,
with `$...$` math left as TeX for KaTeX or MathJax. Markdown metacharacters in
the source text are not markup and must survive unchanged.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `latex.textbf` | `A \textbf{Bold} Claim` | Plain text `A Bold Claim`, with no Markdown `**` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.nested` | `\textbf{a {B} c}` and `\emph{d \textbf{e} f}` | Plain text, with the nested braces and macros resolved | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.accent_braced` | `Caf{\'e}` and `M{\"u}nchen` | `Café` and `München` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.caron_space` | `Ha{\v c}ek on {\v c}` | `Haček on č` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.dotless_i` | `Mar\'\i a` | `María` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.ampersand` | `Pick \& Place` | `Pick & Place` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.percent` | `A 50\% Speedup` | `A 50% Speedup` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.percent_bare` | A bare `%` in a title, at the end of an abstract, doubled as `%%`, and in `\url{https://example.org/a%20b_c}` | A literal `%` each time; the text after it and the whole URL are kept, not read as a comment | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.underscore` | `robot\_arm` | `robot_arm` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.endash` | `1--10` | `1–10` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.emdash` | `Robots---and People` | `Robots—and People` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.quotes` | ` ``Tidy'' ` | Typographic quotes `“Tidy”` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.star_braced` | `{RRT}*` | `RRT*`: the star is kept and the braces are dropped | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.star_plain` | `BIT*` | `BIT*`: the star is kept | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.star_braced_whole` | `{BIT*}` | `BIT*`: the star is kept | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.math` | `$O(n \log n)$` | Left as TeX, delimiters and all, for the renderer | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.html_special` | `< > & " '` in a title | Kept as characters in the data; escaping is the renderer's job | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.markdown_punctuation` | `[a link](x)`, `` `code` ``, `# heading`, `*emphasis*` | Kept verbatim: they are text, not markup | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.unicode_raw` | Raw CJK and emoji | Passed through unchanged | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.abstract` | An abstract with accents, math and `\emph` | Same rules as a title: plain text with math left as TeX | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.note_href` | `note = {Code at \href{url}{our site}}` | The link and its text both survive; the entry is never dropped | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.url` | `note = {Code at \url{https://cs.example.edu/~ann/robot_code?v=2&q=1#frag}.}` | The URL exactly as written, `~`, `_`, `&` and `#` included, not the autolink `<…>` and with no no-break space for `~` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.footnote` | `Tidy Robots\footnote{Funded by …}` | `Tidy Robots (Funded by …)`: the footnote in parentheses, not `[…]` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.cite_ref` | `planners~\cite{k1,k2}` and `shows~\ref{app}` | Both left out with the space before them, not `<cit.>` or `<ref>` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.list_item` | `\item fast` and `\item[(b)] tidy` in `itemize` | A line `• fast` and a line `(b) tidy`, not a Markdown `* ` bullet | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.layout_dropped` | `\includegraphics{fig.png}` and `\maketitle{}` | Both left out, not `< g r a p h i c s >` or a `[NO \title GIVEN]` block | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.textfrac` | `A \textfrac{3}{2}-Approximation` | `A 3/2-Approximation`, not `%s/%s32` | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.text_argument` | `\texttt{zqplan}`, `\mbox{Tidy}`, `\textsf`, `\textup`, `\textmd`, `\textnormal`, `\fbox` and `\hbox` | Each becomes its argument as plain text, with no `LATEX-COMMAND-UNKNOWN` warning | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.title_author_date` | `\title{Tidy Robots}`, `\author{Ann Zq}` and `\date{May 2020}` in a note | Each becomes its argument as plain text, not nothing, with no `LATEX-COMMAND-UNKNOWN` warning | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.argument_not_text` | `\label{…}`, `{\color{red}fast}`, `\citeauthor{k1}`, `\citeyearpar{k1}`, `\pageref{app}`, `\usepackage{…}`, `\definecolor{…}{…}{…}` | Each left out with its arguments, the text around it kept; a citation, label or cross-reference also takes the space before it. No `LATEX-COMMAND-UNKNOWN` warning | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_latex` | pass |
| `latex.unknown_command_arguments` | `\keywords{Tidy}`, `\verb{zqx}`, `\subexercise{…}` and `\xrightarrow[fast]{there}`, whose arguments the parser library knows, beside `\fictionalmacro[a]{b}` | `LATEX-COMMAND-UNKNOWN` for each, and what follows each kept as plain text, as for a command the parser library does not know: `Tidy Robots with zqx`, `Moving [fast]there and [a]b too` | `tests/corpus/invalid/unknown_command_arguments/args.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `latex.text_macros` | `\TeX{}`, `\LaTeX\ `, `\BibTeX`, `\emdash`, `\endash`, `\slash` | `TeX`, `LaTeX`, `BibTeX`, `—`, `–`, `/`, with no `LATEX-COMMAND-UNKNOWN` warning | `tests/corpus/invalid/common_text_macros/macros.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `latex.unknown_macro_in_math` | `$\fictionalop{n}$`, a command with no rule inside math | Math is not searched: no `LATEX-COMMAND-UNKNOWN` warning, and the math is kept as TeX, command and all | `tests/corpus/invalid/unknown_macro_in_math/math.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `latex.unknown_macro_repeated` | One unknown macro in three fields of two entries | One warning line for the macro, with the count of fields and the first of them as the location | `tests/corpus/invalid/unknown_macro_repeated/macro.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `latex.unknown_macro` | `\fictionalmacro{Strange}` | Warning naming the file, key and field; the macro's text is kept and no raw LaTeX reaches the output | `tests/corpus/invalid/unknown_macro/macro.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `latex.definition_commands` | `\newcommand zqx Tidy Robots`, `\newcommand \url{…} Letters`, `\newcommand \href{…}{site} and \def\x{y} z`, and an accent before `\url{…}` | `LATEX-COMMAND-UNKNOWN` for `\newcommand`, `\def` and `\x`, and the text after each kept: `zqx Tidy Robots`, `https://x.org/x Letters`, `site (https://x.org/y) and y z`. The accented URL is `LATEX-CONVERSION-FAILED`, kept as written, and no conversion marker reaches the document | `tests/corpus/invalid/definition_commands/define.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `text.control_characters` | U+0002, U+0001 and U+007F raw in a title, and `"\x01"` and `"\a"` escapes in a person's `name` and in `lab.description` | Warning `TEXT-CONTROL-CHARACTER` at each value, naming the characters; they are removed and nothing else is: the title reads `Alpha Beta 0 Gamma Delta` with no `LATEX-CONVERSION-FAILED`, and the name resolves the author | `tests/corpus/invalid/control_characters/control.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `text.nfc_equivalent` | Two entries with the same authors and title, one with every accent decomposed (`C` + U+0327) and one precomposed (`Ç`), a decomposed citation key, a person's `name` and a `lab` key and value written decomposed | Read as one text, with no diagnostic of its own: both authorships resolve the member and group each collaborator under one key and one spelling, `Vale, Ç.` is an initial either way (`ID-GROUPING-INITIALS-AMBIGUOUS` beside `Vale, Çelik`), and every string, key and name is emitted NFC | `tests/corpus/invalid/nfc_equivalent_text/nfc.bib` | `test_invalid_corpus.py::test_outcome` | pass |

## Links

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `links.doi_bare` | `doi = {10.5555/corpus.0001}` | A link of kind `doi` at the DOI resolver URL | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.doi_url` | `doi = {https://doi.org/10.5555/corpus.0002}` | The same URL, not doubled up | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.doi_resolver_only` | `doi = {https://doi.org/}` and `doi = {http://dx.doi.org/}`, a resolver with no DOI after it | Warning `BIB-DOI-INVALID` naming the file, key, `doi` and the value; no `identifiers.doi` and no link of kind `doi`, rather than an empty DOI the schema rejects. A DOI after its resolver beside them is read | `tests/corpus/invalid/doi_resolver_only/doi.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `links.arxiv_prefixed` | `eprint` with `archivePrefix = {arXiv}` | A link of kind `arxiv` at the abstract page | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.arxiv_unprefixed` | `eprint` with no `archivePrefix` | A link of kind `arxiv` at the abstract page | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.arxiv_other_repository` | `eprint` with `archivePrefix = {HAL}` | The identifier is filed under that repository's scheme, and no arXiv link is built for an identifier that is not an arXiv one | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.youtube` | `url` on youtube.com | A link of kind `video`, and none of kind `url` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.vimeo` | `url` on vimeo.com | A link of kind `video`, and none of kind `url` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.video_field` | `url` on any other host and `video = {…}` | One link of kind `url` and one of kind `video`, both with `origin: input`; `video` is carried in `bibtex` as written and draws no diagnostic | `tests/corpus/valid/video.bib` | `test_valid_corpus.py::test_video_field_beside_a_website_url` | pass |
| `links.url` | `url` on any other host | A link of kind `url`, and none of kind `video` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.origin` | A link from the entry's own `url`, and one sslabdata built from an identifier | `origin: input` for the first, `origin: derived` for the second | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.pdf.local_present` | `pdf_base_url` is a local directory holding `<key>.pdf` | A link of kind `pdf` whose `verification` is `{status: verified}` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.pdf.local_missing` | `pdf_base_url` is a local directory with no `<key>.pdf` | The link is kept with `verification.status: missing`, not deleted: a broken link and an absent one are different answers | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | pass |
| `links.pdf_field` | `pdf = {…}` with `pdf_base_url` set, the same with no `pdf_base_url`, and an empty `pdf` | One link of kind `pdf` with `origin: input` and `verification.status: unchecked`, in place of the one `pdf_base_url` gives; an empty `pdf` is read as absent; no diagnostic | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_pdf_field_replaces_the_base_url_link` | pass |
| `links.pdf.remote_guess` | `pdf_base_url` is a remote URL, nothing says the PDF exists | The link says `verified` or `missing` rather than `unchecked`; a build never fetches, so this needs a committed cache | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_remote_pdf_url_not_verified` | xfail #20 |
| `links.note_link_award` | A `note` holding both an `\href` and an award | Both survive; the award is available as its own field | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_links` | xfail #27 |

## Projects

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `projects.single` | `project = {homebot}` | One project id; the project back-links the paper | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_projects` | pass |
| `projects.multiple` | `project = {homebot, sharedarm}` | Both ids, in source order; both projects back-link the paper | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_projects` | pass |
| `projects.tagged_twice` | `project = {homebot, homebot}` | The project back-links the work once in `work_ids`; nothing is reported | `tests/corpus/invalid/project_tagged_twice/tagged.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `projects.none` | No project tag | Empty `project_ids` | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_projects` | pass |
| `projects.keywords` | `keywords = {project:sharedarm, manipulation}` | The namespaced keyword is read as a project tag | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_projects` | xfail #28 |
| `projects.undefined` | A tag no `projects.yaml` entry defines | Error naming the file, key, field and tag; `--validate` exits non-zero | `tests/corpus/invalid/undefined_project/tagged.bib` | `test_invalid_corpus.py::test_outcome` | pass |
| `projects.duplicate_id` | The same project id twice in `projects.yaml` | Error naming the file and the repeated id | `tests/corpus/invalid/duplicate_project_id/projects.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `projects.invalid_status` | `status: sometimes` | Warning naming the file, project and field | `tests/corpus/invalid/invalid_project_status/projects.yaml` | `test_invalid_corpus.py::test_outcome` | pass |

## People file

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `people.duplicate_id` | The same person id twice in `people.yaml` | Error naming the file and the repeated id | `tests/corpus/invalid/duplicate_person_id/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `people.invalid_role` | A `role` that is missing, empty, or not a string | Warning naming the file, person and field | `tests/corpus/invalid/invalid_person_role/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `people.invalid_status` | `status: retired`, neither current nor alumni | Warning naming the file, person and field | `tests/corpus/invalid/invalid_person_status/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `records.unknown_key` | A key sslabdata does not read in a person (`webiste`), a project (`funding`) and a collaborator (`affiliation`) | Warning `RECORD-KEY-UNKNOWN` for each, naming the file, the record's id (a collaborator's name) and the key; an error under `--strict`; the key is not emitted | `tests/corpus/invalid/record_unknown_key/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `records.key_repeated` | A key given twice in one record: a person's `name`, a project's `status` and another's `id`, a collaborator's `aliases` | Error `RECORD-KEY-REPEATED` for each, naming the file, the record (none when the repeated key is its `id`), the key and both lines; the record is not loaded; fatal, nothing written | `tests/corpus/invalid/record_key_repeated/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `records.merge_key` | A person built with a YAML merge key (`<<: *bob`) that overrides the merged `id` and `name` | Not a repeated key: no diagnostic for it | `tests/corpus/invalid/record_key_repeated/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `records.optional_type_invalid` | Optional person, project and collaborator fields of the wrong type: a number where a string is read, a string where an integer is, aliases that are not a list of non-empty strings, a `status` that is a number | Warning `RECORD-TYPE-INVALID` for each, naming the file, the record and the field; the value is emitted as `null` (a status as its default) and the record is kept | `tests/corpus/invalid/record_field_types/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `records.required_type_invalid` | A person whose `id` and `name` are numbers or a list, a project whose `id` is a boolean, a collaborator whose `name` is a number | Error `*-FIELD-MISSING` naming the file, the record and the field, no traceback; fatal, nothing written | `tests/corpus/invalid/record_id_types/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `people.missing_name` | A person with an `id` but no `name` | Error naming the file, the person and the missing field | `tests/corpus/invalid/people_missing_name/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `people.not_a_list` | A mapping where sslabdata expects a list of people | Error naming the file | `tests/corpus/invalid/people_not_a_list/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `people.invalid_yaml` | A people file that is not valid YAML | Error `PEOPLE-YAML-INVALID` naming the file and line, no traceback; fatal, nothing written | `tests/corpus/invalid/people_invalid_yaml/people.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `projects.invalid_yaml` | A projects file that is not valid YAML | Error `PROJECTS-YAML-INVALID` naming the file and line, no traceback; fatal, nothing written | `tests/corpus/invalid/projects_invalid_yaml/projects.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `collaborators.invalid_yaml` | A collaborators file that is not valid YAML | Error `COLLABORATORS-YAML-INVALID` naming the file and line, no traceback; fatal, nothing written | `tests/corpus/invalid/collaborators_invalid_yaml/collaborators.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `projects.missing_id` | A project with a `title` but no `id` | Error `PROJECTS-FIELD-MISSING` naming the file and the field, no traceback; fatal, nothing written | `tests/corpus/invalid/projects_missing_id/projects.yaml` | `test_invalid_corpus.py::test_outcome` | pass |

## Config keys
Every key of `lab.yaml`, present, missing and wrong-typed. Wrong-typed and
missing-file cases each live in their own `tests/corpus/invalid/` folder.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `config.lab.present` | A `lab:` section | Copied into the output as `lab` | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_present` | pass |
| `config.lab.missing` | No `lab:` section | Accepted; `lab` is emitted as `{}`, so no header and an empty header are the same document | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_lab_missing` | pass |
| `config.lab.wrong_type` | `lab: "Corpus Lab"`, a string | Error naming the file and the key | `tests/corpus/invalid/config_lab_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.value_wrong_type` | `lab: {name: 7}`, a key the schema types as a string | Error `CONFIG-TYPE-INVALID` naming the file, `lab` and the key | `tests/corpus/invalid/config_lab_value_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.date` | `founded: 2010-01-01` and a timestamp under `lab.links`, which YAML reads as a date and a datetime | Emitted as ISO 8601 text, the same in both formats; `--validate --strict` passes and the document validates against the schema | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_lab_dates_are_emitted_as_iso_text` | pass |
| `config.lab.value_nan` | `lab: {ratio: .nan}` | Error `CONFIG-VALUE-NOT-JSON` naming the file, `lab` and `ratio`, in every mode; JSON has no NaN | `tests/corpus/invalid/config_lab_value_nan/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.value_infinity` | `-.inf` in a list under `lab.links` | Error `CONFIG-VALUE-NOT-JSON` located at `links.scores[1]` | `tests/corpus/invalid/config_lab_value_infinity/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.value_set` | `tags: !!set {robots, gardens}` under `lab` | Error `CONFIG-VALUE-NOT-JSON`; a set's order changes between runs | `tests/corpus/invalid/config_lab_value_set/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.value_binary` | `seal: !!binary aGk=` under `lab` | Error `CONFIG-VALUE-NOT-JSON`; binary has no meaning as text | `tests/corpus/invalid/config_lab_value_binary/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.lab.key_type` | `awards: {2019: Best Paper}` under `lab`, a key YAML reads as a number | Error `CONFIG-VALUE-NOT-JSON` located at `awards`, naming the key; YAML would write it as a number and JSON as text | `tests/corpus/invalid/config_lab_key_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.site` | A `site:` section, read by downstream renderers | Accepted by sslabdata and not copied into the output | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_present` | pass |
| `config.bib_dir.present` | `bib_dir: "."` | The `.bib` files are read from that directory | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_present` | pass |
| `config.bib_dir.missing` | No `bib_dir` | Error naming the missing key | `tests/corpus/invalid/config_bib_dir_missing/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_dir.not_found` | `bib_dir` naming a directory that is not there, with two `bib_files` under it | Error `CONFIG-FILE-NOT-FOUND` once, naming `bib_dir` and the path, not once per file | `tests/corpus/invalid/config_bib_dir_not_found/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_dir.not_a_directory` | `bib_dir` naming a file | Error `CONFIG-PATH-WRONG-KIND` naming `bib_dir` and saying the path is not a directory | `tests/corpus/invalid/config_bib_dir_not_a_directory/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_dir.wrong_type` | `bib_dir` as a list | Error naming the file and the key | `tests/corpus/invalid/config_bib_dir_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.present` | `bib_files` with a name and category each | Each file is read and its category lands on every publication in it | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_present` | pass |
| `config.bib_files.missing` | No `bib_files` | Warning naming the key; an empty publication list is not silently normal | `tests/corpus/invalid/config_bib_files_missing/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.wrong_type` | `bib_files` as a string | Error naming the file and the key | `tests/corpus/invalid/config_bib_files_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.name_missing` | A `bib_files` entry with no `name` | Error naming the file, the section and the missing key | `tests/corpus/invalid/config_bib_file_no_name/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.name_absolute` | A `bib_files` entry whose `name` is an absolute path | Error naming the file, the section, the key and the offending name; the configuration does not load, because the name is emitted as `source.file`, which is never absolute | `tests/corpus/invalid/config_bib_file_absolute/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.name_outside_bib_dir` | A `bib_files` entry whose `name` leaves `bib_dir`: by `..`, by a backslash or drive spelling of the same, or through a symlink inside `bib_dir`; a nested `conference/2026.bib` stays valid | Error `CONFIG-BIB-FILE-OUTSIDE-BIB-DIR` naming the file, the section, the key and the offending name, before any `.bib` is parsed; nothing is written. An accepted name is emitted unchanged as `source.file` | `tests/corpus/invalid/config_bib_file_outside/lab.yaml` | `test_invalid_corpus.py::test_a_name_outside_bib_dir_is_rejected_before_anything_is_parsed` | pass |
| `config.bib_files.name_wrong_type` | A `bib_files` entry whose `name` is `7` | Error `CONFIG-TYPE-INVALID` naming the file, the section and the field | `tests/corpus/invalid/config_bib_file_name_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.category_wrong_type` | A `bib_files` entry whose `category` is `7` | Error `CONFIG-TYPE-INVALID` naming the file, the section and the field | `tests/corpus/invalid/config_bib_file_category_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.entry_wrong_type` | A `bib_files` entry that is a string, not a mapping | Error `CONFIG-TYPE-INVALID` naming the file and the section | `tests/corpus/invalid/config_bib_file_entry_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.entry_unknown_key` | A `bib_files` entry with a key other than `name` and `category` | Error `CONFIG-TYPE-INVALID` naming the file, the section and the key | `tests/corpus/invalid/config_bib_file_unknown_key/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.category_missing` | A `bib_files` entry with no `category` | Error naming the file, the section and the missing key | `tests/corpus/invalid/config_bib_file_no_category/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.bib_files.not_found` | A `bib_files` entry naming a file that is not there | Error naming the missing file | `tests/corpus/invalid/bib_file_not_found/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.path.is_directory` | A directory named by a `bib_files` entry, `people_file`, `projects_file` and `collaborators_file` | Error `CONFIG-PATH-WRONG-KIND` for each, naming the key and saying the path is a directory, not a file; not reported as missing | `tests/corpus/invalid/config_path_is_directory/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.pdf_base_url.present` | `pdf_base_url` pointing at a local directory | PDF links are built from it | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_pdf_base_url_present` | pass |
| `config.pdf_base_url.missing` | No `pdf_base_url` | Accepted; no work without its own `pdf` field gets a link of kind `pdf` at all, which is a third answer beside `verified` and `missing` | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_pdf_base_url_missing` | pass |
| `config.pdf_base_url.wrong_type` | `pdf_base_url: 42` | Error naming the file and the key | `tests/corpus/invalid/config_pdf_base_url_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.people_file.present` | `people_file` pointing at a people list | People are loaded and authors are resolved against them | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_people_file_present` | pass |
| `config.people_file.missing` | No `people_file` | Accepted; every author is a collaborator, and `--unresolved` says resolution is not configured | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_people_file_missing` | pass |
| `config.people_file.not_found` | `people_file` naming a file that is not there | Error naming the key and the missing file | `tests/corpus/invalid/people_file_not_found/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.people_file.wrong_type` | `people_file` as a list | Error naming the file and the key | `tests/corpus/invalid/config_people_file_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.projects_file.present` | `projects_file` pointing at a project list | Projects are loaded and tags are validated against them | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_projects_file_present` | pass |
| `config.projects_file.missing` | No `projects_file` | Accepted; no projects, and project tags are kept on works | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_config_projects_file_missing` | pass |
| `config.collaborators_file.present` | `collaborators_file` pointing at a list of `{name, aliases}` | Accepted; the spellings it declares are grouped into one collaborator each, and nothing resolves to a person through it | `tests/corpus/valid/collaborators.yaml` | `test_config_cli.py::test_config_collaborators_file_present` | pass |
| `config.collaborators_file.not_found` | `collaborators_file` naming a file that is not there | Error naming the key and the missing file, not an empty list | `tests/corpus/invalid/collaborators_file_not_found/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.data_file.empty` | `people_file: ""`, `projects_file: ""` and `collaborators_file: ""` | Error `CONFIG-FILE-NOT-FOUND` for each, naming the key; an empty path is not read as no file, which only leaving the key out means | `tests/corpus/invalid/config_data_file_empty/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.collaborators_file.wrong_type` | `collaborators_file` as a list | Error naming the file and the key, no traceback | `tests/corpus/invalid/config_collaborators_file_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.projects_file.not_found` | `projects_file` naming a file that is not there | Error naming the key and the missing file | `tests/corpus/invalid/projects_file_not_found/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.projects_file.wrong_type` | `projects_file` as a list | Error naming the file and the key | `tests/corpus/invalid/config_projects_file_type/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.unknown_key` | A misspelled key such as `people_fil` | Warning naming the file and the unknown key | `tests/corpus/invalid/config_unknown_key/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.key_repeated` | `name` given twice under `lab` | Error `CONFIG-KEY-REPEATED` naming the file, `lab`, the key and both lines, in every mode; the configuration does not load | `tests/corpus/invalid/config_key_repeated/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |
| `config.not_a_mapping` | A `lab.yaml` holding a list | Error naming the file | `tests/corpus/invalid/config_not_a_mapping/lab.yaml` | `test_invalid_corpus.py::test_outcome` | pass |

## CLI flags and output formats

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `cli.config` | `sslabdata` with no `--config` | Usage error naming `--config` | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_config_required` | pass |
| `cli.config_not_found` | `--config` naming a file that is not there | Error naming the file; exits non-zero | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_config_not_found` | pass |
| `cli.mode.required` | `--config` alone, with no mode flag | Usage error naming `--output`, `--validate` and `--unresolved` | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_mode_required` | pass |
| `cli.output` | `--output out/nested/lab.yml` | Writes the file, creating parent directories | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_output_creates_parent_dirs` | pass |
| `cli.output.write_failed` | `--output` naming a directory, a path under a file, or a file in a directory without write permission (skipped as root) | Error `OUTPUT-WRITE-FAILED` located at the destination, exit 1, no traceback; the tree is byte for byte as it was, the old document kept and no temporary file left | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_a_failed_write_is_coded_and_changes_nothing` | pass |
| `cli.format.yaml` | `--format yaml`, and the default with no `--format` | YAML holding the same data as `--format json` | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_format` | pass |
| `cli.format.json` | `--format json` | JSON holding the same data as the YAML export | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_format` | pass |
| `cli.format.invalid` | `--format xml` | Usage error naming the bad value; no file is written | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_format_invalid` | pass |
| `cli.validate` | `--validate` | Counts of works, people and projects, plus any unresolved authors, warnings and unknown projects | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_validate` | pass |
| `cli.validate.agrees_with_output` | `--validate` in each format, over the valid corpus and every invalid fixture, and over a document with a NaN put into `lab` after loading | Exits 0 only where `--output` in that format writes a document; the injected NaN is reported as `CONFIG-VALUE-NOT-JSON` at `lab.yaml:lab:ratio` by both, which exit 1 and write nothing | `tests/corpus/valid/lab.yaml` | `test_invalid_corpus.py::test_validate_passes_only_what_output_writes`, `test_diagnostics.py::test_validate_fails_on_what_serializing_refuses` | pass |
| `cli.unresolved` | `--unresolved` | Lists exactly the author names that did not resolve | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_unresolved` | pass |
| `cli.unresolved_none` | `--unresolved` when every author resolves | Lists nobody | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_unresolved_none` | pass |
| `cli.help` | `--help` | Names every flag | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_help` | pass |

## Messages sslabdata prints
Every message sslabdata can print on its own behalf. Tests match on the file,
key, field and value in a message, never on its English wording, so rewording
a message does not break them.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `diag.wrote` | A successful `--output` run | Names the file written and the counts | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_output_creates_parent_dirs` | pass |
| `diag.validation_passed` | `--validate` with nothing wrong | Exits zero and closes with a line of its own after the counts | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_validate_closes_with_a_summary_line` | pass |
| `diag.unresolved_authors` | `--validate` or `--unresolved` with external co-authors | Lists them; unresolved externals are not errors | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_unresolved` | pass |
| `diag.all_resolved` | `--unresolved` with nothing to report | Prints exactly one line and lists nobody | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_unresolved_none` | pass |
| `diag.config_not_found` | `--config` naming a file that is not there | Names the file; exits non-zero | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_config_not_found` | pass |
| `diag.mode_required` | No mode flag | Names the flags that would be valid | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_mode_required` | pass |
| `diag.format_invalid` | `--format xml` | Names the bad value and the valid ones | `tests/corpus/valid/lab.yaml` | `test_config_cli.py::test_cli_format_invalid` | pass |

## Output fields
Every field of the generated `lab.yml` / `lab.json`, and the checks on the file
as a whole. The structure is defined by
[`schema/v5/output.schema.json`](../schema/v5/output.schema.json).

Every closed object declares every property it can carry, and a value that
does not apply is `null` rather than absent. The open maps — `lab`, `links`,
`identifiers` and every `derived` bag — carry only the keys that have values,
because emitting nulls over an unbounded key set says nothing.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `output.schema_version` | Any run | The output carries `schema_version` 5 | `tests/corpus/valid/lab.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.generator` | Any run | `generator` names the compiler, its package version and the schema version, and carries no timestamp | `tests/corpus/valid/lab.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.lab` | A `lab:` section in the config | Copied through to `lab`, which is always emitted — `{}` when there is no header, so a consumer can tell that from a header with nothing in it | `tests/corpus/valid/lab.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.bib_id` | The citation key | `bib_id` | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.source` | The `bib_files` entry the file was listed under | `source: {file, key}`, where `file` is the configured name and never a path | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.title` | `title` | `title`, as plain text | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.authors` | `author` | `authors`: one authorship per name, in source order, each with `name`, `position`, the four name parts plus `literal`, `resolution`, `derived`, and exactly one of `person_id` and `collaborator_key` | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.editors` | `editor` | `editors`: the same record without a grouping key or an equal-contribution marker; `[]` when the entry names none | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.year` | `year` | `year`, as an integer, or null when the entry supplied none | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.venue` | The container field for the entry type | `venue: {kind, name}`, or null when the entry names no container | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.bibliographic` | `volume`, `number`, `pages`, `series`, `edition`, `publisher`, `address`, `organization`, `chapter`, `month`, `howpublished`, `type` | Each flat on the work under BibTeX's own name, and null when the entry wrote none | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.category` | The `bib_files` category of the file the entry came from | `category` | `tests/corpus/valid/lab.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.entry_type` | The `@type` of the entry | `entry_type`, lower-cased | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.abstract` | `abstract` | `abstract`, or null | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.note` | `note` | `note`, or null | `tests/corpus/valid/latex.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.identifiers` | `doi`, `eprint`, `isbn`, `issn` | `identifiers`, an open map from scheme to a list of identifiers; `{}` when the entry carries none | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.links` | `url`, `pdf_base_url`, and the identifiers sslabdata builds links from | `links`, an open map from kind to a list of `{url, label, origin, verification}` | `tests/corpus/valid/links.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.link.verification` | Any link | `verification` is `{status}` and nothing else: a build never fetches and records no time | `tests/corpus/valid/links.bib` | `test_output_format.py::test_a_link_verification_is_only_its_status` | pass |
| `output.work.project_ids` | `project` or namespaced `keywords` | `project_ids` | `tests/corpus/valid/projects.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.bibtex` | The whole entry | `bibtex`, the copyable source, including fields sslabdata emits no property for; null when it could not be written back out | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.work.bibtex_round_trip` | `\%`, `\&`, `\_`, `\#`, a bare `%` and `&`, math, nested braces and a brace-protected name holding `\&`; and every entry of the valid corpus and the demo | Every field the entry writes as one braced or quoted value is in `bibtex` byte for byte, with whitespace read as BibTeX reads it: nothing already escaped is escaped again, and nothing bare is escaped. The name comes back as written too | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_bibtex_round_trips_every_field` | pass |
| `output.work.derived` | Any run | `derived`, an open bag reserved for sslabdata, `{}` today | `tests/corpus/valid/structure.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.id` | `id` in `people.yaml` | `id` | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.name` | `name` | `name` | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.role` | `role` | `role`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.status` | `status` | `status` | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.website` | `website` | `website`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.photo` | `photo` | `photo`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.email` | `email` | `email`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.co_advisor` | `co_advisor` | `co_advisor`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.start_year` | `start_year` | `start_year`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.end_year` | `end_year` on an alumnus | `end_year`, declared for everyone and null for anyone who has none | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.degree` | `degree` on an alumnus | `degree`, declared for everyone and null for anyone who has none | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.thesis_title` | `thesis_title` on an alumnus | `thesis_title`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.current_position` | `current_position` on an alumnus | `current_position`, or null | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.work_ids` | Works the person authored | `work_ids`, in works order; editors are not authorships and are not listed | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.person.derived` | Any run | `derived`, `{}` today | `tests/corpus/valid/people.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.id` | `id` in `projects.yaml` | `id` | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.title` | `title` | `title` | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.description` | `description` | `description`, or null | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.website` | `website` | `website`, or null | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.image` | `image` on one project and not on another | `image`, a URL or a site path carried as written and as plain text; declared and null where the project has none; neither draws a diagnostic | `tests/corpus/valid/projects.yaml` | `test_output_format.py::test_a_project_image_is_emitted_or_null_and_never_reported` | pass |
| `output.project.status` | `status` | `status` | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.work_ids` | Works tagged with the project | `work_ids` | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.people_ids` | Authors of those works who are lab members | `people_ids`, sorted | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.project.derived` | Any run | `derived`, `{}` today | `tests/corpus/valid/projects.yaml` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.key` | An authorship that resolved to nobody | `key`: a readable slug of the normalised name plus an always-present short digest. A lookup key, explicitly not an assertion about a human | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.grouped_by` | Any collaborator | `grouped_by`: `normalized_name`, or `declared` for a grouping `collaborators_file` asked for (row `identity.collaborator_alias`) | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.name_kind` | A parsed name, and a brace-protected one | `name_kind`, `personal` or `literal` — never `organization`, because braces mean "do not parse this" and cover mononyms too | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.name` | The spellings this key grouped | `name` is the first in document order, and the name parts beside it are that spelling's | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.name_variants` | Two spellings that normalise alike | `name_variants`, the distinct spellings, ascending | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.authorships` | The occurrences this key grouped | `authorships`, each `{work_id, position}`, in document order — the record a consumer that distrusts the grouping falls back to | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.work_ids` | Works that name the collaborator | `work_ids`, in document order, deduplicated | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.last_year` | The most recent of those works | `last_year`, or null when none of them has a year | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.collaborator.derived` | Any run | `derived`, `{}` today | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_output_fields` | pass |
| `output.no_duplicate_counts` | A person's works, and a collaborator's works and occurrences | No `work_count` or `authorship_count` anywhere: each would be the length of the `work_ids` or `authorships` emitted beside it | `tests/corpus/valid/names.bib` | `test_output_format.py::test_no_count_repeats_the_length_of_a_list` | pass |
| `output.collaborators.order` | Several collaborators, including three that share a year and a work count whose name order and key order disagree, two of them sharing a readable name | Sorted by last year descending with null last, then the number of `work_ids` descending, then name ascending, then key ascending. `key` is appended after `name`, not a replacement for it | `tests/corpus/valid/names.bib` | `test_valid_corpus.py::test_collaborators_order` | pass |
| `output.no_markup` | A title carrying Markdown punctuation, and the demo | Nothing sslabdata composes is Markdown or HTML; punctuation that survives is input text, and no string in the corpus or the demo holds `<http`, an autolink or a Markdown link the input did not write | `tests/corpus/valid/latex.bib` | `test_output_format.py::test_markup_in_the_corpus_is_only_text_the_input_wrote` | pass |
| `output.derived_is_empty` | The corpus and the demo | Every `derived` bag is `{}`, so the region cannot quietly fill | `tests/corpus/valid/lab.yaml` | `test_output_format.py::test_every_derived_bag_is_empty` | pass |
| `output.schema` | The valid corpus output | Validates against the JSON Schema, which rejects unknown fields and an authorship carrying two contributor references or none | `tests/corpus/valid/lab.yaml` | `test_output_format.py::test_valid_corpus_matches_schema` | pass |
| `output.versioned_schema` | The published schemas | v5 lives at its own path, and v3 and v4 stay reachable byte for byte, still saying 3 and 4 | `schema/v3/output.schema.json` | `test_output_format.py::test_the_previous_schema_stays_reachable_unchanged` | pass |
| `output.demo_schema` | The Example Lab demo output | Validates against the same schema, in both formats | `examples/demo/lab.yaml` | `test_output_format.py::test_demo_matches_schema` | pass |
| `output.yaml_json_same` | The same run exported twice | The YAML and JSON exports hold the same data | `tests/corpus/valid/lab.yaml` | `test_output_format.py::test_yaml_and_json_hold_the_same_data` | pass |
| `output.full` | The valid corpus entries no open issue owns | Match `tests/corpus/expected/valid.yaml`, compared as parsed data | `tests/corpus/valid/lab.yaml` | `test_output_format.py::test_full_output` | pass |

## Consumer probes
The probes in `examples/consumers/` read the emitted document and nothing
else, and run against the demo in CI. The rows here are the identity
scenarios asserted over the node and edge sets `graph.py` builds.

A grouping keyed on the normalised full name keeps `priya patel`, `p patel`
and `pradeep patel` as three keys, and by construction does not join two
spellings of one person. `collaborators_file` joins them when a human
declares the alias.

| Case | Input | Expected | Fixture | Test | Status |
|---|---|---|---|---|---|
| `probe.identity_fixtures` | The demo document: one external co-author on three works in two spellings, a second with the same first initial and family name on a fourth, and two different people under one written name on a fifth | All four scenarios are present, with the given names kept apart on the authorships and one display name across all of them | `examples/demo/lab.yaml` | `test_consumer_probes.py::test_identity_fixtures_are_present` | pass |
| `probe.identity_one_person` | `Patel, Priya` on two works and `Patel, P.` on a third | Exactly one contributor in the `collaborator:` namespace touches any of the three works, and it holds exactly those three | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_graph_joins_one_co_author_written_two_ways` | pass |
| `probe.identity_distinct_people` | `Patel, Pradeep` on a fourth work | Exactly one contributor in the `collaborator:` namespace holds that work, it holds exactly that work, and it shares no contributor with the three above | `examples/demo/bib/books.bib` | `test_consumer_probes.py::test_graph_separates_co_authors_sharing_an_initial` | pass |
| `probe.identity_authorship` | `Lee, Lin and Lee, Lin`, two different people on one work | The document declares each authorship's `position`, and the graph carries two `authored` edges at those two positions from **one** contributor: one grouping, two addressable authorships | `examples/demo/bib/conference.bib` | `test_consumer_probes.py::test_graph_keeps_two_authorships_written_alike_apart` | pass |
