"""Tests for the resolver: author matching, collaborator grouping, back-linking.

Isolated on purpose: each class names the boundary the conformance corpus would
need a fixture per case to reach."""

import pytest

from sslabdata.models import Author, Contributor, Work, Person, Project, LabData
from sslabdata.loaders import load_collaborators, load_people, load_projects
from sslabdata.diagnostics import (
    CLASSES, FATAL, VALIDATION_ERROR, WARNING, record,
)
from sslabdata.resolver import (
    Candidates,
    normalize_name,
    is_abbreviated,
    shared_declarations,
    fuzzy_matches,
    resolve_authors,
    compute_backlinks,
)


def places(lines):
    """The (code, location) of each diagnostic line. SPEC.md: prose is not stable."""
    return [tuple(str(line).split(" ", 2)[:2]) for line in lines]


def assert_diagnostic(line, code, where, *values):
    """A diagnostic's code and location, and the essential values in its message."""
    prefix = f"{code} {where} "
    line = str(line)
    assert line.startswith(prefix), line
    message = line[len(prefix):]
    missing = [value for value in values if value not in message]
    assert not missing, (missing, line)


class TestNormalizeName:
    """The matching key. Accent and whitespace variants of one name each need
    their own corpus entry to reach through the CLI; a wrong key silently links
    or drops every author it touches."""

    def test_accents(self):
        assert normalize_name("H. Müller") == "h muller"

    def test_whitespace(self):
        assert normalize_name("  A.  Adams  ") == "a adams"


class TestIsAbbreviated:
    """The gate on fuzzy matching. A multi-initial name or a single word read as
    abbreviated would never be suggested; no fixture writes either shape."""

    def test_multi_initial(self):
        assert is_abbreviated("a j kim") is False

    def test_single_word(self):
        assert is_abbreviated("kim") is False


class TestFuzzyMatches:
    """The boundaries of a suggestion: abbreviated names are skipped, and a form two
    people declare suggests neither. Reached through the CLI only by one suggestion
    per fixture."""

    def test_abbreviated_name_skipped(self):
        """Single-initial names should NOT fuzzy match — too ambiguous."""
        assert fuzzy_matches("H. Zhang", Candidates([("yzhang", ["Y. Zhang"])])) == []

    def test_a_form_two_people_declare_suggests_neither(self):
        """`ab kim` is nearest `a kim`, which both Kims declare."""
        candidates = Candidates([("akim", ["Alex Kim", "A. Kim"]),
                                 ("alankim", ["Alan Kim", "A. Kim"])])
        assert fuzzy_matches("Ab Kim", candidates) == []


class TestMatchingPolicy:
    """What matching reports instead of guessing, where no fixture reaches it:
    near misses tied at the best score, and an editor fitting two members."""

    def run(self, people, *authors, editors=()):
        work = Work(bib_id="k1", title="T", category="C", entry_type="article",
                    year=2024, source_file="w.bib", authors=list(authors),
                    editors=list(editors))
        warnings = []
        unresolved = resolve_authors([work], people, diagnostics=warnings,
                                     bib_dir="bib")
        return work, unresolved, warnings

    def test_tied_near_misses_are_all_suggested_in_sorted_order(self):
        """Two people equally close are both suggested, whatever their order
        in `people.yaml`."""
        author = dict(name="Dana Lee", position=1, given="Dana", family="Lee")
        for people in ([Person(id="zlee", name="Dina Lee"),
                        Person(id="alee", name="Dena Lee")],
                       [Person(id="alee", name="Dena Lee"),
                        Person(id="zlee", name="Dina Lee")]):
            _, _, warnings = self.run(people, Author(**author))
            assert len(warnings) == 1
            assert "may be alee, zlee;" in warnings[0].message

    def test_editors_are_matched_and_reported_the_same_way(self):
        people = [Person(id="akim", name="Alex Kim", aliases=["A. Kim"]),
                  Person(id="alankim", name="Alan Kim")]
        work, unresolved, warnings = self.run(
            people, editors=[Contributor(name="A. Kim", position=1, given="A.",
                                         family="Kim")])
        assert work.editors[0].person_id is None
        assert unresolved == []
        assert_diagnostic(warnings[0], "RESOLVE-AMBIGUOUS-NAME",
                          "bib/w.bib:k1:editor:", "A. Kim")


def _resolved(people, **parts):
    """The person_id one name resolves to, or None."""
    author = Author(name=parts.pop("name", "n"), position=1, **parts)
    resolve_authors([Work(bib_id="k", title="T", category="C",
                          entry_type="article", year=2024,
                          authors=[author])], people)
    return author.person_id


class TestRunTogetherInitials:
    """`S.S.` in a given name is `S. S.`, on both sides of a match.

    Read as different spellings, one person splits into two collaborators or a
    member's alias is missed; each spelling pair is its own case."""

    def test_a_brace_protected_name_is_not_split(self):
        people = [Person(id="ssr", name="S. S. Robotics")]
        assert _resolved(people, name="S.S. Robotics",
                         literal="S.S. Robotics") is None
        people = [Person(id="ssr", name="S.S. Robotics")]
        assert _resolved(people, name="S.S. Robotics",
                         literal="S.S. Robotics") == "ssr"

    def test_a_declaration_whose_words_normalise_apart_is_read_whole(self):
        """A `<sup>` span across two words is removed from the whole string
        only, so the words do not line up with it; the declaration is then
        compared as normalised, without spacing any initials."""
        people = [Person(id="sivers", name="Stella Sky Ivers",
                         aliases=["S.S. Ivers<sup>1 2</sup>"])]
        assert _resolved(people, given="S. S.", family="Ivers") is None
        assert _resolved(people, given="SS", family="Ivers") == "sivers"

    @pytest.mark.parametrize("written", ["\u0160.S.", "S\u030c.S."])
    @pytest.mark.parametrize("declared", ["\u0160. S.", "S\u030c. S."])
    def test_accented_initials_precomposed_or_decomposed(self, written, declared):
        """`Š.S.` with the caron precomposed (U+0160) or decomposed (S and
        U+030C), on either side."""
        people = [Person(id="sivers", name="Stella Sky Ivers",
                         aliases=[f"{declared} Ivers"])]
        assert _resolved(people, given=written, family="Ivers") == "sivers"
        people = [Person(id="sivers", name="Stella Sky Ivers",
                         aliases=[f"{written} Ivers"])]
        assert _resolved(people, given=declared, family="Ivers") == "sivers"

    @pytest.mark.parametrize("given, found", [
        ("J.-P.", "jwren"), ("J-P", "jwren"),
        ("J.P.", None), ("J. P.", None), ("JP", None)])
    def test_hyphenated_initials_are_left_as_written(self, given, found):
        people = [Person(id="jwren", name="Jana-Pia Wren", aliases=["J.-P. Wren"])]
        assert _resolved(people, given=given, family="Wren") == found


class TestComputeBacklinks:
    """Back-links ignore editors and are idempotent. The CLI runs them once, so a
    second run is unreachable through conformance."""

    def _work(self, **changes):
        fields = dict(
            bib_id="adams2024",
            title="Test",
            authors=[Author(name="Alice Adams", position=1, person_id="aadams")],
            year=2024,
            category="Test",
            entry_type="article",
        )
        fields.update(changes)
        return Work(**fields)

    def test_editors_are_not_authorships(self):
        """An editor back-links nothing: not the person, not the project."""
        work = self._work(
            authors=[],
            editors=[Contributor(name="Alice Adams", position=1,
                                 person_id="aadams")],
            project_ids=["gardenbot"])
        person = Person(id="aadams", name="Alice Adams")
        project = Project(id="gardenbot", title="Robot Gardening")
        data = LabData(works=[work], people=[person], projects=[project])
        compute_backlinks(data)
        assert person.work_ids == []
        assert project.work_ids == ["adams2024"]
        assert project.people_ids == []

    def test_no_duplicate_backlinks(self):
        """Running compute_backlinks twice should not duplicate entries."""
        work = self._work()
        person = Person(id="aadams", name="Alice Adams")
        data = LabData(works=[work], people=[person], projects=[])
        compute_backlinks(data)
        compute_backlinks(data)
        assert person.work_ids.count("adams2024") == 1


class TestLoadPeople:
    """The loader called directly, as a caller with a hand-built configuration does,
    on a file that is not there. The CLI reports it first, as a coded error."""

    def test_missing_file(self):
        assert load_people("/nonexistent/path.yaml", []) == []


class TestDeclaredCollaboratorGrouping:
    """`collaborators_file` groups spellings; it never produces a person.

    A declared collaborator that became a person, or two people written alike
    that merged, would change every consumer's graph without a diagnostic."""

    def assemble(self, people, declared, *authors_by_work):
        from sslabdata.assembler import declared_collaborators, group_collaborators
        works = [Work(bib_id=f"w{i}", title="T", category="C", entry_type="article",
                      year=2020 + i, source_file="w.bib", authors=list(authors))
                 for i, authors in enumerate(authors_by_work)]
        warnings = []
        resolve_authors(works, people, diagnostics=warnings, bib_dir="bib")
        entries = declared_collaborators(declared, people, "c.yaml", warnings)
        return works, group_collaborators(works, "bib", warnings, entries, people), warnings

    def test_a_run_together_alias_a_member_declares_spaced_is_reported(self):
        from sslabdata.loaders import DeclaredCollaborator
        people = [Person(id="sivers", name="Stella Sky Ivers",
                         aliases=["S. S. Ivers"])]
        _, _, warnings = self.assemble(
            people, [DeclaredCollaborator("Sam Sol Ivers", ["S.S. Ivers"])])
        [warning] = warnings
        assert_diagnostic(warning, "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER",
                          "c.yaml:Sam Sol Ivers:aliases:", "S.S. Ivers", "sivers")

    def test_declared_collaborators_differing_in_the_family_name_stay_apart(self):
        """`S.S. S.S.` spaces its given name only, so it is not `S. S. S. S.`,
        and the authorships of the two are not merged."""
        from sslabdata.loaders import DeclaredCollaborator
        _, collaborators, warnings = self.assemble(
            [], [DeclaredCollaborator("S.S. S.S."), DeclaredCollaborator("S. S. S. S.")],
            [Author(name="S.S. S.S.", position=1, given="S.S.", family="S.S.")],
            [Author(name="S. S. S. S.", position=1, given="S. S. S.", family="S.")])
        assert sorted((c.grouped_by, c.work_ids) for c in collaborators) == [
            ("declared", ["w0"]), ("declared", ["w1"])]
        assert len({c.key for c in collaborators}) == 2
        assert warnings == []

    def test_undeclared_run_together_and_spaced_initials_group_together(self):
        _, collaborators, _ = self.assemble(
            [], [],
            [Author(name="S.S. Quinn", position=1, given="S.S.", family="Quinn")],
            [Author(name="S. S. Quinn", position=1, given="S. S.", family="Quinn")],
            [Author(name="S.S. Quinn", position=1, literal="S.S. Quinn")])
        [grouped] = [c for c in collaborators if c.name_kind == "personal"]
        assert grouped.key.startswith("s-s-quinn-")
        assert (grouped.name_variants, grouped.work_ids) == (
            ["S. S. Quinn", "S.S. Quinn"], ["w0", "w1"])
        [literal] = [c for c in collaborators if c.name_kind == "literal"]
        assert literal.key.startswith("ss-quinn-")


class TestPeopleAndProjectsFiles:
    """What is wrong with a people or projects file, in its three classes.

    The loaders' per-record checks decide which records enter the document
    (an empty file, a non-record entry, a project status, a key that is not a
    string). The corpus holds one bad record per fixture, not each value a
    check must accept."""

    def load(self, tmp_path, loader, text):
        path = tmp_path / "records.yaml"
        path.write_text(text, encoding="utf-8")
        found = []
        records = loader(str(path), found)

        def of(kind):
            return [str(line).replace(str(path), "f.yaml") for line in found
                    if CLASSES[line.code] == kind]
        return records, of(FATAL), of(VALIDATION_ERROR), of(WARNING)

    def test_an_empty_file_is_no_records(self, tmp_path):
        assert self.load(tmp_path, load_people, "") == ([], [], [], [])

    def test_every_record_is_checked_the_same_way(self, tmp_path):
        records, errors, _, _ = self.load(
            tmp_path, load_projects, "- just text\n- {title: No id}\n"
            "- {id: q}\n- {id: p, title: P}\n")
        assert [r.id for r in records] == ["p"]
        assert places(errors) == [("PROJECTS-NOT-A-LIST", "f.yaml:::"),
                                  ("PROJECTS-FIELD-MISSING", "f.yaml::id:"),
                                  ("PROJECTS-FIELD-MISSING", "f.yaml:q:title:")]
        _, errors, _, _ = self.load(tmp_path, load_people, "- {name: No Id}\n")
        assert places(errors) == [("PEOPLE-FIELD-MISSING", "f.yaml::id:")]
        declared, errors, _, _ = self.load(
            tmp_path, load_collaborators,
            "- {aliases: [X]}\n- {name: Priya Patel}\n")
        assert [c.name for c in declared] == ["Priya Patel"]
        assert places(errors) == [("COLLABORATORS-FIELD-MISSING", "f.yaml::name:")]

    @pytest.mark.parametrize("status, reported", [
        ("active", False), ("completed", False), ("paused", True)])
    def test_project_status(self, tmp_path, status, reported):
        _, _, _, warnings = self.load(
            tmp_path, load_projects, f"- {{id: p, title: A, status: {status}}}\n")
        assert bool(warnings) is reported

    def test_a_missing_project_status_is_active_and_not_reported(self, tmp_path):
        records, _, _, warnings = self.load(tmp_path, load_projects,
                                            "- {id: p, title: A}\n")
        assert records[0].status == "active" and warnings == []

    def test_a_key_that_is_not_a_string_is_named_as_text(self, tmp_path):
        path = tmp_path / "records.yaml"
        path.write_text("- {id: p, name: P, role: r, 0: a, 1: b}\n",
                        encoding="utf-8")
        found = []
        load_people(str(path), found)
        assert [record(w, "warning")["field"] for w in found] == ["0", "1"]


class TestSharedDeclarations:
    """Which declared spellings count as one name across people. Each boundary
    (run-together initials, a suffix, a comma, a hyphen) is a way to miss an
    ambiguous alias or to invent one; the ambiguous_alias fixture writes one shape."""

    @pytest.mark.parametrize("first, second", [
        ("S.S. Ivers, Jr.", "S. S. Ivers, Jr."),   # before a suffix
        ("S.S. S.S.", "S. S. S.S."),               # the given name, by position
    ])
    def test_spellings_equal_once_the_given_name_is_spaced(self, first, second):
        people = [Person(id="p1", name="One", aliases=[first]),
                  Person(id="p2", name="Two", aliases=[second])]
        [line] = shared_declarations(people, "people.yaml")
        assert "p1, p2" in line.message

    def test_a_declaration_bibtex_cannot_split_is_compared_as_normalised(self):
        """A word nested more than 100 braces deep makes pybtex raise, so the
        name's given words are not read and it is compared as written."""
        deep = "{" * 101 + "x" + "}" * 101
        people = [Person(id="p1", name="One", aliases=[f"S.S. {deep} Ivers"]),
                  Person(id="p2", name="Two", aliases=[f"s.s. {deep} ivers"]),
                  Person(id="p3", name="Three", aliases=[f"S. S. {deep} Ivers"])]
        [line] = shared_declarations(people, "people.yaml")
        assert "declared by p1, p2;" in line.message

    def test_a_person_repeating_their_own_spelling_is_not_reported(self):
        people = [Person(id="aadams", name="Alice Adams",
                         aliases=["Alice Adams", "A. Adams", "A Adams"])]
        assert shared_declarations(people, "people.yaml") == []
