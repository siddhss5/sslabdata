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
    LabDataConfig, reject_absolute_name, reject_empty_pdf_base_url,
    reject_name_outside_bib_dir,
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


# `grouped_by` and `name_kind` values, both open strings (SPEC.md §5).
GROUPED_BY_NORMALIZED_NAME = "normalized_name"
GROUPED_BY_DECLARED = "declared"

PERSONAL, LITERAL = "personal", "literal"

# The digest is always present, never conditional on a collision (SPEC.md §5).
_DIGEST_LENGTH = 8

# A slug long enough to stay readable and short enough to stay a key.
_SLUG_LENGTH = 60

_NOT_SLUG = re.compile(r"-+")

# The codes this module reports (SPEC.md "Diagnostic codes").
GROUPING_SPANS_SPELLINGS = "ID-GROUPING-SPANS-SPELLINGS"
GROUPING_INITIALS_AMBIGUOUS = "ID-GROUPING-INITIALS-AMBIGUOUS"
GROUPING_AMBIGUOUS_DECLARED = "ID-GROUPING-AMBIGUOUS-DECLARED"
UNRESOLVED_NAME = "RESOLVE-UNRESOLVED-NAME"
COLLABORATOR_ALIAS_IS_MEMBER = "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER"
LAB_NAME_MISSING = "CONFIG-LAB-NAME-MISSING"
FILE_NOT_FOUND = "CONFIG-FILE-NOT-FOUND"
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

KEY_UNKNOWN = "CONFIG-KEY-UNKNOWN"
BIB_FILES_MISSING = "CONFIG-BIB-FILES-MISSING"


@dataclass
class AssemblyResult:
    """Result of assembling lab data: the document and every coded
    diagnostic, in report order, with no severity stored (SPEC.md §1)."""
    data: LabData
    unresolved_authors: List[str] = field(default_factory=list)
    unknown_projects: List[str] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)


class AssemblyError(ValueError):
    """Raised by `assemble()` when a diagnostic is fatal (SPEC.md §1).

    The message is the fatal diagnostics, one per line; ``diagnostics``
    holds every diagnostic the run found, in report order.
    """

    def __init__(self, fatal: List[Diagnostic], diagnostics: List[Diagnostic]):
        super().__init__("\n".join(str(line) for line in fatal))
        self.diagnostics = diagnostics


def collaborator_key(name_kind: str, normalized: str) -> str:
    """A lookup key for one grouping of unresolved authorships, not an
    identity (SPEC.md §5)."""
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
        # Read from the structured parts rather than from the key, and used
        # only by the diagnostics below, which decide nothing about grouping.
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
        """True when this initials-only key could be that fuller one
        (`ID-GROUPING-INITIALS-AMBIGUOUS` in SPEC.md "Diagnostic codes").

        One suffix against none still pairs: an entry that omits its suffix
        has said nothing about it.
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

    The normalised name is what the entry's collaborator key is built from.
    A spelling a member declares is reported and left out, so the member is
    never shadowed.
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
    """Group every unresolved authorship (SPEC.md §5), and say where the
    grouping is risky.

    Mutates ``author.collaborator_key`` in place.
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

    # The order is SPEC.md §3's; `key` last makes it total.
    ordered = sorted(groups.values(),
                     key=lambda g: (g.last_year is None, -(g.last_year or 0),
                                    -len(g.work_ids), g.author.name, g.key))
    return [group.build() for group in ordered]


def _grouping_warnings(groups: Dict[str, "_Grouping"]) -> List[Diagnostic]:
    """The two ways a key over- or under-groups, located at the first
    authorship the key grouped, which is where a human goes to fix the
    spelling. A declared grouping spans its spellings on purpose, so neither
    is reported against it."""
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
    first: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
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
            ``diagnostics`` is (SPEC.md §1).
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

    The CLI reads this rather than `assemble()` because it reports a run
    with fatal diagnostics too; it never writes that run's document.
    """
    # For a configuration built in Python; `from_yaml()` has already checked
    # one read from a file. Before anything is parsed, so it fails early.
    for bib_file in config.bib_files:
        reject_absolute_name(getattr(bib_file, 'name', None))
    for bib_file in config.bib_files:
        reject_name_outside_bib_dir(getattr(bib_file, 'name', None),
                                    config.bib_dir)
    reject_empty_pdf_base_url(config.pdf_base_url)

    found: List[Diagnostic] = []
    source = config.path or 'lab.yaml'

    for key in config.unknown_keys:
        found.append(diagnostic(
            KEY_UNKNOWN, source, key, None,
            f"'{key}' is not a key sslabdata reads, and is ignored"))
    found.extend(config.control_characters)
    if not config.bib_files:
        found.append(diagnostic(
            BIB_FILES_MISSING, source, 'bib_files', None,
            "no bib_files are configured, so the document has no works"))

    # Every path is checked before any is read, so a problem is reported
    # against the key that names it. An empty path is a mistake, not "none".
    def present(path: Optional[str], key: str, field_name=None,
                directory: bool = False) -> bool:
        if path is None:
            return True
        problem = path_problem(path, directory) if path else (
            FILE_NOT_FOUND,
            f"the path is empty; name a file, or leave {key} out for none")
        if problem is None:
            return True
        found.append(diagnostic(problem[0], source, key, field_name,
                                problem[1]))
        return False

    # `bib_dir` is checked only when a file is read from it. The files are
    # opened as `<bib_dir>/<name>`, so an empty one is the root.
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
    if people and config.people_file:
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

    # A `lab` that is not a mapping is malformed rather than unnamed, and
    # `from_yaml()` rejects it under its own code.
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
