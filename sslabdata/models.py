"""
Data models for sslabdata.

Defines the core entity types: Work, Author, Person, Project, Collaborator,
and the assembled LabData output.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# `work.source.file` must never be absolute (SPEC.md section 5).
# `sslabdata.config` owns the code and the exception type because the
# condition is a configuration mistake; `Work.to_dict()` checks as well.
from .config import reject_absolute_name


# Version of the output format (see schema/v5/output.schema.json). Bump it when
# a change to to_dict() output could break a consumer (SPEC.md section 6).
# CHANGELOG.md says what each version changed.
SCHEMA_VERSION = 5

# The name of the compiler, as the document's `generator` record reports it.
GENERATOR_NAME = "sslabdata"

# The one policy for closed objects (SPEC.md section 4): every declared
# property is present, and `null` when it does not apply. The open maps --
# `lab`, `links`, `identifiers` and every `derived` bag -- carry only the keys
# that have values, because emitting nulls over an unbounded key set says
# nothing.


@dataclass
class Venue:
    """Where a work appeared, normalised across entry types.

    ``kind`` is an open string. v4 emits ``journal``, ``conference``, ``book``,
    ``institution`` and ``repository``; a consumer branches on the ones it
    knows and falls back for the rest, so a new kind is not a breaking change.
    ``name`` is the container's own name, as plain text.
    """
    kind: str
    name: str

    def to_dict(self) -> dict:
        return {'kind': self.kind, 'name': self.name}


@dataclass
class Link:
    """One URL a work can be reached at, with where it came from and whether
    anything has checked it.

    ``origin`` is an open string over ``input``, ``sidecar``, ``enrichment``,
    ``inferred`` and ``derived``: only ``input`` means the entry's own field
    supplied it. ``status`` is ``unchecked``, ``verified`` or ``missing``; a
    link that fails verification is kept and labelled, never deleted.
    """
    url: str
    label: Optional[str] = None
    origin: str = "input"
    status: str = "unchecked"

    def to_dict(self) -> dict:
        return {
            'url': self.url,
            'label': self.label,
            'origin': self.origin,
            'verification': {'status': self.status},
        }


@dataclass
class Contributor:
    """One person named on a work: the parts of the name, and who it resolved to.

    ``name`` is the structured parts joined in reading order. It is *a readable
    form of the input name, not a citation form*: it does not abbreviate,
    expand or normalise anything. The parts below it carry what the entry
    supplied, after LaTeX conversion and marker removal, so an entry writing
    ``Brown, B.`` yields ``given: "B."`` and that is correct rather than a gap.
    ``literal`` holds a name written as one brace-protected unit, such as
    ``{Example Robotics Consortium}``, where the other parts do not apply.

    ``position`` is 1-based and is the authorship's address within its work,
    together with the work's ``bib_id``.

    This is the record ``work.editors`` carries. Editing a volume is not an
    authorship, so an editor that matched nobody is simply ``person_id: null``
    and produces no collaborator.
    """
    name: str
    position: int = 0
    person_id: Optional[str] = None
    given: Optional[str] = None
    von: Optional[str] = None
    family: Optional[str] = None
    suffix: Optional[str] = None
    literal: Optional[str] = None
    resolution_status: str = "unresolved"
    resolution_method: Optional[str] = None
    derived: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'position': self.position,
            'person_id': self.person_id,
            'given': self.given,
            'von': self.von,
            'family': self.family,
            'suffix': self.suffix,
            'literal': self.literal,
            'resolution': {'status': self.resolution_status,
                           'method': self.resolution_method},
            'derived': dict(self.derived),
        }


@dataclass
class Author(Contributor):
    """One authorship of a work.

    The authorship, not the contributor, is the primary record: it is
    addressed by ``(work.bib_id, position)``, so two people who write their
    names identically are never merged at this level.

    It references exactly one contributor. ``person_id`` is the id of a person
    in ``people.yaml`` and means nothing else; ``collaborator_key`` is the
    lookup key of the grouping an unresolved authorship fell into. Both are
    always present and exactly one is non-null.

    ``equal_contribution`` records that the entry marked this author with a
    ``*``; the marker itself is taken off the name, so neither the readable
    form nor the name used for matching carries it.
    """
    collaborator_key: Optional[str] = None
    equal_contribution: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = Contributor.to_dict(self)
        d['collaborator_key'] = self.collaborator_key
        d['equal_contribution'] = self.equal_contribution
        return d


@dataclass
class Work:
    """A single work with structured, renderer-agnostic data."""
    bib_id: str
    title: str
    authors: List[Author]
    year: Optional[int]
    category: str
    entry_type: str

    # The configured `bib_files[].name` the entry was read from, relative to
    # `bib_dir`: see `to_dict()`.
    source_file: str = ""

    editors: List[Contributor] = field(default_factory=list)
    venue: Optional[Venue] = None

    # The bibliographic parts, flat on the work rather than nested in the
    # venue: they describe the work's placement, not the container.
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    series: Optional[str] = None
    edition: Optional[str] = None
    publisher: Optional[str] = None
    address: Optional[str] = None
    organization: Optional[str] = None
    chapter: Optional[str] = None
    month: Optional[str] = None
    howpublished: Optional[str] = None
    type: Optional[str] = None

    abstract: Optional[str] = None
    note: Optional[str] = None

    identifiers: Dict[str, List[str]] = field(default_factory=dict)
    links: Dict[str, List[Link]] = field(default_factory=dict)

    project_ids: List[str] = field(default_factory=list)
    bibtex: Optional[str] = None
    derived: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        ``source.key`` is the citation key as written, which is ``bib_id``
        again: a consumer holding only the provenance record can still find
        the entry it came from.

        ``source.file`` is checked here rather than only where it was set:
        both exporters and the CLI serialize through this method, so a `Work`
        built by hand cannot carry an absolute path into the document.
        """
        reject_absolute_name(self.source_file)
        return {
            'bib_id': self.bib_id,
            'source': {'file': self.source_file, 'key': self.bib_id},
            'title': self.title,
            'authors': [a.to_dict() for a in self.authors],
            'editors': [e.to_dict() for e in self.editors],
            'year': self.year,
            'venue': self.venue.to_dict() if self.venue else None,
            'volume': self.volume,
            'number': self.number,
            'pages': self.pages,
            'series': self.series,
            'edition': self.edition,
            'publisher': self.publisher,
            'address': self.address,
            'organization': self.organization,
            'chapter': self.chapter,
            'month': self.month,
            'howpublished': self.howpublished,
            'type': self.type,
            'category': self.category,
            'entry_type': self.entry_type,
            'abstract': self.abstract,
            'note': self.note,
            'identifiers': {scheme: list(values)
                            for scheme, values in self.identifiers.items()},
            'links': {kind: [link.to_dict() for link in links]
                      for kind, links in self.links.items()},
            'project_ids': list(self.project_ids),
            'bibtex': self.bibtex,
            'derived': dict(self.derived),
        }


@dataclass
class Person:
    """A lab member (current or alumni)."""
    id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    role: Optional[str] = None
    status: str = "current"
    photo: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    co_advisor: Optional[str] = None
    start_year: Optional[int] = None

    end_year: Optional[int] = None
    degree: Optional[str] = None
    thesis_title: Optional[str] = None
    current_position: Optional[str] = None

    # Back-linked (computed, not from YAML input)
    work_ids: List[str] = field(default_factory=list)
    derived: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        ``aliases`` are read for matching and are not emitted. Every other
        declared property is present, and null when it does not apply — the
        alumni fields included, whatever the status.
        """
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'status': self.status,
            'photo': self.photo,
            'email': self.email,
            'website': self.website,
            'co_advisor': self.co_advisor,
            'start_year': self.start_year,
            'end_year': self.end_year,
            'degree': self.degree,
            'thesis_title': self.thesis_title,
            'current_position': self.current_position,
            'work_ids': list(self.work_ids),
            'derived': dict(self.derived),
        }


@dataclass
class Collaborator:
    """A grouping over unresolved authorships, not an identity.

    ``key`` is a lookup key and explicitly not an assertion about a human:
    a readable slug of the normalised name plus a short digest, so that
    adding an unrelated collaborator can never change an existing key.
    ``grouped_by`` names the policy that built it: ``normalized_name``, or
    ``declared`` for a grouping `collaborators_file` declares.

    ``name_kind`` is ``personal`` or ``literal``. It is not ``organization``:
    brace protection in BibTeX means "do not parse this", which covers
    organisations but also mononyms, so the document must not assert
    corporate-ness.

    ``authorships`` lists the occurrences that were grouped, each addressed by
    ``(work_id, position)``. A consumer that distrusts the grouping can ignore
    it and work from those occurrences instead.
    """
    key: str
    name: str
    grouped_by: str = "normalized_name"
    name_kind: str = "personal"
    given: Optional[str] = None
    von: Optional[str] = None
    family: Optional[str] = None
    suffix: Optional[str] = None
    literal: Optional[str] = None
    name_variants: List[str] = field(default_factory=list)
    authorships: List[Dict[str, object]] = field(default_factory=list)
    work_ids: List[str] = field(default_factory=list)
    last_year: Optional[int] = None
    derived: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'grouped_by': self.grouped_by,
            'name_kind': self.name_kind,
            'name': self.name,
            'given': self.given,
            'von': self.von,
            'family': self.family,
            'suffix': self.suffix,
            'literal': self.literal,
            'name_variants': list(self.name_variants),
            'authorships': [dict(a) for a in self.authorships],
            'work_ids': list(self.work_ids),
            'last_year': self.last_year,
            'derived': dict(self.derived),
        }


@dataclass
class Project:
    """A research project."""
    id: str
    title: str
    description: Optional[str] = None
    website: Optional[str] = None
    status: str = "active"

    # Back-linked (computed)
    work_ids: List[str] = field(default_factory=list)
    people_ids: List[str] = field(default_factory=list)
    derived: Dict[str, object] = field(default_factory=dict)

    # Declared last so it takes no other field's position in a positional
    # call; to_dict() emits it beside `website`.
    image: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'website': self.website,
            'image': self.image,
            'status': self.status,
            'work_ids': list(self.work_ids),
            'people_ids': list(self.people_ids),
            'derived': dict(self.derived),
        }


@dataclass
class LabData:
    """The fully resolved output: all entities with cross-references."""
    works: List[Work] = field(default_factory=list)
    people: List[Person] = field(default_factory=list)
    projects: List[Project] = field(default_factory=list)
    collaborators: List[Collaborator] = field(default_factory=list)
    lab: Optional[Dict[str, object]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        ``generator`` carries no timestamp: a build timestamp would make every
        run differ, and two runs over the same inputs must produce the same
        bytes (SPEC.md section 3). Git records when. The version is read here
        rather than at import time because the package imports this module
        while defining it.
        """
        from . import __version__

        return {
            'schema_version': SCHEMA_VERSION,
            'generator': {
                'name': GENERATOR_NAME,
                'version': __version__,
                'schema_version': SCHEMA_VERSION,
            },
            'lab': dict(self.lab or {}),
            'works': [w.to_dict() for w in self.works],
            'people': [p.to_dict() for p in self.people],
            'projects': [p.to_dict() for p in self.projects],
            'collaborators': [c.to_dict() for c in self.collaborators],
        }
