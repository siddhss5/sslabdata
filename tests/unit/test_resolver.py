"""Tests for the resolver: author matching, collaborator grouping, back-linking.

Isolated on purpose: each class names the boundary the conformance corpus would
need a fixture per case to reach."""

import pytest

from sslabdata.models import Author, Contributor, Work, Person, Project, LabData
from sslabdata.loaders import load_collaborators, load_people, load_projects
from sslabdata.diagnostics import (
    CLASSES, FATAL, VALIDATION_ERROR, WARNING, code_of, record,
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
    return [tuple(line.split(" ", 2)[:2]) for line in lines]


def assert_diagnostic(line, code, where, *values):
    """A diagnostic's code and location, and the essential values in its message."""
    prefix = f"{code} {where} "
    assert line.startswith(prefix), line
    message = line[len(prefix):]
    missing = [value for value in values if value not in message]
    assert not missing, (missing, line)


class TestNormalizeName:
    """The matching key. Accent, period, whitespace and footnote-markup variants of one name each
    need their own corpus entry to reach through the CLI; a wrong key silently links
    or drops every author it touches."""

    def test_basic(self):
        assert normalize_name("A. Adams") == "a adams"

    def test_accents(self):
        assert normalize_name("H. Müller") == "h muller"

    def test_periods(self):
        assert normalize_name("A.J. Adams") == "aj adams"

    def test_whitespace(self):
        assert normalize_name("  A.  Adams  ") == "a adams"

    def test_superscript(self):
        assert normalize_name("A. Adams<sup>*</sup>") == "a adams"


class TestIsAbbreviated:
    """The gate on fuzzy matching. A wrong answer lets `H. Zhang` suggest an unrelated
    person; the spellings that decide it are too many to write as fixtures."""

    def test_single_initial_surname(self):
        assert is_abbreviated("a kim") is True
        assert is_abbreviated("h zhang") is True

    def test_multi_initial(self):
        assert is_abbreviated("a j kim") is False

    def test_full_name(self):
        assert is_abbreviated("alice adams") is False

    def test_single_word(self):
        assert is_abbreviated("kim") is False


class TestSameInitial:
    """Two members sharing an initial and a family name: an alias one of them never
    declared must not link an abbreviated name to the wrong person, a silent
    misattribution."""

    def test_same_initial_collision_without_alias(self):
        """An alias shared implicitly with another person's initials is ambiguous.

        Alan Kim declares no aliases, but "A. Kim" fits him as well as Alex Kim,
        so it must not resolve to Alex.
        """
        people = [
            Person(id="akim", name="Alex Kim", aliases=["A. Kim"]),
            Person(id="alankim", name="Alan Kim", aliases=[]),
        ]
        work = Work(
            bib_id="kim2024", title="Test", category="Test",
            entry_type="article", year=2024,
            authors=[Author(name="A. Kim", position=1, given="A.", family="Kim")],
        )
        unresolved = resolve_authors([work], people)
        assert work.authors[0].person_id is None
        assert "A. Kim" in unresolved


class TestFuzzyMatches:
    """The threshold and tie boundaries of a suggestion: abbreviated names are skipped,
    ties are all returned in sorted order, and a form two people declare suggests
    neither. Reached through the CLI only by one suggestion per fixture."""

    def test_abbreviated_name_skipped(self):
        """Single-initial names should NOT fuzzy match — too ambiguous."""
        assert fuzzy_matches("H. Zhang", Candidates([("yzhang", ["Y. Zhang"])])) == []

    def test_close_match(self):
        candidates = Candidates([("aadams", ["Alice Adams"])])
        assert fuzzy_matches("Alice A. Adams", candidates, threshold=0.75) == ["aadams"]
        assert fuzzy_matches("Completely Different Name", candidates) == []

    def test_ties_are_all_returned_sorted(self):
        candidates = Candidates([("zlee", ["Dina Lee"]), ("alee", ["Dena Lee"]),
                                 ("aadams", ["Alice Adams"])])
        assert fuzzy_matches("Dana Lee", candidates, threshold=0.8) == ["alee", "zlee"]

    def test_a_form_two_people_declare_suggests_neither(self):
        """`ab kim` is nearest `a kim`, which both Kims declare."""
        candidates = Candidates([("akim", ["Alex Kim", "A. Kim"]),
                                 ("alankim", ["Alan Kim", "A. Kim"])])
        assert fuzzy_matches("Ab Kim", candidates) == []


# The three corpus authorships #56 section 7 predicted would move once
# matching read the full name rather than the abbreviated form:
# (given, von, family, who the abbreviated form found, who they resolve to
# now). The first two are rows #24 owned (`identity.full_name` and
# `names.same_initial_alan`). The third is the one #56 predicted would move
# through a fuzzy match on the full name; a fuzzy match now links nothing, so
# it stays unresolved and is reported as a suggestion instead.
MATCHED_ON_THE_FULL_NAME = [
    ("Frank", None, "Fischer", None, "ffischer"),
    ("Alan", None, "Kim", "akim", "alankim"),
    ("Grace-Ann", None, "Green$^*$", None, None),
]


class TestTheResolverMatchesTheFullName:
    """#24: a full name is matched as written, and never abbreviated to find
    someone who declared the abbreviation.

    The failure is silent: the author is linked to the wrong member and no
    diagnostic is raised, so only an assertion on the resulting `person_id`
    over several name pairs exposes it."""

    PEOPLE = [
        Person(id="aadams", name="Alice Adams", aliases=["A. Adams"]),
        Person(id="akim", name="Alex Kim", aliases=["A. Kim"]),
        Person(id="alankim", name="Alan Kim"),
        Person(id="ffischer", name="Frank Fischer"),
        Person(id="ggreen", name="Grace-Ann Green", aliases=["G.-A. Green"]),
    ]

    def resolve(self, author):
        work = Work(bib_id="w", title="T", category="C", entry_type="article",
                    year=2024, authors=[author])
        resolve_authors([work], self.PEOPLE)
        return work.authors[0].person_id

    @pytest.mark.parametrize(
        "given,von,family,on_match_form,on_full_name",
        MATCHED_ON_THE_FULL_NAME,
        ids=[row[2] for row in MATCHED_ON_THE_FULL_NAME])
    def test_each_predicted_authorship_resolves_on_the_full_name(
            self, given, von, family, on_match_form, on_full_name):
        author = Author(name=" ".join(p for p in (given, von, family) if p),
                        position=1, given=given, von=von, family=family)
        assert self.resolve(author) == on_full_name

    @pytest.mark.parametrize(
        "given,von,family,on_match_form,on_full_name",
        MATCHED_ON_THE_FULL_NAME,
        ids=[row[2] for row in MATCHED_ON_THE_FULL_NAME])
    @pytest.mark.parametrize("display", [
        "Alice Adams", "Alex Kim", "A. Kim", "Somebody Else", ""])
    def test_the_display_name_never_decides(
            self, given, von, family, on_match_form, on_full_name, display):
        """`name` is display-only: a name that disagrees with the parts --
        including one that is another member's name -- resolves as the parts
        say, whatever it is."""
        author = Author(name=display, position=1, given=given, von=von,
                        family=family)
        assert self.resolve(author) == on_full_name

    def test_parts_that_are_nobody_stay_nobody_under_a_members_name(self):
        author = Author(name="Alice Adams", position=1, given="Quentin",
                        family="Quinn")
        assert self.resolve(author) is None

    def test_an_abbreviated_name_still_reaches_its_declared_alias(self):
        author = Author(name="A. Adams", position=1, given="A.", family="Adams")
        assert self.resolve(author) == "aadams"


class TestMatchingPolicy:
    """The order `match()` applies, and what it reports instead of guessing.

    A wrong order links an author to the wrong member with no diagnostic. Each
    rung of the order is one case; a fixture per rung would repeat the lab."""

    def run(self, people, *authors, editors=()):
        work = Work(bib_id="k1", title="T", category="C", entry_type="article",
                    year=2024, source_file="w.bib", authors=list(authors),
                    editors=list(editors))
        warnings = []
        unresolved = resolve_authors([work], people, diagnostics=warnings,
                                     bib_dir="bib")
        return work, unresolved, warnings

    def test_an_ambiguous_initial_is_reported_with_its_location(self):
        people = [Person(id="akim", name="Alex Kim", aliases=["A. Kim"]),
                  Person(id="alankim", name="Alan Kim")]
        work, unresolved, warnings = self.run(
            people, Author(name="Bob Brown", position=1, given="Bob", family="Brown"),
            Author(name="A. Kim", position=2, given="A.", family="Kim"))
        author = work.authors[1]
        assert author.person_id is None
        assert author.resolution_status == "ambiguous"
        assert author.resolution_method is None
        assert unresolved == ["A. Kim", "Bob Brown"]
        [warning] = warnings
        assert_diagnostic(warning, "RESOLVE-AMBIGUOUS-NAME", "bib/w.bib:k1:author:",
                          "A. Kim", "akim", "alankim")

    def test_two_people_declaring_one_full_name_is_ambiguous(self):
        people = [Person(id="lee1", name="Lin Lee"), Person(id="lee2", name="Lin Lee")]
        work, _, warnings = self.run(
            people, Author(name="Lin Lee", position=1, given="Lin", family="Lee"))
        assert work.authors[0].person_id is None
        assert work.authors[0].resolution_status == "ambiguous"
        assert [w.split()[0] for w in warnings] == ["RESOLVE-AMBIGUOUS-NAME"]

    def test_a_near_miss_is_suggested_and_not_linked(self):
        people = [Person(id="ddavis", name="Dave Davis", aliases=["D. Davis"])]
        work, unresolved, warnings = self.run(
            people, Author(name="Dave M. Davis", position=1, given="Dave M.",
                           family="Davis"))
        assert work.authors[0].person_id is None
        assert work.authors[0].resolution_status == "unresolved"
        assert unresolved == ["Dave M. Davis"]
        [warning] = warnings
        assert_diagnostic(warning, "RESOLVE-SUGGESTION", "bib/w.bib:k1:author:",
                          "Dave M. Davis", "ddavis")

    def test_a_fuller_name_is_not_folded_into_a_declared_initial(self):
        """`Alan Kim` is not the Kim who declared `A. Kim`: a suggestion only."""
        people = [Person(id="akim", name="Alex Kim", aliases=["A. Kim"])]
        work, _, warnings = self.run(
            people, Author(name="Alan Kim", position=1, given="Alan", family="Kim"))
        assert work.authors[0].person_id is None
        assert [w.split()[0] for w in warnings] == ["RESOLVE-SUGGESTION"]
        assert "may be akim" in warnings[0]

    def test_an_initial_nobody_declared_is_suggested_and_not_linked(self):
        people = [Person(id="ffischer", name="Frank Fischer")]
        work, _, warnings = self.run(
            people, Author(name="F. Fischer", position=1, given="F.", family="Fischer"))
        assert work.authors[0].person_id is None
        assert "may be ffischer" in warnings[0]

    def test_an_external_name_is_reported_by_nothing(self):
        people = [Person(id="aadams", name="Alice Adams", aliases=["A. Adams"])]
        _, unresolved, warnings = self.run(
            people, Author(name="Quentin Quinn", position=1, given="Quentin",
                           family="Quinn"))
        assert unresolved == ["Quentin Quinn"] and warnings == []

    def test_a_partly_abbreviated_name_reaches_its_declared_alias(self):
        people = [Person(id="bbrown", name="Bob Brown", aliases=["B. A. Brown"]),
                  Person(id="bbrown2", name="Bill A. Brown")]
        work, _, warnings = self.run(
            people, Author(name="Bob A. Brown", position=1, given="Bob A.",
                           family="Brown"))
        assert work.authors[0].person_id == "bbrown" and warnings == []

    def test_particles_suffixes_and_hyphens_are_compared_as_parts(self):
        people = [Person(id="vvdb", name="Victor van den Berg",
                         aliases=["V. van den Berg"]),
                  Person(id="jsmith", name="John Smith, Jr.", aliases=["J. Smith, Jr."]),
                  Person(id="jsmithsr", name="James Smith, Sr."),
                  Person(id="gagreen", name="Grace-Ann Green", aliases=["G.-A. Green"]),
                  Person(id="gbgreen", name="Grace-Beth Green")]
        work, _, warnings = self.run(
            people,
            Author(name="V. van den Berg", position=1, given="V.",
                   von="van den", family="Berg"),
            Author(name="J. Smith Jr.", position=2, given="J.", family="Smith",
                   suffix="Jr."),
            Author(name="John Smith Jr.", position=3, given="John", family="Smith",
                   suffix="Jr."),
            Author(name="G.-A. Green", position=4, given="G.-A.", family="Green"))
        assert [a.person_id for a in work.authors] == [
            "vvdb", "jsmith", "jsmith", "gagreen"]
        assert warnings == []

    def test_a_brace_protected_name_matches_only_as_written(self):
        people = [Person(id="acme", name="Acme Robotics")]
        work, _, warnings = self.run(
            people, Author(name="Acme Robotics", position=1, literal="Acme Robotics"),
            Author(name="Acme Robots", position=2, literal="Acme Robots"))
        assert [a.person_id for a in work.authors] == ["acme", None]

    def test_a_star_in_a_name_is_a_near_miss_and_not_linked(self):
        """A star that is not a marker is part of the name, and a name with a
        star in it is not the person's name."""
        people = [Person(id="astar", name="Alice Star")]
        work, unresolved, warnings = self.run(
            people, Author(name="Alice Star*", position=1, given="Alice",
                           family="Star*"))
        author = work.authors[0]
        assert author.person_id is None
        assert (author.resolution_status, author.resolution_method) == ("unresolved", None)
        assert unresolved == ["Alice Star*"]
        [warning] = warnings
        assert_diagnostic(warning, "RESOLVE-SUGGESTION", "bib/w.bib:k1:author:",
                          "Alice Star*", "astar")

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
            assert "may be alee, zlee;" in warnings[0]

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
    """`S.S.` in a given name is `S. S.`, on both sides of a match (#81).

    Read as different spellings, one person splits into two collaborators or a
    member's alias is missed; each spelling pair is its own case."""

    IVERS = [Person(id="sivers", name="Stella Sky Ivers", aliases=["S. S. Ivers"])]

    @pytest.mark.parametrize("given", ["S.S.", "S.S", "S S", "S. S."])
    def test_written_forms_match_a_spaced_alias(self, given):
        assert _resolved(self.IVERS, given=given, family="Ivers") == "sivers"

    @pytest.mark.parametrize("alias", ["S.S. Ivers", "S.S Ivers", "S S Ivers"])
    def test_declared_forms_match_spaced_initials(self, alias):
        people = [Person(id="sivers", name="Stella Sky Ivers", aliases=[alias])]
        assert _resolved(people, given="S. S.", family="Ivers") == "sivers"

    def test_three_initials(self):
        people = [Person(id="umoss", name="Uma Ann Kaye Moss",
                         aliases=["T.A.K. Moss"])]
        assert _resolved(people, given="T. A. K.", family="Moss") == "umoss"

    @pytest.mark.parametrize("given", ["SS", "Ss"])
    def test_a_part_with_no_period_inside_is_not_split(self, given):
        assert _resolved(self.IVERS, given=given, family="Ivers") is None

    def test_an_undotted_name_is_not_run_together_initials(self):
        people = [Person(id="equill", name="Ed Quill")]
        assert _resolved(people, given="E.D.", family="Quill") is None
        assert _resolved(people, given="Ed", family="Quill") == "equill"

    def test_a_family_name_is_not_split(self):
        people = [Person(id="ada", name="Ada S. S.")]
        assert _resolved(people, given="Ada", family="S.S.") is None
        people = [Person(id="ada", name="Ada S.S.")]
        assert _resolved(people, given="Ada", family="S.S.") == "ada"

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


class TestResolveAuthors:
    """An editor resolves but is never reported as an unresolved author; the
    conformance suite reads the author report only."""

    def _make_work(self, authors, editors=()):
        return Work(
            bib_id="test",
            title="Test",
            authors=list(authors),
            editors=list(editors),
            year=2024,
            category="Test",
            entry_type="article",
        )

    def test_editors_resolve_but_are_never_reported_as_unresolved(self):
        """Editing a volume is not an authorship, so an editor nobody matches
        is not an author sslabdata could not resolve."""
        people = [Person(id="aadams", name="Alice Adams", aliases=["A. Adams"])]
        editors = [Contributor(name="Alice Adams", position=1, given="Alice",
                               family="Adams"),
                   Contributor(name="Quentin Quinn", position=2, given="Quentin",
                               family="Quinn")]
        work = self._make_work([], editors)
        unresolved = resolve_authors([work], people)
        assert [e.person_id for e in work.editors] == ["aadams", None]
        assert unresolved == []


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


class TestLoadProjects:
    """The loader called directly on a file that is not there; see TestLoadPeople."""

    def test_missing_file(self):
        assert load_projects("/nonexistent/path.yaml", []) == []


class TestLoadCollaborators:
    """The loader called directly: aliases are read as declared, and a missing or
    empty file declares nobody."""

    def test_load(self, tmp_path):
        path = tmp_path / "collaborators.yaml"
        path.write_text('- name: "Priya Patel"\n  aliases: ["P. Patel"]\n'
                        '- name: "Quentin Quinn"\n', encoding="utf-8")
        loaded = load_collaborators(str(path), [])
        assert [(c.name, c.aliases) for c in loaded] == [
            ("Priya Patel", ["P. Patel"]), ("Quentin Quinn", [])]

    def test_missing_or_empty_file(self, tmp_path):
        assert load_collaborators("/nonexistent/path.yaml", []) == []
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        assert load_collaborators(str(empty), []) == []


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

    def test_a_declared_alias_joins_one_person_and_not_another(self):
        from sslabdata.loaders import DeclaredCollaborator
        works, collaborators, warnings = self.assemble(
            [], [DeclaredCollaborator("Priya Patel", ["P. Patel"])],
            [Author(name="Priya Patel", position=1, given="Priya", family="Patel")],
            [Author(name="P. Patel", position=1, given="P.", family="Patel")],
            [Author(name="Pradeep Patel", position=1, given="Pradeep", family="Patel")])
        grouped = {c.name: (c.grouped_by, c.work_ids) for c in collaborators}
        assert grouped == {"Priya Patel": ("declared", ["w0", "w1"]),
                           "Pradeep Patel": ("normalized_name", ["w2"])}
        assert [a.person_id for w in works for a in w.authors] == [None] * 3
        assert warnings == []

    def test_run_together_initials_match_a_spaced_declared_alias(self):
        from sslabdata.loaders import DeclaredCollaborator
        _, collaborators, warnings = self.assemble(
            [], [DeclaredCollaborator("Priya Sun Patel", ["P. S. Patel"])],
            [Author(name="Priya Sun Patel", position=1, given="Priya Sun",
                    family="Patel")],
            [Author(name="P.S. Patel", position=1, given="P.S.", family="Patel")])
        assert [(c.name, c.grouped_by, c.work_ids) for c in collaborators] == [
            ("Priya Sun Patel", "declared", ["w0", "w1"])]
        assert warnings == []

    def test_spaced_initials_match_a_run_together_declared_alias(self):
        from sslabdata.loaders import DeclaredCollaborator
        _, collaborators, warnings = self.assemble(
            [], [DeclaredCollaborator("Priya Sun Patel", ["P.S. Patel"])],
            [Author(name="P. S. Patel", position=1, given="P. S.", family="Patel")])
        assert [(c.name, c.grouped_by) for c in collaborators] == [
            ("P. S. Patel", "declared")]
        assert warnings == []

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

    def test_a_name_fitting_two_declared_collaborators_is_reported(self):
        from sslabdata.loaders import DeclaredCollaborator
        _, collaborators, warnings = self.assemble(
            [], [DeclaredCollaborator("Priya Patel", ["P. Patel"]),
                           DeclaredCollaborator("Pradeep Patel")],
            [Author(name="P. Patel", position=2, given="P.", family="Patel")])
        assert [(c.name, c.grouped_by) for c in collaborators] == [
            ("P. Patel", "normalized_name")]
        [warning] = warnings
        assert_diagnostic(warning, "ID-GROUPING-AMBIGUOUS-DECLARED",
                          "bib/w.bib:w0:author:", "P. Patel",
                          "collaborator:pradeep patel", "collaborator:priya patel")

    def test_a_member_competes_with_a_declared_collaborator(self):
        """`P. Patel` could be the member as well, so it joins neither.

        It fits one lab member, not more than one, so it is not
        `RESOLVE-AMBIGUOUS-NAME` (#26 decision 6): it is reported with the
        other grouping ambiguity, as an unresolved outside co-author may be.
        """
        from sslabdata.loaders import DeclaredCollaborator
        people = [Person(id="ppatel", name="Paul Patel")]
        works, collaborators, warnings = self.assemble(
            people, [DeclaredCollaborator("Priya Patel", ["P. Patel"])],
            [Author(name="P. Patel", position=1, given="P.", family="Patel")])
        assert works[0].authors[0].person_id is None
        assert [c.grouped_by for c in collaborators] == ["normalized_name"]
        assert any(w.startswith("ID-GROUPING-AMBIGUOUS-DECLARED")
                   and "person:ppatel" in w for w in warnings)
        assert not any(w.startswith("RESOLVE-AMBIGUOUS-NAME") for w in warnings)

    def test_a_declared_name_that_is_a_member_is_left_to_the_member(self):
        from sslabdata.loaders import DeclaredCollaborator
        people = [Person(id="aadams", name="Alice Adams", aliases=["A. Adams"])]
        works, collaborators, warnings = self.assemble(
            people, [DeclaredCollaborator("Alice Adams")],
            [Author(name="Alice Adams", position=1, given="Alice", family="Adams")])
        assert works[0].authors[0].person_id == "aadams"
        assert collaborators == []
        [warning] = warnings
        assert_diagnostic(warning, "RESOLVE-COLLABORATOR-ALIAS-IS-MEMBER",
                          "c.yaml:Alice Adams:name:", "Alice Adams", "aadams")


class TestPeopleAndProjectsFiles:
    """What is wrong with a people or projects file, in its three classes.

    The loaders' per-record checks decide which records enter the document
    (a blank name, a non-record entry, each status and role value). The corpus
    holds one bad record per fixture, not each value a check must accept."""

    def load(self, tmp_path, loader, text):
        path = tmp_path / "records.yaml"
        path.write_text(text, encoding="utf-8")
        found = []
        records = loader(str(path), found)

        def of(kind):
            return [line.replace(str(path), "f.yaml") for line in found
                    if CLASSES[code_of(line)] == kind]
        return records, of(FATAL), of(VALIDATION_ERROR), of(WARNING)

    def test_an_empty_file_is_no_records(self, tmp_path):
        assert self.load(tmp_path, load_people, "") == ([], [], [], [])

    def test_a_missing_or_blank_name(self, tmp_path):
        records, errors, _, _ = self.load(
            tmp_path, load_people,
            "- {id: q}\n- {id: p, name: ' '}\n- {id: r, name: R, role: x}\n")
        assert [r.id for r in records] == ["r"]
        assert places(errors) == [("PEOPLE-FIELD-MISSING", "f.yaml:q:name:"),
                                  ("PEOPLE-FIELD-MISSING", "f.yaml:p:name:")]

    def test_a_projects_file_that_is_not_a_list_is_fatal(self, tmp_path):
        records, errors, _, _ = self.load(tmp_path, load_projects, "p: {title: T}\n")
        assert records == [] and [e.split(" ", 2)[:2] for e in errors] == [
            ["PROJECTS-NOT-A-LIST", "f.yaml:::"]]

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

    def test_duplicate_ids_are_kept_and_reported(self, tmp_path):
        records, _, diagnostics, _ = self.load(
            tmp_path, load_projects,
            "- {id: p, title: A}\n- {id: p, title: B}\n")
        assert [r.title for r in records] == ["A", "B"]
        [duplicate] = diagnostics
        assert_diagnostic(duplicate, "PROJECTS-ID-DUPLICATE", "f.yaml:p:id:", "'p'")

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

    @pytest.mark.parametrize("role, reported", [
        ("'research scientist'", False), ("visitor", False),
        ("''", True), ("7", True), ("[a]", True), (None, True)])
    def test_any_nonempty_role_is_accepted(self, tmp_path, role, reported):
        entry = "- {id: p, name: P" + (f", role: {role}" if role else "") + "}\n"
        _, _, _, warnings = self.load(tmp_path, load_people, entry)
        assert [w.startswith("PEOPLE-ROLE-INVALID f.yaml:p:role:")
                for w in warnings] == ([True] if reported else [])

    @pytest.mark.parametrize("status, reported", [
        ("current", False), ("alumni", False), ("retired", True)])
    def test_person_status(self, tmp_path, status, reported):
        _, _, _, warnings = self.load(
            tmp_path, load_people, f"- {{id: p, name: P, role: r, status: {status}}}\n")
        assert [w.startswith("PEOPLE-STATUS-INVALID f.yaml:p:status:")
                for w in warnings] == ([True] if reported else [])

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

    def test_a_name_shared_with_an_alias_is_reported_once(self):
        people = [Person(id="aadams", name="Alice Adams", aliases=["A. Adams"]),
                  Person(id="aadamson", name="A. Adams", aliases=[]),
                  Person(id="adup", name="A Adams", aliases=["a. adams"])]
        [line] = shared_declarations(people, "people.yaml")
        assert line.startswith("PEOPLE-ALIAS-AMBIGUOUS people.yaml:aadamson:name: ")
        assert "aadams, aadamson, adup" in line

    def test_run_together_and_spaced_initials_are_one_spelling(self):
        people = [Person(id="sivers", name="Stella Sky Ivers", aliases=["S. S. Ivers"]),
                  Person(id="sivory", name="Sam Sol Ivers", aliases=["S.S. Ivers"])]
        [line] = shared_declarations(people, "people.yaml")
        assert line.startswith("PEOPLE-ALIAS-AMBIGUOUS people.yaml:sivory:aliases: ")
        assert "sivers, sivory" in line

    @pytest.mark.parametrize("first, second", [
        ("S.S. Ivers, Jr.", "S. S. Ivers, Jr."),   # before a suffix
        ("S.S. S.S.", "S. S. S.S."),               # the given name, by position
    ])
    def test_spellings_equal_once_the_given_name_is_spaced(self, first, second):
        people = [Person(id="p1", name="One", aliases=[first]),
                  Person(id="p2", name="Two", aliases=[second])]
        [line] = shared_declarations(people, "people.yaml")
        assert "p1, p2" in line

    @pytest.mark.parametrize("first, second", [
        ("Ada S.S.", "Ada S. S."),      # a family name is not split
        ("S.S. S.S.", "S. S. S. S."),   # nor one written like the given name
        ("Alice Ivers, S.S.", "Alice Ivers, S. S."),   # nor what follows a comma
        ("Ivers, S.S.", "Ivers, S. S."),   # `Family, Given` is left as written
        ("S.S. Ivers", "SS Ivers"),     # a part with no period inside is a name
        ("J.-P. Wren", "J. P. Wren"),   # hyphenated initials are left as written
    ])
    def test_other_spellings_stay_apart(self, first, second):
        people = [Person(id="p1", name="One", aliases=[first]),
                  Person(id="p2", name="Two", aliases=[second])]
        assert shared_declarations(people, "people.yaml") == []

    def test_a_declaration_bibtex_cannot_read_is_compared_as_normalised(self):
        people = [Person(id="p1", name="One", aliases=["A, B, C, D"]),
                  Person(id="p2", name="Two", aliases=["a, b, c, d"])]
        [line] = shared_declarations(people, "people.yaml")
        assert "p1, p2" in line

    def test_a_declaration_bibtex_cannot_split_is_compared_as_normalised(self):
        """A word nested more than 100 braces deep makes pybtex raise, so the
        name's given words are not read and it is compared as written."""
        deep = "{" * 101 + "x" + "}" * 101
        people = [Person(id="p1", name="One", aliases=[f"S.S. {deep} Ivers"]),
                  Person(id="p2", name="Two", aliases=[f"s.s. {deep} ivers"]),
                  Person(id="p3", name="Three", aliases=[f"S. S. {deep} Ivers"])]
        [line] = shared_declarations(people, "people.yaml")
        assert "declared by p1, p2;" in line

    def test_a_person_repeating_their_own_spelling_is_not_reported(self):
        people = [Person(id="aadams", name="Alice Adams",
                         aliases=["Alice Adams", "A. Adams", "A Adams"])]
        assert shared_declarations(people, "people.yaml") == []
