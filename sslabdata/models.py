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

# `config` owns these checks and their codes. `to_dict()` repeats them
# because every document passes through it, including one built in Python
# (SPEC.md §1).
from .config import json_lab, reject_absolute_name


# The document's schema version (schema/v7/output.schema.json). When it
# changes is SPEC.md §6.
SCHEMA_VERSION = 7

GENERATOR_NAME = "sslabdata"

# Every to_dict() emits every declared key, `null` when it does not apply;
# the open maps carry only keys with values (SPEC.md §4).


@dataclass
class Venue:
    """Where a work appeared (SPEC.md §5)."""
    kind: str
    name: str

    def to_dict(self) -> dict:
        return {'kind': self.kind, 'name': self.name}


@dataclass
class Link:
    """One URL a work can be reached at, with its origin and verification
    status (SPEC.md §5)."""
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
class Award:
    """One award a work received: its name, and the year it was given, which
    need not be the work's (SPEC.md §5)."""
    name: str
    year: Optional[int] = None

    def to_dict(self) -> dict:
        return {'name': self.name, 'year': self.year}


@dataclass
class Contributor:
    """One person named on a work: the parts of the name, and who it resolved
    to (SPEC.md §5). The record ``work.editors`` carries.

    ``literal`` holds a name written as one brace-protected unit, where the
    other parts do not apply.
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
    """One authorship of a work, addressed by ``(work.bib_id, position)``
    (SPEC.md §5).

    Exactly one of ``person_id`` and ``collaborator_key`` is non-null.
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

    # The configured `bib_files[].name`, relative to `bib_dir`: see `to_dict()`.
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

    # Declared last so it takes no other field's position in a positional
    # call; to_dict() emits it beside `note`.
    awards: List[Award] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        ``source.file`` is checked here rather than only where it was set:
        every serializer passes through this method, so a `Work` built by hand
        cannot carry an absolute path into the document.
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
            'awards': [award.to_dict() for award in self.awards],
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

    # Plain text with its line breaks as written (SPEC.md §2). Declared last
    # so it takes no other field's position in a positional call; to_dict()
    # emits it beside `current_position`.
    bio: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization; ``aliases`` are read for
        matching and are not emitted."""
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
            'bio': self.bio,
            'work_ids': list(self.work_ids),
            'derived': dict(self.derived),
        }


@dataclass
class Collaborator:
    """A grouping over unresolved authorships, not an identity (SPEC.md §5)."""
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

        ``generator`` carries no timestamp, so the document is deterministic
        (SPEC.md §3). The version is imported here because the package imports
        this module while defining it.
        """
        from . import __version__

        return {
            'schema_version': SCHEMA_VERSION,
            'generator': {
                'name': GENERATOR_NAME,
                'version': __version__,
                'schema_version': SCHEMA_VERSION,
            },
            'lab': json_lab(dict(self.lab or {})),
            'works': [w.to_dict() for w in self.works],
            'people': [p.to_dict() for p in self.people],
            'projects': [p.to_dict() for p in self.projects],
            'collaborators': [c.to_dict() for c in self.collaborators],
        }
