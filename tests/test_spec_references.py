"""SPEC.md's references to the code still resolve (tests/COVERAGE.md row
`spec.references_resolve`).

SPEC.md grounds its rules in named parts of the code rather than in line
numbers. This test reads every such reference out of SPEC.md and checks that
it still names something, so a rename, a move or a removed schema property
fails here with the reference and the SPEC.md section that made it. Whether a
reference *supports* its sentence is for review; this checks only that it
resolves.

What counts as a reference
--------------------------

Only inline code spans (single backticks, on one line) outside fenced code
blocks are read, and only these shapes count. A span of any other shape is
prose, an example value, a CLI flag, a YAML key, a BibTeX field or a
diagnostic code, and is not read (diagnostic codes are checked against the
code by ``test_strict_json.py``). Identifiers are ASCII.

1. **Qualified name** — ``sslabdata`` followed by dotted identifiers,
   optionally ending in ``()``, or ending in ``.*`` for a set of modules:
   ``sslabdata.parsers.bibtex.parse_all_works()``,
   ``sslabdata.models.SCHEMA_VERSION``, ``sslabdata.loaders``. The longest
   importable module prefix is imported and the rest is looked up as
   attributes; a dataclass field counts as an attribute.
2. **Class-qualified name** — a CamelCase class name (a capital, at least one
   lower-case letter, an optional leading underscore) followed by dotted
   identifiers, optionally ending in ``()``: ``Person.to_dict()``,
   ``_CommentSkippingParser.current_entry_key``. The class must be defined
   exactly once in the package.
3. **Bare call** — one identifier followed by ``()``: ``build_venue()``,
   ``from_yaml()``. It must name exactly one definition in the package: a
   module-level function or class, or a member of a class the package
   defines. Two definitions of the name make the reference ambiguous, and it
   has to be qualified.
4. **Bare constant** — an upper-case identifier that has an underscore
   between two words or starts with one: ``TEXT_FIELDS``, ``_SETTINGS``.
   It must name exactly one definition in the package, as above. A single
   upper-case word with no underscore (``PATH``, ``HAL``, ``SS``, ``Z``) is
   prose, so a one-word public constant has to be written qualified.
5. **Schema pointer** — a span starting with ``/`` whose first segment is a
   JSON Schema keyword (``/$defs/person/required``,
   ``/additionalProperties``). It is resolved as a JSON Pointer (RFC 6901)
   against the current output schema. A path such as
   ``/collaborators/{{ id }}`` is not a pointer.
6. **COVERAGE.md row key** — each span in a list directly after
   ``tests/COVERAGE.md`` ``row``, ``rows`` or ``row key such as``, joined by
   ``,`` or ``and``. It must be the case ID of a row of that table.

Every call reference (``()``) must resolve to something callable. Names
resolve against the package as imported; no module is read as text.

Bare CamelCase names (``Person``, ``Target``, ``Warnings``) are not read: too
many are English words. Dotted lower-case names that do not start with
``sslabdata`` (``work.bibtex``, ``lab.yaml``) are document fields and files.

``NOT_REFERENCES`` lists the spans that have a reference's shape but are
not references, each with its reason. An entry that no longer appears in
SPEC.md fails the test, so the list cannot grow stale.

Inspecting the result
---------------------

Set ``SSLABDATA_SPEC_REFERENCES`` to a path to have the test write every
reference it read, in SPEC.md order, as JSON: its kind, the span, the
SPEC.md line and section, and what it resolved to or why it did not. The file
has no timestamps or host paths, so two runs over the same tree give the same
bytes:

    SSLABDATA_SPEC_REFERENCES=spec-references.json \\
      uv run --frozen --extra test pytest --no-cov tests/test_spec_references.py
"""

import dataclasses
import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import re
from collections import Counter
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

import sslabdata

from .conformance.support import REPO_ROOT, SCHEMA_PATH, TESTS_DIR

SPEC_PATH = REPO_ROOT / "SPEC.md"
RESULTS_ENV = "SSLABDATA_SPEC_REFERENCES"

# Spans that have a reference's shape but name nothing in sslabdata.
NOT_REFERENCES = {
    "int()": "Python's built-in, named to show which years it would accept "
             "that the digits rule does not (BIB-YEAR-INVALID)",
}

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
QUALIFIED = re.compile(rf"^sslabdata(?:\.{IDENT})*(?:\(\)|\.\*)?$")
CLASS_QUALIFIED = re.compile(rf"^_?[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*(?:\.{IDENT})+(?:\(\))?$")
BARE_CALL = re.compile(rf"^{IDENT}\(\)$")
BARE_CONSTANT = re.compile(r"^(?:_[A-Z][A-Z0-9_]+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)$")
SCHEMA_KEYWORDS = {"$defs", "definitions", "properties", "additionalProperties",
                   "patternProperties", "items", "required", "allOf", "anyOf",
                   "oneOf", "not", "if", "then", "else"}
ROW_LIST = re.compile(
    r"`tests/COVERAGE\.md`\s+rows?(?:\s+key\s+such\s+as)?\s+"
    r"((?:`[^`\n]+`(?:,?\s+and\s+|,\s+)?)+)")
COVERAGE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)
SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^```.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


class Reference(NamedTuple):
    kind: str       # callable, name, pointer or row
    text: str       # the span as SPEC.md writes it
    line: int
    section: str


# --- Reading SPEC.md --------------------------------------------------------

def spec_text() -> str:
    """SPEC.md with fenced blocks blanked, keeping every offset and line."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    return FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def locate(text: str, offset: int) -> Tuple[int, str]:
    """The 1-based line of an offset and the heading it falls under."""
    section = "(before the first heading)"
    for heading in HEADING.finditer(text, 0, offset):
        section = heading.group(1)
    return text.count("\n", 0, offset) + 1, section


def classify(span: str) -> Optional[str]:
    """The kind of reference a span is, or None for prose."""
    if span.startswith("/"):
        return "pointer" if span[1:].split("/", 1)[0] in SCHEMA_KEYWORDS else None
    call = span.endswith("()")
    if QUALIFIED.match(span) or CLASS_QUALIFIED.match(span) or BARE_CALL.match(span):
        return "callable" if call else "name"
    if BARE_CONSTANT.match(span):
        return "name"
    return None


def extract(text: str) -> List[Reference]:
    """Every reference in SPEC.md, in document order."""
    found: Dict[int, Reference] = {}
    for match in ROW_LIST.finditer(text):
        for span in SPAN.finditer(match.group(1)):
            offset = match.start(1) + span.start()
            found[offset] = Reference("row", span.group(1), *locate(text, offset))
    for span in SPAN.finditer(text):
        if span.start() in found:
            continue
        kind = classify(span.group(1))
        if kind is not None:
            found[span.start()] = Reference(kind, span.group(1), *locate(text, span.start()))
    return [found[offset] for offset in sorted(found)]


# --- Resolving --------------------------------------------------------------

MISSING = object()


def member(owner: Any, name: str) -> Any:
    """An attribute, or a dataclass field that has no class-level default."""
    value = getattr(owner, name, MISSING)
    if value is MISSING and dataclasses.is_dataclass(owner):
        value = {f.name: f for f in dataclasses.fields(owner)}.get(name, MISSING)
    return value


def import_prefix(parts: List[str]) -> Tuple[Any, int]:
    """The longest importable module prefix of a dotted path, and its length."""
    module, length = importlib.import_module(parts[0]), 1
    while length < len(parts) and hasattr(module, "__path__"):
        name = ".".join(parts[:length + 1])
        if importlib.util.find_spec(name) is None:
            break
        module, length = importlib.import_module(name), length + 1
    return module, length


def package_definitions() -> Dict[str, Dict[int, str]]:
    """{name: {id(object): where it is defined}} across the package.

    Module-level names are counted once however many modules import them,
    because an import is the same object; functions and classes count only in
    the module that defines them. Members of the package's classes are
    included, so a bare ``from_yaml()`` finds ``LabDataConfig.from_yaml``.
    """
    modules = [sslabdata] + [importlib.import_module(info.name) for info in
                             pkgutil.walk_packages(sslabdata.__path__, "sslabdata.")]
    index: Dict[str, Dict[int, str]] = {}
    classes = []
    for module in modules:
        for name, value in vars(module).items():
            if inspect.ismodule(value) or name.startswith("__"):
                continue
            if inspect.isclass(value) or inspect.isroutine(value):
                if getattr(value, "__module__", None) != module.__name__:
                    continue
                if inspect.isclass(value):
                    classes.append(value)
            index.setdefault(name, {}).setdefault(id(value), f"{module.__name__}.{name}")
    for cls in classes:
        fields = {f.name: f for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls) else {}
        for name, value in {**fields, **vars(cls)}.items():
            if not name.startswith("__"):
                index.setdefault(name, {})[id(value)] = f"{cls.__module__}.{cls.__qualname__}.{name}"
    return index


def unique(index: Dict[str, Dict[int, str]], name: str) -> Tuple[Optional[str], str]:
    """(where the one definition of a bare name is, or None; the problem)."""
    places = sorted(set(index.get(name, {}).values()))
    if len(places) == 1:
        return places[0], ""
    if not places:
        return None, "defined nowhere in sslabdata"
    return None, "ambiguous, defined as " + ", ".join(places) + "; qualify it"


def resolve_path(path: str) -> Tuple[Any, str]:
    """(the object a dotted path names, or MISSING; the problem)."""
    parts = path.split(".")
    owner, length = import_prefix(parts)
    for depth, name in enumerate(parts[length:], start=length):
        owner = member(owner, name)
        if owner is MISSING:
            return MISSING, f"{'.'.join(parts[:depth])} has no {name}"
    return owner, ""


def resolve(ref: Reference, index, schema, rows: Set[str]) -> str:
    """'' when the reference resolves, else why it does not."""
    text = ref.text
    if ref.kind == "row":
        return "" if text in rows else "no such row in tests/COVERAGE.md"
    if ref.kind == "pointer":
        return resolve_pointer(schema, text)
    call = text.endswith("()")
    path = text[:-2] if call or text.endswith(".*") else text
    head, _, rest = path.partition(".")
    if head == "sslabdata":
        target, problem = resolve_path(path)
    else:
        where, problem = unique(index, head)
        target = MISSING
        if where is not None:
            target, problem = resolve_path(where + ("." + rest if rest else ""))
            if rest and not inspect.isclass(resolve_path(where)[0]):
                target, problem = MISSING, f"{head} is not a class ({where})"
    if target is MISSING:
        return problem
    if call and not callable(target):
        return "names something that is not callable"
    if text.endswith(".*") and not inspect.ismodule(target):
        return "is not a module"
    return ""


def resolve_pointer(schema: Any, pointer: str) -> str:
    """'' when an RFC 6901 pointer resolves in the schema, else why not."""
    node = schema
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return f"no {token!r} in {SCHEMA_PATH.relative_to(REPO_ROOT).as_posix()}"
    return ""


# --- The test ---------------------------------------------------------------

def test_every_spec_reference_resolves():
    """Every code reference in SPEC.md names something that exists."""
    text = spec_text()
    references = extract(text)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rows = set(COVERAGE_ROW.findall((TESTS_DIR / "COVERAGE.md").read_text(encoding="utf-8")))
    index = package_definitions()

    results = []
    for ref in references:
        if ref.text in NOT_REFERENCES:
            problem, status = "", "not a reference: " + NOT_REFERENCES[ref.text]
        else:
            problem = resolve(ref, index, schema, rows)
            status = problem or "resolves"
        results.append((ref, problem, status))

    if os.environ.get(RESULTS_ENV):
        write_results(os.environ[RESULTS_ENV], results)

    problems = [f"SPEC.md:{ref.line} (section {ref.section!r}): {ref.kind} "
                f"`{ref.text}` {problem}" for ref, problem, _ in results if problem]
    spans = {span for span in SPAN.findall(text)}
    problems += [f"NOT_REFERENCES lists `{span}`, which SPEC.md no longer contains"
                 for span in sorted(NOT_REFERENCES) if span not in spans]
    # Each kind is read at least once, so a change to how SPEC.md writes
    # references cannot leave this test checking nothing.
    counts = Counter(ref.kind for ref in references)
    problems += [f"no {kind} reference was read from SPEC.md; has its form changed?"
                 for kind in ("callable", "name", "pointer", "row")
                 if not counts[kind]]
    assert not problems, "\n".join(problems)


def write_results(path: str, results) -> None:
    """The references and their outcomes, as the module docstring describes."""
    records = [{"kind": ref.kind, "reference": ref.text, "line": ref.line,
                "section": ref.section, "result": status}
               for ref, _, status in results]
    counts = dict(sorted(Counter(ref.kind for ref, _, _ in results).items()))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"counts": counts, "references": records}, handle,
                  indent=2, ensure_ascii=False)
        handle.write("\n")
