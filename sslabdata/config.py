"""
Configuration for sslabdata.

Single-layer configuration loaded from a YAML file (lab.yaml).

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import math
import os
import re
import yaml
from dataclasses import dataclass, field
from datetime import date
from typing import (Dict, List, NamedTuple, NoReturn, Optional, Sequence,
                    Tuple, Union)
from pathlib import Path, PureWindowsPath

from .diagnostics import Diagnostic, diagnostic


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

# `lab` is otherwise open, and it reaches both formats of the document, so
# every value in it at any depth must have one JSON form that YAML writes
# alike. A date or a timestamp becomes its ISO 8601 text, which keeps what the
# author wrote. Anything else JSON cannot carry is refused rather than
# guessed at: NaN and the infinities have no JSON form, a set's order changes
# between runs, binary has no meaning as text, and a key that is not a string
# is written as `2019` by YAML and `"2019"` by JSON. Fatal at load, because
# `--output` could not write it and `--validate` must fail where that does.
VALUE_NOT_JSON = "CONFIG-VALUE-NOT-JSON"

# A key given twice in one mapping of `lab.yaml`. PyYAML keeps the last value
# and says nothing, so the first would be lost without a trace, and which of
# the two the user meant is not sslabdata's to guess. Fatal at load, like
# every other `lab.yaml` of the wrong shape.
KEY_REPEATED = "CONFIG-KEY-REPEATED"

MERGE_TAG = "tag:yaml.org,2002:merge"

# A C0 control character other than tab, line feed and carriage return, or
# DEL. None is text (SPEC.md section 2): it makes an XML rendering of the
# document invalid, and U+0001 and U+0002 are the LaTeX conversion's own
# markers. Each is removed where the input is read, before anything else sees
# the value, and reported at the value: a `.bib` field value, or a YAML
# scalar, which can carry one as an escape (`"\x01"`).
CONTROL_CHARACTER = "TEXT-CONTROL-CHARACTER"
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def without_control_characters(text: str) -> Tuple[str, List[str]]:
    """``text`` with its control characters removed, and each character
    removed, once, as ``U+XXXX``, in the order first found."""
    found = list(dict.fromkeys(f"U+{ord(c):04X}" for c in _CONTROL.findall(text)))
    return (_CONTROL.sub("", text) if found else text), found


def control_message(found: List[str]) -> str:
    """What a control-character diagnostic says, for every input."""
    what = ("is a control character" if len(found) == 1
            else "are control characters")
    return (f"{', '.join(found)} {what}, not text; removed from this value, "
            "and the rest of it is kept")


class RepeatedKey(NamedTuple):
    """A key given again in a mapping it is already in.

    ``path`` leads from the document's root to that mapping: a mapping key
    as text, a list index as an integer. ``line`` is where the key is given
    again and ``first_line`` where it was first given, both counted from 1.
    """
    path: Tuple[Union[str, int], ...]
    key: str
    line: int
    first_line: int


class ControlCharacters(NamedTuple):
    """The control characters removed from one scalar, as ``U+XXXX``.

    ``path`` leads from the document's root to the scalar, as a
    `RepeatedKey`'s does; for a mapping key, it ends at that key.
    """
    path: Tuple[Union[str, int], ...]
    found: List[str]


class YAMLLoader(yaml.SafeLoader):
    """PyYAML's safe loader, which also records every repeated mapping key,
    and removes and records every control character (`CONTROL_CHARACTER`).

    Every YAML file sslabdata reads is read with it, through `read_yaml()`.
    Keys are compared as the loader constructs them, so `1` and `0x1`, which
    one dict would hold as one key, are a repeat too. A merge key (`<<`) is
    not: the keys it merges in are overridden by the mapping's own, which is
    what a merge is for, and PyYAML merges them as it always has.
    """

    def __init__(self, stream):
        super().__init__(stream)
        self.repeated: List[RepeatedKey] = []
        self.controls: List[ControlCharacters] = []

    def construct_scalar(self, node):
        return without_control_characters(super().construct_scalar(node))[0]

    def construct_document(self, node):
        seen = set()

        def controls(node, path):
            found = without_control_characters(node.value)[1]
            if found:
                self.controls.append(ControlCharacters(path, found))

        def walk(node, path):
            # An alias is the node it names, so each node is walked once,
            # where it first appears, and a recursive alias ends the walk.
            if id(node) in seen:
                return
            seen.add(id(node))
            if isinstance(node, yaml.ScalarNode):
                controls(node, path)
            elif isinstance(node, yaml.SequenceNode):
                for index, child in enumerate(node.value):
                    walk(child, (*path, index))
            elif isinstance(node, yaml.MappingNode):
                first: Dict[object, int] = {}
                for key_node, value_node in node.value:
                    if key_node.tag == MERGE_TAG:
                        walk(value_node, (*path, "<<"))
                        continue
                    # A key that is not a scalar cannot be a dict key;
                    # constructing the mapping reports it.
                    if not isinstance(key_node, yaml.ScalarNode):
                        continue
                    key = self.construct_object(key_node)
                    controls(key_node, (*path, str(key)))
                    line = key_node.start_mark.line + 1
                    if key in first:
                        self.repeated.append(RepeatedKey(
                            path, str(key), line, first[key]))
                    else:
                        first[key] = line
                    walk(value_node, (*path, str(key)))

        walk(node, ())
        return super().construct_document(node)


def read_yaml(stream) -> Tuple[object, List[RepeatedKey],
                               List[ControlCharacters]]:
    """One YAML document, every key repeated in a mapping of it, and every
    scalar its control characters were removed from."""
    loader = YAMLLoader(stream)
    try:
        return loader.get_single_data(), loader.repeated, loader.controls
    finally:
        loader.dispose()


def dotted(path: Sequence[Union[str, int]]) -> str:
    """A path as a diagnostic's field names it: keys joined by `.`, with a
    list member's index in brackets (`links.scores[1]`)."""
    text = ""
    for step in path:
        text += (f"[{step}]" if isinstance(step, int)
                 else f".{step}" if text else step)
    return text


def repeated_message(repeat: RepeatedKey) -> str:
    """What a repeated key's diagnostic says, in every file."""
    return (f"'{repeat.key}' is given at line {repeat.first_line} and again "
            f"at line {repeat.line} of one mapping; YAML would silently keep "
            "the last value")


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


def json_lab(lab: dict, file: Optional[str] = None) -> dict:
    """``lab`` as the document carries it, by the rule at `VALUE_NOT_JSON`.

    Returns a copy with every date and timestamp as ISO 8601 text, or raises
    at `<file>:lab:<path>`, where the path is the keys down to the value,
    joined by `.`, with a list member's index in brackets.
    """
    def plain(value, path):
        def refuse(what):
            raise ConfigurationError(diagnostic(
                VALUE_NOT_JSON, file, "lab", path or None,
                f"{f'lab.{path}' if path else 'lab'} {what}; a "
                "value under lab is text, a number, a boolean, a date, or a "
                "list or mapping of them with string keys"))
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, float) and not math.isfinite(value):
            refuse(f"is {value!r}, which JSON cannot write")
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, list):
            return [plain(v, f"{path}[{i}]") for i, v in enumerate(value)]
        if isinstance(value, dict):
            for key in value:
                if not isinstance(key, str):
                    refuse(f"has the key {key}, {_kind(key)}, which YAML and "
                           "JSON would write differently")
            return {k: plain(v, f"{path}.{k}" if path else k)
                    for k, v in value.items()}
        refuse(f"is {'binary' if isinstance(value, bytes) else _kind(value)}")

    return plain(lab, "")


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
    lab: Optional[Dict[str, object]] = None

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

    # A `CONTROL_CHARACTER` diagnostic for each value of `lab.yaml` its
    # control characters were removed from, for the assembler to report.
    # Never emitted.
    control_characters: List[Diagnostic] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> 'LabDataConfig':
        """Load configuration from a YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data, repeated, controls = read_yaml(f)

        def reject(code: str, key: Optional[str], field_name: Optional[str],
                   message: str) -> NoReturn:
            raise ConfigurationError(
                diagnostic(code, str(path), key, field_name, message))

        # The first repeat is reported, as the first of any other fault is.
        for repeat in repeated:
            reject(KEY_REPEATED, *_located((*repeat.path, repeat.key)),
                   repeated_message(repeat))

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
        lab = None if data.get('lab') is None else json_lab(data['lab'],
                                                            str(path))
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
            lab=lab,
            path=str(path),
            collaborators_file=data.get('collaborators_file'),
            unknown_keys=[str(key) for key in data if key not in KNOWN_KEYS],
            control_characters=[
                diagnostic(CONTROL_CHARACTER, str(path), *_located(found.path),
                           control_message(found.found))
                for found in controls],
        )


def _located(steps) -> Tuple[Optional[str], Optional[str]]:
    """A path in `lab.yaml` as any key of the file is located: the top-level
    key, then the path below it."""
    top = steps[0] if steps and isinstance(steps[0], str) else None
    return top, dotted(steps[1 if top else 0:]) or None


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
