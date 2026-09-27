"""
BibTeX parsing pipeline.

pybtex reads the files — @string macros, BibTeX's own name splitting, entry
order — and this module maps its Entry and Person objects onto sslabdata's
Work model: per-field LaTeX conversion (latex.py), the structured venue,
identifiers, links and diagnostics.

Together with latex.py this is the adapter: no other module imports pybtex or
pylatexenc, and nothing here lets a library object or a library message reach
the rest of sslabdata.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import pybtex.errors
from pybtex.database import Entry, Person
from pybtex.exceptions import PybtexError
from pybtex.database.input.bibtex import (
    LowLevelParser, Parser as PybtexParser, SkipEntry, UndefinedMacro,
)
from pybtex.scanner import PybtexSyntaxError

from .latex import latex_to_text, strip_braces, unknown_commands
from ..diagnostics import Diagnostic, diagnostic
from ..models import Author, Contributor, Link, Venue, Work


# Field values that hold prose and are converted from LaTeX to plain text.
# Everything else (url, doi, eprint, project, ...) is data, and is kept raw.
TEXT_FIELDS = frozenset({
    "title", "abstract", "note", "journal", "booktitle", "school",
    "institution", "type", "series", "publisher", "address", "organization",
})

# A name list ending in "and others" means "et al."; it is not an author.
OTHERS = "others"

# A stable code makes validation output suitable for CI and tooling without
# making callers depend on its English wording. The code names the condition
# only: the same duplicate is an error under --validate and a warning
# elsewhere, so severity is not part of it. See "Diagnostic codes" in SPEC.md.
DUPLICATE_CITATION_KEY = "BIB-DUPLICATE-KEY"

# An entry that cross-refers to another is rejected rather than resolved, so
# no work carries a field its own entry did not write. A hard error costs one
# edit, and going from "rejected" to "supported" later is additive.
CROSSREF_UNSUPPORTED = "BIB-CROSSREF-UNSUPPORTED"

# An entry with no year is emitted with `year: null` and says so, rather than
# claiming year 0 — a value indistinguishable from a real year 0 that would
# also put the entry somewhere meaningless in the order.
YEAR_MISSING = "BIB-YEAR-MISSING"

# A year that is present but is not a number is treated as no year, and says
# so, rather than stopping the run: the entry is still a work.
YEAR_INVALID = "BIB-YEAR-INVALID"

# A `doi` that is a resolver URL with nothing after it. It names no DOI, so
# the work gets no DOI identifier and no link rather than an empty one.
DOI_INVALID = "BIB-DOI-INVALID"

# A value naming an `@string` macro that nothing defines. The parser library
# reads it as empty, as BibTeX does; the entry is kept.
STRING_UNDEFINED = "BIB-STRING-UNDEFINED"

# Text the parser library could not read as BibTeX. Inside an entry, the
# entry is kept as far as it was read; outside one, the text is skipped.
SYNTAX_ERROR = "BIB-SYNTAX-ERROR"

# An `@article` with no `journal`, or an `@inproceedings` with no
# `booktitle`. Its venue is null, or read from another container field it
# does carry.
VENUE_MISSING = "BIB-VENUE-MISSING"

# An entry of a type sslabdata does not document. It is kept, and its venue is
# read by the field rules alone.
ENTRY_TYPE_UNSUPPORTED = "BIB-ENTRY-TYPE-UNSUPPORTED"

# Every `@string` macro a run defines more than once, in one summary line.
# The last definition is used, as in BibTeX. Always a warning, in every mode.
STRING_REDEFINED = "BIB-STRING-REDEFINED"

# A message the parser library raised that is neither a syntax error nor an
# undefined macro -- a field repeated in one entry, a name list it cannot
# split -- kept in the library's own words after the code.
PARSER_MESSAGE = "BIB-PARSER-MESSAGE"

# A field whose LaTeX the converter could not read at all; its text is kept
# as written, with the braces taken off.
LATEX_CONVERSION_FAILED = "LATEX-CONVERSION-FAILED"

# An entry that could not be written back out as BibTeX; its `bibtex` is null.
WRITE_BACK_FAILED = "BIB-WRITE-BACK-FAILED"

# A `.bib` file that is not UTF-8. Fatal, and no other encoding is guessed:
# reading Latin-1 bytes as something else would silently change names.
ENCODING_INVALID = "BIB-ENCODING-INVALID"

# A LaTeX command the converter does not know. It is dropped, and a braced
# argument after it is kept as plain text.
LATEX_COMMAND_UNKNOWN = "LATEX-COMMAND-UNKNOWN"

# Equal contribution is written as a star on one part of a name, in one of
# these four forms. It is an annotation rather than part of the name, so it is
# taken off the part before the name is read and recorded on the author
# instead. Other author annotations — corresponding author, affiliation
# numbers, daggers — are not read.
#
# A star, caret or dollar written with a backslash in front of it is escaped
# text rather than the start of a marker: `Brown\*` is not marked, and the
# ordinary LaTeX conversion then consumes the escaped star, so the name reads
# `Brown` (tests/COVERAGE.md row `names.equal_contribution_escaped`). The
# accent in `C{\^o}t{\'e}$^{*}$` is escaped the same way, and the marker after
# it is not, which is why that name reads `Côté` and is marked.
_WRITTEN = r"\$\^\{\*\}\$|\^\{\*\}|\\textsuperscript\s*\{\*\}"
_MARKER = rf"(?<!\\)(?:{_WRITTEN}|\*)"

# A marker at the end of a name part, on its own or in a brace group of its
# own: BibTeX grouping such as `Brown{$^{*}$}` protects the marker from the
# name, and does not make it part of it. Only a form that brings its own
# command is unwrapped, because a lone `{*}` is how any other command takes
# its argument — the star in `Brown\^{*}` is an accented star, not a marker.
_ANY_MARKER = rf"(?:(?<!\\)\{{\s*(?:{_WRITTEN})\s*\}}|{_MARKER})"
EQUAL_CONTRIBUTION = re.compile(rf"{_ANY_MARKER}\s*$")

# `\textsuperscript {*}`, with a space before the argument, is the same form:
# BibTeX splits a name on spaces, so the command and its argument arrive as two
# name parts and neither is a marker on its own. Only this one command takes
# its argument back, written as the command and not as an escaped backslash,
# and only from a part that is the argument and nothing but further markers —
# so the accent in `Brown\^ {*}`, a `{*}` after any other command, and a part
# carrying text of its own all keep their own boundary. What the part carries
# after `{*}` is left to the stripping below, as it is for an unspaced marker.
_MARKER_COMMAND = re.compile(r"(?<!\\)\\textsuperscript\s*$")
_MARKER_ARGUMENT = re.compile(rf"\{{\*\}}(?:{_ANY_MARKER})*")


# The command name pybtex is about to read, when that name is `comment`.
_COMMENT_COMMAND = re.compile(r'\s*comment\s*[{(]', re.IGNORECASE)



def _redefined_macros(text: str,
                      definitions: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """Every redefinition of an ``@string`` macro, as ``(name, line)``, in
    source order: each definition after a macro's first.

    ``definitions`` are the ``(name, offset)`` of every ``@string`` the parser
    actually read from ``text``, so a definition inside an ``@comment`` group
    is not one. Names compare without case, as the parser's macros do.

    pybtex takes the last definition, as BibTeX does, and says nothing about
    it. sslabdata reports it instead of letting a redefinition pass unnoticed.
    """
    seen: set = set()
    repeated: List[Tuple[str, int]] = []
    for name, offset in definitions:
        name = name.lower()
        if name in seen:
            repeated.append((name, text.count("\n", 0, offset) + 1))
        else:
            seen.add(name)
    return repeated


def redefined_summary(redefinitions: List[Tuple[str, str, int]]) -> Optional[Diagnostic]:
    """One `STRING_REDEFINED` line for ``(file, name, line)`` redefinitions.

    The macros are named once each, sorted, and every redefinition is listed
    as `file:line`, by file and then by line. The location names the file when every redefinition is
    in one, and is otherwise left empty. None when there is nothing to say.
    """
    if not redefinitions:
        return None
    names = sorted({name for _, name, _ in redefinitions})
    files = sorted({path for path, _, _ in redefinitions})
    where = ", ".join(f"{path}:{line}" for path, _, line in sorted(
        redefinitions, key=lambda found: (found[0], found[2])))
    count = f"{len(names)} @string macro{'s' if len(names) != 1 else ''}"
    return diagnostic(
        STRING_REDEFINED, files[0] if len(files) == 1 else None, None, None,
        f"{count} redefined (last definition used): {', '.join(names)} "
        f"[{where}]")


class _CommentSkippingParser(LowLevelParser):
    """pybtex's tokenizer, with a balanced ``@comment{...}`` group stepped over.

    pybtex raises ``SkipEntry`` for ``@comment`` before reading the body, so
    the scanner resumes just inside the group and an entry written there is a
    real entry to it — BibTeX behaves the same way. sslabdata treats a
    commented-out entry as commented out, so the group is consumed here, at
    the parser's own position and with the parser's own scanner. Nothing else
    in the file is read by sslabdata, which is why the shape of a value or of a
    neighbouring command cannot be got wrong.

    Only a *balanced* group is consumed. Prose that merely mentions
    ``@comment{`` does not close, so the position is put back and pybtex reads
    the rest of the file itself: at worst a commented-out entry stays visible,
    never a real entry disappears.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # (macro name, offset of its `@`) for every `@string` read in full.
        self.definitions: List[Tuple[str, int]] = []

    def parse_string_body(self, body_end):
        """Read one ``@string`` body, and remember the definition it made."""
        super().parse_string_body(body_end)
        self.definitions.append((self.current_field_name, self.command_start))

    def parse_command(self):
        # pybtex raises SkipEntry for a @comment, and also for an entry that
        # `wanted_entries` filters out — which leaves the scanner somewhere
        # quite different. Only the first is ours to recover from, so the
        # command is identified before the parser reads it.
        comment = _COMMENT_COMMAND.match(self.text, self.pos) is not None
        try:
            return super().parse_command()
        except SkipEntry:
            if comment:
                position, lineno = self.pos, self.lineno
                if not self._skip_comment_group():
                    self.pos, self.lineno = position, lineno
            raise

    def _skip_comment_group(self) -> bool:
        """Consume the ``@comment`` body just opened. False if it never closes."""
        closing = self.RBRACE if self.text[self.pos - 1] == "{" else self.RPAREN
        while True:
            token = self.skip_to([closing, self.LBRACE])
            if token is None:
                return False
            if token.pattern is closing:
                return True
            try:
                for _ in self.parse_string(self.RBRACE):
                    pass
            except PybtexSyntaxError:
                return False


class _Parser(PybtexParser):
    """pybtex's BibTeX parser, reading ``@comment`` groups as comments.

    ``Parser.parse_string`` names ``LowLevelParser`` directly, so swapping the
    tokenizer means restating that loop. It is the one place sslabdata touches a
    pybtex internal, which is why ``pybtex~=0.26`` is pinned.
    """

    def __init__(self, *args, duplicate_keys=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicate_keys = duplicate_keys if duplicate_keys is not None else []
        # (error, entry key, field name, where the command began) for every
        # syntax error, with the tokenizer's position in the file as it was
        # when the error was raised: by the time the file is read, it has
        # moved on.
        self.syntax_errors: List[Tuple[PybtexSyntaxError, Optional[str],
                                       Optional[str], Optional[int]]] = []
        # The entry key each captured library message was raised while
        # reading, by the message's identity.
        self.message_keys: Dict[int, str] = {}

    def handle_error(self, error):
        """Keep a syntax error with where it happened; relay anything else."""
        if isinstance(error, PybtexSyntaxError):
            tokenizer = error.parser
            self.syntax_errors.append((error, tokenizer.current_entry_key,
                                       tokenizer.current_field_name,
                                       tokenizer.command_start))
            return
        super().handle_error(error)

    def process_entry(self, entry_type, key, fields):
        """Remember duplicate keys before pybtex discards the later entry.

        ``BibliographyData.add_entry`` reports a parser-library warning and
        keeps the first entry. Recording the key here lets sslabdata surface a
        stable, file-qualified diagnostic instead of exposing that wording.
        """
        if key is not None and key in self.data.entries:
            self.duplicate_keys.append(key)
        captured = pybtex.errors.captured_errors
        before = len(captured) if captured is not None else 0
        super().process_entry(entry_type, key, fields)
        for error in (captured or [])[before:]:
            self.message_keys[id(error)] = key

    def parse_string(self, text: str):
        self.unnamed_entry_counter = 1
        self.command_start = 0
        commands = _CommentSkippingParser(
            text,
            keyless_entries=self.keyless_entries,
            handle_error=self.handle_error,
            want_entry=self.data.want_entry,
            filename=self.filename,
            macros=self.macros,
        )
        self.string_definitions = commands.definitions
        for command, arguments in commands:
            kind = command.lower()
            if kind == "preamble":
                self.process_preamble(*arguments)
            elif kind != "string":
                self.process_entry(command, *arguments)
        return self.data


def _duplicate_key_error(
    path: str,
    key: str,
    first_path: Optional[str] = None,
    first_key: Optional[str] = None,
) -> Diagnostic:
    """One stable duplicate-key diagnostic, with both locations when known."""
    message = "duplicate citation key"
    if first_path is not None:
        first_location = f"{first_path}:{first_key or key}:citation_key"
        message += f"; first defined in {first_location}"
    return diagnostic(DUPLICATE_CITATION_KEY, path, key, "citation_key", message)


def _on_comment_line(text: str, position: Optional[int]) -> bool:
    """True when ``position`` is on a line that starts with `%`.

    The parser library reads an `@` anywhere outside an entry as the start of
    a command, so prose on a `%` line that mentions `@article` fails to parse.
    That failure is not reported: the prose was never meant as BibTeX
    (`tests/COVERAGE.md` row `structure.comment_lines`). Only the report is
    suppressed. A well-formed command on such a line is read, as the library
    reads it.
    """
    if position is None:
        return False
    line_start = text.rfind("\n", 0, position) + 1
    return text[line_start:position].lstrip().startswith("%")


def _syntax_diagnostic(path: str, error: PybtexSyntaxError,
                       key: Optional[str], field_name: Optional[str]) -> Diagnostic:
    """One parser-library syntax error, in sslabdata's voice and located."""
    if isinstance(error, UndefinedMacro):
        macro = str(error).rsplit(": ", 1)[-1]
        return diagnostic(
            STRING_UNDEFINED, path, key, field_name if key else None,
            f"the macro '{macro}' is not defined by any @string; it is read "
            "as empty, and the entry is kept")
    if key is None:
        return diagnostic(
            SYNTAX_ERROR, path, None, None,
            f"the text at line {error.lineno} does not read as BibTeX and is "
            "skipped")
    after = f", after the value of '{field_name}'" if field_name else ""
    return diagnostic(
        SYNTAX_ERROR, path, key, field_name,
        f"the entry stops reading as BibTeX at line {error.lineno}{after}. "
        "It is kept as far as it was read, so that value may hold text meant "
        "for later fields; check its braces and quotes")


def parse_bibtex_file(
    path: str,
    diagnostics: List[Diagnostic],
    redefinitions: List[Tuple[str, str, int]],
) -> Dict[str, Entry]:
    """Parse one BibTeX file into pybtex entries, keyed by citation key.

    Anything the parser has to say is captured and reported by sslabdata, so no
    library logging reaches the user. Syntax errors, undefined macros and
    repeated citation keys go to ``diagnostics``, located at the entry and
    field they were found in. Redefined ``@string`` macros are added to
    ``redefinitions``, for the caller to summarise over a whole run.
    """
    text = Path(path).read_text(encoding="utf-8-sig")

    duplicate_keys: List[str] = []
    with pybtex.errors.capture() as errors:
        parser = _Parser(duplicate_keys=duplicate_keys)
        data = parser.parse_string(text)

    redefinitions.extend((path, name, line) for name, line
                         in _redefined_macros(text, parser.string_definitions))
    for error, key, field_name, start in parser.syntax_errors:
        if key is None and _on_comment_line(text, start):
            continue
        diagnostics.append(_syntax_diagnostic(path, error, key, field_name))
    for key in duplicate_keys:
        diagnostics.append(_duplicate_key_error(path, key))
    for error in errors:
        # The duplicate has already been recorded with sslabdata's stable code.
        if str(error).startswith("repeated bibliography entry:"):
            continue
        diagnostics.append(diagnostic(PARSER_MESSAGE, path,
                                      parser.message_keys.get(id(error)), None,
                                      str(error)))

    return data.entries



_UNREADABLE_LATEX = ("could not read the LaTeX in this field; keeping the text "
                     "as written")


def _convert(value: str, on_unknown) -> str:
    """Convert one field from LaTeX, keeping the raw text if that fails.

    Each command the converter does not know is passed to ``on_unknown``,
    which knows where the field is, and so is a value it cannot read at all
    (``on_unknown.failed()``).
    """
    try:
        text = latex_to_text(value)
    except Exception:  # noqa: BLE001 - never drop an entry over one field
        on_unknown.failed()
        return strip_braces(value)
    for command in unknown_commands(value):
        on_unknown(command)
    return text


def unknown_command_diagnostic(command: str, where: Tuple[str, str, str],
                               fields: int) -> Diagnostic:
    """One `LATEX_COMMAND_UNKNOWN` line for a whole run: how many fields use
    the command, located at ``(file, key, field)``, the first of them."""
    uses = (f"; used in {fields} field{'s' if fields != 1 else ''}, "
            "located at the first")
    return diagnostic(
        LATEX_COMMAND_UNKNOWN, *where,
        f"the LaTeX command '\\{command}' is not one sslabdata converts; it "
        f"is dropped, and a braced argument after it is kept as plain "
        f"text{uses}")


def _unknown_command_reporter(report, file: str, key: str,
                              tally: Dict[str, list]):
    """For one entry: a field name → the ``on_unknown`` for that field.

    A command is counted once per field, however many times it is used, and
    added to ``tally[command]`` as ``[fields, first location]``, for a caller
    that reports a whole run in one line per command. A field whose LaTeX
    cannot be read is reported to ``report`` at once.
    """
    reported = set()

    def in_field(field_name: str):
        def on_unknown(command: str) -> None:
            if (field_name, command) in reported:
                return
            reported.add((field_name, command))
            where = (file, key, field_name)
            if command in tally:
                tally[command][0] += 1
            else:
                tally[command] = [1, where]

        def failed() -> None:
            report(diagnostic(LATEX_CONVERSION_FAILED, file, key, field_name,
                              _UNREADABLE_LATEX))
        on_unknown.failed = failed
        return on_unknown
    return in_field


def _name_part_groups(person: Person) -> List[List[str]]:
    """A pybtex name's parts, grouped as the BibTeX parts that read them.

    Given and middle names are one group because they are read as one part,
    and because BibTeX puts the first word of a given name in one list and the
    rest in the other — which is a split a marker can land across.
    """
    return [list(person.first_names) + list(person.middle_names),
            list(person.prelast_names),
            list(person.last_names),
            list(person.lineage_names)]


def _with_marker_joined(parts: List[str]) -> List[str]:
    """One group of name parts, with a marker split across two of them joined."""
    joined: List[str] = []
    for part in parts:
        if (joined and _MARKER_ARGUMENT.fullmatch(part)
                and _MARKER_COMMAND.search(joined[-1])):
            joined[-1] += part
        else:
            joined.append(part)
    return joined


def _name_parts(person: Person) -> List[str]:
    """Every part of a pybtex name, as written, with split markers joined."""
    return [part for group in _name_part_groups(person)
            for part in _with_marker_joined(group)]


def _without_marker(part: str) -> str:
    """One name part with its equal-contribution markers taken off the end.

    Stripping repeats, because a name written ``Brown$^{*}$*`` carries the
    marker twice and taking one off would leave the other in the name.
    """
    while True:
        stripped = EQUAL_CONTRIBUTION.sub("", part, count=1)
        if stripped == part:
            return part
        part = stripped


def marks_equal_contribution(person: Person) -> bool:
    """True when any part of this name carries an equal-contribution marker.

    Given, family, von and suffix are all read: BibTeX splits the name before
    sslabdata sees it, so which part the star landed on is the author's choice
    of where to write it, not a different meaning.
    """
    return any(_without_marker(part) != part for part in _name_parts(person))


def _is_others(person: Person) -> bool:
    """``and others``: BibTeX's "et al.", not a person."""
    return (not person.first_names and not person.middle_names
            and not person.prelast_names and not person.lineage_names
            and [name.lower() for name in person.last_names] == [OTHERS])


def _is_literal(person: Person) -> bool:
    """A corporate author: one brace-protected unit, with no given name."""
    return (not person.first_names and not person.middle_names
            and not person.prelast_names and not person.lineage_names
            and len(person.last_names) == 1
            and person.last_names[0].startswith("{")
            and person.last_names[0].endswith("}"))


def person_name_parts(person: Person, on_unknown) -> Dict[str, Optional[str]]:
    """One pybtex Person as the parts BibTeX split it into, converted to text.

    ``given``, ``von``, ``family`` and ``suffix`` are BibTeX's four parts; a
    corporate name comes back as ``literal`` instead, with the other four
    unset. An empty part is ``None`` rather than ``""``, so the output says
    "this name has no such part" rather than "it is blank".

    An equal-contribution marker is not part of the name and does not appear
    in any part; ``marks_equal_contribution`` reports it separately.
    """
    def text(parts) -> Optional[str]:
        joined = " ".join(_convert(_without_marker(part), on_unknown)
                          for part in _with_marker_joined(parts)).strip()
        return joined or None

    if _is_literal(person):
        return {"given": None, "von": None, "family": None, "suffix": None,
                "literal": text(person.last_names)}
    return {
        "given": text(person.first_names + person.middle_names),
        "von": text(person.prelast_names),
        "family": text(person.last_names),
        "suffix": text(person.lineage_names),
        "literal": None,
    }


def given_words(name: str) -> List[str]:
    """The words BibTeX reads as the given name of a plain string: its first
    and middle names, as written. Empty when BibTeX cannot read it."""
    try:
        person = Person(name)
    except PybtexError:
        # pybtex raises for three or more commas, and for a word nested
        # more than 100 braces deep. `declared_form()` passes no comma, so
        # from there only the nesting reaches this.
        return []
    return list(person.first_names) + list(person.middle_names)


def readable_name(parts: Dict[str, Optional[str]]) -> str:
    """The parts of a name joined in reading order: ``John van Last Jr.``

    This is *a readable form of the input name, not a citation form*. It does
    not abbreviate, expand or normalise anything, so an entry writing
    ``Brown, B.`` yields ``B. Brown`` and one writing ``Brown, Bob`` yields
    ``Bob Brown``. The resolver matches on the structured parts rather than
    on this string (`sslabdata.resolver`), so matching can change without
    changing what the document displays.

    A name written as one brace-protected unit keeps its full form, because
    there is nothing to join.
    """
    if parts["literal"]:
        return parts["literal"]
    ordered = (parts["given"], parts["von"], parts["family"], parts["suffix"])
    return " ".join(part for part in ordered if part)


def _contributors(entry: Entry, role: str, on_unknown) -> List[Dict]:
    """The entry's names for one role, in source order, as parts plus position.

    A terminal ``and others`` is BibTeX's "et al." and is dropped rather than
    emitted as a person. A name that reads as empty is dropped too, so
    ``position`` counts the names that reach the document and nothing else.
    """
    persons = list(entry.persons.get(role, []))
    if persons and _is_others(persons[-1]):
        persons.pop()

    found = []
    for person in persons:
        parts = person_name_parts(person, on_unknown)
        name = readable_name(parts)
        if name:
            found.append({"name": name, "position": len(found) + 1,
                          "parts": parts, "person": person})
    return found


def parse_author_list(entry: Entry, on_unknown) -> List[Author]:
    """The entry's authors, in source order, with no contributor resolved yet.

    Each authorship carries the parts BibTeX split its name into, a readable
    form built from them, its 1-based position, and whether the entry marked
    it as an equal contribution. Matching those parts to a person is the
    resolver's.
    """
    return [Author(name=found["name"],
                   position=found["position"],
                   equal_contribution=marks_equal_contribution(found["person"]),
                   **found["parts"])
            for found in _contributors(entry, "author", on_unknown)]


def parse_editor_list(entry: Entry, on_unknown) -> List[Contributor]:
    """The entry's editors, read by the same machinery as its authors.

    An editor is name-parsed and resolved to a person the same way, but
    editing a volume is not an authorship: editors are excluded from
    `person.work_ids`, from a project's people and from `collaborators`, so an editor who matches nobody is simply unresolved.
    """
    return [Contributor(name=found["name"], position=found["position"],
                        **found["parts"])
            for found in _contributors(entry, "editor", on_unknown)]


def entry_fields(bib_id: str, entry: Entry, unknown_in) -> Dict[str, str]:
    """The entry's fields, with prose converted from LaTeX.

    ``ENTRYTYPE`` and ``ID`` are included so the rules below read one plain
    dictionary and know nothing about pybtex. No field is filled in from any
    other entry: ``crossref`` is rejected rather than resolved.
    """
    fields = {name.lower(): value for name, value in entry.fields.items()}
    read = {
        name: _convert(value, unknown_in(name)) if name in TEXT_FIELDS else value
        for name, value in fields.items()
    }
    read["ENTRYTYPE"] = entry.type.lower()
    read["ID"] = bib_id
    return read


def format_bibtex(bib_id: str, entry: Entry, source: str,
                  report) -> Optional[str]:
    """The entry written back out as BibTeX, for readers to copy.

    This is the entry as it was read, before LaTeX conversion, so fields
    sslabdata does not emit as properties are preserved rather than rewritten.
    It is a re-serialization of the entry's data and explicitly not a source
    of properties: nothing in sslabdata reads a value back out of it.
    """
    try:
        return entry.to_string("bibtex").strip()
    except Exception:  # noqa: BLE001 - a copyable string is not worth an entry
        report(diagnostic(
            WRITE_BACK_FAILED, source, bib_id, "bibtex",
            "could not write this entry back out as BibTeX; bibtex is null"))
        return None



# The one place sslabdata normalises across entry types: the field that names
# the container a work appeared in. Everything else bibliographic is flat on
# the work, because it describes the work's placement rather than the
# container. The order is the precedence, so an entry carrying more than one
# of them gets the most specific.
CONTAINER_FIELDS = ("journal", "booktitle", "school", "institution")

# The venue kind each container field implies. `booktitle` depends on the
# entry type, because a proceedings volume and a collection are different
# kinds of container under one field name.
CONTAINER_KINDS = {"journal": "journal", "school": "institution",
                   "institution": "institution"}
BOOKTITLE_KINDS = {"inproceedings": "conference", "conference": "conference",
                   "proceedings": "conference", "incollection": "book",
                   "inbook": "book", "book": "book"}
OTHER_KIND = "other"

# A preprint's venue is the repository it sits in, which is what
# `archivePrefix` names. arXiv is the default, because a bare `eprint` is
# read as an arXiv identifier (`build_identifiers`) and linked as one.
ARXIV = "arXiv"
REPOSITORY_KIND = "repository"

# The bibliographic fields carried flat on the work, under BibTeX's own names
# and with BibTeX's own meanings. `number` in particular is an issue number
# for an @article and a report number for a @techreport; reinterpreting it is
# not sslabdata's job, and `venue.kind` gives a consumer the branch it needs.
FLAT_FIELDS = ("volume", "number", "pages", "series", "edition", "publisher",
               "address", "organization", "chapter", "month", "howpublished",
               "type")

# The identifier schemes sslabdata reads out of an entry, and the field each
# comes from. The registry is open: a scheme is documented, never enumerated
# in the schema, so one can be added without a version bump.
IDENTIFIER_FIELDS = {"doi": "doi", "isbn": "isbn", "issn": "issn"}

# A DOI written as a URL is the resolver plus the DOI; the identifier is the
# part after it. Stripping exactly these prefixes is not a guess -- they are
# the registered resolvers -- and it is what makes `identifiers.doi` usable
# as an identifier rather than as a second copy of the link.
DOI_RESOLVERS = ("https://doi.org/", "http://doi.org/",
                 "https://dx.doi.org/", "http://dx.doi.org/")
DOI_BASE = "https://doi.org/"
ARXIV_BASE = "https://arxiv.org/abs/"

# Link kinds, and the origin of each. Only `input` means the entry's own
# field supplied the link; a link sslabdata built from an identifier or from
# `pdf_base_url` is `derived`, and says so.
FROM_INPUT = "input"
DERIVED = "derived"
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")

UNCHECKED, VERIFIED, MISSING = "unchecked", "verified", "missing"


def build_venue(entry: dict) -> Optional[Venue]:
    """The container this work appeared in, or None when the entry names none.

    The four container fields collapse to one name plus a kind, which is the
    single biggest gain over raw BibTeX: a consumer asks for the venue's name
    once instead of branching on the entry type to find it.
    """
    entry_type = entry.get("ENTRYTYPE", "")
    for field_name in CONTAINER_FIELDS:
        value = (entry.get(field_name) or "").strip()
        if not value:
            continue
        if field_name == "booktitle":
            kind = BOOKTITLE_KINDS.get(entry_type, OTHER_KIND)
        else:
            kind = CONTAINER_KINDS[field_name]
        return Venue(kind=kind, name=value)

    eprint = (entry.get("eprint") or "").strip()
    if eprint:
        return Venue(kind=REPOSITORY_KIND, name=_archive_prefix(entry))
    return None


def _archive_prefix(entry: dict) -> str:
    """The repository an `eprint` belongs to, as the entry names it."""
    prefix = entry.get("archivePrefix", entry.get("archiveprefix", ""))
    return prefix.strip() or ARXIV


def bare_doi(doi: str) -> str:
    """One DOI with its resolver prefix taken off, if it was written as a URL."""
    doi = doi.strip()
    for resolver in DOI_RESOLVERS:
        if doi.lower().startswith(resolver):
            return doi[len(resolver):]
    return doi


def build_identifiers(entry: dict, source: str, report) -> Dict[str, List[str]]:
    """The entry's identifiers, as a map from scheme to a list of identifiers.

    The list shape is there because ISBN and ISSN genuinely repeat — a print
    and an electronic one are two values of one identifier — even though a
    BibTeX field holds one value, so v4 emits at most one per scheme. A `doi`
    that is a resolver and nothing after it names no DOI, and is reported
    rather than emitted empty.
    """
    identifiers: Dict[str, List[str]] = {}
    for scheme, field_name in IDENTIFIER_FIELDS.items():
        value = (entry.get(field_name) or "").strip()
        if not value:
            continue
        if scheme == "doi":
            if not bare_doi(value):
                report(diagnostic(
                    DOI_INVALID, source, entry.get("ID"), field_name,
                    f"'{value}' is a DOI resolver with no DOI after it; the "
                    "work gets no DOI identifier and no DOI link"))
                continue
            value = bare_doi(value)
        identifiers[scheme] = [value]

    eprint = (entry.get("eprint") or "").strip()
    if eprint:
        # The scheme is what `archivePrefix` said, which is why the prefix
        # field needs no property of its own: it is the scheme.
        identifiers[_archive_prefix(entry).lower()] = [eprint]
    return identifiers


def is_video_url(url: str) -> bool:
    """True when a URL's host is a video host, or a subdomain of one.

    Only the parsed hostname counts: a lookalike domain, or a host named in
    the path, query or fragment, does not. A URL that cannot be parsed, or has
    no host, is not a video.
    """
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return False
    return hostname is not None and any(
        hostname == host or hostname.endswith("." + host)
        for host in VIDEO_HOSTS)


def pdf_link(bib_id: str, pdf_base_url: Optional[str]) -> Optional[Link]:
    """The PDF this work would be at under ``pdf_base_url``, checked if local.

    A local base is checked against the filesystem and the link is labelled
    `verified` or `missing`; a remote base is labelled `unchecked`, because a
    build never fetches. The link is kept either way, so "no base configured",
    "the file is not there" and "nobody has looked" are three distinct
    answers rather than one null.
    """
    if not pdf_base_url:
        return None
    base = pdf_base_url.rstrip('/')
    url = f"{base}/{bib_id}.pdf"
    if pdf_base_url.startswith(('http://', 'https://')):
        return Link(url=url, origin=DERIVED, status=UNCHECKED)
    return Link(url=url, origin=DERIVED,
                status=VERIFIED if Path(url).exists() else MISSING)


def build_links(entry: dict, bib_id: str, identifiers: Dict[str, List[str]],
                pdf_base_url: Optional[str]) -> Dict[str, List[Link]]:
    """Every URL this work can be reached at, filed by kind.

    A map from kind to a *list* of links, so that two code repositories or a
    talk video beside a supplementary one can both be carried, which a plain
    kind-to-url map cannot express. A link does not name the identifier it was
    built from: that is redundant with its kind and origin, and it would be a
    cross-record constraint JSON Schema cannot express.
    """
    links: Dict[str, List[Link]] = {}

    def add(kind: str, link: Optional[Link]) -> None:
        if link is not None:
            links.setdefault(kind, []).append(link)

    url = (entry.get("url") or "").strip()
    if url:
        add("video" if is_video_url(url) else "url",
            Link(url=url, origin=FROM_INPUT, status=UNCHECKED))
    # `video` is always a video, whatever its host, so an entry can name a
    # project website in `url` and its video here.
    video = (entry.get("video") or "").strip()
    if video:
        add("video", Link(url=video, origin=FROM_INPUT, status=UNCHECKED))
    # A `pdf` the entry names is the work's PDF, so it replaces the one
    # guessed from `pdf_base_url` rather than sitting beside it.
    pdf = (entry.get("pdf") or "").strip()
    if pdf:
        add("pdf", Link(url=pdf, origin=FROM_INPUT, status=UNCHECKED))
    else:
        add("pdf", pdf_link(bib_id, pdf_base_url))
    for doi in identifiers.get("doi", []):
        add("doi", Link(url=DOI_BASE + doi, origin=DERIVED, status=UNCHECKED))
    for eprint in identifiers.get(ARXIV.lower(), []):
        add("arxiv", Link(url=ARXIV_BASE + eprint, origin=DERIVED,
                          status=UNCHECKED))
    return links


def extract_note(entry: dict) -> Optional[str]:
    """Extract and format the note field."""
    note = entry.get("note", "").strip().rstrip('. ')
    if not note:
        return None
    return note


def parse_project_ids(entry: dict) -> List[str]:
    """Parse the project field from a BibTeX entry."""
    project_field = entry.get("project", "").strip()
    if not project_field:
        return []
    project_field = project_field.strip('{}')
    return [p.strip() for p in project_field.split(',') if p.strip()]


def entry_year(entry: dict, source: str, report) -> Optional[int]:
    """The entry's year, or None with a diagnostic when it has none.

    A work with no year sorts last, and its year is None rather than 0, so a
    consumer can tell "no year" from "the year zero". A year that is not a
    number is reported and read as no year.
    """
    raw = str(entry.get("year", "")).strip()
    if not raw:
        report(diagnostic(YEAR_MISSING, source, entry.get("ID"), "year",
                          "entry has no year"))
        return None
    try:
        return int(raw)
    except ValueError:
        report(diagnostic(YEAR_INVALID, source, entry.get("ID"), "year",
                          f"'{raw}' is not a number; the work is emitted "
                          "with year: null and sorts last"))
        return None


# The container field checked for an entry type, and the entry types sslabdata
# documents (tests/COVERAGE.md, *Entry types*, with `@conference` and
# `@proceedings`, which the venue rule names). Any other type is kept and
# reported.
REQUIRED_CONTAINER = {"article": "journal", "inproceedings": "booktitle"}
SUPPORTED_TYPES = frozenset({
    "article", "inproceedings", "conference", "proceedings", "incollection",
    "inbook", "book", "phdthesis", "mastersthesis", "techreport", "manual",
    "misc"})


def check_entry_type(entry: dict, source: str, report) -> None:
    """Report an entry type sslabdata does not document, or a missing container."""
    entry_type, key = entry["ENTRYTYPE"], entry["ID"]
    if entry_type not in SUPPORTED_TYPES:
        report(diagnostic(
            ENTRY_TYPE_UNSUPPORTED, source, key, "entry_type",
            f"@{entry_type} is not an entry type sslabdata documents; the "
            "entry is kept, with its venue read from whichever container "
            "field it carries"))
        return
    required = REQUIRED_CONTAINER.get(entry_type)
    if required and not (entry.get(required) or "").strip():
        report(diagnostic(
            VENUE_MISSING, source, key, required,
            f"@{entry_type} has no {required}; the entry is kept, and its "
            "venue is read from any other container field it carries, or "
            "is null"))


def entry_to_work(
    bib_id: str,
    entry: Entry,
    category: str,
    pdf_base_url: Optional[str],
    source: str,
    source_file: str,
    report,
    unknown_commands_seen: Dict[str, list],
) -> Work:
    """Convert one pybtex Entry to a Work dataclass.

    Unknown LaTeX commands are added to ``unknown_commands_seen``
    (`_unknown_command_reporter`); every other diagnostic goes to ``report``.
    """
    unknown_in = _unknown_command_reporter(report, source, bib_id,
                                           unknown_commands_seen)
    fields = entry_fields(bib_id, entry, unknown_in)
    identifiers = build_identifiers(fields, source, report)
    check_entry_type(fields, source, report)

    return Work(
        bib_id=bib_id,
        title=fields.get("title", ""),
        authors=parse_author_list(entry, unknown_in("author")),
        editors=parse_editor_list(entry, unknown_in("editor")),
        year=entry_year(fields, source, report),
        category=category,
        entry_type=fields["ENTRYTYPE"],
        source_file=source_file,
        venue=build_venue(fields),
        abstract=fields.get("abstract"),
        note=extract_note(fields),
        identifiers=identifiers,
        links=build_links(fields, bib_id, identifiers, pdf_base_url),
        project_ids=parse_project_ids(fields),
        bibtex=format_bibtex(bib_id, entry, source, report),
        **{name: fields.get(name) for name in FLAT_FIELDS},
    )


def _encoding_error(path: str, error: UnicodeDecodeError) -> Diagnostic:
    """The one diagnostic for a `.bib` file that is not UTF-8.

    No other encoding is tried: a wrong guess would silently change names.
    """
    line = error.object[:error.start].count(b"\n") + 1
    return diagnostic(ENCODING_INVALID, path, None, None,
                      f"the file is not UTF-8: byte "
                      f"0x{error.object[error.start]:02x} on line {line} "
                      "cannot be read. Save the file as UTF-8.")


def _crossref_error(path: str, bib_id: str, parent: str) -> Diagnostic:
    """The one diagnostic for an entry that carries a ``crossref`` field.

    A field that is there but empty is reported as what it is rather than as
    a parent whose name happens to be blank.
    """
    names = f"names the parent '{parent}'" if parent else "names no parent"
    return diagnostic(CROSSREF_UNSUPPORTED, path, bib_id, "crossref",
                      f"crossref is not supported; this entry {names}. "
                      "Write the fields out on the entry itself.")


def parse_all_works(
    bib_dir: str,
    bib_files: list,
    diagnostics: List[Diagnostic],
    pdf_base_url: Optional[str] = None,
) -> List[Work]:
    """Parse all configured BibTeX files and return a flat list of Works.

    Every file is read first, so a citation key repeated across two of them is
    reported against both.

    Args:
        bib_dir: Directory containing the BibTeX files
        bib_files: List of dicts with 'name' and 'category' keys
        diagnostics: The list that receives every coded diagnostic, in the
            order found; its class in `sslabdata.diagnostics.CLASSES` decides
            its severity
        pdf_base_url: Base URL/path for PDFs

    Returns:
        List of Work objects, sorted by year descending, works with no year
        last.
    """
    read: List[Tuple[str, str, str, Entry, str]] = []
    first_source: Dict[str, Tuple[str, str]] = {}

    report = diagnostics.append

    # Every file's redefined macros, summarised once when all are read.
    redefinitions: List[Tuple[str, str, int]] = []
    for bib_file in bib_files:
        name = bib_file['name'] if isinstance(bib_file, dict) else bib_file.name
        category = bib_file['category'] if isinstance(bib_file, dict) else bib_file.category
        path = f"{bib_dir}/{name}"
        try:
            parsed = parse_bibtex_file(path, diagnostics, redefinitions)
        except UnicodeDecodeError as error:
            report(_encoding_error(path, error))
            continue
        for bib_id, entry in parsed.items():
            normalized = bib_id.lower()
            if normalized in first_source:
                previous_path, previous_key = first_source[normalized]
                report(_duplicate_key_error(path, bib_id, previous_path, previous_key))
            else:
                first_source[normalized] = (path, bib_id)
            # Rejected on presence, not on value, and not emitted. An empty
            # `crossref = {}` is a field the entry carries, so it is an error
            # too: otherwise an entry could cross-refer without a diagnostic
            # under a different spelling.
            crossref = [value for field_name, value in entry.fields.items()
                        if field_name.lower() == "crossref"]
            if crossref:
                report(_crossref_error(path, bib_id, str(crossref[0]).strip()))
                continue
            read.append((path, name, bib_id, entry, category))

    summary = redefined_summary(redefinitions)
    if summary:
        report(summary)

    # One line per unknown command for the whole run: a real bibliography
    # can use one command in thousands of fields, and a line for each would
    # bury every other diagnostic.
    unknown: Dict[str, list] = {}
    works = [
        entry_to_work(bib_id, entry, category, pdf_base_url, path, name, report,
                      unknown)
        for path, name, bib_id, entry, category in read
    ]
    for command, (fields, where) in unknown.items():
        report(unknown_command_diagnostic(command, where, fields))
    works.sort(key=lambda w: (w.year is not None, w.year or 0), reverse=True)
    return works
