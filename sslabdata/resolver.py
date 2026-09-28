"""
Entity resolution: link works to people and projects, and compute
back-links. Names are matched as SPEC.md "How a name is matched" says.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from .diagnostics import Diagnostic, diagnostic
from .models import Contributor, Work, Person, Project, LabData
from .parsers.bibtex import given_words


# Default fuzzy match threshold (0.0 to 1.0). A fuzzy match is only ever a
# suggestion reported to a human; it never links anything.
FUZZY_THRESHOLD = 0.85

# Pattern for abbreviated names: single initial + surname (e.g., "A. Kim")
# After normalization (no periods): "a kim", "h zhang", etc.
_ABBREVIATED_NAME_RE = re.compile(r'^[a-z] [a-z]+$')

# `resolution.status` and `resolution.method` values, both open strings
# (SPEC.md §5).
RESOLVED, UNRESOLVED, AMBIGUOUS = "resolved", "unresolved", "ambiguous"
BY_NAME = "exact"

# The codes this module reports (SPEC.md "Diagnostic codes").
AMBIGUOUS_NAME = "RESOLVE-AMBIGUOUS-NAME"
SUGGESTION = "RESOLVE-SUGGESTION"
ALIAS_AMBIGUOUS = "PEOPLE-ALIAS-AMBIGUOUS"
PROJECT_UNKNOWN = "RESOLVE-PROJECT-UNKNOWN"

# One part of a given name that is an initial rather than a name: a letter,
# its period optional, and a hyphenated run of them -- `A.`, `A`, `G.-A.`,
# `J-P`. A Unicode letter, so `Ç.` is read as an initial and a name outside
# ASCII is not silently exempt. Tested once combining marks are off, so a
# letter with a mark that has no precomposed form, `Q̇.`, is one too. A part
# that is anything else is read as a name, which is the safe direction for a
# warning: it reports one grouping key too few rather than one too many.
_INITIAL = re.compile(r"^[^\W\d_]\.?(?:-[^\W\d_]\.?)*$", re.UNICODE)

# Initials written without a space between them, `S.S.` or `T.A.K.`, read as
# one initial per letter in a given name only. Tested once combining marks
# are off. SPEC.md "How a name is matched" has the rule.
_RUN_TOGETHER = re.compile(r"^[^\W\d_](?:\.[^\W\d_])+\.?$", re.UNICODE)


def _is_mark(c: str) -> bool:
    return unicodedata.category(c) == 'Mn'


def _without_marks(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not _is_mark(c))


def _is_initial(part: str) -> bool:
    return bool(_INITIAL.match(_without_marks(part)))


def _split_initials(word: str) -> List[str]:
    """``S.S.`` → ``["S.", "S."]``; any other word is returned whole.

    The initials come back without their combining marks: every reader of
    them removes marks too (`normalize_name()`, `_is_initial()`).
    """
    bare = _without_marks(word)
    if not _RUN_TOGETHER.match(bare):
        return [word]
    return [c + '.' for c in bare if c != '.']


def _spaced_initials(text: str) -> str:
    """``S.S. Adams`` → ``S. S. Adams``: run-together initials, one per part."""
    return ' '.join(part for word in text.split() for part in _split_initials(word))


def normalize_name(name: str) -> str:
    """Normalize a name for matching.

    Exactly the steps SPEC.md "How a name is matched" lists, so a change
    here is a change to the contract.
    """
    name = name.lower().strip()
    name = ''.join(
        c for c in unicodedata.normalize('NFD', name)
        if unicodedata.category(c) != 'Mn'
    )
    name = name.replace('.', '')
    name = re.sub(r'<sup>.*?</sup>', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def declared_form(name: str) -> str:
    """How a declared name or alias compares with another declaration
    (SPEC.md "How a name is matched").

    A declaration is read as `full_form()` joins a name, `Given von Family,
    Suffix`. Where the parse does not line up with the words, it is
    `normalize_name()` exactly.
    """
    before = name.split(",", 1)[0]
    words = before.split()
    given = given_words(before)
    if words[:len(given)] != given or all(
            _split_initials(word) == [word] for word in given):
        return normalize_name(name)
    spaced = [_spaced_initials(word) for word in given] + words[len(given):]
    return normalize_name(" ".join(spaced) + name[len(before):])


def written_form(contributor: Contributor) -> str:
    """How an unresolved name is grouped: `normalize_name()` of the readable
    name, with run-together initials spaced in its structured given name, so
    `S.S. Quinn` and `S. S. Quinn` are one grouping. A brace-protected name,
    or one with nothing to space, is `normalize_name()` of the name exactly.
    """
    given = contributor.given or ""
    if (contributor.literal or not contributor.name.startswith(given)
            or _spaced_initials(given) == " ".join(given.split())):
        return normalize_name(contributor.name)
    return normalize_name(_spaced_initials(given) + contributor.name[len(given):])


def _given_parts(given: Optional[str]) -> List[str]:
    return [part for part in _spaced_initials(given or "").split() if part]


def initials_only(given: Optional[str]) -> bool:
    """True when every part of a given name is an initial rather than a name."""
    parts = _given_parts(given)
    return bool(parts) and all(_is_initial(part) for part in parts)


def has_initial(given: Optional[str]) -> bool:
    """True when any part of a given name is an initial: ``Dave M.``, ``A.``"""
    return any(_is_initial(part) for part in _given_parts(given))


def given_initials(given: Optional[str]) -> Tuple[str, ...]:
    """The initial of each part of a given name, normalised.

    ``Alice Jane`` and ``A. J.`` both give ``("a", "j")``; ``Grace-Ann`` and
    ``G.-A.`` both give ``("g-a",)``, because both halves of a hyphenated
    given name carry an initial.
    """
    return tuple("-".join(normalize_name(piece)[:1]
                          for piece in part.split("-") if piece)
                 for part in _given_parts(given))


def _initials(given: str) -> str:
    """Abbreviate one given name: ``Alice`` → ``A.``, ``Grace-Ann`` → ``G.-A.``"""
    parts = [part for part in given.split("-") if part]
    return "-".join(f"{part[0]}." for part in parts)


def full_form(contributor: Contributor) -> str:
    """The form a full name is matched on: ``Alice Jane van Last, Jr.``

    The structured parts in reading order, with the suffix after a comma as
    `people.yaml` writes it. Nothing is abbreviated. A name written as one
    brace-protected unit is matched as written.
    """
    if contributor.literal:
        return contributor.literal
    name = " ".join(part for part in (contributor.given, contributor.von,
                                      contributor.family) if part)
    suffix = contributor.suffix
    return f"{name}, {suffix}" if suffix and name else (name or suffix or "")


def is_abbreviated(name: str) -> bool:
    """Check if a normalized name is a single-initial abbreviation.

    Returns True for names like "a kim" or "h zhang" — these have
    too little information for reliable fuzzy matching.
    """
    return bool(_ABBREVIATED_NAME_RE.match(name))


def shared_declarations(people: List[Person], source: str) -> List[Diagnostic]:
    """One `ALIAS_AMBIGUOUS` warning per spelling more than one person declares.

    Compared through `declared_form()`, so `S.S. Ivers` and `S. S. Ivers`
    are one spelling.
    """
    declared: Dict[str, List[Tuple[str, str, str]]] = {}
    for person in people:
        for field_name, written in [("name", person.name)] + [
                ("aliases", alias) for alias in person.aliases]:
            key = declared_form(written)
            owners = declared.setdefault(key, [])
            if key and person.id not in [owner for owner, _, _ in owners]:
                owners.append((person.id, field_name, written))
    reported = []
    for owners in declared.values():
        if len(owners) < 2:
            continue
        _, field_name, _ = owners[1]
        spellings = sorted({repr(written) for _, _, written in owners})
        reported.append(diagnostic(
            ALIAS_AMBIGUOUS, source, owners[1][0], field_name,
            f"{' / '.join(spellings)} is declared by "
            f"{', '.join(owner for owner, _, _ in owners)}; a name written "
            "this way fits all of them and resolves to none"))
    return reported


def fuzzy_matches(name: str, candidates: "Candidates",
                  threshold: float = FUZZY_THRESHOLD) -> List[str]:
    """Every id tied at the best similarity at or above the threshold,
    sorted, so a tie does not depend on the order of `people.yaml`.

    Compared against each normalised form exactly one entity declares: a form
    more than one declares suggests nobody, and `shared_declarations()`
    reports it. A single-initial name such as ``S. Zhang`` is never compared,
    because it carries too little to suggest anyone.
    """
    normalized = normalize_name(name)
    if is_abbreviated(normalized):
        return []

    best_ratio = 0.0
    best_ids: Set[str] = set()

    for key, ids in candidates.exact.items():
        if len(ids) != 1:
            continue
        ratio = SequenceMatcher(None, normalized, key).ratio()
        if ratio > best_ratio:
            best_ratio, best_ids = ratio, set(ids)
        elif ratio == best_ratio:
            best_ids |= ids

    return sorted(best_ids) if best_ratio >= threshold else []


def _is_initial_token(token: str) -> bool:
    pieces = [piece for piece in token.split("-") if piece]
    return bool(pieces) and all(len(piece) == 1 for piece in pieces)


def _tokens_agree(written: str, declared: str) -> bool:
    """One given-name part against another: equal, or the same initials
    where either side is only an initial."""
    if _is_initial_token(written) or _is_initial_token(declared):
        return (tuple(p[0] for p in written.split("-") if p)
                == tuple(p[0] for p in declared.split("-") if p))
    return written == declared


class NameKey(NamedTuple):
    """A name as matching compares it, through `normalize_name()`: its given
    name piece by piece, run-together initials one piece per letter, and the
    rest as one string. ``S.S. van Kim, Jr.`` is ``(("s", "s"), "van kim, jr")``.
    """
    given: Tuple[str, ...]
    rest: str


def _pieces(given: str) -> Tuple[str, ...]:
    """The normalised pieces of a given name, run-together initials spaced."""
    return tuple(piece for piece in (normalize_name(part) for part in
                                     _spaced_initials(given).split()) if piece)


def _written_key(contributor: Contributor) -> NameKey:
    """The key of a name from a work. A brace-protected name is all rest."""
    if contributor.literal:
        return NameKey((), normalize_name(contributor.literal))
    rest = normalize_name(" ".join(part for part in (contributor.von,
                                                     contributor.family) if part))
    if contributor.suffix:
        rest = f"{rest}, {normalize_name(contributor.suffix)}"
    return NameKey(_pieces(contributor.given or ""), rest)


def _declared_keys(name: str, key: str) -> List[NameKey]:
    """A declared name or alias divided at each of its words in turn.

    A declared string is not parsed into name parts: the division that counts
    is the one whose rest is the compared name's own. Its words are
    normalised one at a time and lined up with ``key``, the whole name
    normalised; where they do not line up, each word of ``key`` is one piece.
    """
    words = [(normalize_name(word), _pieces(word)) for word in name.split()]
    words = [(plain, pieces) for plain, pieces in words if plain]
    if " ".join(plain for plain, _ in words) != key:
        words = [(word, (word,)) for word in key.split()]
    return [NameKey(tuple(piece for _, pieces in words[:at] for piece in pieces),
                    " ".join(plain for plain, _ in words[at:]))
            for at in range(len(words) + 1)]


class Candidates:
    """The names a matcher compares against: ``(id, [name, *aliases])`` each.

    Every form is read through `normalize_name()`, so case, accents and
    periods do not matter.
    """

    def __init__(self, entries: Sequence[Tuple[str, Sequence[str]]]):
        self.exact: Dict[str, Set[str]] = {}
        # (id, declared given name) for each declared key, by its rest.
        self._by_rest: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = {}
        for entity_id, names in entries:
            for name in names:
                key = normalize_name(name)
                if not key:
                    continue
                self.exact.setdefault(key, set()).add(entity_id)
                for declared in _declared_keys(name, key):
                    self._by_rest.setdefault(declared.rest, []).append(
                        (entity_id, declared.given))

    def named(self, key: NameKey) -> Set[str]:
        """Every entity with a form whose key is ``key``."""
        return {entity_id for entity_id, given in self._by_rest.get(key.rest, ())
                if given == key.given}

    def compatible(self, key: NameKey) -> Set[str]:
        """Every entity one of whose forms this name could be.

        Same family, particles and suffix, and the given names agreeing part
        by part over the shorter of the two -- an initial agreeing with any
        name it abbreviates. `A. Kim` could be `Alex Kim` or `Alan Kim`;
        `Alan Kim` could not be `Alex Kim`. Used to find everyone a name
        could be, never on its own to link one.
        """
        return {entity_id for entity_id, given in self._by_rest.get(key.rest, ())
                if key.given and given and all(
                    _tokens_agree(w, d) for w, d in zip(key.given, given))}


class Match:
    """What matching one name found.

    ``status`` is `RESOLVED` with the one id in ``ids``, `AMBIGUOUS` with
    every id the name fits, or `UNRESOLVED` with ``ids`` holding the
    suggestions a human might check, which may be empty.
    """

    def __init__(self, status: str, ids: Set[str]):
        self.status = status
        self.ids = sorted(ids)

    @property
    def id(self) -> Optional[str]:
        return self.ids[0] if self.status == RESOLVED else None


def match(contributor: Contributor, candidates: Candidates) -> Match:
    """Match one name, on its full form first.

    The order of the rules is SPEC.md "How a name is matched".
    """
    written = _written_key(contributor)
    abbreviated = has_initial(contributor.given)
    exact = candidates.named(written)
    if len(exact) == 1 and not abbreviated:
        return Match(RESOLVED, exact)
    if len(exact) > 1:
        return Match(AMBIGUOUS, exact)

    compatible = (set() if contributor.literal or not contributor.family
                  else candidates.compatible(written))
    if contributor.literal or not abbreviated:
        return Match(UNRESOLVED, compatible)

    declared = exact | candidates.named(written._replace(given=tuple(
        normalize_name(_initials(part)) for part in _given_parts(contributor.given))))
    fits = compatible | declared
    if len(fits) > 1:
        return Match(AMBIGUOUS, fits)
    if declared:
        return Match(RESOLVED, declared)
    return Match(UNRESOLVED, fits)


def person_candidates(people: Sequence[Person]) -> Candidates:
    return Candidates([(p.id, [p.name] + list(p.aliases)) for p in people])


def _resolve(contributors: Sequence[Contributor], candidates: Candidates,
             fuzzy_threshold: float,
             where: Tuple[str, str, str],
             report: Optional[List[Diagnostic]]) -> List[str]:
    """Resolve one list of contributors in place; return the names left over.

    ``where`` is the ``(file, key, field)`` a diagnostic is located at.
    """
    unresolved: List[str] = []
    for contributor in contributors:
        found = match(contributor, candidates)
        if found.status == RESOLVED:
            contributor.person_id = found.id
            contributor.resolution_status = RESOLVED
            contributor.resolution_method = BY_NAME
            continue

        contributor.resolution_status = found.status
        unresolved.append(contributor.name)
        if report is None:
            continue
        if found.status == AMBIGUOUS:
            report.append(diagnostic(
                AMBIGUOUS_NAME, *where,
                f"position {contributor.position}, '{contributor.name}', fits "
                f"more than one person and is left unresolved: "
                f"{', '.join(found.ids)}"))
            continue
        suggested = set(found.ids) | set(
            fuzzy_matches(full_form(contributor), candidates, fuzzy_threshold))
        if suggested:
            report.append(diagnostic(
                SUGGESTION, *where,
                f"position {contributor.position}, '{contributor.name}', "
                f"matched no person but may be {', '.join(sorted(suggested))}; "
                "not linked, declare an alias if it is"))
    return unresolved


def resolve_authors(
    works: List[Work],
    people: List[Person],
    fuzzy_threshold: float = FUZZY_THRESHOLD,
    diagnostics: Optional[List[Diagnostic]] = None,
    bib_dir: str = ".",
) -> List[str]:
    """Resolve contributor names in works to person IDs, by `match()`.

    Ambiguous names and suggestions are reported into ``diagnostics`` when a
    list is given. Editors are resolved too, but are not authorships, so an
    editor that matches nobody is not in the returned list.

    Mutates ``person_id`` and ``resolution`` in place.

    Returns:
        The readable names of authorships that matched no person, sorted.
    """
    if not people:
        return []

    candidates = person_candidates(people)
    unresolved: Set[str] = set()

    for work in works:
        file = f"{bib_dir}/{work.source_file}"
        unresolved |= set(_resolve(work.authors, candidates, fuzzy_threshold,
                                   (file, work.bib_id, "author"), diagnostics))
        _resolve(work.editors, candidates, fuzzy_threshold,
                 (file, work.bib_id, "editor"), diagnostics)

    return sorted(unresolved)


def resolve_projects(
    works: List[Work],
    projects: List[Project],
    diagnostics: Optional[List[Diagnostic]] = None,
    bib_dir: str = ".",
) -> List[str]:
    """Return the unknown project IDs in works, sorted, and report each into
    ``diagnostics`` when a list is given. They stay on the work (SPEC.md §5).
    """
    known_ids = {p.id for p in projects}
    unknown: Set[str] = set()

    for work in works:
        for pid in work.project_ids:
            if pid not in known_ids:
                unknown.add(pid)
                if diagnostics is not None:
                    diagnostics.append(diagnostic(
                        PROJECT_UNKNOWN, f"{bib_dir}/{work.source_file}",
                        work.bib_id, "project",
                        f"'{pid}' is not a project id in the projects file"))

    return sorted(unknown)


def compute_backlinks(data: LabData) -> None:
    """Populate `Person.work_ids`, `Project.work_ids` and
    `Project.people_ids` in place (SPEC.md §3). Editors are not authorships
    and contribute to none of them."""
    people_by_id = {p.id: p for p in data.people}
    projects_by_id = {p.id: p for p in data.projects}

    for work in data.works:
        for author in work.authors:
            if author.person_id and author.person_id in people_by_id:
                person = people_by_id[author.person_id]
                if work.bib_id not in person.work_ids:
                    person.work_ids.append(work.bib_id)

        for pid in work.project_ids:
            if pid in projects_by_id:
                project = projects_by_id[pid]
                if work.bib_id not in project.work_ids:
                    project.work_ids.append(work.bib_id)

    for project in data.projects:
        people_set: Set[str] = set()
        for work_id in project.work_ids:
            linked = next((w for w in data.works if w.bib_id == work_id), None)
            if linked:
                for author in linked.authors:
                    if author.person_id:
                        people_set.add(author.person_id)
        project.people_ids = sorted(people_set)
