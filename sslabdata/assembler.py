"""
Main pipeline orchestrator.

Assembles the complete LabData output from configuration:
config → parse BibTeX → load people/projects → resolve links → back-link.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import (
    LabDataConfig, reject_absolute_name, reject_name_outside_bib_dir,
)
from .diagnostics import (
    ERROR, Diagnostic, diagnostic, in_report_order, severity,
)
from .models import Author, Collaborator, LabData, Person, Work
from .parsers.bibtex import parse_all_works
from .loaders import (
    DeclaredCollaborator, load_collaborators, load_people, load_projects,
)
from .resolver import (
    AMBIGUOUS, RESOLVED, Candidates, compute_backlinks, declared_form,
    given_initials, initials_only, match, normalize_name,
    written_form,
    resolve_authors, resolve_projects, shared_declarations,
)


# The policy that built a collaborator key. It is a declared, open string, so
# a new policy can be emitted without a schema version bump.
# `declared` is a grouping `collaborators_file` asked for: its name and
# aliases joined the spellings, and it is still a grouping, never a person.
GROUPED_BY_NORMALIZED_NAME = "normalized_name"
GROUPED_BY_DECLARED = "declared"

# Whether the name was written as one brace-protected unit. Not
# `person`/`organization`: braces in BibTeX mean "do not parse this", which
# covers organisations but also mononyms, so the document must not assert
# corporate-ness.
PERSONAL, LITERAL = "personal", "literal"

# The digest is always present, never conditional on a collision, so adding
# an unrelated collaborator can never change an existing key. Eight hex
# characters of SHA-256 over the name kind and the normalised name.
_DIGEST_LENGTH = 8

# A slug long enough to stay readable and short enough to stay a key.
_SLUG_LENGTH = 60

_NOT_SLUG = re.compile(r"-+")

# Two ways a grouping key can be wrong that the document would otherwise keep
# to itself. Neither is ever an error: an author who matched no lab member is
# not (SPEC.md section 1).
GROUPING_SPANS_SPELLINGS = "ID-GROUPING-SPANS-SPELLINGS"
GROUPING_INITIALS_AMBIGUOUS = "ID-GROUPING-INITIALS-AMBIGUOUS"

# An unresolved authorship that fits more than one `collaborators_file`
# entry, or an entry and a lab member it did not resolve to, so it is grouped
# by its own name. Never an error, as above.
# `RESOLVE-AMBIGUOUS-NAME` is about lab members only; it is reported as well,
# as an error under `--strict`, when the name also fits more than one member.
GROUPING_AMBIGUOUS_DECLARED = "ID-GROUPING-AMBIGUOUS-DECLARED"

# One author name that matched no person, as `--unresolved --format json`
# lists it. Never an error, as above.
UNRESOLVED_NAME = "RESOLVE-UNRESOLVED-NAME"

# A `collaborators_file` name or alias that a lab member already declares.
# Resolving to the member wins, because the collaborator file never produces
# a `person_id`, and the collaborator entry is not used for that spelling;
# saying so is what keeps the choice from being silent.
COLLABORATOR_ALIAS_IS_MEMBER = "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER"

# A document needs a header, and a header with no name is one a renderer
# cannot title a page from.
LAB_NAME_MISSING = "CONFIG-LAB-NAME-MISSING"

# A `.bib`, people, projects or collaborators file the configuration names
# that is not there. Fatal: compiling on without it would emit a document
# missing its works, people, projects or declared groupings.
FILE_NOT_FOUND = "CONFIG-FILE-NOT-FOUND"

# A path the configuration names that is there but is the wrong kind: a
# directory, or anything else that is not a regular file, where a file is
# named, or a `bib_dir` that is not a directory. Its own code, because "not
# found" would send the user looking for a typo in a path that exists. Fatal,
# as a missing file is.
PATH_WRONG_KIND = "CONFIG-PATH-WRONG-KIND"


def path_problem(path: str, directory: bool = False
                 ) -> Optional[Tuple[str, str]]:
    """What is wrong with a configured path, as ``(code, message)``, or
    ``None`` when it is a regular file (a directory, with ``directory``).

    Symlinks are followed, so a dangling one is missing.
    """
    target = Path(path)
    if not target.exists():
        return FILE_NOT_FOUND, f"'{path}' does not exist"
    if directory:
        if target.is_dir():
            return None
        return PATH_WRONG_KIND, f"'{path}' is not a directory"
    if target.is_file():
        return None
    return PATH_WRONG_KIND, (f"'{path}' is a directory, not a file"
                             if target.is_dir() else
                             f"'{path}' is not a regular file")

# A key `lab.yaml` holds that sslabdata does not read, such as a misspelt
# `people_fil`. A warning: nothing is lost that was ever read.
KEY_UNKNOWN = "CONFIG-KEY-UNKNOWN"

# No `.bib` file is configured, so the document has no works. A warning,
# because that can be meant, but it is never silently normal.
BIB_FILES_MISSING = "CONFIG-BIB-FILES-MISSING"


@dataclass
class AssemblyResult:
    """Result of assembling lab data, including diagnostics.

    ``diagnostics`` holds every coded diagnostic in report order
    (`sslabdata.diagnostics.in_report_order()`). Each one's severity is not
    stored: it depends on the run as well as the code, and
    `sslabdata.diagnostics.severity()` decides it (SPEC.md, *Diagnostic
    codes*).
    """
    data: LabData
    unresolved_authors: List[str] = field(default_factory=list)
    unknown_projects: List[str] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)


class AssemblyError(ValueError):
    """Raised by `assemble()` when a diagnostic is fatal, so no document is
    returned from input sslabdata will not compile from.

    The message is the fatal diagnostics, one per line; ``diagnostics``
    holds every diagnostic the run found, in report order.
    """

    def __init__(self, fatal: List[Diagnostic], diagnostics: List[Diagnostic]):
        super().__init__("\n".join(str(line) for line in fatal))
        self.diagnostics = diagnostics


def collaborator_key(name_kind: str, normalized: str) -> str:
    """A lookup key for one grouping of unresolved authorships.

    A readable slug of the normalised name plus a short digest of the name
    kind and that same normalised name. It is explicitly **not** an assertion
    about a human: a name-derived value used as an id is an identity claim
    however it is described, because that is how consumers use it.

    The digest is always present rather than added on collision, so an
    unrelated collaborator arriving later can never change an existing key.
    A name that leaves no slug behind -- one written entirely in punctuation,
    or the corpus name with a newline in it -- is keyed on the digest alone.
    """
    digest = hashlib.sha256(
        (name_kind + "\x00" + normalized).encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    slug = "".join(c if c.isalnum() else "-" for c in normalized)
    slug = _NOT_SLUG.sub("-", slug).strip("-")[:_SLUG_LENGTH].strip("-")
    return f"{slug}-{digest}" if slug else digest


class _Grouping:
    """One collaborator under construction, in the order the works are read."""

    def __init__(self, key: str, author: Author, normalized: str,
                 grouped_by: str = GROUPED_BY_NORMALIZED_NAME):
        self.key = key
        self.grouped_by = grouped_by
        self.normalized = normalized
        self.name_kind = LITERAL if author.literal else PERSONAL
        self.author = author            # the first spelling, in document order
        # Read from the structured parts rather than from the key, so a
        # particle, a second initial, a hyphenated family name and a name
        # outside ASCII are all visible. Used by the diagnostics below and by
        # nothing else: they decide nothing about grouping or matching.
        self.family = normalize_name(author.family or "")
        self.von = normalize_name(author.von or "")
        self.suffix = normalize_name(author.suffix or "")
        self.initials = given_initials(author.given)
        self.initials_only = initials_only(author.given)
        self.variants: List[str] = []
        self.authorships: List[Dict[str, object]] = []
        self.work_ids: List[str] = []
        self.last_year: Optional[int] = None
        self.where: Tuple[str, str, str] = ("", "", "")

    def add(self, work: Work, author: Author,
            where: Tuple[str, str, str]) -> None:
        if not self.authorships:
            self.where = where
        if author.name not in self.variants:
            self.variants.append(author.name)
        self.authorships.append({"work_id": work.bib_id,
                                 "position": author.position})
        if work.bib_id not in self.work_ids:
            self.work_ids.append(work.bib_id)
        if work.year is not None:
            self.last_year = max(self.last_year or work.year, work.year)

    def could_be(self, other: "_Grouping") -> bool:
        """True when this initials-only key could be that fuller one.

        Same family and same particles, and one set of initials a prefix of
        the other, in whichever direction is shorter: `A. Smith` could be
        `Alice Smith` or `Alice Jane Smith`, and `A. J. Smith` could be
        either as well. A name written as one brace-protected unit has no
        parts to compare and takes part in neither side.

        Two lineage suffixes that disagree are two people: `J. Smith, Jr.` is
        not `John Smith, Sr.`, and saying so would be a warning about a
        merge that cannot happen. One suffix against none is not a
        disagreement -- an entry that omits it has said nothing -- so those
        still pair.
        """
        if other.key == self.key or not self.initials_only:
            return False
        if self.name_kind != PERSONAL or other.name_kind != PERSONAL:
            return False
        if other.initials_only or not other.initials:
            return False
        if not self.family or self.family != other.family:
            return False
        if self.von != other.von:
            return False
        if self.suffix and other.suffix and self.suffix != other.suffix:
            return False
        shorter, longer = sorted((self.initials, other.initials), key=len)
        return longer[:len(shorter)] == shorter

    def build(self) -> Collaborator:
        return Collaborator(
            key=self.key,
            name=self.author.name,
            grouped_by=self.grouped_by,
            name_kind=self.name_kind,
            given=self.author.given,
            von=self.author.von,
            family=self.author.family,
            suffix=self.author.suffix,
            literal=self.author.literal,
            name_variants=sorted(self.variants),
            authorships=self.authorships,
            work_ids=self.work_ids,
            last_year=self.last_year,
        )


def declared_collaborators(declared: List[DeclaredCollaborator],
                           people: List[Person], source: str,
                           diagnostics: List[Diagnostic]
                           ) -> List[Tuple[str, List[str]]]:
    """The `collaborators_file` entries as ``(normalised name, spellings)``,
    minus any spelling a lab member already declares.

    The normalised name is what the entry's collaborator key is built from. A
    name or alias equal to a member's name or alias is reported under
    `COLLABORATOR_ALIAS_IS_MEMBER` and left out, so the member is never
    shadowed and the collaborator never silently chosen.
    """
    members: Dict[str, set] = {}
    for person in people:
        for name in [person.name] + list(person.aliases):
            members.setdefault(declared_form(name), set()).add(person.id)
    entries = []
    for collaborator in declared:
        kept = []
        for field_name, name in [("name", collaborator.name)] + [
                ("aliases", alias) for alias in collaborator.aliases]:
            owners = members.get(declared_form(name), set())
            if owners:
                diagnostics.append(diagnostic(
                    COLLABORATOR_ALIAS_IS_MEMBER, source, collaborator.name,
                    field_name,
                    f"'{name}' is also declared by {', '.join(sorted(owners))}; "
                    "the member keeps it and the collaborator entry is not "
                    "used for it"))
            else:
                kept.append(name)
        entries.append((declared_form(collaborator.name), kept))
    return entries


def group_collaborators(works: List[Work], bib_dir: str,
                        diagnostics: List[Diagnostic],
                        declared: Optional[List[Tuple[str, List[str]]]] = None,
                        people: Optional[List[Person]] = None) -> List[Collaborator]:
    """Group every unresolved authorship, and say where the grouping is risky.

    The grouping is keyed on the normalised full name. An authorship that
    matches exactly one `collaborators_file` entry -- by the same rules a
    person is matched by, with the lab members competing -- is grouped under
    that entry's key instead, which is what joins `Patel, Priya` and
    `Patel, P.` once `P. Patel` is declared. A name that fits a declared
    collaborator and anyone else is reported and grouped by name.

    Mutates ``author.collaborator_key`` in place, so every authorship
    references exactly one contributor.
    """
    rivals = None
    if declared:
        rivals = Candidates(
            [(f"collaborator:{name}", spellings) for name, spellings in declared]
            + [(f"person:{p.id}", [p.name] + list(p.aliases))
               for p in (people or [])])
    groups: Dict[str, _Grouping] = {}
    for work in works:
        where = (f"{bib_dir}/{work.source_file}", work.bib_id, "author")
        for author in work.authors:
            if author.person_id:
                continue
            normalized = written_form(author)
            kind = LITERAL if author.literal else PERSONAL
            grouped_by = GROUPED_BY_NORMALIZED_NAME
            if rivals is not None:
                found = match(author, rivals)
                ids = found.ids
                if found.status == RESOLVED and ids[0].startswith("collaborator:"):
                    normalized = ids[0].split(":", 1)[1]
                    kind, grouped_by = PERSONAL, GROUPED_BY_DECLARED
                elif found.status == AMBIGUOUS and any(
                        i.startswith("collaborator:") for i in ids):
                    diagnostics.append(diagnostic(
                        GROUPING_AMBIGUOUS_DECLARED, *where,
                        f"position {author.position}, '{author.name}', fits "
                        "more than one collaborators_file entry, or an entry "
                        "and a lab member, and is grouped by its own name: "
                        f"{', '.join(ids)}"))
            key = collaborator_key(kind, normalized)
            author.collaborator_key = key
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Grouping(key, author, normalized, grouped_by)
            group.add(work, author, where)

    diagnostics.extend(_grouping_warnings(groups))

    # The readable name breaks ties, because it is what a reader sees, and
    # `key` breaks the rest: two keys can carry the same readable name -- a
    # parsed and a brace-protected spelling of one string are two keys -- so
    # the name alone is not a total order.
    ordered = sorted(groups.values(),
                     key=lambda g: (g.last_year is None, -(g.last_year or 0),
                                    -len(g.work_ids), g.author.name, g.key))
    return [group.build() for group in ordered]


def _grouping_warnings(groups: Dict[str, "_Grouping"]) -> List[Diagnostic]:
    """The two ways a key over- or under-groups, reported against a work.

    Both are located at the first authorship the key grouped, which is where
    a human goes to fix the spelling. A grouping `collaborators_file`
    declared spans its spellings because a human said it should, so neither
    is reported against it.
    """
    reported = []
    for group in sorted(groups.values(), key=lambda g: g.key):
        if group.grouped_by == GROUPED_BY_DECLARED:
            continue
        if len(group.variants) > 1:
            spellings = ", ".join(repr(v) for v in sorted(group.variants))
            reported.append(diagnostic(
                GROUPING_SPANS_SPELLINGS, *group.where,
                f"collaborator key '{group.key}' groups {len(group.variants)} "
                f"spellings of one name: {spellings}"))
        fuller = sorted(other.key for other in groups.values()
                        if group.could_be(other))
        if fuller:
            reported.append(diagnostic(
                GROUPING_INITIALS_AMBIGUOUS, *group.where,
                f"collaborator key '{group.key}' is initials only and could "
                "be any of: " + ", ".join(repr(k) for k in fuller)))
    return reported


def unresolved_name_diagnostics(works: List[Work], names: List[str],
                                bib_dir: str) -> List[Diagnostic]:
    """One `UNRESOLVED_NAME` diagnostic per name, in the order given.

    Each is located at the first authorship, in document order, that is
    written that way and linked to no person; its message is the name.
    """
    first: Dict[str, Tuple[str, str]] = {}
    for work in works:
        for author in work.authors:
            if author.person_id is None and author.name not in first:
                first[author.name] = (f"{bib_dir}/{work.source_file}", work.bib_id)
    return [diagnostic(UNRESOLVED_NAME, *first.get(name, (None, None)),
                       "author", name)
            for name in names]


def assemble(config: LabDataConfig, diagnostics: bool = False):
    """Main entry point: config → fully resolved LabData.

    Args:
        config: Lab data configuration
        diagnostics: If True, return AssemblyResult with diagnostics.
                     If False (default), return LabData directly, and print
                     each diagnostic to standard error first, fatal or not.

    Raises:
        AssemblyError: when any diagnostic is fatal, whatever
            ``diagnostics`` is: a document built from input sslabdata will
            not compile from is never returned.
    """
    result = assemble_result(config)
    if not diagnostics:
        for message in result.diagnostics:
            print(f"Warning: {message}", file=sys.stderr)
    fatal = [line for line in result.diagnostics
             if severity(line, validating=False, strict=False) == ERROR]
    if fatal:
        raise AssemblyError(fatal, result.diagnostics)
    return result if diagnostics else result.data


def assemble_result(config: LabDataConfig) -> AssemblyResult:
    """The document and every diagnostic, whether or not one is fatal.

    1. Parse all BibTeX files into Works
    2. Load people and projects from YAML
    3. Resolve contributor names → person IDs
    4. Validate project IDs
    5. Group the authorships that resolved to nobody
    6. Compute back-links (people→works, projects→works, projects→people)

    The CLI reads this rather than `assemble()` because it reports a run
    with fatal diagnostics too; it never writes that run's document.
    """
    # Every configured name, checked before anything is parsed, so a
    # configuration sslabdata will not compile from fails here rather than
    # after the work of reading every file. The CLI never reaches these:
    # `LabDataConfig.from_yaml()` rejects the same things first, with the file
    # the user would edit named.
    for bib_file in config.bib_files:
        reject_absolute_name(getattr(bib_file, 'name', None))
    for bib_file in config.bib_files:
        reject_name_outside_bib_dir(getattr(bib_file, 'name', None),
                                    config.bib_dir)

    found: List[Diagnostic] = []
    source = config.path or 'lab.yaml'

    for key in config.unknown_keys:
        found.append(diagnostic(
            KEY_UNKNOWN, source, key, None,
            f"'{key}' is not a key sslabdata reads, and is ignored"))
    if not config.bib_files:
        found.append(diagnostic(
            BIB_FILES_MISSING, source, 'bib_files', None,
            "no bib_files are configured, so the document has no works"))

    # Every path the configuration names, checked before any is read, so a
    # missing one, or one of the wrong kind, is reported against the key that
    # names it.
    def present(path: Optional[str], key: str, field_name=None,
                directory: bool = False) -> bool:
        if not path:
            return True
        problem = path_problem(path, directory)
        if problem is None:
            return True
        found.append(diagnostic(problem[0], source, key, field_name,
                                problem[1]))
        return False

    # `bib_dir` is checked only when a file is read from it, and then once:
    # when it is not a directory, no file under it is looked for. The files
    # are opened as `<bib_dir>/<name>`, so an empty one is the root.
    bib_dir_found = not config.bib_files or present(
        config.bib_dir or "/", 'bib_dir', directory=True)
    bib_files = [{'name': bf.name, 'category': bf.category}
                 for bf in config.bib_files if bib_dir_found and
                 present(f"{config.bib_dir}/{bf.name}", 'bib_files', 'name')]
    people_found = present(config.people_file, 'people_file')
    projects_found = present(config.projects_file, 'projects_file')
    collaborators_found = present(config.collaborators_file,
                                  'collaborators_file')
    works = parse_all_works(
        bib_dir=config.bib_dir,
        bib_files=bib_files,
        diagnostics=found,
        pdf_base_url=config.pdf_base_url,
    )

    people = (load_people(config.people_file, found)
              if config.people_file and people_found else [])
    projects = (load_projects(config.projects_file, found)
                if config.projects_file and projects_found else [])
    if people:
        found.extend(shared_declarations(people, config.people_file))

    unresolved_authors = resolve_authors(works, people, diagnostics=found,
                                         bib_dir=config.bib_dir)
    unknown_projects = resolve_projects(works, projects, found,
                                        bib_dir=config.bib_dir)

    declared = None
    if config.collaborators_file and collaborators_found:
        declared = declared_collaborators(
            load_collaborators(config.collaborators_file, found), people,
            config.collaborators_file, found)
    collaborators = group_collaborators(works, config.bib_dir, found,
                                        declared, people)

    # A header a renderer cannot title a page from. A `lab` that is not a
    # mapping at all is a different condition -- the header is malformed
    # rather than unnamed -- and `LabDataConfig.from_yaml()` rejects it under
    # its own code, so this one is not reported against it.
    if config.lab is None or isinstance(config.lab, dict):
        if not (config.lab or {}).get("name"):
            found.append(diagnostic(
                LAB_NAME_MISSING, config.path or 'lab.yaml', "lab", "name",
                "the lab header declares no name"))

    data = LabData(
        works=works,
        people=people,
        projects=projects,
        collaborators=collaborators,
        lab=config.lab,
    )

    compute_backlinks(data)

    return AssemblyResult(
        data=data,
        unresolved_authors=unresolved_authors,
        unknown_projects=unknown_projects,
        diagnostics=in_report_order(found),
    )
