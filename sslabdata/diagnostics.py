"""
Coded diagnostics, one line each (SPEC.md "Diagnostic codes").

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
        # A line break in the message -- a library's multi-line wording, or a
        # name written across two lines -- becomes a space, so every line of
        # output carries a code.
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


# The four classes a code can belong to (SPEC.md "Diagnostic codes").
FATAL_AT_LOAD = "fatal at load"
FATAL = "fatal"
VALIDATION_ERROR = "validation error"
WARNING = "warning"

# Every code in use, with its class. The registry under
# SPEC.md "Diagnostic codes" lists the same codes; a test holds the two
# together.
CLASSES: Dict[str, str] = {
    "CONFIG-BIB-FILE-ABSOLUTE": FATAL_AT_LOAD,
    "CONFIG-BIB-FILE-OUTSIDE-BIB-DIR": FATAL_AT_LOAD,
    "CONFIG-NOT-A-MAPPING": FATAL_AT_LOAD,
    "CONFIG-KEY-MISSING": FATAL_AT_LOAD,
    "CONFIG-TYPE-INVALID": FATAL_AT_LOAD,
    "CONFIG-VALUE-NOT-JSON": FATAL_AT_LOAD,
    "CONFIG-KEY-REPEATED": FATAL_AT_LOAD,
    "CONFIG-NOT-FOUND": FATAL_AT_LOAD,
    "CONFIG-UNREADABLE": FATAL_AT_LOAD,
    "BIB-CROSSREF-UNSUPPORTED": FATAL,
    "CONFIG-FILE-NOT-FOUND": FATAL,
    "CONFIG-PATH-WRONG-KIND": FATAL,
    "PEOPLE-NOT-A-LIST": FATAL,
    "PEOPLE-FIELD-MISSING": FATAL,
    "PEOPLE-YAML-INVALID": FATAL,
    "PROJECTS-YAML-INVALID": FATAL,
    "PROJECTS-NOT-A-LIST": FATAL,
    "PROJECTS-FIELD-MISSING": FATAL,
    "COLLABORATORS-YAML-INVALID": FATAL,
    "COLLABORATORS-NOT-A-LIST": FATAL,
    "COLLABORATORS-FIELD-MISSING": FATAL,
    "RECORD-KEY-REPEATED": FATAL,
    "OUTPUT-WRITE-FAILED": FATAL,
    "BIB-ENCODING-INVALID": FATAL,
    "BIB-DUPLICATE-KEY": VALIDATION_ERROR,
    "RESOLVE-PROJECT-UNKNOWN": VALIDATION_ERROR,
    "PEOPLE-ID-DUPLICATE": VALIDATION_ERROR,
    "PROJECTS-ID-DUPLICATE": VALIDATION_ERROR,
    "BIB-YEAR-MISSING": WARNING,
    "BIB-YEAR-INVALID": WARNING,
    "BIB-DOI-INVALID": WARNING,
    "BIB-OTHERS-NOT-LAST": WARNING,
    "BIB-STRING-UNDEFINED": WARNING,
    "BIB-STRING-REDEFINED": WARNING,
    "BIB-SYNTAX-ERROR": WARNING,
    "BIB-BRACE-MISMATCH": WARNING,
    "BIB-VENUE-MISSING": WARNING,
    "BIB-ENTRY-TYPE-UNSUPPORTED": WARNING,
    "BIB-PARSER-MESSAGE": WARNING,
    "BIB-WRITE-BACK-FAILED": WARNING,
    "LATEX-COMMAND-UNKNOWN": WARNING,
    "LATEX-CONVERSION-FAILED": WARNING,
    "LINK-SCHEME-UNSUPPORTED": WARNING,
    "TEXT-CONTROL-CHARACTER": WARNING,
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

# The codes `--strict` leaves as warnings. Each one's reason is in
# SPEC.md "Diagnostic codes".
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

    The rule is SPEC.md "Diagnostic codes".
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
    """The diagnostics in report order: by class, stable within one."""
    order = (FATAL_AT_LOAD, FATAL, VALIDATION_ERROR, WARNING)
    return sorted(lines, key=lambda line: order.index(CLASSES[line.code]))


def record(line: Diagnostic, level: str) -> Dict[str, Optional[str]]:
    """One diagnostic as a JSON record (SPEC.md "Diagnostics as JSON")."""
    return {"code": line.code, "severity": level,
            "file": line.file or None, "key": line.key or None,
            "field": line.field or None, "message": line.message}
