# sslabdata specification

sslabdata is a compiler. It reads BibTeX and a little YAML and emits one
document describing a lab's works, people, projects and the links between
them.

This file states the parts of that contract a JSON Schema cannot express:
what the strings in the document are, what order the lists are in, what an
absent key means, which fields are computed, when the version changes, and
how a repeated `@string` macro resolves. `schema/v5/output.schema.json`
states the rest.

Everything here is normative unless it carries a `Target` note. A `Target`
note marks a rule that the emitted document does **not** satisfy today, and
names the issue that will make it true. Until that issue lands, the rule is
the intent and the note is the fact. A `Version note` marks behaviour that
changed at a known release boundary, and states both sides.

- Applies to: `schema_version` 5 (`sslabdata.models.SCHEMA_VERSION`), package
  version 3.0.0 (`sslabdata.__version__`).

### How this file cites the code

Every rule below is grounded in a named part of the code rather than a line
number, because line numbers rot silently: a function such as
`sslabdata.parsers.bibtex.parse_all_works()`, a method such as
`Person.to_dict()`, a module-level constant such as `TEXT_FIELDS`, a JSON
Pointer into `schema/v5/output.schema.json` such as `/$defs/person/required`, or
a `tests/COVERAGE.md` row key such as `config.people_file.missing`. A bare
statement is cited by its enclosing function.

Nothing yet checks that these references resolve; #63 proposes the test that
would.

---

## 1. Contract hierarchy

**The emitted document plus its published schema is normative.** Everything
else in this repository — the CLI's internals, the Python classes — exists
to produce that document.

**When the emitted document and the schema disagree, the schema wins and the
code is the bug.** A consumer that validates against the published schema and
is rejected by sslabdata's own output has found a defect in sslabdata, never in
itself.

**If a consumer probe cannot be written from the emitted document alone, that
is a schema bug, not a probe bug.** The document is the whole contract, so a
consumer that needs a property the document does not carry has found a gap in
the document; the fix belongs in the schema, not in the consumer. Recovering
the property from `work.bibtex` does not close the gap, because that
record is an opaque re-serialization of the entry rather than a set of
first-class properties (§5), and neither does taking a composed string such
as `venue` apart. `examples/consumers/` holds three such probes — a LaTeX CV
fragment, a CSL-JSON export and a person/project/work edge list — each reading
the document and nothing else, and
`tests/conformance/test_consumer_probes.py` runs every one of them against the
demo output. Under `schema_version` 3 none of them could produce correct
output; `schema_version` 4 closed every one of those gaps but one. Their
failing assertions are marked `xfail(strict=True)` against **the issue that
owns the missing property**. The last of them was #24's, which asked for two
spellings of one external co-author to be joined — something a grouping keyed
on a name cannot do by construction — and it passes now that
`collaborators_file` can declare the alias (§5). A strict `xfail` swallows every failure
in its test, including one in something the probe already does correctly, so
such a test is kept to the assertions that name the missing property — and,
for the prerequisites it cannot avoid relying on, the rule is: **every
prerequisite an xfailed test already satisfies is independently enforced by a
test that passes.** The identity test that was xfailed reads the graph's
`authored` edges; the passing `test_graph_is_well_formed` asserts that every
one of them matches the document, and the passing
`test_identity_fixtures_are_present` asserts that the works it is about are
still there, so neither prerequisite was checked only inside a marker.
`examples/consumers/README.md` lists what each probe asserts.

**The CLI is the reference compiler.** Its flags, its exit codes and the
stream each kind of message goes to are public API.

Flags, as `sslabdata.cli.main()` defines them:

| Flag | Meaning |
|---|---|
| `--config PATH` | Required. The `lab.yaml` to compile. |
| `--format {yaml,json}` | Default `yaml`. It has **two meanings**. With `--output` alone it is the **document's** format, and diagnostics stay on standard error as text. With `--validate` or `--unresolved`, `json` prints the **diagnostics** as one JSON array on standard output instead of the text report (*Diagnostics as JSON* below), and `yaml` is the text report. |
| `--output PATH` | Write the document to `PATH`. The document is written in full to a temporary file beside `PATH` and then moved over it, so a failed write leaves any file already there as it was and creates none. |
| `--validate` | Report counts and problems, then exit without writing. |
| `--unresolved` | List author names that matched no person, then exit. A name left ambiguous is one of them. |
| `--strict` | Combines with any mode. Every coded diagnostic is an error except those the class table below marks as never an error: a redefined `@string` macro, and anything about an author who matched no lab member. Any error exits `1`, and an export writes nothing. Without it, the exit codes below are unchanged. |

**At least one** of `--output`, `--validate` or `--unresolved` is required —
not exactly one. `sslabdata.cli.main()` rejects only the case where all three
are absent, so combinations are accepted and resolved by **precedence**:
`--validate` is handled first and returns; `--unresolved` next; `--output`
only if neither was given. So `sslabdata --config c.yaml --validate --output
out.yml` runs validation and reports normally, but **does not write
`out.yml`**, and exits `0`. Verified by running both combinations.

Exit codes, as `sslabdata.cli.main()` returns them:

| Code | Meaning |
|---|---|
| `0` | Success. `--output` wrote the file; `--validate` found no errors; `--unresolved` reported. |
| `1` | Error. Configuration file missing, or configuration failed to load — unreadable, a `bib_files[].name` that is absolute or leaves `bib_dir`, or a `lab.yaml` of the wrong shape; a file the configuration names is not there; a people file cannot be read as records; an entry carries `crossref`; `--validate` found unknown project ids or duplicate citation keys, person ids or project ids; or, under `--strict`, any coded diagnostic that the class table does not keep as a warning. The *Diagnostic codes* table below gives the class of each. |
| `2` | Usage error from the argument parser: a missing or unrecognised flag, or none of `--output` / `--validate` / `--unresolved`. |

**Streams and message shapes.** Ordinary reporting goes to **standard
output**: the counts and unresolved names of
`--validate` and `--unresolved`, and, in output mode, the `Wrote …` line and
the entity counts that follow it. **Diagnostics** go to **standard error**,
except where `--validate` gathers them into its report on standard output,
and except with `--format json` beside `--validate` or `--unresolved`, where
standard output holds one JSON array and nothing else (*Diagnostics as JSON*
below). **Every diagnostic carries a code**, and every line of one does: a
message is kept to one line. As text there are three shapes:

| Shape | Stream | Source |
|---|---|---|
| `<CODE> <file>:<key>:<field>: …` | see right | A diagnostic raised **during assembly**, described under *Diagnostic codes* below. Under `--validate` it is on standard **output**, beneath `Bibliography errors` when it fails the run and beneath `Warnings` when it does not. In the other modes it is on standard **error**: prefixed `Warning: ` when it is a warning, unprefixed when it fails the run. |
| `Error: <CODE> …` and `Error loading configuration: <CODE> …` | standard error | Configuration failures, from `sslabdata.cli.main()`: every fatal-at-load code. A configuration sslabdata cannot find, cannot read or will not compile from, in **every** mode including `--validate`, because nothing is assembled and there is no report to gather it into. `Error: ` precedes `CONFIG-NOT-FOUND`; `Error loading configuration: ` precedes the others, for example `Error loading configuration: CONFIG-BIB-FILE-ABSOLUTE lab.yaml:bib_files:name: …`. |
| `usage: …` / `…: error: …` | standard error | Argument errors, in the argument parser's own format. They are not diagnostics and carry no code. |

There is no single prefix across all diagnostics. A consumer looking for a
**code** should search the whole line rather than anchor at its start,
because of the second shape — or read `--format json`, which needs no
parsing of text at all.

**Where the severities live.** `sslabdata.assembler.AssemblyResult` carries the
diagnostics that survive assembly in one list, `diagnostics`, in the order
every report lists them: fatal codes first, then validation errors, then
warnings, each class in the order it was found. A diagnostic's severity is
not stored with it; it follows from its class and the run
(`sslabdata.diagnostics.severity()`). Fatal codes fail every mode, validation
errors fail `--validate` and are warnings elsewhere, and warnings never fail
anything. A fourth class never reaches an `AssemblyResult` at all, because it
stops the configuration from loading. The table under *Diagnostic codes*
below says which class each code belongs to.

**Unresolved authors are not errors**, not even under `--strict`.
`--validate` lists them and still exits `0`. This is intended, not a gap: an author who is not in `people.yaml`
is usually an external collaborator, and #26 states the rule (decision 10):
**an author who matched no lab member is never an error under `--strict`**,
because sslabdata cannot tell an outside co-author from a possible member
until #25 lets an author be declared external. The known cost is that a
misspelt member's name passes `--strict`, reported only as a
`RESOLVE-SUGGESTION` warning; #25 revisits this. What fails the run is
a defect in data sslabdata does own: a project id naming no project, a
repeated citation key, person id or project id, and the fatal conditions in
the class table below.

> **Target (#80).** An unhandled failure prints a Python traceback and also
> exits `1`, so `1` does not by itself distinguish a diagnosed error from a
> crash. Ordinary malformed input does not do this: a `.bib` file that does
> not exist or is not UTF-8, a `year` that is not a number, and a people,
> projects or collaborators file that is not valid YAML or not a list of
> records are each reported under a code (`CONFIG-FILE-NOT-FOUND`,
> `BIB-ENCODING-INVALID`, `BIB-YEAR-INVALID`, `PEOPLE-YAML-INVALID` and the
> rows beside it).

**Diagnostic *prose* is not stable**, though every diagnostic carries a code
and a location. A message the BibTeX parser raises that is neither a syntax
error nor an undefined macro is coded `BIB-PARSER-MESSAGE` but keeps that
library's wording as its prose, and so does `CONFIG-UNREADABLE`. Consumers
may depend on the stream, the shapes above, the codes in the registry below
and the JSON records, not on the wording of a message.

### Diagnostic codes

A diagnostic may carry a **stable code** so that tooling can recognise it
without depending on English wording. Codes obey three rules:

1. The form is `<COMPONENT>-<CONDITION>` in upper case, for example
   `BIB-DUPLICATE-KEY`, followed by a space, then `<file>:<key>:<field>`, then
   a colon and prose. A part of the location that does not apply is left
   empty and its separator kept: `CONFIG-NOT-A-MAPPING lab.yaml::: …` names a
   file and nothing in it, and `CONFIG-KEY-MISSING lab.yaml:bib_dir:: …` a
   top-level key with no field under it. For a configuration file, `<key>` is
   the top-level key and `<field>` the key under it; for a people or projects
   file, `<key>` is the record's `id`.
2. **Severity is not part of the code.** A code says *what was found*, never
   how badly the run took it. Severity belongs to the condition and the mode
   together, and four classes are in use:

   | Class | `--validate` | Every other mode | Codes |
   |---|---|---|---|
   | **Fatal at load** | `Error loading configuration: <CODE> …` (`Error: <CODE> …` for `CONFIG-NOT-FOUND`) on standard error; exits `1` before anything is compiled, so there is no report. | The same. | `CONFIG-BIB-FILE-ABSOLUTE`, `CONFIG-BIB-FILE-OUTSIDE-BIB-DIR`, `CONFIG-NOT-A-MAPPING`, `CONFIG-KEY-MISSING`, `CONFIG-TYPE-INVALID`, `CONFIG-NOT-FOUND`, `CONFIG-UNREADABLE` |
   | **Fatal** | Listed under `Bibliography errors` and counted; exits `1`. | Written to standard error unprefixed; exits `1`, and `--output` writes nothing. | `BIB-CROSSREF-UNSUPPORTED`, `BIB-ENCODING-INVALID`, `CONFIG-FILE-NOT-FOUND`, `PEOPLE-YAML-INVALID`, `PEOPLE-NOT-A-LIST`, `PEOPLE-FIELD-MISSING`, `PROJECTS-YAML-INVALID`, `PROJECTS-NOT-A-LIST`, `PROJECTS-FIELD-MISSING`, `COLLABORATORS-YAML-INVALID`, `COLLABORATORS-NOT-A-LIST`, `COLLABORATORS-FIELD-MISSING` |
   | **Validation error** | Listed under `Bibliography errors` and counted; exits `1`. | Prefixed `Warning: ` on standard error; the run continues and exits `0`. | `BIB-DUPLICATE-KEY`, `RESOLVE-PROJECT-UNKNOWN`, `PEOPLE-ID-DUPLICATE`, `PROJECTS-ID-DUPLICATE` |
   | **Warning** | Listed under `Warnings`; not counted, and does not change the exit code. | Prefixed `Warning: ` on standard error; the run continues. | `BIB-YEAR-MISSING`, `BIB-YEAR-INVALID`, `BIB-STRING-UNDEFINED`, `BIB-SYNTAX-ERROR`, `BIB-VENUE-MISSING`, `BIB-ENTRY-TYPE-UNSUPPORTED`, `LATEX-COMMAND-UNKNOWN`, `ID-GROUPING-SPANS-SPELLINGS`, `ID-GROUPING-INITIALS-AMBIGUOUS`, `RESOLVE-AMBIGUOUS-NAME`, `RESOLVE-SUGGESTION`, `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER`, `PEOPLE-ALIAS-AMBIGUOUS`, `PEOPLE-ROLE-INVALID`, `PEOPLE-STATUS-INVALID`, `PROJECTS-STATUS-INVALID`, `CONFIG-LAB-NAME-MISSING`, `CONFIG-KEY-UNKNOWN`, `RECORD-KEY-UNKNOWN`, `RECORD-TYPE-INVALID`, `CONFIG-BIB-FILES-MISSING`, `BIB-PARSER-MESSAGE`, `LATEX-CONVERSION-FAILED`, `BIB-WRITE-BACK-FAILED`, `BIB-STRING-REDEFINED`, `ID-GROUPING-AMBIGUOUS-DECLARED`, `RESOLVE-UNRESOLVED-NAME` |

   The same code always carries the same class. What varies with the mode is
   how the run reacts to it, which is why the class is not in the code, and
   why a consumer reads the exit code and the stream rather than the
   spelling.

   **Under `--strict`**, in every mode, every code is an **error** except
   six, which stay **warnings** (`sslabdata.diagnostics.NEVER_AN_ERROR`). Five
   of them follow one rule, #26 decision 10: **an author who matched no lab
   member is never an error under `--strict`**, because sslabdata cannot tell
   an outside co-author from a possible member until #25 lets an author be
   declared external.

   | Code | Why it is never an error |
   |---|---|
   | `BIB-STRING-REDEFINED` | Decided on #26: BibTeX's own last-wins rule settles a redefinition (§7), so it is reported and never fails a run. |
   | `ID-GROUPING-SPANS-SPELLINGS`, `ID-GROUPING-INITIALS-AMBIGUOUS`, `ID-GROUPING-AMBIGUOUS-DECLARED` | Decision 10: each is about how authors who matched no lab member are grouped. |
   | `RESOLVE-UNRESOLVED-NAME` | Decision 10: it *is* an author who matched no lab member. |
   | `RESOLVE-SUGGESTION` | Decision 10: it is an author who matched no lab member, whose name is close to a member's. It may be a misspelt member or an outside co-author with a similar name, and sslabdata cannot tell which. The known cost: a misspelt member's name passes `--strict` with this warning, until #25 revisits it. |

   So a fatal code is an error in every mode with or without `--strict`; a
   validation error is an error under `--validate`, and under `--strict` in
   every mode; a warning is an error under `--strict` unless it is one of
   the six. Under `--strict` an error is reported where a fatal one is — under
   `Bibliography errors` with `--validate`, unprefixed on standard error
   otherwise, `"severity": "error"` in JSON — the run exits `1`, and
   `--output` writes nothing, leaving any file already at that path as it
   was.
3. A published code is permanent. It is never reused for a different
   condition, and retiring one is a breaking change.

Codes in use:

| Code | Condition |
|---|---|
| `BIB-DUPLICATE-KEY` | The same citation key appears twice in one `.bib` file, or in two of the configured files. A validation error. |
| `BIB-CROSSREF-UNSUPPORTED` | An entry carries a `crossref` field. Reported on the field's **presence**, whatever its value: an empty `crossref = {}` is a field the entry carries. The diagnostic names the file, the entry key and the parent key, or says the entry names no parent when the field is empty; the entry is not emitted and the run fails, in every mode. |
| `BIB-YEAR-MISSING` | An entry has no `year` field. The work is emitted with `year: null` and sorts last. A warning. |
| `ID-GROUPING-SPANS-SPELLINGS` | One collaborator key grouped more than one distinct spelling of a name. Reported against the first authorship the key grouped. A warning, in every mode including under `--strict`: an author who matched no lab member is never an error (#26 decision 10). |
| `ID-GROUPING-INITIALS-AMBIGUOUS` | A collaborator key whose given name is nothing but initials could be one of the fuller keys under the same family name. Decided on the **structured parts** — the initials of the given name against a fuller given name, with the family name and the surname particles equal, and the shorter run of initials a prefix of the longer, and two lineage suffixes that disagree ruling the pair out — so a particle, a second initial, a hyphenated family name, a suffix and a letter outside ASCII are all seen. Reported against the first authorship the key grouped, naming every fuller key. A warning in every mode, for the same reason. |
| `RESOLVE-AMBIGUOUS-NAME` | An author or editor name fits more than one **lab member**, so it is given no `person_id` and `resolution.status` is `ambiguous`. Located at the work — `<bib_dir>/<file>:<key>:author` or `:editor` — with the position and every id it fits in the prose. A warning; an error under `--strict`, because it is about lab members, whom sslabdata does own. **Narrowed** by #26 decision 6: until then it also covered an unresolved authorship that fits a declared collaborator and someone else, which is now `ID-GROUPING-AMBIGUOUS-DECLARED`. No release carried the wider meaning. |
| `RESOLVE-SUGGESTION` | An author or editor name matched no person but is close to one: its initials fit a person's name that declares no such alias, or it is a near miss on string similarity. Nothing is linked. Located as above, naming the position and the suggested ids. A warning in every mode, including under `--strict`: an author who matched no lab member is never an error (#26 decision 10), because sslabdata cannot tell an outside co-author from a possible member until #25. The known cost is that a misspelt member's name passes `--strict` with only this warning. |
| `ID-GROUPING-AMBIGUOUS-DECLARED` | An unresolved name fits more than one `collaborators_file` entry, or one entry and one lab member it did not resolve to, so it joins none of them and is grouped by its own name (#26 decisions 6 and 10). Located like `RESOLVE-AMBIGUOUS-NAME`, naming every candidate (`collaborator:<name>`, `person:<id>`). A warning in every mode, including under `--strict`: an author who matched no lab member is never an error. Two other codes can accompany it for the same authorship. When the name fits one entry and **one** lab member — `Patel, P.` beside an entry declaring `P. Patel` and a member Paul Patel who declares no such alias — the resolver also reports `RESOLVE-SUGGESTION` for that member, before this code; both are warnings under #26 decision 10, so `--strict` passes. When it fits one entry and **more than one** lab member, it is also reported here, and `RESOLVE-AMBIGUOUS-NAME` reports the members' ambiguity first, with no `RESOLVE-SUGGESTION`; that one is an error under `--strict`. |
| `RESOLVE-UNRESOLVED-NAME` | One author name that matched no person, as `--unresolved --format json` lists them: one record per name `--unresolved` would print, in the same order. Located at the first authorship, in document order, written that way and linked to nobody; the message is the name itself, with any line break as a space. Emitted **only** by `--unresolved --format json`; the text modes list these names as before, and `--validate --format json` carries only the other codes. A warning in every mode, including under `--strict` (#26 decision 10). |
| `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER` | A `collaborators_file` `name` or alias equal to a lab member's name or alias. The member keeps the spelling and the collaborator entry is not used for it. Located at `<collaborators_file>:<collaborator name>:name` or `:aliases`. A warning. |
| `CONFIG-LAB-NAME-MISSING` | The `lab` header declares no `name`. A `lab` that is not a mapping at all is a different condition and is not reported under this code. A warning. |
| `BIB-YEAR-INVALID` | An entry's `year` is present but is not a number (`int()` rejects it), such as `in press`. The work is emitted with `year: null` and sorts last, as one with no year does. A warning. |
| `BIB-STRING-UNDEFINED` | A field value names an `@string` macro that nothing defined earlier in the same file. Located at the entry and field that use it, and naming the macro. It is read as empty, as BibTeX reads it, and the entry and its neighbours are kept. A macro used inside another `@string` definition is located at the file alone. A warning. |
| `BIB-STRING-REDEFINED` | One or more `@string` macros are defined more than once. One line per run, however many files and macros: the count, the macros and every redefinition as `file:line` (§7). Only definitions the parser reads count, so one inside an `@comment` group does not, while a well-formed `@string{…}` on a `%` line does: the parser reads it, as it does on `main`, and it changes the macro's value. Whether it should be read is #78. The last definition is used, as in BibTeX. A warning in every mode, including under `--strict`. |
| `BIB-SYNTAX-ERROR` | Text the BibTeX parser cannot read. Inside an entry, located at that entry and at the field the parser was reading or had just read, which is where an unclosed brace or quote leaves it, or with the field left empty when the error comes before any field; the entry is kept as far as it was read, so that value may hold text meant for later fields. Outside any entry — an `@` that begins no well-formed command — located at the file alone and skipped. A syntax error the parser library raises on a `%` line outside any entry — prose that mentions `@article`, say, which the library reads as the start of a command — is not reported (`sslabdata.parsers.bibtex._on_comment_line()`), so the prose `tests/COVERAGE.md` rows `structure.comment_lines` and `structure.comment_mentions_command` describe says nothing. A **well-formed** command on such a line is read, as it is on `main` and in classic BibTeX, which has no `%` comment outside an entry: `% @article{hidden, …}` is an entry. Whether it should be is #78. The prose gives the line. A warning. |
| `BIB-VENUE-MISSING` | An `@article` has no `journal`, or an `@inproceedings` has no `booktitle` (`sslabdata.parsers.bibtex.REQUIRED_CONTAINER`). No other entry type is checked. A field present but empty counts as missing. The entry is kept, and its venue is read by the usual rule from any other container field it carries, or is `null`. A warning. |
| `BIB-ENTRY-TYPE-UNSUPPORTED` | An entry's type is not one sslabdata documents. Those are `@article`, `@inproceedings`, `@conference`, `@proceedings`, `@incollection`, `@inbook`, `@book`, `@phdthesis`, `@mastersthesis`, `@techreport`, `@manual` and `@misc` (`sslabdata.parsers.bibtex.SUPPORTED_TYPES`); `@unpublished` and `@booklet`, for two, are not. Located at `<file>:<key>:entry_type`. The entry is kept, and its venue is read by the field rules alone. A warning. |
| `LATEX-COMMAND-UNKNOWN` | A text field or a name uses a LaTeX command sslabdata's conversion has no rule for (`sslabdata.parsers.latex.unknown_commands()`): one outside the converter's table and not one of the two whose conversion sslabdata documents, `\textsuperscript{…}`, which becomes its argument, and the escaped star `\*`, which is consumed (`tests/COVERAGE.md` rows `names.equal_contribution` and `names.equal_contribution_escaped`). The command is dropped and a braced argument after it is kept as plain text, so no raw LaTeX reaches the document. Math is not searched. One line per command for the whole run, however many fields use it: the number of fields, located at the first of them in document order. A warning. |
| `RESOLVE-PROJECT-UNKNOWN` | A work's `project` field names an id `projects_file` does not define. Located at `<bib_dir>/<file>:<key>:project`, naming the id. The id stays on the work (§5). A validation error. |
| `PEOPLE-YAML-INVALID` | `people_file` is not valid YAML, or not UTF-8. Located at the file alone; the prose is the YAML library's own wording, on one line, and gives the line and column. Fatal, as a `lab.yaml` that cannot be read is. |
| `PEOPLE-NOT-A-LIST` | `people_file` is not a list of records, or an entry of the list is not a mapping. Located at the file alone. An empty file is no records, and is not reported. Fatal: nothing is emitted from a file that cannot be read as records. |
| `PEOPLE-FIELD-MISSING` | A person has no `id` or no `name`, or an empty one, or one that is not a string: a number, a list or a boolean is never read as text. Located at `<people_file>:<id>:name`, or `<people_file>::id` for a person with no usable id. The record is not loaded, and the run is fatal: a document cannot carry a person with no id or name. |
| `PROJECTS-YAML-INVALID`, `PROJECTS-NOT-A-LIST`, `PROJECTS-FIELD-MISSING` | The same three conditions for `projects_file`, checked by the same code (`sslabdata.loaders._records()`). A project needs an `id` and a `title`, each a non-empty string. Fatal. |
| `COLLABORATORS-YAML-INVALID`, `COLLABORATORS-NOT-A-LIST`, `COLLABORATORS-FIELD-MISSING` | The same three conditions for `collaborators_file`. A collaborator needs a `name`, a non-empty string, and a missing one is located at `<collaborators_file>::name`. Fatal. |
| `BIB-ENCODING-INVALID` | A `.bib` file is not UTF-8. Located at the file alone; the prose names the first byte that cannot be read and its line. No other encoding is tried, because a wrong guess would silently change names. Fatal: the file's works are not read. |
| `PEOPLE-ID-DUPLICATE` | Two people declare one `id`. Located at the second. Both are kept, as a repeated citation key is. A validation error. |
| `PEOPLE-ROLE-INVALID` | A person's `role` is missing, empty or not a string. Located at `<people_file>:<id>:role`. A role that is not a string is emitted as `null`. A role is otherwise open: any non-empty string is accepted, so no list of roles is checked. A warning. |
| `PEOPLE-STATUS-INVALID` | A person's `status` is present and is not `current` or `alumni`. Located at `<people_file>:<id>:status`, naming the value. A missing status reads as `current`, and so does one that is not a string. A warning. |
| `PEOPLE-ALIAS-AMBIGUOUS` | One spelling, compared through `normalize_name()`, is declared as a name or alias by more than one person, so a name written that way fits all of them and resolves to none. Located at the second person to declare it, under `name` or `aliases`, naming every person who does. A warning, as the `RESOLVE-AMBIGUOUS-NAME` it leads to is. |
| `PROJECTS-ID-DUPLICATE` | Two projects declare one `id`. Located at the second. Both are kept. A validation error. |
| `PROJECTS-STATUS-INVALID` | A project's `status` is present and is not `active` or `completed`. A missing status reads as `active`, and so does one that is not a string. A warning. |
| `RECORD-KEY-UNKNOWN` | A person, project or collaborator record holds a key sslabdata does not read (`sslabdata.loaders.PERSON_KEYS`, `PROJECT_KEYS`, `COLLABORATOR_KEYS`), such as `hobby` or a misspelt `webiste`. One code for all three files. Located at `<people_file>:<id>:<key>`, `<projects_file>:<id>:<key>` or `<collaborators_file>:<collaborator name>:<key>`, once per key. The key is ignored and never emitted; the record is kept. Only a record that is loaded is checked, so a record missing a required field reports that alone. A warning. |
| `RECORD-TYPE-INVALID` | An optional field of a person, project or collaborator record has a value of the wrong type, other than the `role` and `status` that have codes of their own. A person's `photo`, `website`, `email`, `co_advisor`, `degree`, `thesis_title` and `current_position`, and a project's `description`, `website` and `image`, are strings; a person's `start_year` and `end_year` are integers, not booleans; a person's or collaborator's `aliases` is a list of non-empty strings. One code for all three files, located at `<file>:<id>:<field>` (a collaborator's name for its id). The value is read as empty, so it is emitted as `null`, and a wrong `aliases` declares none; the record is kept. Only a record that is loaded is checked. A warning. |
| `CONFIG-NOT-A-MAPPING` | `lab.yaml` is not a mapping of keys, or is empty. Fatal at load. |
| `CONFIG-KEY-MISSING` | A required key is absent: `bib_dir`, or the `name` or `category` of a `bib_files` entry (`lab.yaml:bib_files:name`). Fatal at load. |
| `CONFIG-TYPE-INVALID` | A key has a value of the wrong type: `bib_dir`, `pdf_base_url`, `people_file`, `projects_file` or `collaborators_file` that is not a string, `lab` that is not a mapping, a `lab` key the schema types (`name`, `description`, `institution`, `department`, `website`, `email`, `address` and `logo` are strings, `links` a mapping) whose value is another type or empty, or `bib_files` that is not a list. A `bib_files` entry is a mapping of a string `name` and a string `category` and nothing else: one that is not a mapping, whose `name` or `category` is not a string, or that holds another key is this code too, located at `lab.yaml:bib_files:<field>`. Fatal at load. |
| `CONFIG-KEY-UNKNOWN` | `lab.yaml` holds a key sslabdata does not read (`sslabdata.config.KNOWN_KEYS`), such as a misspelt `people_fil`. It is ignored. A warning. |
| `CONFIG-BIB-FILES-MISSING` | No `bib_files` are configured, absent or empty, so the document has no works. A warning: that can be meant, but it is never silently normal. |
| `CONFIG-FILE-NOT-FOUND` | A file the configuration names is not there: a `bib_files` entry under `bib_dir` (`lab.yaml:bib_files:name`), `people_file`, `projects_file` or `collaborators_file`. Named with the path it looked for. Fatal: compiling on would emit a document without that file's works, people or projects. |
| `BIB-PARSER-MESSAGE` | The BibTeX parser library raised a message that is neither a syntax error nor an undefined macro — a field repeated within one entry, or a name list it cannot split. The prose is the **library's own wording**, kept as it phrased it. Located at the file, and at the entry key when the library raised it while reading one; the field is left empty. The entry is kept as the library read it. A warning. |
| `LATEX-CONVERSION-FAILED` | A text field or a name part whose LaTeX the converter could not read at all. Its text is kept as written, with the braces taken off, so it may still hold LaTeX (§2, *Two degraded cases*). Located at the entry and field. A warning. |
| `BIB-WRITE-BACK-FAILED` | An entry that could not be written back out as BibTeX. Its `bibtex` is `null`. Located at `<file>:<key>:bibtex`. A warning. |
| `CONFIG-NOT-FOUND` | The `--config` file does not exist. Located at that path alone; `Error: CONFIG-NOT-FOUND …` on standard error. Fatal at load. |
| `CONFIG-UNREADABLE` | The `--config` file exists but cannot be read — not valid YAML, not UTF-8, or a file the operating system will not open — or another input file, such as a `people_file`, exists but the operating system will not open it. Located at the `--config` path alone; the prose is the reading library's own wording, on one line. Fatal at load. |
| `CONFIG-BIB-FILE-ABSOLUTE` | A `bib_files[].name` is an absolute path, under POSIX or Windows rules. Fatal at load, because the name is emitted as `work.source.file`, which is promised never to be absolute. Raised as a `sslabdata.config.ConfigurationError` — its own type, so that a crash still reaches the user as a crash — by `LabDataConfig.from_yaml()`, by `BibFile` itself, by `assemble()` on every name it is about to compile, and by `Work.to_dict()`. **The last is the one that holds**, because it is the boundary every emitted document passes through: `BibFile` is a plain, mutable dataclass, so a name can be set after it was checked, and a `Work` can be built without a configuration at all. The three earlier checks stay because they fail sooner and say more — `from_yaml()` names the file the user would edit. |
| `CONFIG-BIB-FILE-OUTSIDE-BIB-DIR` | A `bib_files[].name` that does not stay under `bib_dir`. Fatal at load, because the file would be read from, and its name emitted as `work.source.file` relative to, a directory the configuration never named. Two checks, both made before any `.bib` is parsed and for every configured name. *Lexical*: the name is read by Windows rules on every host, so `/` and `\` both separate components; a `..` component, or a drive (`C:x.bib`, which is relative to a drive's directory and so not caught by `CONFIG-BIB-FILE-ABSOLUTE`), is rejected. *Resolved*: symlinks are followed, and the file, opened as `<bib_dir>/<name>` (so an empty `bib_dir` is the filesystem root), must lie inside the resolved `bib_dir`, compared by path components rather than by string prefix, so a sibling `bib_dir_evil` does not pass; a dangling symlink whose target is outside is rejected. A file that does not exist is not rejected here and keeps `CONFIG-FILE-NOT-FOUND`. An accepted name is emitted unchanged. The diagnostic is located at `lab.yaml:bib_files:name`. Raised as a `sslabdata.config.ConfigurationError` by `LabDataConfig.from_yaml()` and by `assemble()`. |

Every diagnostic sslabdata prints carries one of these codes (#26 decision
8). What is not a diagnostic carries none: the counts and headers of a
report, the `Wrote …` line, the argument parser's usage errors, and a Python
traceback, which is a crash (Target (#80) above).

### Diagnostics as JSON

`--format json` beside `--validate` or `--unresolved` prints, on standard
output, exactly **one JSON array** and nothing else, in every outcome —
including a configuration that fails to load, whose one record is then the
array. Each element is one diagnostic, and **these fields are a stable
interface**:

| Field | Type | Meaning |
|---|---|---|
| `code` | string | A code from the registry above. |
| `severity` | `"error"` or `"warning"` | How **this run** took it: by its class, the mode and `--strict`, as the class table says. |
| `file` | string or `null` | The `<file>` part of the location, as the text form writes it. |
| `key` | string or `null` | The `<key>` part. |
| `field` | string or `null` | The `<field>` part. |
| `message` | string | The prose after the location, on one line. Not stable wording. |

A location part that is empty in the text form is `null` here. The records
come in the order the text report would list them, the diagnostics of
assembly first. The exit code is the one the run would have had as text: `1`
when any record has `"severity": "error"`, else `0`. Standard error is empty.
The array, as JSON Schema — `tests/test_strict_json.py` validates the output
against this block:

<!-- diagnostics-json-schema -->
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["code", "severity", "file", "key", "field", "message"],
    "properties": {
      "code": {"type": "string", "pattern": "^[A-Z]+(-[A-Z]+)+$"},
      "severity": {"enum": ["error", "warning"]},
      "file": {"type": ["string", "null"], "minLength": 1},
      "key": {"type": ["string", "null"], "minLength": 1},
      "field": {"type": ["string", "null"], "minLength": 1},
      "message": {"type": "string", "pattern": "^[^\\n\\r]*$"}
    }
  }
}
```

What each mode puts in the array:

- `--validate --format json`: the coded diagnostics of the run and nothing
  else. The counts are not carried, and neither are the unresolved names:
  those appear only under `--unresolved`.
- `--unresolved --format json`: the same diagnostics, then one
  `RESOLVE-UNRESOLVED-NAME` record per name that matched no person. With no
  `people_file`, nothing was resolved and no such record is emitted.
- `--output` with `--format json` is the **document**, not this array; its
  diagnostics stay text on standard error.

> **Version note (#26, PR #64).** Duplicate citation keys were invisible
> through commit `dd06e37`: the parser library kept the first entry, and a key
> repeated across two configured files passed `--validate` with exit `0`.
> Since PR #64 merged, `sslabdata.parsers.bibtex.parse_all_works()`
> reports each duplicate under the `BIB-DUPLICATE-KEY` code, `--validate`
> exits `1`, and the other modes emit the same diagnostic as a warning and
> continue. The code was introduced as `E-BIB-DUPLICATE-KEY` and renamed to
> drop the severity prefix before any release, under rule 2 above.

> **Version note (#56, #65, PR for `schema_version` 4).** Through commit
> `78570e6`, the document's works were `publications`, the bibliography was
> one composed `venue` string, links and identifiers were five flat `*_url`
> properties, and an entry carrying `crossref` compiled with its parent's
> fields and none of its own authors. Since `schema_version` 4 the top level
> is `works`, the bibliography is structured, `links` and `identifiers` are
> open registries, `collaborators` is a declared grouping over unresolved
> authorships, and `crossref` is rejected under `BIB-CROSSREF-UNSUPPORTED`.
> The package version is 3.0.0; a consumer that needs the old document pins
> `schema_version` 3 and the schema at `schema/v3/output.schema.json`.
>
> **`collaborators` changes in four ways at once**, because the key changed:
> v3 grouped on the abbreviated display name, v4 on the normalised full name
> (§5). Which authorships land together changes, and so does how many entries
> there are — the demo goes from 7 to 9, one `P. Patel` group of four
> occurrences becoming `Priya Patel`, `Pradeep Patel` and `P. Patel`. The
> counts change meaning as well as value: v3's `publication_count` counted
> occurrences and v4 has both `work_count`, deduplicated per work, and
> `authorship_count` (v5 removes both; see the version note under §6). The
> displayed `name` expands, because it is now the parts joined rather than
> the abbreviated form: `T. Turner` becomes `Trent Turner`. The **order §3 promises keeps its rule** — `last_year`
> descending, then work count descending, then `name` — with `key` appended
> after `name`, because two keys can now carry the same readable name and the
> name alone is no longer total. What moves in the list moves because the
> names and the groups moved, not because the rule did. All of it follows
> from the key and the name, and #24 tunes the policy behind them.

> **Version note (#22, PR #61).** Through commit `cf9e055`, `--unresolved`
> printed `All authors resolved.` when no `people_file` was configured, where
> nothing had been attempted. Since PR #61 merged, the `--unresolved` branch
> of `sslabdata.cli.main()` prints `Author resolution is not configured (no
> people_file).` and exits `0`. `tests/COVERAGE.md` row
> `config.people_file.missing` records the current behaviour as `pass`.

**The Python API is convenience only.** Public: the names in `sslabdata.__all__`
— `assemble`, `AssemblyResult`, `AssemblyError`, the models `LabData`,
`Work`, `Author`, `Contributor`, `Venue`, `Link`, `Person`, `Project`,
`Collaborator`, the config loader `LabDataConfig` with `BibFile`, and the exporters
`export_to_yaml` and `export_to_json`, and the exception
`ConfigurationError`. `Publication` was renamed to `Work` at package version
3.0.0, when the document's `publications` became `works`.

**`sslabdata.ConfigurationError`** (defined in `sslabdata.config`) is a subclass
of `ValueError`, raised for a configuration sslabdata will not compile from.
It has its own type so that a caller can tell a rejected configuration from
anything else that raises a `ValueError`. For an absolute `bib_files` name
(`CONFIG-BIB-FILE-ABSOLUTE`) it is raised by `LabDataConfig.from_yaml()`, by
`BibFile`'s constructor, by `assemble()` on every configured name before it
compiles one, and by `Work.to_dict()` — which is the boundary every emitted
document passes through, so it is the one that holds whatever built the
objects. For a name that leaves `bib_dir` (`CONFIG-BIB-FILE-OUTSIDE-BIB-DIR`)
it is raised by `from_yaml()` and by `assemble()`. For a `lab.yaml` of the wrong shape (`CONFIG-NOT-A-MAPPING`,
`CONFIG-KEY-MISSING`, `CONFIG-TYPE-INVALID`) it is raised by `from_yaml()`
alone. Its message is always one coded diagnostic line.

**`sslabdata.AssemblyError`** (defined in `sslabdata.assembler`) is a subclass
of `ValueError`, raised by `assemble()` when any diagnostic is of class
*fatal* in the table under *Diagnostic codes*, whatever its `diagnostics`
argument is, so no document is returned from input with a fatal-class code.
That argument decides only printing: with `diagnostics=False`, every
diagnostic of the run, fatal ones included, is printed to standard error in
report order, each prefixed `Warning: `, before the exception is raised; with
`diagnostics=True` nothing is printed, and the diagnostics are returned in an
`AssemblyResult` or carried by the exception. The exception's message is the
fatal diagnostics, one per line, and its `diagnostics` attribute holds every
diagnostic of the run in report order. A validation error, such as a repeated
citation key, does not raise: the document is returned, as `--output` writes
it, with the diagnostic returned or printed alongside the rest.

Private, and free to change without a version bump: `sslabdata.parsers.*`,
`sslabdata.loaders`, `sslabdata.resolver`, `sslabdata.cli`'s internals, and every
underscore-prefixed name. Importing them is unsupported. In particular, no
guarantee is made about which BibTeX or LaTeX library sits behind
`sslabdata.parsers`; that it is an adapter boundary is stated in the
`sslabdata.parsers.bibtex` module docstring.

The package version (`sslabdata.__version__`) and the document's
`schema_version` (`sslabdata.models.SCHEMA_VERSION`) are independent. Neither
can be derived from the other.

---

## 2. The text rule

**Every string in the emitted document that is meant for display is plain
Unicode text.** Not HTML, not Markdown, not escaped, not LaTeX. The document
also carries strings that are not display text at all — identifiers, URLs and
the `bibtex` record — and heading 4 below lists them.

**Text is untrusted.** A title may contain `<`, `&`, `"`, `*` or `$`, and
often does: `Informed RRT*` and `BIT*` are real paper titles. sslabdata does
not escape them and will not, because it does not know what they are being
escaped for. **Renderers are responsible for escaping** — for HTML bodies, for
HTML attributes, for shell arguments, for whatever they emit.

### What sslabdata converts, and what it does not

This is the part that must be read carefully, because sslabdata enforces the
rule in one place only.

The four headings below are **lenses, not a partition**. Conversion and fate
are separate stages: a field is first converted or not, and then emitted,
consumed into a derived field, or discarded. A field can therefore appear
under more than one heading, and several do. `journal` is converted (1) and
then consumed into `venue.name` (3). `work.links[*][*].url` is built from
input (3) and is a URL rather than display text (4). Read each heading as a
question to ask about a string, not as a box the string lives in.

**1. Converted prose — the rule is enforced here.** Prose fields read from
BibTeX are converted from LaTeX to Unicode by
`sslabdata.parsers.latex.latex_to_text()`, so `C{\^o}t{\'e}` arrives as `Côté`
and `\textbf{Best Paper}` arrives as `Best Paper`. Beside the converter's own
table, a few common text macros have a rule (`sslabdata.parsers.latex._TEXT_MACROS`):
`\TeX`, `\LaTeX`, `\LaTeXe` and `\BibTeX` become their names, `\emdash` and
`\endash` their dashes, and `\slash` a `/`. Exactly the fields in
`sslabdata.parsers.bibtex.TEXT_FIELDS` are converted — `title`, `abstract`,
`note`, `journal`, `booktitle`, `school`, `institution`, `type`, `series`,
`publisher`, `address`, `organization` — applied in `entry_fields()`. Name
parts are converted the same way, in `person_name_parts()`, for authors and
editors alike.

Being converted is not the same as being emitted. Of these fields, `title`,
`abstract`, `note`, `type`, `series`, `publisher`, `address` and
`organization` are emitted under their own names; `journal`, `booktitle`,
`school` and `institution` are consumed by `build_venue()` and reach the
document as `venue.name`, which is the one place sslabdata normalises across
entry types.

**2. Emitted without conversion — the rule is a requirement on the input.**
These strings do reach the document, exactly as written, and sslabdata neither
converts nor checks them:

- **The person and project strings supplied in YAML.**
  `sslabdata.loaders.load_people()` and `load_projects()` perform no conversion
  of any kind — they check the types of a record's fields, a person's `role` and that a
  `status` is one they know, but emit every string as written — so a person's `name`, `role`, `current_position` or
  `thesis_title`, and a project's `title` or `description`, are copied
  straight from `people.yaml` and `projects.yaml`. Not every YAML string is
  emitted — `aliases` and the configuration paths are not; see heading 3.
- **`work.category`**, which comes from the `category` of the `bib_files`
  entry in `lab.yaml`, not from the `.bib` file
  (`sslabdata.config.LabDataConfig.from_yaml()`, then
  `sslabdata.parsers.bibtex.parse_all_works()`).
- **`lab`**, copied through from `lab.yaml` unchanged
  (`LabDataConfig.from_yaml()`, then `LabData.to_dict()`).
- **The bibliographic parts** `volume`, `number`, `pages`, `chapter`, `month`,
  `edition` and `howpublished`, which are outside `TEXT_FIELDS` and are
  emitted as the entry wrote them.
- **Every identifier** in `identifiers`, and the `url` of a link whose
  `origin` is `input`.

For these the plain-Unicode rule is a **requirement on the input, not a
guarantee sslabdata enforces**. If `people.yaml` says `name: "<b>Alice</b>"`,
or a `bib_files` category is `"**Journal** Papers"`, that string appears in
the document exactly as written and no diagnostic is raised. Verified
directly: a category of `<b>Cat</b> & **md**` is emitted unchanged. Authors
of input files are responsible for keeping these plain, and renderers should
escape them as they escape everything else.

**3. Read and acted on.** sslabdata reads each of these and does something with
it other than passing it through as display text: transforms it, consumes it
into a derived field, or reads it only to make a decision. None of them
reaches the document as a plain-text string under its own name, so the text
rule does not apply to the input itself — only to whatever it produces.

| Input | What becomes of it |
|---|---|
| `doi` | Becomes `identifiers.doi`, with a resolver prefix taken off if it was written as a URL, and a link of kind `doi` built from it (`bare_doi()`, `build_identifiers()`, `build_links()`). |
| `eprint` | Becomes an identifier under the scheme `archivePrefix` names, and a link of kind `arxiv` when that scheme is arXiv (`build_identifiers()`, `build_links()`). |
| `archivePrefix` (or `archiveprefix`) | Becomes the **scheme** of the `eprint` identifier, **lower-cased**, and the `venue.name` of a preprint, as written (`_archive_prefix()`). It has no property of its own, because naming the repository is what a scheme does. An entry that names no prefix is read as an arXiv one, which is the only case the default covers; an entry that names `HAL` is filed under `hal` and gets no arXiv link. |
| `isbn`, `issn` | Become `identifiers.isbn` and `identifiers.issn` (`build_identifiers()`). |
| `project` | Parsed into the list `project_ids` (`parse_project_ids()`). |
| `url` | Becomes a link of kind `video` when its host is youtube.com, youtu.be or vimeo.com or a subdomain of one, and of kind `url` otherwise, with `origin: input` (`is_video_url()`, `build_links()`). |
| `video` | Becomes a link of kind `video` whatever its host, with `origin: input`, after any video link `url` gave (`build_links()`). |
| `pdf` | Becomes the work's one link of kind `pdf`, with `origin: input`, in place of the one `pdf_base_url` would give (`build_links()`). Empty or whitespace-only is read as absent. |
| `author` | Parsed into the `authors` list (`parse_author_list()`); the name parts are converted under heading 1. |
| `editor` | Parsed into the `editors` list (`parse_editor_list()`), resolved by the same machinery, and excluded from `person.work_ids`, from a project's people and from `collaborators`. |
| `year` | Emitted as the integer `year` — not a string — or `null` with a `BIB-YEAR-MISSING` diagnostic when the entry supplied none. It drives the works order (§3). |
| `crossref` | **Rejected, on presence rather than on value.** An entry carrying the field is an error under `BIB-CROSSREF-UNSUPPORTED`, whatever is inside it: an empty `crossref = {}` is a field the entry carries, and letting it through would put the silent path back under a different spelling. The entry is not emitted and the run fails in every mode (`parse_all_works()`). No field of any entry is filled in from any other entry. |
| `journal`, `booktitle`, `school`, `institution` | Converted under heading 1, then consumed by `build_venue()` into `venue.name`, with the `venue.kind` each implies. |
| The citation key and the entry type | Become `bib_id` (and `source.key`) and `entry_type` (`entry_fields()`); see heading 4. |
| `person.aliases` | Read for matching by `sslabdata.resolver.match()`, never emitted — `Person.to_dict()` has no `aliases` key. |
| `collaborators_file` entries | A list of `{name, aliases}` read by `sslabdata.loaders.load_collaborators()`. Read only to decide which unresolved authorships share one `collaborators` grouping (§5); never emitted as such and never a source of `person_id`. |
| `bib_dir`, `people_file`, `projects_file`, `collaborators_file`, `pdf_base_url` | Configuration. Never emitted; `pdf_base_url` survives only inside the constructed PDF link. `bib_files[].name` **is** emitted, as `work.source.file`, and is therefore checked: an absolute one is rejected (`sslabdata.config.is_absolute_path()`), at load and again when the document is built, and one that leaves `bib_dir` is rejected at load (`CONFIG-BIB-FILE-OUTSIDE-BIB-DIR`). |
| Any BibTeX field named nowhere in this table or heading 1 — `keywords`, `annote`, `language` and the rest | Not interpreted by sslabdata outside the `bibtex` record. `entry_fields()` copies it and `format_bibtex()` serializes it, but nothing reads its value, so it affects no other property (§5). |

The fields named in that table and in heading 1 are the complete set sslabdata
*interprets* from a `.bib` entry; everything else falls in the last row.
Verified by enumerating the field names `sslabdata/parsers/bibtex.py` looks up,
and by looking up every field of every entry in the demo's input in the
property the document gives it (`tests/COVERAGE.md` row
`fields.demo_every_field`).

"Not emitted" throughout that table means *not emitted as a property of the
work*. Every field of the entry, read or not, also survives inside the
`bibtex` record, which is a re-serialization of the entry's data rather than
a set of first-class properties (§5).

**4. Not display text.** Some emitted strings are identifiers or machine
values, and the plain-text rule is beside the point for them: `bib_id`,
`source.key`, `entry_type`, `person_id`, `collaborator_key`, `venue.kind`,
every link `url`, `origin` and `verification.status`, every identifier in
`identifiers`, `resolution.status` and `resolution.method`, the `generator`
record, and every id in `project_ids`, `work_ids` and `people_ids`. Also here
is **`work.bibtex`**, which is a BibTeX record meant to be copied rather than
displayed, and which still contains LaTeX — see §5 for what it does and does
not preserve. `lab` is a YAML mapping rather than a string; its *values* fall
under heading 2.

`work.category` is *not* in this group. It is a label a renderer displays as
a section heading as well as grouping by, so it is display text and heading 2
applies to it in full. Neither is `collaborator.key`: it is an identifier,
but it is built from a name and is explicitly not an assertion about a human
(§5).

### The one markup exception

**Math is left as TeX**, delimited by `$…$`, so that KaTeX or MathJax can
typeset it (`sslabdata.parsers.latex._CONVERTER` is built with
`math_mode='verbatim'`). This is the one place a text field is expected to
contain markup, and it applies only to the fields under heading 1.

### Two degraded cases

- When a field cannot be converted, sslabdata warns
  (`LATEX-CONVERSION-FAILED`) and falls back to
  `sslabdata.parsers.latex.strip_braces()`, keeping the text as written with
  its braces removed (`sslabdata.parsers.bibtex._convert()`). Such a value may
  still contain LaTeX commands. This is a degraded case, not a second
  contract: the document is still declared plain text, and the warning is the
  signal that one field did not make it.
- `\href{url}{text}` is rewritten to `text (url)` before conversion, in
  `sslabdata.parsers.latex.latex_to_text()`, because the converter cannot read
  it. Carrying link content into explicit fields is #27.

> **Version note (#18, #56).** Through `schema_version` 3,
> `venue` was composed with Markdown emphasis by
> `format_venue()` — an article in journal `J` published in 2021 yielded the
> string `*J*, 2021` — and it was the only place sslabdata *generated* markup
> into a text field, as distinct from the YAML strings above, which it merely
> passes through. `schema_version` 4 replaced it with a structured container
> and flat bibliographic properties, so there is nothing left to compose and
> nothing left to generate. `tests/COVERAGE.md` rows `output.no_markup` and
> the two tests behind it assert it: nothing in the demo document is Markdown
> or HTML, and the Markdown punctuation the corpus does carry is input text
> in a property whose value the input supplies. #18 remains open for
> renderers — escaping, attribute-safe escaping and the checks on rendered
> output.

---

## 3. Ordering

Every list in the document is covered here. A list not described as ordered
is **unordered**, and a consumer that depends on its order is depending on an
accident.

| List | Order |
|---|---|
| `works` | `year` **descending**, with works that have no year **last**. Ties keep *read order* (below). The sort is the final statement of `sslabdata.parsers.bibtex.parse_all_works()`. |
| `work.authors` | The order the `author` field wrote them (`sslabdata.parsers.bibtex.parse_author_list()`). A terminal `and others` is BibTeX's "et al." and is dropped rather than emitted as an author. `position` is that order, 1-based, and counts only the names that reach the document. |
| `work.editors` | The order the `editor` field wrote them, read the same way (`parse_editor_list()`). |
| `work.project_ids` | The order the `project` field wrote them, comma-separated, whitespace trimmed, empty entries dropped (`sslabdata.parsers.bibtex.parse_project_ids()`). |
| `people` | The order of `people_file`. sslabdata does not sort people (`sslabdata.loaders.load_people()`, called by `sslabdata.assembler.assemble()`). |
| `projects` | The order of `projects_file`, likewise (`sslabdata.loaders.load_projects()`). |
| `person.work_ids` | The order of the `works` list, filtered to that person's authorships, first occurrence only (`sslabdata.resolver.compute_backlinks()`). Editors are not authorships and do not appear. |
| `project.work_ids` | The order of the `works` list, filtered to that project, first occurrence only (`compute_backlinks()`). |
| `project.people_ids` | Person id **ascending**, by Unicode code point (`compute_backlinks()` sorts the set it collects). |
| `collaborators` | `last_year` **descending** with `null` last, then the number of `work_ids` **descending**, then `name` **ascending** by Unicode code point, then `key` **ascending** by Unicode code point (the sort in `sslabdata.assembler.group_collaborators()`; `tests/COVERAGE.md` row `output.collaborators.order`). `key` is appended after `name` rather than replacing it: two keys can carry the same readable name — a parsed and a brace-protected spelling of one string are two keys — so the name alone is no longer total, but it is still what decides. |
| `collaborator.authorships` | The order of the `works` list, then `position` within a work (`group_collaborators()`). |
| `collaborator.work_ids` | The same order, first occurrence only. |
| `collaborator.name_variants` | **Ascending** by Unicode code point. `collaborator.name` is the *first* spelling in document order, which need not be the first variant. |
| `links`, `identifiers` | **Unordered.** They are maps, and a consumer reads them by key and filters the list under it. The list under one key is in the order sslabdata built it, which is not promised. |
| `lab` | Unordered. It is a YAML mapping copied through; consumers read it by key. |

**Read order** is the order in which entries were parsed: the files in the
order `bib_files` lists them in `lab.yaml`, and within each file, the order
the entries appear in the source. `parse_all_works()` accumulates entries in
that order before sorting. Because the works sort is stable, read order is
the tie-breaker for works of the same year, and it is a promise, not an
accident.

**Ties and missing sort keys.**

- Two works of the same year appear in read order. Two entries with the same
  year in the same file appear in source order.
- A work with **no `year` field has `year: null`** and sorts **last**, which
  is where `year: 0` used to put it. The position is unchanged; what changed
  is that `null` is now distinguishable from a genuine year `0`, and that the
  entry is reported under `BIB-YEAR-MISSING`.
- Two collaborators can only tie through all four sort keys if they share a
  `key`, and a `key` is unique by construction, so the order is total. Two
  that tie through the first three are separated by the `key` alone, which is
  why it is there.
- Sorting by "Unicode code point" means `Z` sorts before `a`, and `Ö` sorts
  after `z`. No locale collation is applied.

**Key order within an object is not part of the contract.** The YAML export
writes keys in insertion order (`sslabdata.exporters.export_to_yaml()` passes
`sort_keys=False`) and the JSON export does the same, but both formats define
objects as unordered and consumers must treat them that way.

**YAML and JSON carry the same document.** `--format yaml` and `--format
json` serialize the identical structure (`sslabdata.exporters.export_to_yaml()`
and `export_to_json()` both serialize `LabData.to_dict()`); neither is more
authoritative.

**The document is deterministic.** Nothing in it records when it was built:
`generator` carries the compiler's name and version and no timestamp, and a
link's `verification` carries a status and no time, because a build never
fetches. Two runs over the same inputs with the
same package version produce the same bytes, which is what makes
`tests/corpus/expected/valid.yaml` a reviewable record rather than noise.

---

## 4. Absent versus null

**One policy, refined by the kind of object it applies to.** The refinement
is not a second policy: it is the same rule, read correctly for a container
whose keys are not declared in advance.

> **For a closed object**, every property the schema declares is **always
> present**. A value that does not apply, or was not supplied, is **`null`**.
> An absent key and a `null` key mean the same thing, and consumers must not
> read meaning into the difference.
>
> **Inside an open map** — `lab`, `links`, `identifiers` and every `derived`
> bag — only the keys that have values are present. Emitting nulls over an
> unbounded key set is meaningless: there is no list of the keys that might
> have applied, so "absent" there means exactly "no value", and a consumer
> probes for the key it wants.

A consumer may therefore treat `entry.get("photo")` and `entry["photo"]` as
equivalent on a person, and must not use `"photo" in entry` as a test for
whether a person has a photo. The test is whether the value is `null`. Inside
`links`, the opposite holds: `"pdf" in work["links"]` is exactly the test for
whether the work has a PDF link, and there is no `null` to check.

Two consequences worth stating outright:

- `author.person_id` is `null` when the name matched no person in
  `people_file`. That is an ordinary, expected value, not an error; the
  authorship then carries a `collaborator_key` instead, and exactly one of
  the two is non-null.
- An empty list is `[]`, never `null` and never absent. `project.people_ids`
  for a project with no works is `[]`, and `work.editors` is `[]` for an
  entry that names no editor.

This rule is satisfied by `Author.to_dict()`, `Contributor.to_dict()`,
`Work.to_dict()`, `Person.to_dict()`, `Project.to_dict()` and
`Collaborator.to_dict()`, each of which emits every declared key
unconditionally, and by `LabData.to_dict()`, which always emits `lab`.

> **Version note (#56).** Three deviations existed through `schema_version`
> 3, and each was a bug against the rule above rather than a second policy.
> (a) `Person.to_dict()` emitted only `id`, `name`, `role`, `status`,
> `website` and `publication_count` unconditionally and **omitted** `photo`,
> `email`, `co_advisor`, `start_year`, `publication_ids` and the alumni
> fields whenever their value was falsy, with the alumni fields additionally
> omitted for anyone whose `status` was not `alumni`. (b)
> `Publication.to_dict()` omitted `bibtex` when the entry could not be
> written back out as BibTeX. (c) `LabData.to_dict()` omitted top-level `lab`
> when `lab.yaml` had no `lab` section — and, because it tested the value's
> truthiness rather than its presence, also when `lab.yaml` supplied an empty
> `lab: {}`, so a consumer could not tell "no header" from "an empty header".
> All three are fixed in `schema_version` 4: every declared property is
> present, `bibtex` is `null` when it could not be produced, and `lab` is
> always emitted, `{}` when there is nothing in it. Fixing them changed the
> schema's `required` lists and the nullability of the affected properties,
> which is breaking under §6, which is why they waited for the bump.

**Where "absent" cannot happen at all.** The schema defines the document
itself and each entity type as **closed**: `/additionalProperties` and each
of `/$defs/authorship`, `/$defs/editorship`, `/$defs/work`, `/$defs/person`,
`/$defs/project`, `/$defs/collaborator`, `/$defs/venue`, `/$defs/link`,
`/$defs/resolution`, and the `source` and `generator` objects, set
`additionalProperties: false`. Within those, a property that is not declared
cannot appear, and "absent" always means a declared property with no value.

**The open ones are `lab`, `links`, `identifiers` and `derived`.**
`/properties/lab` declares a handful of properties for documentation only and
keeps `additionalProperties: true`, so any keys whatever validate inside it:
its keys are whatever `lab.yaml` supplied, and a consumer must probe for the
ones it wants rather than expect a fixed set. `/$defs/linkMap` and
`/$defs/identifierMap` constrain the *value* under any key — a list of link
records, a unique list of identifier strings — and leave the key set open, so
a new link kind or identifier scheme is not a breaking change.
`/$defs/derived` constrains nothing; see §5 for who owns it.

## 5. Input versus derived

**Input** fields come from the author's files and sslabdata carries them
through. **Derived** fields sslabdata computes. Derived fields are **read-only
outputs**: they must never be written back into `people.yaml`,
`projects.yaml` or a `.bib` file. Doing so makes the next compile read
sslabdata's own output as input, and a wrong derivation becomes permanent.

| Field | Origin |
|---|---|
| `schema_version` | Derived — a constant of the compiler (`sslabdata.models.SCHEMA_VERSION`). |
| `generator` | Derived — the compiler's name, its package version and the schema version (`LabData.to_dict()`). No timestamp. |
| `lab` | Input — the `lab` section of `lab.yaml`, copied unchanged (`LabDataConfig.from_yaml()`), and always emitted. |
| `work.bib_id`, `work.source.key` | Input — the BibTeX citation key, **as written**. `sslabdata.parsers.bibtex.entry_fields()` preserves its case. |
| `work.source.file` | Input — the `name` of the `bib_files` entry the file was listed under, **never an absolute path**. A *relative* directory is fine and is passed through as written: `sub/journal.bib` is a name under `bib_dir`; one that leaves `bib_dir` is rejected under `CONFIG-BIB-FILE-OUTSIDE-BIB-DIR`. The guarantee is kept by rejecting the input rather than by rewriting it — rewriting would quietly discard that directory — and it is enforced under `CONFIG-BIB-FILE-ABSOLUTE` at `Work.to_dict()`, the boundary every emitted document passes through, so that it holds whatever built the objects. `LabDataConfig.from_yaml()`, `BibFile`'s constructor and `assemble()` check it earlier as well, for messages that fail sooner and name more. |
| `work.entry_type` | Input — the BibTeX entry type, **lowercased** by `entry_fields()`. Of it and `bib_id`, it is the only one that is case-folded. |
| `work.title`, `abstract`, `note` | Input — BibTeX fields, converted from LaTeX to text (§2). `note` additionally has trailing `.` and whitespace trimmed (`sslabdata.parsers.bibtex.extract_note()`). |
| `work.year` | Input — the BibTeX `year`, as an integer; `null` when the entry supplied none, with a diagnostic (`entry_year()`). |
| `work.category` | Input — the `category` of the `bib_files` entry the file was listed under, not anything in the `.bib` file (`sslabdata.config.BibFile`, read by `parse_all_works()`). |
| `work.venue` | **Derived** — the first of `journal`, `booktitle`, `school` and `institution` the entry wrote, as `name`, with the `kind` that field and the entry type imply; a preprint's repository when the entry has only an `eprint`; `null` when it names no container (`sslabdata.parsers.bibtex.build_venue()`). See below. |
| `work.volume`, `number`, `pages`, `series`, `edition`, `publisher`, `address`, `organization`, `chapter`, `month`, `howpublished`, `type` | Input — the BibTeX fields of those names, under BibTeX's names and with BibTeX's meanings (`FLAT_FIELDS`, read in `entry_to_work()`). Those in `TEXT_FIELDS` are converted from LaTeX (§2); the rest are emitted as written. |
| `work.identifiers` | **Derived** — a map from scheme to identifiers, built from `doi`, `eprint` with `archivePrefix`, `isbn` and `issn` (`build_identifiers()`). A `doi` written as a resolver URL has that prefix taken off. An `eprint`'s scheme is the repository `archivePrefix` named, **lower-cased**, as `entry_type` is: the scheme is a vocabulary token rather than display text, so a round trip recovers the repository and not the spelling the entry used. |
| `work.links` | **Derived** — a map from kind to link records, built from the entry's `url`, `video` and `pdf`, from `pdf_base_url` and from the identifiers above (`build_links()`). See below. |
| `work.project_ids` | Input — the `project` field, split on commas (`parse_project_ids()`). |
| `work.bibtex` | **Derived** — the entry re-serialized as BibTeX, or `null` when that failed (`format_bibtex()`). See below. |
| `author.given`, `von`, `family`, `suffix`, `literal` | Input — the parts BibTeX split the name into, converted from LaTeX, with an equal-contribution marker removed (`person_name_parts()`). An entry writing `Brown, B.` yields `given: "B."`, and that is correct, not a gap. |
| `author.name` | **Derived** — the parts joined in reading order (`readable_name()`). *A readable form of the input name, not a citation form*: it does not abbreviate, expand or normalise. |
| `author.position` | **Derived** — where the authorship sits in its work's list, 1-based, counting only the names that reach the document. |
| `author.person_id` | **Derived** — the resolver's match against `people_file` (`sslabdata.resolver.resolve_authors()`): on the structured full name, then — only for a name that is itself abbreviated — on a declared alias, and never when the name fits more than one person or only nearly matches. See *How a name is matched* below. |
| `author.collaborator_key` | **Derived** — the key of the grouping an unresolved authorship fell into (`sslabdata.assembler.group_collaborators()`). Exactly one of it and `person_id` is non-null. |
| `author.resolution` | **Derived** — `status` over `resolved`, `unresolved` and `ambiguous`, and `method` `exact`, or `null` when nothing matched (`resolve_authors()`). Both are open strings; `fuzzy` is no longer emitted (Version note under §6). |
| `author.equal_contribution` | **Derived** — whether the entry wrote a `*` marker on any part of the name (`sslabdata.parsers.bibtex.marks_equal_contribution()`). |
| `work.editors[*]` | The same, minus `collaborator_key` and `equal_contribution`. An editor that matched nobody is simply `person_id: null` (`parse_editor_list()`). |
| `person.*` except the two below | Input — the fields of `people_file` (`sslabdata.loaders.load_people()`). `aliases` is read for matching and is **not** emitted. `status` is `current` or `alumni`, and `current` when absent; `role` is open, any non-empty string (`PEOPLE-STATUS-INVALID`, `PEOPLE-ROLE-INVALID`). |
| `person.work_ids` | **Derived** — back-links over authorships (`sslabdata.resolver.compute_backlinks()`). Editors are not authorships and are not listed. |
| `project.id`, `title`, `description`, `website`, `image`, `status` | Input — the fields of `projects_file` (`sslabdata.loaders.load_projects()`). `status` is one of `active` and `completed`, and `active` when absent (`PROJECTS-STATUS-INVALID`). `image` is a URL or a site path, the same kind of value as a person's `photo`, carried as plain text: deciding which URLs are safe to render is the renderer's job. |
| `project.work_ids`, `people_ids` | **Derived** — back-links, and the people reached through them (`compute_backlinks()`). |
| `collaborators` | **Derived, entirely** — see below (`sslabdata.assembler.group_collaborators()`). |
| `derived` | Reserved for sslabdata; empty today. See below. |

### How a name is matched

`sslabdata.resolver.match()` compares a name's structured parts against every
person's `name` and `aliases`, all read through `normalize_name()`. That
function does exactly this, in this order:

1. Lower-cases the string and strips whitespace from both ends.
2. Decomposes it to Unicode NFD and deletes every character of category `Mn`
   (nonspacing mark). That removes combining accents, so `José` becomes
   `jose`, but also any other `Mn` character, such as the emoji variation
   selector U+FE0F and the Devanagari virama. Marks of category `Mc` and `Me`
   are kept, and the result stays decomposed: `각` comes out as three jamo.
3. Deletes every ASCII full stop (U+002E). Other full stops, such as the
   fullwidth `．`, stay.
4. Deletes each non-overlapping match of the regular expression
   `<sup>.*?</sup>`. Because it runs after lower-casing, it matches the tags
   in any letter case. The `.` matches any character except a line feed, so
   a span containing `\n` is not removed but one containing `\r` is. The
   match is non-greedy and ends at the first `</sup>`, so nested tags are
   not handled: `<sup>outer<sup>inner</sup>tail</sup>X` becomes
   `tail</sup>x`.
5. Replaces each run of whitespace with one space and strips both ends.

Nothing else is changed. A `*` that is not an equal-contribution marker
stays part of the name unless step 4 removed it with a `<sup>` span.

**Run-together initials in a given name.** A given-name part written as two
or more letters, each but the last followed by a full stop and the last
one's optional, is read as one initial per letter before it is normalised:
`S.S.` and `S.S` are `S. S.`, and `T.A.K.` is `T. A. K.` The test is made
once combining marks are removed, so `Š.S.` is read alike whether its accent
is precomposed or decomposed. So a given name written `S.S.`, `S.S`, `S S`
or `S. S.` matches any of the others. A part with no full stop between its
letters is a name and is never split: `SS`, `Ed`, `Jo`, `Al.` and `Ng` stay
whole, so `E.D. Quill` is not `Ed Quill`. Hyphenated initials are left as
written and go through the steps above like any other part: step 3 still
removes their full stops, so `J.-P.` equals `J-P`, but it is not equal to
`J.P.`, `J. P.` or `JP`. The rule applies only to a given name:

- On the `.bib` side, to the structured given name, never to the family
  name, a particle, a suffix or a brace-protected name.
- Matching a `.bib` name against a declared name or alias in `people_file`
  or `collaborators_file`: the declaration is not parsed; its given name is
  what is left once the compared name's particles, family name and suffix
  are taken off its end.
- Comparing two declarations with each other (`PEOPLE-ALIAS-AMBIGUOUS`, and
  `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER`): a declaration is read as
  `Given von Family, Suffix`, the form `full_form()` joins a name in, so
  only the text before its first comma is read with BibTeX's own name
  parsing, and the given name is the leading words it reads as first and
  middle names. Particles, the family name and everything after the comma
  are never spaced, so `S.S. Ivers, Jr.` equals `S. S. Ivers, Jr.`, while
  `S.S. S.S.` equals `S. S. S.S.` but not `S. S. S. S.`, and
  `Alice Ivers, S.S.` does not equal `Alice Ivers, S. S.` sslabdata has no
  way to tell a suffix from a given name after a comma, so a declaration
  written `Family, Given` is not spaced at all: `Ivers, S.S.` and
  `Ivers, S. S.` stay two spellings, as on `main`. Where the parse does not
  line up with the words, the declaration is compared through
  `normalize_name()` alone.
- Grouping an unresolved author into a collaborator: the grouping key is
  built from the readable name with its structured given name spaced, so
  `S.S. Quinn` and `S. S. Quinn` are one key (a key spanning two spellings,
  reported as such), and a `collaborators_file` entry's key from its name
  spaced the same way as between declarations. A name with nothing to space
  keeps the key it had.

The emitted `name` and name parts keep what the entry wrote, and
`normalize_name()` itself is unchanged.

The match decides in this order:

1. **The full name.** The parts joined as `given von family, suffix`, equal to
   exactly one person's name or alias: resolved, `method: exact`. Equal to two
   people's: `ambiguous`.
2. **A declared alias, only where the input is abbreviated** — where some part
   of the given name is an initial. The name abbreviated to initials, equal
   to a name or alias exactly one person declares, resolves only if no other
   person's name or alias *could be* it: same family, particles and suffix,
   and the given names agreeing part by part, an initial agreeing with any
   name it abbreviates. `Kim, A.` is `ambiguous` when Alex Kim declares
   `A. Kim` and Alan Kim declares nothing. A full name is never abbreviated
   to find a match, so `Kim, Alan` cannot reach the alias `A. Kim`.
3. **Otherwise nothing is linked.** Everyone the name could be, and the best
   string-similarity match at or above 0.85, are reported as a suggestion.

A name that is ambiguous or unresolved is reported (`RESOLVE-AMBIGUOUS-NAME`,
`RESOLVE-SUGGESTION`) and, for an authorship, grouped into a collaborator
like any other unresolved one.

### Six derived regions that need more than a row

**`work.venue` normalises across entry types, and is `null` when it cannot.**
`build_venue()` takes the first of `journal`, `booktitle`, `school` and
`institution` that the entry wrote, in that order, as the venue's `name`.
The `kind` follows from the field, and for `booktitle` from the entry type as
well: `journal` for a journal, `conference` for `@inproceedings`,
`@conference` and `@proceedings`, `book` for `@incollection`, `@inbook` and
`@book`, `other` for any other entry type carrying a `booktitle`, and
`institution` for a `school` or an `institution`. An entry with none of the
four but with an `eprint` gets `{kind: "repository", name: <archivePrefix>}`,
defaulting to `arXiv`, because the repository is what the preprint's
container is. Anything else gets `null`: sslabdata does not invent a container
the entry did not name. `kind` is an **open string**, deliberately not a JSON
Schema enum, so a new work type (#31) needs no version bump.

**`work.links` keeps a link that failed verification, and says so.**
`build_links()` files links by kind — `url` and `video` from the entry's own
`url` field and `video` from its `video` field, with `origin: input`; `pdf` from
the entry's `pdf` field, with `origin: input`, or else from `pdf_base_url`
plus the citation key, with `origin: derived`; `doi` and
`arxiv` built from the identifiers — and each record carries
`{url, label, origin, verification}`. `origin` is an open string over
`input`, `sidecar`, `enrichment`, `inferred` and `derived`, and only `input`
means the entry's own field supplied the link. `verification.status` is
`unchecked`, `verified` or `missing`.

**A build never fetches.** `verification` is set only from a local filesystem
check or from a committed cache, never from a network fetch, because a fetch
would cost determinism and make the document depend on the weather. So for
an entry without its own `pdf` field, a local `pdf_base_url` yields `verified`
or `missing` and a remote one yields `unchecked`; an entry's own `pdf` is
`unchecked` whatever the base. `verification` is `{status}` and records no
time. Three states replace a null: "no base configured" is no link at all for an entry without a `pdf`
field, "the file is not there" is `missing`, and "nobody has looked" is
`unchecked`. Verifying a remote link is #20.

A link does **not** name the identifier it was built from. That is redundant
with its kind and its origin, and it would be a cross-record constraint JSON
Schema cannot express and sslabdata would have to police by hand.

**`work.bibtex` is re-serialized, not verbatim.** It is produced by
`format_bibtex()`, which calls pybtex's `Entry.to_string("bibtex")` on the
*parsed* entry. What survives is the set of fields and their values. What does
**not** survive is how they were written: field order, brace-versus-quote
delimiters, whitespace and indentation are all the serializer's, and
`@string` macros are gone — a field written `journal = j` comes back as
`journal = "Expanded Journal"`. Verified directly.

It is produced *before* LaTeX conversion, so LaTeX markup is still present.
Read it as "the entry's data, re-typeset", not as "the entry as the author
wrote it", and never as a source of properties: nothing in sslabdata reads a
value back out of it, and a consumer probe that mined it would prove nothing
about the document (§1).

**`collaborators` is a grouping over unresolved authorships, not a list of
people.** `group_collaborators()` walks every work's authorships and, for
each one with no `person_id`, computes a key and files the occurrence under
it. What that buys, and what it does not:

- **The authorship is the primary contributor record.** It is addressed by
  `(work.bib_id, author.position)`, both emitted, with no hash and no new
  identifier, so two people who write their names identically are never
  merged at this level. `collaborator.authorships` lists the occurrences each
  key grouped, so **a consumer that distrusts the grouping can ignore it and
  work from occurrences.** That property is what makes the grouping safe to
  publish.
- **`key` is a lookup key, not an identity.** A name-derived value used as an
  *id* is a human-identity claim however it is described, because that is how
  consumers use it — a template writes `/collaborators/{{ id }}` and the
  disclaimer never reaches the reader. The key is a readable slug of the
  normalised name plus an **always-present** short digest of
  `name_kind + NUL + normalized_name`, for example `rachel-ross-0797b357`.
  The digest is always there rather than added on collision, so adding an
  unrelated collaborator can never change an existing key. A name that leaves
  no slug behind is keyed on the digest alone.
- **People and collaborators occupy separate namespaces.** A graph writes
  `person:aadams` and `collaborator:rachel-ross-0797b357`, never both under
  `person:`. An unresolved string is never labelled a person.
- **`grouped_by` names the policy.** It is `normalized_name`, or `declared`
  for a grouping `collaborators_file` asked for, and an open string, so #25
  can emit `explicit` or `orcid` without a bump.
- **`name_kind` is `personal` or `literal`, not `person`/`organization`.**
  Brace protection in BibTeX means "do not parse this", which covers
  organisations but also mononyms, so the document must not assert
  corporate-ness.
- **`work_ids` is deduplicated per work; `authorships` lists occurrences.**
  One work listing two authorships under one key contributes one entry to
  `work_ids` and two to `authorships`.
- **The policy.** An unresolved authorship is keyed on its normalised full
  name, which removes most of the merge risk but over-splits: one person
  written `Priya Patel` on two works and `P. Patel` on a third is two keys.
  **`collaborators_file` joins them when a human says so**: a list of
  `{name, aliases}`, each entry matched by the same rules as a person (§5,
  *How a name is matched*), with the lab members competing. An authorship
  that matches exactly one entry is grouped under the key of that entry's
  normalised name, `grouped_by: declared`; one that fits an entry and anyone
  else is reported under `RESOLVE-AMBIGUOUS-NAME` and grouped by its own
  name. A `name` or alias a member already declares is reported under
  `RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER` and not used. The file never
  produces a `person_id`. The remaining risk is **reported** rather than
  silent:
  `ID-GROUPING-SPANS-SPELLINGS` when one key grouped more than one spelling,
  and `ID-GROUPING-INITIALS-AMBIGUOUS` when an initials-only key could be any
  of several fuller ones. Both read the **structured parts**, not the key, so
  neither is limited to the shape a pattern over a normalised string happens
  to match. Both are diagnostics and nothing else: they change no key, no
  grouping and no emitted value, and neither is reported against a
  `declared` grouping, whose spellings a human joined on purpose.

**`derived` is sslabdata's, and it is not an extension mechanism.** Every
closed entity carries a `derived` object with `additionalProperties: true`.
Every key inside it is **reserved for sslabdata**. Consumers must tolerate keys
they do not know — that is the point of it — and must not write their own,
because a key they invent can collide with one sslabdata adds later. A key
**graduating out of `derived` into a named property is still a major
change**, for the same reason any new property is: the entity is closed. It
is **not** a general extension mechanism and not a place to park data the
schema declined to model; §8 says why there is no such mechanism. Today every
`derived` bag is `{}` in both the demo and the corpus, and
`tests/COVERAGE.md` row `output.derived_is_empty` asserts it so the region
cannot quietly fill.

**Unknown project ids are kept, not dropped.** A `project_ids` entry naming no
project in `projects_file` stays on the work so the problem stays visible, and
`--validate` reports it under `RESOLVE-PROJECT-UNKNOWN` and exits `1`
(`sslabdata.resolver.resolve_projects()`).

---

## 6. Version policy

The document carries a single integer, `schema_version`
(`sslabdata.models.SCHEMA_VERSION`, pinned in the schema at
`/properties/schema_version/const`). It has no minor component, because there
is nothing in the document a consumer would branch on below the level of "can
I still read this".

**A major change increments `schema_version`.** A change is major — breaking —
when it can make a conforming consumer reject the output or misinterpret it:

- **Adding, removing or renaming a property** of any closed object — the
  document itself and each entity type (§4). *Adding* is breaking there
  because those objects set `additionalProperties: false`, so a consumer
  validating against the previous version rejects a document carrying a new
  key. That includes a new **top-level** property beside `works`, `people`,
  `projects` and `collaborators`: the document is closed too, so a new entity
  collection is a breaking change on its own. **Inside an open map this does
  not hold**: `lab`, `links`, `identifiers` and every `derived` bag declare
  no key set, and adding a key there breaks no conforming consumer. Giving
  one of them a declared structure would itself be breaking, because it would
  close a door that is currently open.
- **Changing a type**, including making a string an object or a scalar a list.
- **Changing nullability** — a property that could not be `null` now can, or
  the reverse.
- **Changing requiredness** — moving a property into or out of a `required`
  list such as `/$defs/work/required`.
- **Changing meaning** while keeping the name and type.
- **Changing an identifier or a relationship** — how `bib_id` or a person
  `id` is formed, what `work_ids` points at, or which namespace a reference
  addresses.
- **Changing an order that §3 promises.** Reordering `works`, or moving where
  a work with no year lands, is breaking. Changing the order of a list §3
  calls unordered is not.

**A minor change does not increment it.** Minor changes are those that leave
every conforming document conforming and every conforming reading correct:
new CLI flags, new diagnostics, faster or clearer implementations,
documentation, and bug fixes whose output was already non-conforming. A new
value of an open string — a `venue.kind`, a link `origin`, a
`resolution.status`, a `grouped_by` — is minor by construction, which is why
those vocabularies are documented here rather than enumerated in the schema.

### What a schema version freezes, and what it does not

**A schema version freezes the *shape*, the *target namespace*, the *meaning*
and the *guarantees* of a relationship — not every result an implementation
produces.** `author.person_id` is frozen as "the id of a person in
`people.yaml`, or null": its type, the namespace it points into, and the
promise that it is never widened to reach anything else. It is **not** frozen
as "whichever person sslabdata matched on the day version 4 shipped".

So a **resolver correction** — a change that makes the matcher better satisfy
the documented matching policy, without changing the shape, the namespace or
the meaning of the relationship — is a package-level behaviour change
recorded as a **Version note** here, not a `schema_version` bump. A consumer
that needs byte-identical compilation pins the **package** version; one that
needs to read the document pins `schema_version`. The two are independent, and
this is why.

The precedent is already in this file. PR #61 changed what `--unresolved`
prints when no `people_file` is configured, and PR #64 made duplicate citation
keys an error where they had been invisible; both changed behaviour a user
could observe, both are recorded above as Version notes, and neither
incremented `schema_version`. The same reading is what lets #24 change how
authors resolve without a fifth version.

What that does **not** license: changing `person_id` to point at a
collaborator, making it a list, allowing it to carry something other than a
person's id, or reordering a list §3 promises. Those are shape, namespace,
meaning and guarantees, and each of them is a bump.

> **Version note (#24).** Through commit `eec03e6`, every author was
> abbreviated to initials before matching (`match_form()`), so a full name
> could resolve to whoever declared the abbreviation, and a near miss on
> string similarity was linked with `method: fuzzy`. Since #24, matching
> reads the structured full name first and the abbreviated form only where
> the input itself is abbreviated (§5, *How a name is matched*); a name that
> fits more than one person gets `resolution.status: ambiguous` and no
> `person_id`, a near miss is reported under `RESOLVE-SUGGESTION` and never
> linked, and `collaborators_file` can join the spellings of one external
> co-author, as `grouped_by: declared`. `schema_version` stays 4: the shape,
> namespace and meaning of `person_id` are unchanged, and `ambiguous` and
> `declared` are new members of open strings. In the valid corpus six
> `person_id` values move — `name-kim-alan` from `akim` to `alankim`,
> `name-kim-initial` from `akim` to null, `id-full-name` from null to
> `ffischer`, and three near misses that were linked by fuzzy matching and
> now are not: `id-fuzzy` author 1 (`Davis, Dave M.`),
> `name-equal-normalized` author 4 (`Davis{*}`) and `name-equal-escaped`
> author 2 (`Davis\^{*}`), each from `ddavis` to null. That moves works from
> `akim` to `alankim` and away from `ddavis`, removes the `Frank Fischer`
> collaborator, and adds three: `A. Kim`, `Dave M. Davis`, and one grouping
> the two starred Davis spellings, which normalise alike. In the demo no `person_id` moves; it now
> declares `P. Patel` as an alias of `Priya Patel` in
> `examples/demo/collaborators.yaml`, so `P. Patel` joins her grouping and the
> `P. Patel` collaborator is gone. Exit codes are unchanged.

**Published schemas are immutable and live at versioned paths.** A schema that
has been published is never edited. Version `N`'s schema stays reachable, byte
for byte, at its own path after version `N+1` ships, so a consumer pinned to
`N` keeps a stable target. `schema/v3/output.schema.json`,
`schema/v4/output.schema.json` and `schema/v5/output.schema.json` are those
paths, and `tests/COVERAGE.md` row `output.versioned_schema` asserts that the
older two are unchanged byte for byte and still say `3` and `4`.

**The `$id` is a pinned tag URL.** v5's `$id` is
`https://raw.githubusercontent.com/siddhss5/sslabdata/schema-v5/schema/v5/output.schema.json`.
The rule that makes it a contract rather than a guess: **the `schema-v5` tag
is created when this version ships and is never moved.** A branch URL such as
`blob/main` is not usable — it serves an HTML page rather than the schema, so
no consumer can ever have resolved v3's `$id` — and this repository publishes
no website to serve it from. A commit SHA would be
genuinely immutable rather than immutable by convention, but a commit cannot
reference its own SHA, so the file that introduces a version cannot carry one;
the tag is the closest thing that can be written down at the time the file is
written. Each later version gets its own tag, at its own path, under the same
rule.

**The published addresses carry the old repository name.** The project was
called `labdata` until #82 renamed it, and its repository with it, to
`sslabdata`. The v3 and v4 schema files were published before the rename, so
their `$id`s, and the titles and descriptions inside them, still say
`labdata`, and they are left byte for byte as published rather than
rewritten. v4's raw `$id` still resolves: GitHub redirects the old repository
name to the new one. v3's `blob/main` `$id` still does not resolve, as above.
v5 is the first schema published under the new name: its `$id`, title and
descriptions say `sslabdata`.

**Version history** of `sslabdata.models.SCHEMA_VERSION`:

| `schema_version` | Change |
|---|---|
| 1 | The original document. |
| 2 | Authors carry their structured name parts (#23). Breaking: the object is closed, so a v1 consumer rejects the new keys. |
| 3 | Authors carry `equal_contribution` (#46). Breaking, for the same reason. |
| 4 | One consolidated breaking change (#56): `publications` becomes `works`, the bibliography is structured, `links` and `identifiers` are open registries, `collaborators` is a declared grouping over unresolved authorships, every closed object declares every property it can carry, and `crossref` is rejected (#65). |
| 5 | A project carries an optional `image`; `verification.checked_at` is removed; `work_count` and `authorship_count` are removed (#101). Breaking: each adds or removes a property of a closed object. |

> **Version note (#101, `schema_version` 5).** Three changes, and nothing
> else in the document moves:
>
> 1. **A project carries `image`.** `projects.yaml` accepts it — a URL or a
>    site path, the same kind of value as a person's `photo` — and every
>    project emits it, `null` when absent (§4). It is plain text; deciding
>    which URLs are safe to render is the renderer's job.
> 2. **`verification.checked_at` is removed.** Nothing produced it and it was
>    always `null`. A link's `verification` is `{status}`.
> 3. **Counts that repeat the length of a list are removed:** `work_count` and
>    `authorship_count` from collaborators, and `work_count` from people. A
>    consumer reads `len(work_ids)` or `len(authorships)` instead.
>
> A consumer that needs the old document pins `schema_version` 4 and the
> schema at `schema/v4/output.schema.json`.

---

## 7. `@string` macros: last definition wins

BibTeX `@string` macros are expanded before a field reaches sslabdata. When one
file defines the same macro more than once, **the last definition wins**.

This matches classic BibTeX. It is not universal: some BibTeX parsers keep the
first definition instead, which is why the rule has to be written down rather
than assumed.

Verified: `tests/corpus/valid/strings.bib` defines `rss`, `cfx` and `jfx`
twice each, and `tests/COVERAGE.md` row `strings.repeat_last_wins` records
that the last definition is used and the first never appears in the output.

**Precisely: expansion is positional.** A definition applies to every use
*after* it in the same file, and a redefinition replaces it from that point
on. In the ordinary layout, where a file's `@string` block precedes its
entries, that is exactly "the last definition wins" for the whole file. It
differs only for an entry written *between* two definitions, which expands
with the earlier one — the definition that was in force where it was written.
Verified directly against a file with an entry between two definitions of the
same macro; `tests/corpus/valid/strings.bib` defines all three macros before
any entry uses them, so the corpus does not distinguish the two readings.

A redefinition is never silent. `sslabdata.parsers.bibtex._redefined_macros()`
finds every definition of a macro after its first — among the definitions
the parser itself reads, so an `@string` inside an `@comment` group is not
counted, and a line number counts lines as the parser does, after a byte
order mark and with CRLF read as one line end — and `parse_all_works()`
reports all of a run's in **one line**, under `BIB-STRING-REDEFINED`
(`redefined_summary()`; `tests/COVERAGE.md` row `strings.redefined_report`):

```
BIB-STRING-REDEFINED ./strings.bib::: 3 @string macros redefined (last definition used): cfx, jfx, rss [./strings.bib:15, ./strings.bib:16, ./strings.bib:17]
```

The macros are named once each, in sorted order, and every redefinition is
listed as `file:line`, by file and then by line. The location names the file
when every redefinition is in one, and is left empty (`:::`) when they span
several. The message is **globally worded** where the rule is positional —
"last definition used" is true of every use after the last definition, which
is the ordinary case, but not of an entry written between two definitions.
The rule above, not the message, is the contract.

**Macros are scoped to the file that defines them.** Each `.bib` file is
parsed with its own parser instance in `parse_bibtex_file()`, so a macro
defined in one file is undefined in the next. A use of an undefined macro is
reported under `BIB-STRING-UNDEFINED`, naming the file, entry key, field and
macro, and expands to the empty string; the entry itself is kept, not
dropped (`tests/COVERAGE.md` row `strings.undefined`).

---

## 8. The entity boundary, and the evidence for it

The document describes exactly these entities:

```
schema_version, generator, lab, people, works, projects,
collaborators (a derived grouping)
```

`lab` is the one entity sslabdata does not compute anything from. It is kept
deliberately: a document needs a header, and it is where contact information
lives.

The boundary is a finding, not an omission. The project's stated evidence is
two independent surveys of real academic lab websites — 27 groups and 18
groups, spanning robotics, biology, chemistry, physics, economics and public
health, across six countries — which found only three content types at or
above **85% prevalence**: people, works, and projects or research
areas. Everything else fell below **70%**. The types that recur most often
below that line — news, openings, teaching — are prose or
institution-specific, with no shared structure to compile: there is no schema
for them that two labs would both accept, and nothing for a compiler to
check. The surveys themselves are not in this repository and are not
independently reproducible from it; the reasoning is recorded in #38, and #60
is the one experiment that could later change it.

So each rejected type is rejected for a stated reason, and each has a home:

| Not an entity | Where it belongs instead |
|---|---|
| News and blog posts | Prose pages in your site repository; #60 explores deriving a feed from works instead of modelling news. |
| Openings and recruiting | A prose page in your site repository. |
| Teaching and courses | A prose page in your site repository, or the institution's course catalogue. |
| Press and media coverage | A typed link on the work it covers: `links` is an open map from kind to links, so #27 adds the kind without a version bump. |
| Galleries, photos and videos | Your site repository; a video already reaches the document as a link of kind `video`. |
| Awards and honours | An attribute of the work, today `work.note`; #27 moves it out of `note`. |
| Funding and grants | Your site repository. Nothing in the document depends on it. |
| Software and datasets | Not a separate collection — they are kinds of *work*, added by #31. |
| Alumni | Not a collection — a `status` on a person (`sslabdata.models.Person.status`). |
| Robots, platforms, facilities | Your site repository; one of 27 surveyed sites had such a page. |

**There is no generic extension mechanism and no `collections` escape hatch.**
What one would carry is mostly prose, and its one real service — catching
references that point at nothing — is delivered by #58 without the document
owning the payload. `derived` is not that hatch either: it is sslabdata's own
(§5), and the open maps `links` and `identifiers` are open over *their own*
vocabularies, not over arbitrary content.

---

## 9. What this file is not

It does not list the document's fields; `schema/v5/output.schema.json` does.
It does not describe renderers such as
[sslabdata-site](https://github.com/siddhss5/sslabdata-site), which are
downstream consumers in their own repositories. It does not describe the input formats `lab.yaml`,
`people.yaml` and `projects.yaml` beyond what §5 needs; schemas for those are
#37.

`tests/COVERAGE.md` is the case-by-case record of what sslabdata does with each
input, with the fixture and the test for each. Where it and this file disagree
about current behaviour, `tests/COVERAGE.md` is the one backed by a test.
