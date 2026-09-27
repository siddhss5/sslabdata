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

## Package 3.0.0 (not yet released)

The first package release since `v2.0.0`. It has no tag and no release date
yet. It emits `schema_version` 5 and carries the `schema_version` 4 and 5
changes and the package changes below. The project is named `sslabdata`
(#82), and the Python API's `Publication` is `Work`. It requires Python 3.10 or
later. Its distribution metadata carries the README as the long description, an
MIT license expression and links to the specification, the changelog and the
issue tracker (#111). The wheel installs the current output schema, readable
as `sslabdata/schema/v5/output.schema.json` through `importlib.resources`; the
earlier schemas are not in the wheel, and their tagged URLs stay their access
path. The source distribution holds the package, `README.md`, `LICENSE`,
`SPEC.md` and every schema in `schema/`, and no tests (#112).

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
