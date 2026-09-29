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
import unicodedata
import yaml
from dataclasses import dataclass, field
from datetime import date
from typing import (Dict, List, NamedTuple, NoReturn, Optional, Sequence,
                    Tuple, Union)
from pathlib import Path, PureWindowsPath

from .diagnostics import Diagnostic, diagnostic


# A `.bib` name is emitted as `work.source.file`, never absolute (SPEC.md §5).
# Both path flavours are checked, so a configuration is accepted or rejected
# alike wherever it is compiled.
BIB_FILE_ABSOLUTE = "CONFIG-BIB-FILE-ABSOLUTE"

BIB_FILE_OUTSIDE = "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR"

NOT_A_MAPPING = "CONFIG-NOT-A-MAPPING"
KEY_MISSING = "CONFIG-KEY-MISSING"
TYPE_INVALID = "CONFIG-TYPE-INVALID"

# Every key `lab.yaml` may hold; any other is reported. `site` is read by
# renderers, not by sslabdata, and is accepted without being checked.
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

# `lab` reaches both formats of the document, so every value in it must have
# one JSON form that YAML writes alike (SPEC.md "Diagnostic codes").
VALUE_NOT_JSON = "CONFIG-VALUE-NOT-JSON"

KEY_REPEATED = "CONFIG-KEY-REPEATED"

MERGE_TAG = "tag:yaml.org,2002:merge"

# The control characters that are not text (SPEC.md §2). They are removed
# where the input is read, before anything else sees the value: U+0001 and
# U+0002 are also the LaTeX conversion's own markers.
CONTROL_CHARACTER = "TEXT-CONTROL-CHARACTER"
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def without_control_characters(text: str) -> Tuple[str, List[str]]:
    """``text`` with its control characters removed, and each character
    removed, once, as ``U+XXXX``, in the order first found."""
    found = list(dict.fromkeys(f"U+{ord(c):04X}" for c in _CONTROL.findall(text)))
    return (_CONTROL.sub("", text) if found else text), found


def nfc(text: str) -> str:
    """``text`` in Unicode Normalization Form C (SPEC.md §2).

    Applied where the input is read, after control characters are removed,
    whose removal can leave a letter and its combining mark side by side. A
    canonically equivalent spelling is the same text, so nothing is reported.
    """
    return unicodedata.normalize("NFC", text)


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
    """PyYAML's safe loader, which also records every repeated mapping key
    -- PyYAML alone keeps the last value silently -- and removes and records
    every control character, and puts every string in NFC.

    Every YAML file sslabdata reads is read with it, through `read_yaml()`.
    Keys are compared as the loader constructs them, so `1` and `0x1`, which
    one dict would hold as one key, are a repeat too.
    """

    def __init__(self, stream):
        super().__init__(stream)
        self.repeated: List[RepeatedKey] = []
        self.controls: List[ControlCharacters] = []

    def construct_scalar(self, node):
        return nfc(without_control_characters(super().construct_scalar(node))[0])

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
    """A configuration sslabdata will not compile from (SPEC.md §1). Its
    message is one coded diagnostic line."""


def is_absolute_path(name: str) -> bool:
    """True when ``name`` is rooted rather than relative to ``bib_dir``.

    A leading separator counts: ``\\x.bib`` is rooted on Windows even though
    Python does not call it absolute without a drive.
    """
    return name.startswith(("/", "\\")) or PureWindowsPath(name).is_absolute()


def reject_absolute_name(name, file: Optional[str] = None) -> None:
    """Raise when a configured `.bib` name would reach the document absolute,
    located at `<file>:bib_files:name`."""
    if isinstance(name, str) and is_absolute_path(name):
        raise ConfigurationError(diagnostic(
            BIB_FILE_ABSOLUTE, file, "bib_files", "name",
            f"'{name}' is an absolute path; a bib_files name is a name under "
            "bib_dir, and it is emitted as the work's source.file, which is "
            "never absolute"))


def reject_empty_pdf_base_url(value, file: Optional[str] = None) -> None:
    """Raise when ``pdf_base_url`` is empty or whitespace alone, located at
    `<file>:pdf_base_url:`. Only leaving the key out, or `None`, means no PDF
    link is guessed: an empty base is more likely a mistake than that."""
    if isinstance(value, str) and not value.strip():
        raise ConfigurationError(diagnostic(
            TYPE_INVALID, file, "pdf_base_url", None,
            "pdf_base_url is empty or whitespace alone; name a base URL or "
            "directory, or leave pdf_base_url out to guess no PDF links"))


def reject_name_outside_bib_dir(name, bib_dir, file: Optional[str] = None) -> None:
    """Raise when a configured `.bib` name does not stay under ``bib_dir``
    (SPEC.md "Diagnostic codes"), located as `reject_absolute_name` locates.

    The lexical check reads ``name`` by Windows rules on every host, so the
    result does not depend on where it is compiled.
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
    """``lab`` as the document carries it: a copy with every date and
    timestamp as ISO 8601 text, or `VALUE_NOT_JSON` raised at the value."""
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

    ``name`` is a name under ``bib_dir``. It is checked here and, because the
    dataclass is mutable, again by `Work.to_dict()` (SPEC.md §1).
    """
    name: str
    category: str

    def __post_init__(self):
        reject_absolute_name(self.name)


@dataclass
class LabDataConfig:
    """Configuration for sslabdata, loadable from a `lab.yaml` (format:
    README.md)."""
    bib_dir: str
    bib_files: List[BibFile]
    pdf_base_url: Optional[str] = None
    people_file: Optional[str] = None
    projects_file: Optional[str] = None
    lab: Optional[Dict[str, object]] = None

    # Where this configuration was read from, so a diagnostic about it can
    # name the file the user would edit. Never emitted.
    path: Optional[str] = None

    # After `path`, so the fields above keep their positions in the
    # constructor.
    collaborators_file: Optional[str] = None

    # Keys `lab.yaml` held that sslabdata does not read, for the assembler to
    # report. Named as text, because a YAML key need not be a string (`7:`).
    # Never emitted.
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
        reject_empty_pdf_base_url(data.get('pdf_base_url'), str(path))
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
