"""
YAML data loaders for people and projects.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import yaml
from dataclasses import dataclass, field
from typing import Dict, List
from pathlib import Path

from .config import (
    CONTROL_CHARACTER, RepeatedKey, _kind, control_message, dotted,
    read_yaml, repeated_message,
)
from .diagnostics import Diagnostic, diagnostic
from .models import EarlierRole, Person, Project


# One code per condition and file; the RECORD-* codes cover all three files
# (SPEC.md "Diagnostic codes").
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
PEOPLE_ROLE_YEARS_INVALID = "PEOPLE-ROLE-YEARS-INVALID"
PEOPLE_STATUS_INVALID = "PEOPLE-STATUS-INVALID"
PROJECTS_ID_DUPLICATE = "PROJECTS-ID-DUPLICATE"
PROJECTS_STATUS_INVALID = "PROJECTS-STATUS-INVALID"
RECORD_KEY_UNKNOWN = "RECORD-KEY-UNKNOWN"
RECORD_KEY_REPEATED = "RECORD-KEY-REPEATED"
RECORD_TYPE_INVALID = "RECORD-TYPE-INVALID"

# The keys each file's records are read for. Any other key is reported and
# ignored, so a misspelt `webiste` is not silently dropped from the document.
# A role's keys are read on a person, for the current or last role, and on
# each of its `earlier_roles`; `status` and `current_position` describe the
# person and are read on the person alone (SPEC.md §5).
ROLE_KEYS = ("role", "start_year", "end_year", "degree", "thesis_title",
             "co_advisor")
PERSON_KEYS = ("id", "name", "aliases", *ROLE_KEYS, "status", "photo",
               "website", "email", "current_position", "bio", "earlier_roles")
PROJECT_KEYS = ("id", "title", "description", "website", "image", "status")
COLLABORATOR_KEYS = ("name", "aliases")

# The type each optional field accepts; `role` and `status` have codes of
# their own. A value of another type is read as empty, so it never reaches the
# document as the wrong type.
STRING, INTEGER, ALIASES, ROLES = ("a string", "an integer",
                                   "a list of non-empty strings",
                                   "a list of earlier roles")
ROLE_TYPES = {"start_year": INTEGER, "end_year": INTEGER,
              **dict.fromkeys(("degree", "thesis_title", "co_advisor"),
                              STRING)}
PERSON_TYPES = {**ROLE_TYPES,
                **dict.fromkeys(("photo", "website", "email",
                                 "current_position", "bio"), STRING),
                "aliases": ALIASES, "earlier_roles": ROLES}
PROJECT_TYPES = dict.fromkeys(("description", "website", "image"), STRING)
COLLABORATOR_TYPES = {"aliases": ALIASES}

# There is no list of roles: any non-empty string is one, so that any lab's
# roles fit (SPEC.md §5).
PERSON_STATUSES = ("current", "alumni")
PROJECT_STATUSES = ("active", "completed")


def _has_type(value, expected: str) -> bool:
    if expected == STRING:
        return isinstance(value, str)
    if expected == INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == ROLES:
        # Each entry is checked as a role is, by `_earlier_roles()`.
        return isinstance(value, list)
    return isinstance(value, list) and all(
        isinstance(v, str) and v.strip() for v in value)


def _check_fields(entry: dict, known, optional, report) -> None:
    """Report each key of ``entry`` not in ``known`` and each optional field
    whose value is not of the type ``optional`` gives it, reading that value
    as empty. ``report(code, field, message)`` locates a diagnostic at the
    record. A person, a project, a collaborator and an earlier role are each
    checked by this one function."""
    # A YAML key need not be a string (`0:`, `true:`); it is named as text so
    # that every unknown key has a location, even a falsy one.
    for key in entry:
        if key not in known:
            report(RECORD_KEY_UNKNOWN, str(key),
                   f"'{key}' is not a key sslabdata reads, and is ignored")
    for name, expected in optional.items():
        if entry.get(name) is not None and not _has_type(entry[name],
                                                         expected):
            report(RECORD_TYPE_INVALID, name,
                   f"{name} is {_kind(entry[name])}; it must be {expected}, "
                   "and is read as empty")
            entry[name] = None


def _role_is_invalid(role) -> bool:
    """Whether a role draws `PEOPLE-ROLE-INVALID`, on a person or an earlier
    role: any non-empty string is a role (SPEC.md §5)."""
    return not isinstance(role, str) or not role.strip()


def _records(path: str, codes, required, known, optional,
             diagnostics) -> List[dict]:
    """The records of one people, projects or collaborators file that can be
    emitted, every file checked the same way.

    ``codes`` are the file's YAML-invalid, not-a-list and field-missing
    codes, ``required`` the fields a record cannot be emitted without --
    each a non-empty string, the first naming the record -- ``known`` the
    keys the file's records are read for and ``optional`` the type each
    optional field accepts. A missing file reads as no records: the assembler
    reports it, naming the configuration key.
    """
    yaml_invalid, not_a_list, field_missing = codes
    fail = diagnostics.append
    if not Path(path).exists():
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data, repeated, controls = read_yaml(f)
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        fail(diagnostic(yaml_invalid, path, None, None,
                        " ".join(str(error).split())))
        return []

    # Each located as a repeat is: at the record, named by its first required
    # field, and the path inside it; or, outside any record, at the path.
    for found in controls:
        index = found.path[0] if found.path else None
        record = (data[index] if isinstance(data, list)
                  and isinstance(index, int) else None)
        key = record.get(required[0]) if isinstance(record, dict) else None
        fail(diagnostic(CONTROL_CHARACTER, path,
                        key if isinstance(key, str) else None,
                        dotted(found.path[1:] if isinstance(record, dict)
                               else found.path) or None,
                        control_message(found.found)))

    # Each repeat inside a record is reported with that record, below; one
    # anywhere else is reported here, at the file and the path to the key.
    in_record: Dict[int, List[RepeatedKey]] = {}
    for repeat in repeated:
        index = repeat.path[0] if repeat.path else None
        if (isinstance(data, list) and isinstance(index, int)
                and isinstance(data[index], dict)):
            in_record.setdefault(index, []).append(repeat)
        else:
            fail(diagnostic(RECORD_KEY_REPEATED, path, None,
                            dotted((*repeat.path, repeat.key)),
                            repeated_message(repeat)))

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
        if number - 1 in in_record:
            # The record is named by its first required field, unless that
            # is the key given twice.
            repeats = in_record[number - 1]
            key = entry.get(required[0])
            if (not isinstance(key, str) or
                    any(r.path == (number - 1,) and r.key == required[0]
                        for r in repeats)):
                key = None
            for repeat in repeats:
                fail(diagnostic(RECORD_KEY_REPEATED, path, key,
                                dotted((*repeat.path[1:], repeat.key)),
                                repeated_message(repeat)))
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
        _check_fields(entry, known, optional,
                      lambda code, name, message, key=entry[required[0]]:
                      fail(diagnostic(code, path, key, name, message)))
        records.append(entry)
    return records


def _earlier_roles(entry: dict, path: str, warn) -> List[EarlierRole]:
    """A person's `earlier_roles`, each entry checked as the person's own
    role fields are, by the same functions, and located at the person and
    the entry (`earlier_roles[1].end_year`). An entry that is not a record,
    or whose role is not a string, cannot be emitted and is reported and left
    out; any other problem is reported and the entry kept. Then the years
    are checked as one history (`_check_role_years()`)."""
    roles: List[EarlierRole] = []
    places: List[int] = []
    for index, item in enumerate(entry.get('earlier_roles') or []):
        at = f"earlier_roles[{index}]"

        def report(code, name, message, at=at):
            warn(diagnostic(code, path, entry['id'], f"{at}.{name}",
                            message))

        if not isinstance(item, dict):
            warn(diagnostic(RECORD_TYPE_INVALID, path, entry['id'], at,
                            f"{at} is {_kind(item)}; it must be a record "
                            "with a role, and is left out"))
            continue
        role = item.get('role')
        if not isinstance(role, str):
            report(RECORD_TYPE_INVALID, 'role',
                   f"role is {_kind(role)}; an earlier role must have a role, "
                   "a string, and this one is left out")
            continue
        _check_fields(item, ROLE_KEYS, ROLE_TYPES, report)
        if _role_is_invalid(role):
            report(PEOPLE_ROLE_INVALID, 'role',
                   "role is empty; any non-empty string is accepted")
        roles.append(EarlierRole(
            role=role,
            start_year=item.get('start_year'),
            end_year=item.get('end_year'),
            degree=item.get('degree'),
            thesis_title=item.get('thesis_title'),
            co_advisor=item.get('co_advisor'),
        ))
        places.append(index)
    _check_role_years(roles, places, entry.get('start_year'),
                      lambda index, name, message: warn(diagnostic(
                          PEOPLE_ROLE_YEARS_INVALID, path, entry['id'],
                          f"earlier_roles[{index}].{name}", message)))
    return roles


def _check_role_years(roles: List[EarlierRole], places: List[int],
                      current_start, report) -> None:
    """Report years that cannot be one history: an earlier role that ends
    before it starts, one that starts before one listed above it or after the
    current role, and one that ends after the current role starts. A year
    that is absent is not compared. ``places`` holds each role's index in
    the file, and ``report(index, field, message)`` locates a diagnostic."""
    latest = None
    for role, index in zip(roles, places):
        start, end = role.start_year, role.end_year
        if start is not None and end is not None and end < start:
            report(index, 'end_year', f"ends in {end}, before it starts in "
                   f"{start}")
        if start is not None:
            if latest is not None and start < latest:
                report(index, 'start_year', f"starts in {start}, before an "
                       "earlier role listed above it, which starts in "
                       f"{latest}; earlier roles are listed oldest first")
            elif current_start is not None and start > current_start:
                report(index, 'start_year', f"starts in {start}, after the "
                       f"current role, which starts in {current_start}")
            latest = start if latest is None else max(latest, start)
        if (end is not None and current_start is not None
                and end > current_start):
            report(index, 'end_year', f"ends in {end}, after the current "
                   f"role starts in {current_start}")


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
    """Load people from a YAML file (format: README.md); ``diagnostics``
    receives what is wrong with it."""
    warn = diagnostics.append
    people = []
    records = _records(path, (PEOPLE_YAML_INVALID, PEOPLE_NOT_A_LIST,
                              PEOPLE_FIELD_MISSING), ('id', 'name'), PERSON_KEYS,
                       PERSON_TYPES, diagnostics)
    _repeated_ids(records, path, PEOPLE_ID_DUPLICATE, diagnostics.append)
    for entry in records:
        role = entry.get('role')
        if _role_is_invalid(role):
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
            bio=entry.get('bio'),
            earlier_roles=_earlier_roles(entry, path, warn),
        )
        people.append(person)

    return people


def load_projects(path: str, diagnostics: List[Diagnostic]) -> List[Project]:
    """Load projects from a YAML file, checked as `load_people()` checks
    its own."""
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
    """Load declared external co-authors from a YAML file, checked as
    `load_people()` checks its own."""
    records = _records(path, (COLLABORATORS_YAML_INVALID,
                              COLLABORATORS_NOT_A_LIST,
                              COLLABORATORS_FIELD_MISSING), ('name',),
                       COLLABORATOR_KEYS, COLLABORATOR_TYPES, diagnostics)
    return [DeclaredCollaborator(name=entry['name'],
                                 aliases=entry.get('aliases') or [])
            for entry in records]
