"""
Coded diagnostics: one line each, `<CODE> <file>:<key>:<field>: <message>`.

A located part that does not apply is left empty, so the separators stay
where a reader expects them: `CONFIG-NOT-A-MAPPING lab.yaml::: ...` names a
file and nothing inside it. See "Diagnostic codes" in SPEC.md.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Diagnostic:
    """One coded diagnostic: its parts, and the line they make (``str()``).

    The parts are kept so that no caller has to split the line, which a
    citation key containing a colon would defeat.
    """

    code: str
    file: Optional[str]
    key: Optional[str]
    field: Optional[str]
    message: str

    def __post_init__(self) -> None:
        # An unregistered code is rejected here, not later in `severity()`.
        # A line break in the message -- a library's multi-line wording, or a
        # name written across two lines -- becomes a space, so a diagnostic is
        # always one line and every line of it carries its code.
        if self.code not in CLASSES:
            raise ValueError(f"unregistered diagnostic code {self.code!r}")
        object.__setattr__(self, "message",
                           " ".join(self.message.splitlines()))

    def __str__(self) -> str:
        return (f"{self.code} {self.file or ''}:{self.key or ''}:"
                f"{self.field or ''}: {self.message}")


def diagnostic(code: str, file: Optional[str], key: Optional[str],
               field: Optional[str], message: str) -> Diagnostic:
    """Build one coded diagnostic; ``None`` parts are left empty in its line."""
    return Diagnostic(code, file, key, field, message)


# The four classes a code can belong to (SPEC.md, *Diagnostic codes*).
FATAL_AT_LOAD = "fatal at load"
FATAL = "fatal"
VALIDATION_ERROR = "validation error"
WARNING = "warning"

# Every code in use, with its class. SPEC.md's registry lists the same codes;
# a test holds the two together.
CLASSES: Dict[str, str] = {
    "CONFIG-BIB-FILE-ABSOLUTE": FATAL_AT_LOAD,
    "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR": FATAL_AT_LOAD,
    "CONFIG-NOT-A-MAPPING": FATAL_AT_LOAD,
    "CONFIG-KEY-MISSING": FATAL_AT_LOAD,
    "CONFIG-TYPE-INVALID": FATAL_AT_LOAD,
    "CONFIG-VALUE-NOT-JSON": FATAL_AT_LOAD,
    "CONFIG-NOT-FOUND": FATAL_AT_LOAD,
    "CONFIG-UNREADABLE": FATAL_AT_LOAD,
    "BIB-CROSSREF-UNSUPPORTED": FATAL,
    "CONFIG-FILE-NOT-FOUND": FATAL,
    "PEOPLE-NOT-A-LIST": FATAL,
    "PEOPLE-FIELD-MISSING": FATAL,
    "PEOPLE-YAML-INVALID": FATAL,
    "PROJECTS-YAML-INVALID": FATAL,
    "PROJECTS-NOT-A-LIST": FATAL,
    "PROJECTS-FIELD-MISSING": FATAL,
    "COLLABORATORS-YAML-INVALID": FATAL,
    "COLLABORATORS-NOT-A-LIST": FATAL,
    "COLLABORATORS-FIELD-MISSING": FATAL,
    "BIB-ENCODING-INVALID": FATAL,
    "BIB-DUPLICATE-KEY": VALIDATION_ERROR,
    "RESOLVE-PROJECT-UNKNOWN": VALIDATION_ERROR,
    "PEOPLE-ID-DUPLICATE": VALIDATION_ERROR,
    "PROJECTS-ID-DUPLICATE": VALIDATION_ERROR,
    "BIB-YEAR-MISSING": WARNING,
    "BIB-YEAR-INVALID": WARNING,
    "BIB-STRING-UNDEFINED": WARNING,
    "BIB-STRING-REDEFINED": WARNING,
    "BIB-SYNTAX-ERROR": WARNING,
    "BIB-VENUE-MISSING": WARNING,
    "BIB-ENTRY-TYPE-UNSUPPORTED": WARNING,
    "BIB-PARSER-MESSAGE": WARNING,
    "BIB-WRITE-BACK-FAILED": WARNING,
    "LATEX-COMMAND-UNKNOWN": WARNING,
    "LATEX-CONVERSION-FAILED": WARNING,
    "ID-GROUPING-SPANS-SPELLINGS": WARNING,
    "ID-GROUPING-INITIALS-AMBIGUOUS": WARNING,
    "ID-GROUPING-AMBIGUOUS-DECLARED": WARNING,
    "RESOLVE-AMBIGUOUS-NAME": WARNING,
    "RESOLVE-SUGGESTION": WARNING,
    "RESOLVE-UNRESOLVED-NAME": WARNING,
    "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER": WARNING,
    "PEOPLE-ALIAS-AMBIGUOUS": WARNING,
    "PEOPLE-ROLE-INVALID": WARNING,
    "PEOPLE-STATUS-INVALID": WARNING,
    "PROJECTS-STATUS-INVALID": WARNING,
    "CONFIG-LAB-NAME-MISSING": WARNING,
    "CONFIG-KEY-UNKNOWN": WARNING,
    "RECORD-KEY-UNKNOWN": WARNING,
    "RECORD-TYPE-INVALID": WARNING,
    "CONFIG-BIB-FILES-MISSING": WARNING,
}

# The codes `--strict` leaves as warnings (SPEC.md section 1). A redefined
# `@string` macro is settled by BibTeX's own last-wins rule. Every other one is
# about an author who matched no lab member, and such an author is never an
# error under `--strict`: `collaborators_file` declares a grouping, not an
# identity, so sslabdata cannot tell an outside co-author from a possible
# member. The known cost is that a misspelt member's name passes `--strict`,
# reported as a `RESOLVE-SUGGESTION` warning.
NEVER_AN_ERROR = frozenset({
    "BIB-STRING-REDEFINED",
    "ID-GROUPING-SPANS-SPELLINGS",
    "ID-GROUPING-INITIALS-AMBIGUOUS",
    "ID-GROUPING-AMBIGUOUS-DECLARED",
    "RESOLVE-UNRESOLVED-NAME",
    "RESOLVE-SUGGESTION",
})

# Severities as a run reports them.
ERROR, WARN = "error", "warning"


def severity(line: Diagnostic, validating: bool, strict: bool) -> str:
    """`ERROR` or `WARN` for one diagnostic in one run.

    Fatal codes are errors in every mode. A validation error is an error under
    ``--validate``. Under ``--strict`` every code is an error except those in
    `NEVER_AN_ERROR`.
    """
    code = line.code
    kind = CLASSES[code]
    if kind in (FATAL_AT_LOAD, FATAL):
        return ERROR
    if kind == VALIDATION_ERROR and validating:
        return ERROR
    if strict and code not in NEVER_AN_ERROR:
        return ERROR
    return WARN


def in_report_order(lines: List[Diagnostic]) -> List[Diagnostic]:
    """Fatal codes first, then validation errors, then warnings, each class
    in the order it was found: the order every report lists them in."""
    order = (FATAL_AT_LOAD, FATAL, VALIDATION_ERROR, WARNING)
    return sorted(lines, key=lambda line: order.index(CLASSES[line.code]))


def record(line: Diagnostic, level: str) -> Dict[str, Optional[str]]:
    """One diagnostic as the JSON record SPEC.md specifies."""
    return {"code": line.code, "severity": level,
            "file": line.file or None, "key": line.key or None,
            "field": line.field or None, "message": line.message}
