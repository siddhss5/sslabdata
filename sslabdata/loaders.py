"""
YAML data loaders for people and projects.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import yaml
from dataclasses import dataclass, field
from typing import List
from pathlib import Path

from .config import _kind
from .diagnostics import Diagnostic, diagnostic
from .models import Person, Project


# What can be wrong with a people, projects or collaborators file, one code
# per condition and file; an unknown key is one code for all three, as the
# check is the same in each. A file that is not valid YAML or not a list of
# records, and a record missing a field it cannot be emitted without, fail
# every mode; a repeated id fails `--validate`, as a repeated citation key
# does; the rest are warnings. A required field that is not a string is as
# unusable as a missing one, and is reported under the same code.
PEOPLE_YAML_INVALID = "PEOPLE-YAML-INVALID"
PEOPLE_NOT_A_LIST = "PEOPLE-NOT-A-LIST"
PEOPLE_FIELD_MISSING = "PEOPLE-FIELD-MISSING"
PROJECTS_YAML_INVALID = "PROJECTS-YAML-INVALID"
PROJECTS_NOT_A_LIST = "PROJECTS-NOT-A-LIST"
PROJECTS_FIELD_MISSING = "PROJECTS-FIELD-MISSING"
COLLABORATORS_YAML_INVALID = "COLLABORATORS-YAML-INVALID"
COLLABORATORS_NOT_A_LIST = "COLLABORATORS-NOT-A-LIST"
COLLABORATORS_FIELD_MISSING = "COLLABORATORS-FIELD-MISSING"
PEOPLE_ID_DUPLICATE = "PEOPLE-ID-DUPLICATE"
PEOPLE_ROLE_INVALID = "PEOPLE-ROLE-INVALID"
PEOPLE_STATUS_INVALID = "PEOPLE-STATUS-INVALID"
PROJECTS_ID_DUPLICATE = "PROJECTS-ID-DUPLICATE"
PROJECTS_STATUS_INVALID = "PROJECTS-STATUS-INVALID"
RECORD_KEY_UNKNOWN = "RECORD-KEY-UNKNOWN"
RECORD_TYPE_INVALID = "RECORD-TYPE-INVALID"

# The keys each file's records are read for. Any other key is reported and
# ignored, so a misspelt `webiste` is not silently dropped from the document.
PERSON_KEYS = ("id", "name", "aliases", "role", "status", "photo", "website",
               "email", "co_advisor", "start_year", "end_year", "degree",
               "thesis_title", "current_position")
PROJECT_KEYS = ("id", "title", "description", "website", "image", "status")
COLLABORATOR_KEYS = ("name", "aliases")

# The YAML type each optional field of a record accepts, beyond `role` and
# `status`, which have codes of their own. The required fields (`id`, `name`,
# `title`) are strings. A value of any other type is reported and read as
# empty, so it is emitted as null (or, for aliases, declares none) and never
# reaches the document as the wrong type.
STRING, INTEGER, ALIASES = ("a string", "an integer",
                            "a list of non-empty strings")
PERSON_TYPES = {**dict.fromkeys(("photo", "website", "email", "co_advisor",
                                 "degree", "thesis_title",
                                 "current_position"), STRING),
                "start_year": INTEGER, "end_year": INTEGER,
                "aliases": ALIASES}
PROJECT_TYPES = dict.fromkeys(("description", "website", "image"), STRING)
COLLABORATOR_TYPES = {"aliases": ALIASES}

# A person's `status` is one of these. A `role` is any non-empty string, so
# that any lab's roles fit (SPEC.md section 5).
PERSON_STATUSES = ("current", "alumni")
PROJECT_STATUSES = ("active", "completed")


def _has_type(value, expected: str) -> bool:
    if expected == STRING:
        return isinstance(value, str)
    if expected == INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, list) and all(
        isinstance(v, str) and v.strip() for v in value)


def _records(path: str, codes, required, known, optional,
             diagnostics) -> List[dict]:
    """The records of one people, projects or collaborators file that can be
    emitted, every file checked the same way.

    ``codes`` are the file's YAML-invalid, not-a-list and field-missing
    codes, ``required`` the fields a record cannot be emitted without --
    each a non-empty string -- ``known`` the keys the file's records are read
    for and ``optional`` the type each optional field accepts.
    A missing file is not this function's to report (the assembler names the
    configuration key instead) and reads as no records, as does an empty one.
    A file that is not valid YAML or not a list, a record that is not a
    mapping and a record missing a required field are reported to
    ``diagnostics`` and left out. A kept record's unknown keys are reported
    at the record's first required field -- its `id`, or a collaborator's
    `name` -- and the record is kept without them, as it is with an optional
    field of the wrong type, which is set to ``None``.
    """
    yaml_invalid, not_a_list, field_missing = codes
    fail = diagnostics.append
    if not Path(path).exists():
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        fail(diagnostic(yaml_invalid, path, None, None,
                        " ".join(str(error).split())))
        return []

    if data is None:
        return []
    if not isinstance(data, list):
        fail(diagnostic(not_a_list, path, None, None,
                        "the file must be a list of records, one per entry; "
                        f"it is a {type(data).__name__}"))
        return []

    records = []
    for number, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            fail(diagnostic(not_a_list, path, None, None,
                            f"entry {number} is a {type(entry).__name__}, "
                            "not a record"))
            continue
        missing = [name for name in required
                   if not isinstance(entry.get(name), str)
                   or not entry[name].strip()]
        if missing:
            name, value = missing[0], entry.get(missing[0])
            key = entry.get('id')
            fail(diagnostic(
                field_missing, path, key if isinstance(key, str) else None,
                name, f"entry {number} has no {name}"
                if value is None or isinstance(value, str) else
                f"entry {number}'s {name} is {_kind(value)}; it must be a "
                "string"))
            continue
        # A YAML key need not be a string (`0:`, `true:`); it is named as
        # text so that every unknown key has a location, even a falsy one.
        for key in entry:
            if key not in known:
                diagnostics.append(diagnostic(
                    RECORD_KEY_UNKNOWN, path, entry[required[0]], str(key),
                    f"'{key}' is not a key sslabdata reads, and is ignored"))
        for name, expected in optional.items():
            if entry.get(name) is not None and not _has_type(entry[name],
                                                             expected):
                fail(diagnostic(
                    RECORD_TYPE_INVALID, path, entry[required[0]], name,
                    f"{name} is {_kind(entry[name])}; it must be {expected}, "
                    "and is read as empty"))
                entry[name] = None
        records.append(entry)
    return records


def _repeated_ids(records: List[dict], path: str, code: str, report) -> None:
    """Report each id declared again, at the record that repeats it; both
    are kept, as the parser library keeps a repeated citation key."""
    seen = set()
    for entry in records:
        key = entry['id']
        if key in seen:
            report(diagnostic(code, path, key, 'id',
                              f"the id '{key}' is declared more than once"))
        seen.add(key)


def load_people(path: str, diagnostics: List[Diagnostic]) -> List[Person]:
    """Load people from a YAML file.

    Expected format (list of dicts):
        - id: "aadams"
          name: "Alice Adams"
          aliases: ["A. Adams", "A. J. Adams"]
          role: "pi"
          status: "current"
          ...

    ``diagnostics`` receives what is wrong with the file.
    """
    warn = diagnostics.append
    people = []
    records = _records(path, (PEOPLE_YAML_INVALID, PEOPLE_NOT_A_LIST,
                              PEOPLE_FIELD_MISSING), ('id', 'name'), PERSON_KEYS,
                       PERSON_TYPES, diagnostics)
    _repeated_ids(records, path, PEOPLE_ID_DUPLICATE, diagnostics.append)
    for entry in records:
        role = entry.get('role')
        if not isinstance(role, str) or not role.strip():
            warn(diagnostic(PEOPLE_ROLE_INVALID, path, entry['id'], 'role',
                            "role is missing, empty or not a string; any "
                            "non-empty string is accepted"))
        status = entry.get('status', 'current')
        if status not in PERSON_STATUSES:
            warn(diagnostic(PEOPLE_STATUS_INVALID, path, entry['id'], 'status',
                            f"'{status}' is not one of "
                            f"{', '.join(PERSON_STATUSES)}"))
            # A status that is not a string reads as the absent default: the
            # schema requires a string, and the warning has said why.
            if not isinstance(status, str):
                status = 'current'
        person = Person(
            id=entry['id'],
            name=entry['name'],
            aliases=entry.get('aliases') or [],
            role=role if isinstance(role, str) else None,
            status=status,
            photo=entry.get('photo'),
            website=entry.get('website'),
            email=entry.get('email'),
            co_advisor=entry.get('co_advisor'),
            start_year=entry.get('start_year'),
            end_year=entry.get('end_year'),
            degree=entry.get('degree'),
            thesis_title=entry.get('thesis_title'),
            current_position=entry.get('current_position'),
        )
        people.append(person)

    return people


def load_projects(path: str, diagnostics: List[Diagnostic]) -> List[Project]:
    """Load projects from a YAML file.

    Expected format (list of dicts):
        - id: "gardenbot"
          title: "Robot-Assisted Gardening"
          description: "Autonomous gardening systems"
          website: "https://gardenbot.example.org"
          status: "active"

    The file is checked as `load_people()` checks its own; a project needs
    an id and a title.
    """
    warn = diagnostics.append
    records = _records(path, (PROJECTS_YAML_INVALID, PROJECTS_NOT_A_LIST,
                              PROJECTS_FIELD_MISSING), ('id', 'title'), PROJECT_KEYS,
                       PROJECT_TYPES, diagnostics)
    _repeated_ids(records, path, PROJECTS_ID_DUPLICATE, diagnostics.append)
    projects = []
    for entry in records:
        status = entry.get('status', 'active')
        if status not in PROJECT_STATUSES:
            warn(diagnostic(PROJECTS_STATUS_INVALID, path, entry['id'],
                            'status', f"'{status}' is not one of "
                            f"{', '.join(PROJECT_STATUSES)}"))
            if not isinstance(status, str):
                status = 'active'
        project = Project(
            id=entry['id'],
            title=entry['title'],
            description=entry.get('description'),
            website=entry.get('website'),
            image=entry.get('image'),
            status=status,
        )
        projects.append(project)

    return projects


@dataclass
class DeclaredCollaborator:
    """One external co-author declared in `collaborators_file`.

    It only groups authorships into `collaborators`; it is never a person
    and never produces a `person_id`.
    """
    name: str
    aliases: List[str] = field(default_factory=list)


def load_collaborators(path: str, diagnostics: List[Diagnostic]
                       ) -> List[DeclaredCollaborator]:
    """Load declared external co-authors from a YAML file.

    Expected format (list of dicts):
        - name: "Priya Patel"
          aliases: ["P. Patel"]

    The file is checked as `load_people()` checks its own; a collaborator
    needs a name.
    """
    records = _records(path, (COLLABORATORS_YAML_INVALID,
                              COLLABORATORS_NOT_A_LIST,
                              COLLABORATORS_FIELD_MISSING), ('name',),
                       COLLABORATOR_KEYS, COLLABORATOR_TYPES, diagnostics)
    return [DeclaredCollaborator(name=entry['name'],
                                 aliases=entry.get('aliases') or [])
            for entry in records]
