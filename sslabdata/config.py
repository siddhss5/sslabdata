"""
Configuration for sslabdata.

Single-layer configuration loaded from a YAML file (lab.yaml).

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa <siddh@cs.washington.edu>
MIT License - see LICENSE file for details.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path, PureWindowsPath

from .diagnostics import diagnostic


# A configured `.bib` name reaches the document as `work.source.file`, where
# it is promised never to be an absolute path (SPEC.md section 5): a document
# is shared, and one carrying a compiling machine's directory layout leaks it
# to every consumer. Rejecting the input is what makes the promise true;
# rewriting the name would quietly discard a relative directory the user
# meant. Both path flavours are checked, so the same configuration is
# accepted or rejected wherever it is compiled.
BIB_FILE_ABSOLUTE = "CONFIG-BIB-FILE-ABSOLUTE"

# A relative name can still leave `bib_dir`, by `..` or through a symlink:
# it would read a file the configuration was never meant to reach, and emit a
# name that exposes the layout above `bib_dir`. Fatal at load for the same
# reason as the absolute name.
BIB_FILE_OUTSIDE = "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR"

# A `lab.yaml` sslabdata cannot compile from, found while it is read. Each is
# fatal at load, like the absolute name above: nothing is assembled from a
# configuration whose shape is wrong, so there is no partial document either.
NOT_A_MAPPING = "CONFIG-NOT-A-MAPPING"
KEY_MISSING = "CONFIG-KEY-MISSING"
TYPE_INVALID = "CONFIG-TYPE-INVALID"

# Every key `lab.yaml` may hold. `site` is read by renderers, not by sslabdata,
# and is accepted without being checked. Any other key is reported, because a
# misspelt `people_fil` would otherwise be silently the same as no key at all.
KNOWN_KEYS = ("lab", "site", "bib_dir", "bib_files", "pdf_base_url",
              "people_file", "projects_file", "collaborators_file")

# The keys whose value, when present, must be a string: a path or a URL.
_STRING_KEYS = ("pdf_base_url", "people_file", "projects_file",
                "collaborators_file")

# The `lab` keys the schema types (`lab` is otherwise copied through open), by
# accepted YAML type. An empty value is not one: `name:` with nothing after it
# is null, and null is not a string.
_LAB_TYPES = {**dict.fromkeys(("name", "description", "institution",
                               "department", "website", "email", "address",
                               "logo"), str), "links": dict}


class ConfigurationError(ValueError):
    """A configuration sslabdata will not compile from.

    Its own type, not a bare ``ValueError``, so that a caller can tell a
    rejected configuration from anything else that raises one. Its message
    is one coded diagnostic line (SPEC.md, *Diagnostic codes*).
    """


def is_absolute_path(name: str) -> bool:
    """True when ``name`` is rooted rather than relative to ``bib_dir``.

    Both path flavours, and a leading separator on its own: ``/x.bib`` is
    absolute on POSIX, ``C:\\x.bib`` and ``\\\\server\\share\\x.bib`` are absolute
    on Windows, and ``\\x.bib`` is rooted on Windows even though Python does
    not call it absolute without a drive. All four escape ``bib_dir``, which
    is the thing being ruled out.
    """
    return name.startswith(("/", "\\")) or PureWindowsPath(name).is_absolute()


def reject_absolute_name(name, file: Optional[str] = None) -> None:
    """Raise when a configured `.bib` name would reach the document absolute.

    The diagnostic is located at `<file>:bib_files:name`. A caller that knows
    which file the configuration came from names it; one that does not
    leaves the file part empty.
    """
    if isinstance(name, str) and is_absolute_path(name):
        raise ConfigurationError(diagnostic(
            BIB_FILE_ABSOLUTE, file, "bib_files", "name",
            f"'{name}' is an absolute path; a bib_files name is a name under "
            "bib_dir, and it is emitted as the work's source.file, which is "
            "never absolute"))


def reject_name_outside_bib_dir(name, bib_dir, file: Optional[str] = None) -> None:
    """Raise when a configured `.bib` name does not stay under ``bib_dir``.

    Two checks. The lexical one reads ``name`` by Windows rules, which take
    both ``/`` and ``\\`` as separators, on every host: a name with a ``..``
    component, or a drive (``C:x.bib`` is relative to a drive's current
    directory, so `is_absolute_path` lets it through), is rejected wherever
    it is compiled. The filesystem one then resolves symlinks and requires
    the file to lie inside the resolved ``bib_dir``. A file that does not
    exist is not rejected here, so a missing one keeps its not-found
    diagnostic; a dangling symlink whose target is outside is.

    The diagnostic is located at `<file>:bib_files:name`, as for
    `reject_absolute_name`.
    """
    if not isinstance(name, str) or "\0" in name:
        return
    parts = PureWindowsPath(name)
    escapes = bool(parts.drive) or ".." in parts.parts
    if not escapes:
        root = Path(os.path.realpath(bib_dir))
        # The path the readers open, built the way they build it: with an
        # empty bib_dir it is rooted, not relative to the working directory.
        target = Path(os.path.realpath(f"{bib_dir}/{name}"))
        escapes = not target.is_relative_to(root)
    if escapes:
        raise ConfigurationError(diagnostic(
            BIB_FILE_OUTSIDE, file, "bib_files", "name",
            f"'{name}' is not under bib_dir '{bib_dir}'; a bib_files name is "
            "a name under bib_dir, with no '..' component and no symlink "
            "leading out of it"))


@dataclass
class BibFile:
    """A single BibTeX file and its category label.

    ``name`` is a name under ``bib_dir``, not a path of its own: it is
    emitted as ``work.source.file`` and must never be absolute. The
    constructor checks it where the mistake is made, but a plain, mutable
    dataclass can be changed afterwards, so `sslabdata.models.Work.to_dict()`
    checks again (SPEC.md, *`sslabdata.ConfigurationError`*).
    """
    name: str
    category: str

    def __post_init__(self):
        reject_absolute_name(self.name)


@dataclass
class LabDataConfig:
    """Configuration for sslabdata, loadable from YAML.

    Example lab.yaml:
        lab:
          name: "My Lab"
          description: "What our lab does"
          website: "https://mylab.edu"

        bib_dir: "data/bib"
        bib_files:
          - name: "journal.bib"
            category: "Journal Papers"
          - name: "conference.bib"
            category: "Conference Papers"

        pdf_base_url: "https://lab.edu/pdfs"
        people_file: "data/people.yaml"
        projects_file: "data/projects.yaml"
        collaborators_file: "data/collaborators.yaml"
    """
    bib_dir: str
    bib_files: List[BibFile]
    pdf_base_url: Optional[str] = None
    people_file: Optional[str] = None
    projects_file: Optional[str] = None
    lab: Optional[Dict[str, str]] = None

    # Where this configuration was read from, so a diagnostic about it can
    # name the file the user would edit. Never emitted.
    path: Optional[str] = None

    # External co-authors whose spellings should be grouped together. After
    # `path`, so the fields above keep their positions in the constructor.
    collaborators_file: Optional[str] = None

    # Keys `lab.yaml` held that sslabdata does not read, in file order, so the
    # assembler can report them against `path`. A YAML key need not be a
    # string (`7:`, `2025-01-01:`); it is named as text, as a record's unknown
    # key is, so that a diagnostic's `key` is always a string. Never emitted.
    unknown_keys: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> 'LabDataConfig':
        """Load configuration from a YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        def reject(code, key, field_name, message):
            raise ConfigurationError(
                diagnostic(code, str(path), key, field_name, message))

        if not isinstance(data, dict):
            reject(NOT_A_MAPPING, None, None,
                   f"the configuration is {_kind(data)}, not a mapping of keys")
        if data.get('bib_dir') is None:
            reject(KEY_MISSING, 'bib_dir', None,
                   "the required key bib_dir is missing")
        if not isinstance(data['bib_dir'], str):
            reject(TYPE_INVALID, 'bib_dir', None,
                   f"bib_dir is {_kind(data['bib_dir'])}; it must be a string")
        if data.get('lab') is not None and not isinstance(data['lab'], dict):
            reject(TYPE_INVALID, 'lab', None,
                   f"lab is {_kind(data['lab'])}; it must be a mapping")
        for key, expected in _LAB_TYPES.items():
            if key in (data.get('lab') or {}) and not isinstance(
                    data['lab'][key], expected):
                reject(TYPE_INVALID, 'lab', key,
                       f"lab.{key} is {_kind(data['lab'][key])}; it must be "
                       f"{'a mapping' if expected is dict else 'a string'}")
        for key in _STRING_KEYS:
            if data.get(key) is not None and not isinstance(data[key], str):
                reject(TYPE_INVALID, key, None,
                       f"{key} is {_kind(data[key])}; it must be a string")
        entries = data.get('bib_files')
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            reject(TYPE_INVALID, 'bib_files', None,
                   f"bib_files is {_kind(entries)}; it must be a list of "
                   "{name, category} mappings")
        # An entry is a mapping of exactly a string `name` and a string
        # `category`: both reach the document as strings (`work.source.file`
        # and `work.category`), so neither is coerced.
        for number, bf in enumerate(entries, start=1):
            if not isinstance(bf, dict):
                reject(TYPE_INVALID, 'bib_files', None,
                       f"bib_files entry {number} is {_kind(bf)}; it must be "
                       "a {name, category} mapping")
            for key in bf:
                if key not in ('name', 'category'):
                    reject(TYPE_INVALID, 'bib_files', str(key),
                           f"bib_files entry {number} has the key '{key}'; "
                           "an entry holds only name and category")
            for required in ('name', 'category'):
                if bf.get(required) is None:
                    reject(KEY_MISSING, 'bib_files', required,
                           f"bib_files entry {number} has no {required}")
                if not isinstance(bf[required], str):
                    reject(TYPE_INVALID, 'bib_files', required,
                           f"bib_files entry {number} has a {required} that "
                           f"is {_kind(bf[required])}; it must be a string")

        # Checked here as well as in `BibFile`, because here the file the
        # user would edit is known and the diagnostic can name it.
        for bf in entries:
            reject_absolute_name(bf['name'], str(path))
        for bf in entries:
            reject_name_outside_bib_dir(bf['name'], data['bib_dir'], str(path))

        bib_files = [BibFile(**bf) for bf in entries]

        return cls(
            bib_dir=data['bib_dir'],
            bib_files=bib_files,
            pdf_base_url=data.get('pdf_base_url'),
            people_file=data.get('people_file'),
            projects_file=data.get('projects_file'),
            lab=data.get('lab'),
            path=str(path),
            collaborators_file=data.get('collaborators_file'),
            unknown_keys=[str(key) for key in data if key not in KNOWN_KEYS],
        )


def _kind(value) -> str:
    """What a YAML value is, in the words a diagnostic uses for it."""
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a mapping"
    return f"a {type(value).__name__}"
