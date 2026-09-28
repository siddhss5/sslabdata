"""
Entity resolution: link works to people and projects.

Matches contributor names in works to people in people.yaml on the
structured full name, then on declared aliases. A name that fits more than
one person is left unresolved and reported, and a near miss is reported as a
suggestion rather than linked. Resolves project tags and computes back-links.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .diagnostics import Diagnostic, diagnostic
from .models import Contributor, Work, Person, Project, LabData
from .parsers.bibtex import given_words


# Default fuzzy match threshold (0.0 to 1.0). A fuzzy match is only ever a
# suggestion reported to a human; it never links anything.
FUZZY_THRESHOLD = 0.85

# Pattern for abbreviated names: single initial + surname (e.g., "A. Kim")
# After normalization (no periods): "a kim", "h zhang", etc.
_ABBREVIATED_NAME_RE = re.compile(r'^[a-z] [a-z]+$')

# How a contributor's `resolution.status` reads, and how it resolved.
# `ambiguous` is a name that fits more than one person. Both are open strings,
# so a new status or method is not a breaking change.
RESOLVED, UNRESOLVED, AMBIGUOUS = "resolved", "unresolved", "ambiguous"
BY_NAME = "exact"

# Two things the resolver declines to decide, reported rather than guessed.
# Both are warnings. `AMBIGUOUS_NAME` means a name fits more than one lab
# member, and `--strict` makes it an error; `SUGGESTION` is about an author
# who matched no lab member, which is never an error under `--strict`.
AMBIGUOUS_NAME = "RESOLVE-AMBIGUOUS-NAME"
SUGGESTION = "RESOLVE-SUGGESTION"

# One spelling declared, as a name or an alias, by more than one person in
# `people_file`. A name written that way fits all of them and resolves to
# none, which is why the declaration itself is reported, and not only each
# authorship it leaves ambiguous. A warning, as those are.
ALIAS_AMBIGUOUS = "PEOPLE-ALIAS-AMBIGUOUS"

# A work tagged with a project id that `projects_file` does not define. It
# fails `--validate`: the id is a typo in data sslabdata owns (SPEC.md section 1).
PROJECT_UNKNOWN = "RESOLVE-PROJECT-UNKNOWN"

# One part of a given name that is an initial rather than a name: a letter,
# its period optional, and a hyphenated run of them -- `A.`, `A`, `G.-A.`,
# `J-P`. A Unicode letter, so `Ç.` is read as an initial and a name outside
# ASCII is not silently exempt. A part that is anything else is read as a
# name, which is the safe direction for a warning: it reports one grouping
# key too few rather than one too many.
_INITIAL = re.compile(r"^[^\W\d_]\.?(?:-[^\W\d_]\.?)*$", re.UNICODE)

# Initials written without a space between them: two or more letters, each
# but the last followed by a period, the last period optional -- `S.S.`,
# `S.S`, `T.A.K.`. In a given name they are read as one initial per letter,
# so `S.S.` matches as `S. S.` does. A part with no period inside it (`SS`,
# `Al.`) is a name, and a hyphenated one (`J.-P.`) is left as written. Never
# applied to a family name, a particle, a suffix or a brace-protected name.
# Tested once combining marks are off, so `Š.S.` is read alike whether the
# accent is precomposed or decomposed.
_RUN_TOGETHER = re.compile(r"^[^\W\d_](?:\.[^\W\d_])+\.?$", re.UNICODE)


def _is_mark(c: str) -> bool:
    return unicodedata.category(c) == 'Mn'


def _split_initials(word: str) -> List[str]:
    """``S.S.`` → ``["S.", "S."]``; any other word is returned whole."""
    decomposed = unicodedata.normalize('NFD', word)
    if not _RUN_TOGETHER.match(''.join(c for c in decomposed if not _is_mark(c))):
        return [word]
    letters: List[str] = []
    for c in decomposed:
        if _is_mark(c) and letters:
            letters[-1] += c
        elif c != '.':
            letters.append(c)
    return [unicodedata.normalize('NFC', letter) + '.' for letter in letters]


def _spaced_initials(text: str) -> str:
    """``S.S. Adams`` → ``S. S. Adams``: run-together initials, one per part."""
    return ' '.join(part for word in text.split() for part in _split_initials(word))


def normalize_name(name: str) -> str:
    """Normalize a name for matching.

    Lowercases, strips accents, removes periods and extra whitespace,
    and standardizes initial formats.
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
    """How a declared name or alias compares with another declaration.

    `normalize_name()`, with run-together initials spaced in the given name
    only: `S.S. Ivers` and `S. S. Ivers` are one form. A declaration is
    written `Given von Family, Suffix`, as `full_form()` joins a name, so
    only the text before the first comma is read with BibTeX's name parsing,
    and its given name is the words it reads as first and middle names, by
    position: the leading words. Particles, the family name and anything
    after the comma are never spaced. Where there is nothing to space, or
    the parse does not line up with the words, it is `normalize_name()`
    exactly.
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
    return bool(parts) and all(_INITIAL.match(part) for part in parts)


def has_initial(given: Optional[str]) -> bool:
    """True when any part of a given name is an initial: ``Dave M.``, ``A.``"""
    return any(_INITIAL.match(part) for part in _given_parts(given))


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


def _joined(given: str, contributor: Contributor) -> str:
    name = " ".join(part for part in (given, contributor.von,
                                      contributor.family) if part)
    suffix = contributor.suffix
    return f"{name}, {suffix}" if suffix and name else (name or suffix or "")


def full_form(contributor: Contributor) -> str:
    """The form a full name is matched on: ``Alice Jane van Last, Jr.``

    The structured parts in reading order, with the suffix after a comma as
    `people.yaml` writes it. Nothing is abbreviated. A name written as one
    brace-protected unit is matched as written.
    """
    if contributor.literal:
        return contributor.literal
    return _joined(contributor.given or "", contributor)


def is_abbreviated(name: str) -> bool:
    """Check if a normalized name is a single-initial abbreviation.

    Returns True for names like "a kim" or "h zhang" — these have
    too little information for reliable fuzzy matching.
    """
    return bool(_ABBREVIATED_NAME_RE.match(name))


def shared_declarations(people: List[Person], source: str) -> List[Diagnostic]:
    """One `ALIAS_AMBIGUOUS` warning per spelling more than one person declares.

    Compared through `declared_form()`, so `S.S. Ivers` and `S. S. Ivers`
    are one spelling. Located at the
    second person to declare the spelling, under the field that declares it
    there, and naming every person who does.
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


class Candidates:
    """The names a matcher compares against: ``(id, [name, *aliases])`` each.

    Every form is read through `normalize_name()`, so case, accents and
    periods do not matter.
    """

    def __init__(self, entries: Sequence[Tuple[str, Sequence[str]]]):
        self.forms: List[Tuple[str, str, List[Tuple[str, List[str]]]]] = []
        self.exact: Dict[str, Set[str]] = {}
        for entity_id, names in entries:
            for name in names:
                key = normalize_name(name)
                if not key:
                    continue
                self.forms.append((entity_id, key, _declared_parts(name, key)))
                self.exact.setdefault(key, set()).add(entity_id)

    def ids_for(self, key: str) -> Set[str]:
        return set(self.exact.get(key, ()))

    def _given(self, contributor: Contributor):
        """``(id, declared given parts)`` for every form ending in this
        name's particles, family name and suffix.

        A declared string is not parsed into name parts: its given name is
        what is left once the contributor's own tail is taken off, and only
        there are run-together initials read one per letter.
        """
        tail = normalize_name(" ".join(part for part in (contributor.von,
                                                     contributor.family) if part))
        if contributor.suffix:
            tail = f"{tail}, {normalize_name(contributor.suffix)}"
        size = len(tail.split())
        for entity_id, _, parts in self.forms:
            if len(parts) < size or " ".join(
                    plain for plain, _ in parts[len(parts) - size:]) != tail:
                continue
            yield entity_id, [piece for _, spaced in parts[:len(parts) - size]
                              for piece in spaced]

    def named(self, contributor: Contributor, given: List[str]) -> Set[str]:
        """Every entity with a form equal to this name, its given name read
        as ``given``. A brace-protected name is compared as written."""
        if contributor.literal:
            return self.ids_for(normalize_name(contributor.literal))
        return {entity_id for entity_id, declared in self._given(contributor)
                if declared == given}

    def compatible(self, contributor: Contributor) -> Set[str]:
        """Every entity one of whose forms this name could be.

        Same family, particles and suffix, and the given names agreeing part
        by part over the shorter of the two -- an initial agreeing with any
        name it abbreviates. `A. Kim` could be `Alex Kim` or `Alan Kim`;
        `Alan Kim` could not be `Alex Kim`. Used to find everyone a name
        could be, never on its own to link one.
        """
        if contributor.literal or not contributor.family:
            return set()
        written = _normalized_given(contributor.given)
        return {entity_id for entity_id, declared in self._given(contributor)
                if written and declared and all(
                    _tokens_agree(w, d) for w, d in zip(written, declared))}


def _declared_parts(name: str, key: str) -> List[Tuple[str, List[str]]]:
    """Each word of a declared name as ``(normalised, normalised with
    run-together initials spaced)``, lined up with the words of ``key``."""
    parts = [(normalize_name(word),
              [piece for piece in (normalize_name(p)
                                   for p in _spaced_initials(word).split()) if piece])
             for word in name.split()]
    parts = [(plain, spaced) for plain, spaced in parts if plain]
    if " ".join(plain for plain, _ in parts) != key:
        return [(word, [word]) for word in key.split()]
    return parts


def _normalized_given(given: Optional[str]) -> List[str]:
    """The parts of a given name, normalised, run-together initials spaced."""
    return [piece for piece in (normalize_name(part) for part in _given_parts(given))
            if piece]


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

    1. The full name, or a declared alias written in full, equal to exactly
       one entity's: resolved. Equal to two: ambiguous.
    2. Only when the name is itself abbreviated -- some part of the given
       name an initial -- its abbreviated form against the declared names and
       aliases. It resolves only when exactly one entity declares it *and*
       no other entity's name could be it too: `A. Kim` is ambiguous when
       one Kim declares the alias and another Kim is `Alan`.
    3. Otherwise nothing is linked, and every entity the name could be is a
       suggestion.
    """
    exact = candidates.named(contributor, _normalized_given(contributor.given))
    if len(exact) == 1 and not (contributor.given and has_initial(contributor.given)):
        return Match(RESOLVED, exact)
    if len(exact) > 1:
        return Match(AMBIGUOUS, exact)

    compatible = candidates.compatible(contributor)
    if contributor.literal or not has_initial(contributor.given):
        return Match(UNRESOLVED, compatible)

    declared = exact | candidates.named(contributor, [
        normalize_name(_initials(part)) for part in _given_parts(contributor.given)])
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
    """Resolve contributor names in works to person IDs.

    Strategy, in `match()`: the structured full name, then -- only for a
    name that is itself abbreviated -- a declared alias. A name that fits
    more than one person is left unresolved, and a near miss is never
    linked. Both are reported under `AMBIGUOUS_NAME` and `SUGGESTION` into
    ``diagnostics``, located at the work, when a list is given.

    Editors are resolved by the same machinery. They are not authorships, so
    an editor that matches nobody is not reported as an unresolved author.

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
    """Validate project IDs in works against known projects.

    Returns list of unknown project IDs found in works, and reports each
    unknown tag under `PROJECT_UNKNOWN` into ``diagnostics``, located at the work,
    when a list is given.
    Does NOT remove unknown project IDs from works (they're kept
    for debugging visibility).
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
    """Populate back-references on people and projects.

    Editing a volume is not an authorship, so `work.editors` contribute to
    none of these: not to a person's works and not to a project's people.

    Mutates data in place:
    - Person.work_ids
    - Project.work_ids, Project.people_ids
    """
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
