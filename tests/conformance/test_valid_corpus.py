"""Field-level checks on the valid corpus (tests/corpus/valid/).

Each table row is ``case(case_id, bib_key, field_path, expected)`` and checks
one field of one exported publication. Rows with a strict xfail
mark describe the intended behavior, which the issue in the reason delivers.
"""

import json

import pytest

from .support import (
    VALID, AllOf, Contains, Excludes, assert_field, case, export, item,
    run_sslabdata, work, write_variant,
)


def check_work(output, bib_key, path, expected):
    assert_field(work(output, bib_key), path, expected, where=f"{bib_key}: ")


# --- @string macros ----------------------------------------------------------

STRINGS = [
    case("strings.macro", "str-repeat", "venue.name", Contains("Robotics Venue")),
    case("strings.repeat_last_wins", "str-repeat", "venue.name",
         Excludes("Old Robotics Venue")),
    case("strings.concat", "str-concat", "title", "Joined Title"),
    case("strings.concat", "str-concat", "venue.name",
         AllOf(Contains("Proceedings of the Fictional Conference"), Excludes("Old"))),
    case("strings.macro_journal", "str-journal", "venue.name",
         "Journal of Fictional Robots Letters"),
    case("strings.defined_once", "str-once", "venue.name",
         "Journal of Fictional Robots"),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", STRINGS)
def test_strings(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# Covers strings.redefined_report
def test_redefined_strings_reported_once(valid_validate):
    """The three redefined macros are reported together by sslabdata, not one by one.

    One warning line names the code, the file, the macros and the line of
    each redefinition in strings.bib.
    """
    lines = valid_validate.output.splitlines()
    summary = [line for line in lines if all(m in line for m in ("rss", "cfx", "jfx"))]
    assert len(summary) == 1, valid_validate.output
    assert summary[0].startswith("  - BIB-STRING-REDEFINED ./strings.bib::: ")
    for value in ("./strings.bib:15", "./strings.bib:16", "./strings.bib:17"):
        assert value in summary[0]
    warnings = valid_validate.stdout.split("\nWarnings (", 1)[1]
    assert summary[0] in warnings


# Covers strings.defined_once
def test_macro_defined_once_is_not_reported(valid_validate, valid_export):
    """A macro defined exactly once is used, and nothing is said about it."""
    run, _ = valid_export
    for output in (valid_validate.output, run.output):
        assert "jrl" not in output, output


# --- Names and identity ------------------------------------------------------

NAMES = [
    case("names.last_first", "name-last-first", "authors.0.name", "Alice Adams"),
    case("names.last_first", "name-last-first", "authors.0.person_id", "aadams"),
    case("names.first_last", "name-first-last", "authors.0.name", "Bob Brown"),
    case("names.first_last", "name-first-last", "authors.0.person_id", "bbrown"),
    case("names.particle_last_first", "name-particle-van", "authors.0.name",
         "Victor van den Berg"),
    case("names.particle_last_first", "name-particle-van", "authors.0.person_id", "vvandenberg"),
    case("names.particle_first_last", "name-particle-de", "authors.0.name",
         "Rupert de la Cruz"),
    case("names.particle_first_last", "name-particle-de", "authors.0.person_id", "rdelacruz"),
    case("names.suffix", "name-suffix", "authors.0.name", "John Smith Jr."),
    case("names.suffix", "name-suffix", "authors.1.person_id", "aadams"),
    case("names.corporate", "name-corporate", "authors.0.name",
         "Example Robotics Consortium"),
    case("names.corporate", "name-corporate", "authors.0.person_id", None),
    case("names.corporate_escaped", "name-corporate-amp", "authors.0.name", "AT&T Research"),
    case("names.corporate_escaped", "name-corporate-amp", "authors.1.person_id", "aadams"),
    case("names.hyphenated", "name-hyphen", "authors.0.name", "Grace-Ann Green"),
    case("names.hyphenated", "name-hyphen", "authors.0.person_id", "ggreen"),
    case("names.accent_tex", "name-accent-tex", "authors.0.name", "Carol Côté"),
    case("names.accent_tex", "name-accent-tex", "authors.0.person_id", "ccote"),
    case("names.accent_utf8", "name-accent-utf8", "authors.0.name", "Carol Côté"),
    case("names.accent_utf8", "name-accent-utf8", "authors.0.person_id", "ccote"),
    case("names.others", "name-others", "authors.*.person_id", Contains("aadams", "bbrown")),
    case("names.others", "name-others", "authors.*.name", Excludes("others")),
    case("names.same_initial_alex", "name-kim-alex", "authors.0.person_id", "akim"),
    case("names.same_initial_alan", "name-kim-alan", "authors.0.person_id", "alankim"),
    case("names.initials_ambiguous", "name-kim-initial", "authors.0.person_id", None),
    case("names.initials_run_together", "name-initials-run-together",
         "authors.0.person_id", "sivers"),
    case("names.initials_run_together", "name-initials-run-together",
         "authors.0.name", "S.S. Ivers"),
    case("names.initials_run_together", "name-initials-run-together",
         "authors.0.given", "S.S."),
    case("names.initials_run_together_alias", "name-initials-run-together-alias",
         "authors.0.person_id", "tlark"),
    case("names.initials_run_together_three", "name-initials-run-together-three",
         "authors.0.person_id", "umoss"),
    case("names.initials_run_together_unmatched",
         "name-initials-run-together-unmatched", "authors.*.person_id",
         [None, None]),
    case("names.initials_multiletter_whole", "name-initials-multiletter",
         "authors.*.person_id", [None, None]),
    case("names.initials_hyphenated", "name-initials-hyphenated",
         "authors.*.person_id", ["jwren", None]),
    case("identity.alias", "name-last-first", "authors.0.person_id", "aadams"),
    case("identity.full_name", "id-full-name", "authors.0.person_id", "ffischer"),
    case("identity.normalized", "id-normalized", "authors.0.person_id", "ddavis"),
    case("identity.fuzzy", "id-fuzzy", "authors.0.person_id", None),
    case("identity.external", "id-external-2023", "authors.1.person_id", None),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", NAMES)
def test_names(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# --- Equal contribution ------------------------------------------------------
# Four corpus entries differing only in the marker form, each writing it on a
# different part of a name, give the sixteen combinations of form and part.
# Every marked author is a lab member, so each one also says the cleaned name
# still finds its person.

EQUAL_ENTRIES = ["name-equal-dollar", "name-equal-caret",
                 "name-equal-superscript", "name-equal-star"]
EQUAL_NAMES = ["Bob Brown", "Carol Côté", "Victor van den Berg",
               "John Smith Jr.", "Alice Adams"]
EQUAL_IDS = ["bbrown", "ccote", "vvandenberg", "jsmith", "aadams"]
# The part each author carries the marker on, and how that part reads once it
# is off. The last author is never marked.
EQUAL_PARTS = [("authors.0.given", "Bob"), ("authors.1.family", "Côté"),
               ("authors.2.von", "van den"), ("authors.3.suffix", "Jr.")]
EQUAL_MARKED = [True, True, True, True, False]

EQUAL_CONTRIBUTION = [
    case("names.equal_contribution", bib_key, path, expected)
    for bib_key in EQUAL_ENTRIES
    for path, expected in ([("authors.*.name", EQUAL_NAMES),
                            ("authors.*.person_id", EQUAL_IDS)] + EQUAL_PARTS)
] + [
    case("names.equal_contribution_marker", bib_key, "authors.*.equal_contribution",
         EQUAL_MARKED)
    for bib_key in EQUAL_ENTRIES
] + [
    # A marker written twice, one in a brace group of its own, and one whose
    # command and argument BibTeX split into two name parts: each comes off
    # whole, and the name still resolves. A brace group holding only a star is
    # another command's argument, not a marker, and is left alone -- so
    # `Dave Davis*` is not Dave Davis's name. It is a near miss, reported as a
    # suggestion and never linked (`identity.fuzzy`).
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.*.person_id", ["bbrown", "akim", "ggreen", None, "aadams"]),
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.*.equal_contribution", [True, True, True, False, False]),
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.0.name", "Bob Brown"),
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.1.name", "Alex Kim"),
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.2.name", "Grace-Ann Green"),
    case("names.equal_contribution_normalized", "name-equal-normalized",
         "authors.3.name", Contains("Davis", "*")),
    # A spaced marker followed by another, in each of the four forms: the
    # first is joined back together, the rest is stripped, and nothing of
    # either is left in the name.
    case("names.equal_contribution_normalized", "name-equal-stacked",
         "authors.*.name",
         ["Bob Brown", "Dave Davis", "Grace-Ann Green", "Alex Kim",
          "Alice Adams"]),
    case("names.equal_contribution_normalized", "name-equal-stacked",
         "authors.*.person_id", ["bbrown", "ddavis", "ggreen", "akim", "aadams"]),
    case("names.equal_contribution_normalized", "name-equal-stacked",
         "authors.*.equal_contribution", [True, True, True, True, False]),
    # An escaped star, caret, dollar or backslash is text: nobody is marked,
    # and the name parts keep their own boundaries. What each spelling becomes
    # is the ordinary LaTeX conversion's doing, and is pinned here as it is.
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.*.equal_contribution", [False, False, False, False, False]),
    # The three whose escaped marker stayed in the family name resolve to
    # nobody, because a name with a star in it is no person's name. `Davis\^{*}`
    # and `Green\$^{*}$` are near misses on Dave Davis and Grace-Ann Green,
    # reported as suggestions and never linked (`identity.fuzzy`); the second
    # is pinned as well in `test_resolver.py`'s `MATCHED_ON_THE_FULL_NAME`.
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.*.person_id",
         ["bbrown", None, None, None, "aadams"]),
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.0.name", "Bob Brown"),
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.1.name", Contains("Davis", "*")),
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.2.name", Contains("Green", "*")),
    case("names.equal_contribution_escaped", "name-equal-escaped",
         "authors.3.name", Contains("Evans", " *")),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", EQUAL_CONTRIBUTION)
def test_equal_contribution(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# The parts BibTeX split each name into, carried through to the output rather
# than collapsed into the display string. The resolver matches on them.

NAME_PARTS = [
    case("names.structured", "name-suffix", "authors.0.given", "John"),
    case("names.structured", "name-suffix", "authors.0.von", None),
    case("names.structured", "name-suffix", "authors.0.family", "Smith"),
    case("names.structured", "name-suffix", "authors.0.suffix", "Jr."),
    case("names.structured", "name-suffix", "authors.0.literal", None),
    case("names.structured", "name-particle-van", "authors.0.given", "Victor"),
    case("names.structured", "name-particle-van", "authors.0.von", "van den"),
    case("names.structured", "name-particle-van", "authors.0.family", "Berg"),
    case("names.structured", "name-hyphen", "authors.0.given", "Grace-Ann"),
    case("names.structured", "name-hyphen", "authors.0.family", "Green"),
    case("names.structured", "name-corporate", "authors.0.literal",
         "Example Robotics Consortium"),
    case("names.structured", "name-corporate", "authors.0.given", None),
    case("names.structured", "name-corporate", "authors.0.family", None),
    case("names.structured", "name-corporate-amp", "authors.0.literal", "AT&T Research"),
    case("names.structured", "name-corporate-amp", "authors.1.given", "Alice"),
    case("names.structured", "name-corporate-amp", "authors.1.family", "Adams"),
    case("names.structured", "name-corporate-amp", "authors.1.literal", None),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", NAME_PARTS)
def test_name_parts(valid_output, case_id, bib_key, path, expected):
    """The structured parts survive on the author, not only the display name."""
    check_work(valid_output, bib_key, path, expected)


def readable_name_from_parts(contributor):
    """The readable form the parts imply: the parts joined in reading order.

    It abbreviates nothing. ``Grace-Ann Green`` stays whole, and ``Brown, B.``
    yields ``B. Brown`` because that is what the entry supplied.
    """
    ordered = (contributor["given"], contributor["von"], contributor["family"],
               contributor["suffix"])
    return " ".join(part for part in ordered if part)


# Covers names.structured
def test_every_readable_name_agrees_with_its_parts(valid_output):
    """Across the whole corpus, the readable name follows from the parts, and
    abbreviates nothing.

    A row-by-row check of the parts would still pass if the parts were filled
    in beside a name built some other way. This rebuilds the whole name from
    the parts and compares it, for authorships and editors alike, and then
    asserts that no full given name came out as an initial -- which is what
    the name used to be and what a consumer must not be handed here.
    """
    checked = 0
    for work_ in valid_output["works"]:
        for contributor in work_["authors"] + work_["editors"]:
            where = f"{work_['bib_id']}: {contributor}"
            if contributor["literal"]:
                assert contributor["name"] == contributor["literal"], where
                assert [contributor[part]
                        for part in ("given", "von", "family", "suffix")] \
                    == [None, None, None, None], where
            else:
                assert contributor["family"], where
                assert contributor["name"] == readable_name_from_parts(contributor), where
                given = contributor["given"]
                if given and not given.endswith("."):
                    assert given in contributor["name"], where
            checked += 1
    # The loop has to have run over the names the corpus is built from.
    assert checked > 40, checked


MARKED_ENTRIES = set(EQUAL_ENTRIES) | {"name-equal-normalized", "name-equal-stacked"}


# Covers names.equal_contribution_marker
def test_only_marked_authors_are_equal_contributors(valid_output):
    """Across the corpus, equal_contribution is set exactly where a marker was.

    The rows above say the marked authors are marked. This says the unmarked
    ones are not: no name elsewhere in the corpus — a starred title, a
    corporate name, an accent written in TeX, an escaped star — picks the flag
    up. Nor does a marked name keep a star once the marker is off.
    """
    marked = {(w["bib_id"], a["name"]) for w in valid_output["works"]
              for a in w["authors"] if a["equal_contribution"]}
    assert {bib_id for bib_id, _ in marked} == MARKED_ENTRIES
    # Four parts marked in each of the four form entries, three of the five
    # authors of name-equal-normalized, and four of name-equal-stacked.
    assert len(marked) == len(EQUAL_ENTRIES) * 4 + 3 + 4, sorted(marked)
    assert [name for _, name in marked if "*" in name] == []


# Covers names.initials_ambiguous
def test_ambiguous_initials_listed(valid_unresolved):
    """An initials-only name that fits two members is listed for a human to resolve."""
    assert "A. Kim" in valid_unresolved.stdout


# Covers identity.ambiguous_reported
def test_ambiguous_name_reported_as_a_located_warning(valid_validate, valid_unresolved):
    """The author that fits both Kims is reported with its file, key and
    position, as a warning: neither mode's exit code moves."""
    for run in (valid_validate, valid_unresolved):
        assert run.code == 0 and run.crash is None, run.output
        [line] = [line for line in run.output.splitlines()
                  if "RESOLVE-AMBIGUOUS-NAME" in line]
        assert "names.bib:name-kim-initial:author" in line
        assert all(token in line for token in ("position 1", "akim", "alankim"))
    report = valid_validate.stdout
    assert report.index("RESOLVE-AMBIGUOUS-NAME") > report.index("Warnings (")
    assert "Bibliography errors" not in report


# Covers identity.suggestion_reported
def test_near_miss_reported_as_a_suggestion(valid_validate, valid_unresolved, valid_output):
    """`Davis, Dave M.` is suggested as ddavis, located, and linked to nobody."""
    for run in (valid_validate, valid_unresolved):
        assert run.code == 0 and run.crash is None, run.output
        [line] = [line for line in run.output.splitlines()
                  if "RESOLVE-SUGGESTION" in line and "id-fuzzy" in line]
        assert "names.bib:id-fuzzy:author" in line
        assert "position 1" in line and "ddavis" in line
    assert work(valid_output, "id-fuzzy")["authors"][0]["collaborator_key"]


# Covers identity.external
def test_external_author_listed(valid_unresolved, valid_output):
    assert "Quentin Quinn" in valid_unresolved.stdout
    quinn = item(valid_output, "collaborators", "name", "Quentin Quinn")
    assert len(quinn["work_ids"]) == 2


# --- LaTeX and text ----------------------------------------------------------
# Titles and abstracts come out as plain Unicode text; $...$ math stays TeX.

LATEX = [
    case("latex.textbf", "tex-textbf", "title", "A Bold Claim"),
    case("latex.nested", "tex-nested", "title", "a B c and d e f"),
    case("latex.accent_braced", "tex-accent", "title", "Café Robots in München"),
    case("latex.caron_space", "tex-caron", "title", "Haček on č"),
    case("latex.dotless_i", "tex-dotless", "title", "María's Robot"),
    case("latex.ampersand", "tex-amp", "title", "Pick & Place"),
    case("latex.percent", "tex-percent", "title", "A 50% Speedup"),
    case("latex.underscore", "tex-underscore", "title", "The robot_arm Package"),
    case("latex.endash", "tex-endash", "title", "Pages 1–10"),
    case("latex.emdash", "tex-emdash", "title", "Robots—and People"),
    case("latex.quotes", "tex-quotes", "title", "The “Tidy” Robot"),
    case("latex.star_braced", "tex-rrt", "title", "Faster RRT* Planning"),
    case("latex.star_plain", "tex-bit", "title", "BIT* in Clutter"),
    case("latex.star_braced_whole", "tex-bit-braced", "title", "BIT* Revisited"),
    case("latex.math", "tex-math", "title", r"Planning in $O(n \log n)$ Time"),
    case("latex.html_special", "tex-html", "title", "When a < b > c & \"d\" isn't 'e'"),
    case("latex.markdown_punctuation", "tex-markdown", "title",
         "Not [a link](x), not `code`, not # heading, not *emphasis*"),
    case("latex.unicode_raw", "tex-unicode", "title", "Robots 机器人 and Émoji 🤖"),
    case("latex.abstract", "tex-abstract", "abstract",
         "Café robots run in $O(n)$ time and are very tidy."),
    case("latex.note_href", "tex-note-href", "note",
         Contains("https://example.org/code", "our site")),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", LATEX)
def test_latex(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# --- Links -------------------------------------------------------------------

LINKS = [
    case("links.doi_bare", "link-doi-bare", "links.doi.0.url",
         "https://doi.org/10.5555/corpus.0001"),
    case("links.doi_url", "link-doi-url", "links.doi.0.url",
         "https://doi.org/10.5555/corpus.0002"),
    case("links.arxiv_prefixed", "link-arxiv-prefix", "links.arxiv.0.url",
         "https://arxiv.org/abs/2401.00001"),
    case("links.arxiv_unprefixed", "link-arxiv-bare", "links.arxiv.0.url",
         "https://arxiv.org/abs/2401.00002"),
    # An eprint in another repository gets no arXiv URL: the link is built
    # from the arXiv identifier, and this is not one.
    case("links.arxiv_other_repository", "link-eprint-hal", "links.arxiv", None),
    case("links.arxiv_other_repository", "link-eprint-hal", "identifiers.hal",
         ["hal-04001234"]),
    case("links.youtube", "link-youtube", "links.video.0.url",
         "https://www.youtube.com/watch?v=corpus00001"),
    case("links.youtube", "link-youtube", "links.url", None),
    case("links.vimeo", "link-vimeo", "links.video.0.url", "https://vimeo.com/000000001"),
    case("links.url", "link-url", "links.url.0.url",
         "https://example.org/papers/link-url"),
    case("links.url", "link-url", "links.video", None),
    # Where a link came from, which is what tells a consumer whether the
    # entry itself supplied it.
    case("links.origin", "link-url", "links.url.0.origin", "input"),
    case("links.origin", "link-doi-bare", "links.doi.0.origin", "derived"),
    case("links.pdf.local_present", "present", "links.pdf.0.url",
         Contains("present.pdf")),
    case("links.pdf.local_present", "present", "links.pdf.0.verification.status",
         "verified"),
    # Kept and labelled, not deleted: "the file is not there" and "no base is
    # configured" are different answers.
    case("links.pdf.local_missing", "missing", "links.pdf.0.url",
         Contains("missing.pdf")),
    case("links.pdf.local_missing", "missing", "links.pdf.0.verification.status",
         "missing"),
    # A build never fetches, so the verification carries a status and no time.
    case("links.pdf.local_present", "present", "links.pdf.0.verification",
         {"status": "verified"}),
    case("links.note_link_award", "link-note-award", "note",
         Contains("https://example.org/papers/award")),
    case("links.note_link_award", "link-note-award", "award", "Best Paper Award Finalist",
         marks=pytest.mark.xfail(strict=True, raises=AssertionError,
                                 reason="#27: the award field is not read")),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", LINKS)
def test_links(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# Covers links.video_field
def test_video_field_beside_a_website_url(tmp_path):
    """`url` stays the website and `video` becomes the video link; the field
    is carried in `bibtex` as written and draws no diagnostic."""
    variant = write_variant(tmp_path, pdf_base_url=None, bib_files=[
        {"name": "video.bib", "category": "Links"}])
    run, data = export(VALID, tmp_path, variant)
    assert run.code == 0 and run.crash is None, run.output
    found = work(data, "link-video-field")
    input_link = {"label": None, "origin": "input",
                  "verification": {"status": "unchecked"}}
    assert found["links"] == {
        "url": [{"url": "https://example.org/projects/link-video-field",
                 **input_link}],
        "video": [{"url": "https://example.org/videos/link-video-field.mp4",
                   **input_link}],
    }
    assert ('video = "https://example.org/videos/link-video-field.mp4"'
            in found["bibtex"])
    report = run_sslabdata(["--config", variant, "--validate", "--format", "json"],
                           VALID)
    assert report.code == 0 and report.crash is None, report.output
    assert json.loads(report.stdout) == []


# Covers links.pdf_field
def test_pdf_field_replaces_the_base_url_link(valid_output, tmp_path):
    """A `pdf` field is the work's one PDF link whether or not `pdf_base_url`
    is set; an empty one is read as absent and draws no diagnostic."""
    pdf_link = [{"url": "https://example.org/papers/link-pdf-field.pdf",
                 "label": None, "origin": "input",
                 "verification": {"status": "unchecked"}}]
    assert work(valid_output, "link-pdf-field")["links"] == {"pdf": pdf_link}
    assert work(valid_output, "link-pdf-empty")["links"] == {"pdf": [
        {"url": "pdfs/link-pdf-empty.pdf", "label": None, "origin": "derived",
         "verification": {"status": "missing"}}]}

    variant = write_variant(tmp_path, pdf_base_url=None, bib_files=[
        {"name": "links.bib", "category": "Links"}])
    run, data = export(VALID, tmp_path, variant)
    assert run.code == 0 and run.crash is None, run.output
    assert work(data, "link-pdf-field")["links"] == {"pdf": pdf_link}
    assert work(data, "link-pdf-empty")["links"] == {}
    report = run_sslabdata(["--config", variant, "--validate", "--format", "json"],
                           VALID)
    assert report.code == 0 and report.crash is None, report.output
    assert json.loads(report.stdout) == []


# --- BibTeX structure, entry types and fields -------------------------------

STRUCTURE = [
    case("structure.uppercase", "struct-upper", "entry_type", "article"),
    case("structure.uppercase", "struct-upper", "title", "Upper-Case Type and Fields"),
    case("structure.uppercase", "struct-upper", "authors.0.person_id", "aadams"),
    case("structure.uppercase", "struct-upper", "venue.name",
         "Journal of Fictional Robots"),
    case("structure.value_quoted", "struct-quoted", "title", "A Quoted Title"),
    case("structure.value_quoted", "struct-quoted", "year", 2019),
    case("structure.value_braced", "struct-braced", "title", "A Braced Title"),
    case("structure.value_numeric", "struct-numeric", "year", 2019),
    case("structure.value_numeric", "struct-numeric", "volume", "7"),
    case("structure.value_numeric", "struct-numeric", "number", "2"),
    # An ordinary @proceedings entry, of the kind a crossref used to point
    # at. Rejecting crossref must not change how one of these is read.
    case("structure.proceedings", "struct-parent", "year", 2018),
    case("structure.proceedings", "struct-parent", "entry_type", "proceedings"),
    case("structure.proceedings", "struct-parent", "venue.name",
         "Proceedings of the Fictional Workshop"),
    case("structure.proceedings", "struct-parent", "authors.0.person_id", "aadams"),
    case("structure.bom_crlf", "enc-bom-crlf", "title", "Byte Order Mark and CRLF"),
    case("structure.bom_crlf", "enc-bom-crlf", "authors.0.person_id", "ccote"),
    case("structure.bom_crlf", "enc-second", "title", "Second Entry After CRLF"),
    case("types.article", "type-article", "venue",
         {"kind": "journal", "name": "Journal of Fictional Robots"}),
    case("types.article", "type-article", "volume", "12"),
    case("types.article", "type-article", "number", "3"),
    case("types.article", "type-article", "year", 2020),
    case("types.inproceedings", "type-inproceedings", "venue",
         {"kind": "conference", "name": "Proceedings of the Fictional Conference"}),
    case("types.phdthesis", "type-phdthesis", "venue",
         {"kind": "institution", "name": "Example University"}),
    case("types.mastersthesis", "type-mastersthesis", "venue",
         {"kind": "institution", "name": "Example University"}),
    case("types.techreport", "type-techreport", "venue",
         {"kind": "institution", "name": "Example University"}),
    case("types.techreport", "type-techreport", "type", "Technical Report"),
    # BibTeX's `number`, with BibTeX's meaning: a report number here, an
    # issue number on the article above.
    case("types.techreport", "type-techreport", "number", "EU-TR-7"),
    case("types.techreport_default", "type-techreport-plain", "venue",
         {"kind": "institution", "name": "Example University"}),
    case("types.techreport_default", "type-techreport-plain", "type", None),
    case("types.misc_arxiv", "type-misc-arxiv", "venue",
         {"kind": "repository", "name": "arXiv"}),
    case("types.misc_arxiv", "type-misc-arxiv", "identifiers.arxiv", ["2401.00007"]),
    # Nothing names a container, so there is none: null, not a bare year.
    case("types.misc", "type-misc", "venue", None),
    case("types.misc", "type-misc", "year", 2020),
    case("fields.journal", "type-article", "venue.name", "Journal of Fictional Robots"),
    case("fields.volume", "type-article", "volume", "12"),
    case("fields.number", "type-article", "number", "3"),
    case("fields.pages", "type-article", "pages", "1--10"),
    case("fields.publisher", "type-article", "publisher", "Fictional Press"),
    case("fields.booktitle", "type-inproceedings", "venue.name",
         AllOf(Contains("Proceedings of the Fictional Conference"), Excludes("{"))),
    case("fields.school", "type-phdthesis", "venue.name", "Example University"),
    case("fields.institution", "type-techreport", "venue.name", "Example University"),
    case("fields.type", "type-techreport", "type", "Technical Report"),
    case("fields.eprint", "type-misc-arxiv", "identifiers.arxiv", ["2401.00007"]),
    # The prefix is the scheme: naming the repository is all it did, and the
    # scheme says it, so it needs no property of its own. Which means the
    # prefix has to *determine* the scheme rather than be assumed -- a
    # compiler that defaulted to arXiv would pass the row below and lose the
    # field, so the entry that names another repository is what pins it.
    case("fields.archiveprefix", "link-arxiv-prefix", "identifiers.arxiv",
         ["2401.00001"]),
    case("fields.archiveprefix", "link-eprint-hal", "identifiers.hal",
         ["hal-04001234"]),
    case("fields.archiveprefix", "link-eprint-hal", "identifiers.arxiv", None),
    case("fields.archiveprefix", "link-eprint-hal", "venue",
         {"kind": "repository", "name": "HAL"}),
    case("fields.doi", "link-doi-bare", "identifiers.doi", ["10.5555/corpus.0001"]),
    # A DOI written as a resolver URL is recorded as the identifier it is.
    case("fields.doi", "link-doi-url", "identifiers.doi", ["10.5555/corpus.0002"]),
    case("fields.url", "link-url", "links.url.0.url",
         "https://example.org/papers/link-url"),
    case("fields.project", "proj-single", "project_ids", ["homebot"]),
    # A field sslabdata emits no property for is still not dropped.
    case("fields.unread", "proj-keywords", "bibtex", Contains("keywords")),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", STRUCTURE)
def test_structure(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# Covers structure.comment_lines, structure.comment_mentions_command
def test_comment_lines_raise_no_syntax_error(valid_validate, valid_export):
    """A `%` comment line is ignored, so nothing is said about its prose.

    The corpus's comments mention `@string` and `@comment{`, which the parser
    library would otherwise read as the start of a command.
    """
    run, _ = valid_export
    for output in (valid_validate.output, run.output):
        assert "BIB-SYNTAX-ERROR" not in output, output


# Covers names.equal_contribution, names.equal_contribution_escaped
def test_documented_latex_commands_are_not_reported_unknown(valid_validate,
                                                            valid_export):
    """`\\textsuperscript{*}` and an escaped `\\*` have documented conversions."""
    run, _ = valid_export
    for output in (valid_validate.output, run.output):
        assert "LATEX-COMMAND-UNKNOWN" not in output, output


# Covers structure.comment_lines, structure.comment_entry, structure.preamble,
# structure.comment_mentions_command
def test_comments_and_preamble_are_not_works(valid_output):
    structure = {w["bib_id"] for w in valid_output["works"]
                 if w["category"] == "Structure"}
    # Entries on both sides of the comments and the preamble are all read.
    assert {"struct-upper", "type-article", "type-misc"} <= structure
    # The @article inside @comment{...} is not a work.
    assert "fake" not in structure
    # A % comment line that only mentions @comment{ is prose, not a command:
    # the entry after it is read like any other.
    assert "struct-comment-prose" in structure
    assert not [w for w in valid_output["works"]
                if w["entry_type"] in ("comment", "preamble", "string")]


# Covers structure.bom_crlf
def test_encoding_fixture_has_bom_and_crlf():
    """Guard the fixture itself: git or an editor must not normalize it."""
    raw = (VALID / "encoding.bib").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf@article{")
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


# --- Projects ----------------------------------------------------------------

PROJECTS = [
    case("projects.single", "proj-single", "project_ids", ["homebot"]),
    case("projects.multiple", "proj-multiple", "project_ids", ["homebot", "sharedarm"]),
    case("projects.none", "proj-none", "project_ids", []),
    case("projects.keywords", "proj-keywords", "project_ids", Contains("sharedarm"),
         marks=pytest.mark.xfail(strict=True, raises=AssertionError,
                                 reason="#28: keywords are not read as project tags")),
]


@pytest.mark.parametrize("case_id, bib_key, path, expected", PROJECTS)
def test_projects(valid_output, case_id, bib_key, path, expected):
    check_work(valid_output, bib_key, path, expected)


# Covers projects.single, projects.multiple
def test_project_backlinks(valid_output):
    homebot = item(valid_output, "projects", "id", "homebot")
    sharedarm = item(valid_output, "projects", "id", "sharedarm")
    assert homebot["work_ids"] == ["proj-single", "proj-multiple"]
    assert sharedarm["work_ids"] == ["proj-multiple"]
    assert homebot["people_ids"] == ["aadams", "bbrown", "ccote"]
    assert sharedarm["people_ids"] == ["aadams", "ccote"]


# --- Every output field ------------------------------------------------------
# (case_id, section, lookup key, lookup value, field path, expected)

OUTPUT_FIELDS = [
    case("output.schema_version", "", "", "", "schema_version", 5),
    case("output.generator", "", "", "", "generator.name", "sslabdata"),
    case("output.generator", "", "", "", "generator.schema_version", 5),
    case("output.lab", "", "", "", "lab.name", "Corpus Lab"),
    case("output.work.bib_id", "works", "bib_id", "type-article", "bib_id",
         "type-article"),
    case("output.work.source", "works", "bib_id", "type-article", "source",
         {"file": "structure.bib", "key": "type-article"}),
    case("output.work.title", "works", "bib_id", "tex-unicode", "title",
         "Robots 机器人 and Émoji 🤖"),
    case("output.work.authors", "works", "bib_id", "name-last-first", "authors",
         [{"name": "Alice Adams", "position": 1, "person_id": "aadams",
           "given": "Alice", "von": None, "family": "Adams", "suffix": None,
           "literal": None,
           "resolution": {"status": "resolved", "method": "exact"},
           "derived": {}, "collaborator_key": None,
           "equal_contribution": False}]),
    case("output.work.authors", "works", "bib_id", "name-suffix",
         "authors.*.position", [1, 2]),
    # An authorship that matched nobody references the grouping it fell into
    # instead, and never a person.
    case("output.work.authors", "works", "bib_id", "id-external-2023",
         "authors.1.person_id", None),
    case("output.work.authors", "works", "bib_id", "id-external-2023",
         "authors.1.collaborator_key", Contains("quentin-quinn")),
    case("output.work.authors", "works", "bib_id", "id-external-2023",
         "authors.1.resolution", {"status": "unresolved", "method": None}),
    # No editors in the corpus: an empty list, never null and never absent.
    case("output.work.editors", "works", "bib_id", "type-article", "editors", []),
    case("output.work.year", "works", "bib_id", "type-article", "year", 2020),
    case("output.work.venue", "works", "bib_id", "type-article", "venue",
         {"kind": "journal", "name": "Journal of Fictional Robots"}),
    case("output.work.venue", "works", "bib_id", "type-misc", "venue", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "volume", "12"),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "number", "3"),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "pages", "1--10"),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "publisher",
         "Fictional Press"),
    # Declared and null when the entry wrote none, not absent.
    case("output.work.bibliographic", "works", "bib_id", "type-article", "series", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "edition", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "address", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article",
         "organization", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "chapter", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "month", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article",
         "howpublished", None),
    case("output.work.bibliographic", "works", "bib_id", "type-article", "type", None),
    case("output.work.category", "works", "bib_id", "type-article", "category",
         "Structure"),
    case("output.work.entry_type", "works", "bib_id", "type-phdthesis",
         "entry_type", "phdthesis"),
    case("output.work.abstract", "works", "bib_id", "tex-abstract", "abstract",
         Contains("$O(n)$")),
    case("output.work.note", "works", "bib_id", "tex-note-href", "note",
         Contains("our site")),
    case("output.work.identifiers", "works", "bib_id", "link-doi-bare", "identifiers",
         {"doi": ["10.5555/corpus.0001"]}),
    # An open map carries only the keys that have values: no identifier is
    # an empty map, not a map of nulls over an unbounded key set.
    case("output.work.identifiers", "works", "bib_id", "type-misc", "identifiers", {}),
    case("output.work.links", "works", "bib_id", "link-url", "links.url",
         [{"url": "https://example.org/papers/link-url", "label": None,
           "origin": "input",
           "verification": {"status": "unchecked"}}]),
    case("output.work.project_ids", "works", "bib_id", "proj-multiple",
         "project_ids", ["homebot", "sharedarm"]),
    case("output.work.bibtex", "works", "bib_id", "type-article", "bibtex",
         Contains("@article{type-article,", "Journal of Fictional Robots")),
    case("output.work.derived", "works", "bib_id", "type-article", "derived", {}),
    case("output.person.id", "people", "name", "Alice Adams", "id", "aadams"),
    case("output.person.name", "people", "id", "ccote", "name", "Carol Côté"),
    case("output.person.role", "people", "id", "aadams", "role", "professor"),
    case("output.person.status", "people", "id", "eevans", "status", "alumni"),
    case("output.person.website", "people", "id", "aadams", "website",
         "https://example.org/people/aadams"),
    case("output.person.photo", "people", "id", "aadams", "photo", "images/aadams.jpg"),
    # Declared and null for the people who have none, not omitted.
    case("output.person.photo", "people", "id", "bbrown", "photo", None),
    case("output.person.email", "people", "id", "aadams", "email", "aadams@example.org"),
    case("output.person.co_advisor", "people", "id", "bbrown", "co_advisor", "Peggy Park"),
    case("output.person.start_year", "people", "id", "aadams", "start_year", 2015),
    case("output.person.end_year", "people", "id", "eevans", "end_year", 2020),
    # The alumni fields are declared for everyone, whatever the status.
    case("output.person.end_year", "people", "id", "aadams", "end_year", None),
    case("output.person.degree", "people", "id", "eevans", "degree", "PhD"),
    case("output.person.degree", "people", "id", "aadams", "degree", None),
    case("output.person.thesis_title", "people", "id", "eevans", "thesis_title",
         "Learning to Tidy"),
    case("output.person.current_position", "people", "id", "eevans", "current_position",
         "Research Scientist, Example Robotics Inc."),
    case("output.person.work_ids", "people", "id", "ccote", "work_ids",
         ["proj-multiple", "name-accent-tex", "name-accent-utf8", "name-equal-dollar",
          "name-equal-caret", "name-equal-superscript", "name-equal-star",
          "enc-bom-crlf"]),
    case("output.person.derived", "people", "id", "aadams", "derived", {}),
    case("output.project.id", "projects", "title", "Household Manipulation", "id", "homebot"),
    case("output.project.title", "projects", "id", "sharedarm", "title", "Shared Control"),
    case("output.project.description", "projects", "id", "homebot", "description",
         "Robots that tidy up a fictional kitchen."),
    case("output.project.website", "projects", "id", "homebot", "website",
         "https://example.org/projects/homebot"),
    case("output.project.image", "projects", "id", "homebot", "image",
         "images/projects/homebot.jpg"),
    case("output.project.status", "projects", "id", "sharedarm", "status", "completed"),
    case("output.project.work_ids", "projects", "id", "homebot", "work_ids",
         ["proj-single", "proj-multiple"]),
    case("output.project.people_ids", "projects", "id", "homebot", "people_ids",
         ["aadams", "bbrown", "ccote"]),
    case("output.project.derived", "projects", "id", "homebot", "derived", {}),
    case("output.collaborator.key", "collaborators", "name", "Rachel Ross", "key",
         Contains("rachel-ross-")),
    case("output.collaborator.grouped_by", "collaborators", "name", "Rachel Ross",
         "grouped_by", "normalized_name"),
    case("output.collaborator.name_kind", "collaborators", "name", "Rachel Ross",
         "name_kind", "personal"),
    # A brace-protected name is `literal`, not `organization`: braces say
    # "do not parse this", which covers mononyms too.
    case("output.collaborator.name_kind", "collaborators", "name", "AT&T Research",
         "name_kind", "literal"),
    case("output.collaborator.name", "collaborators", "name", "Rachel Ross", "name",
         "Rachel Ross"),
    case("output.collaborator.name", "collaborators", "name", "Rachel Ross", "family",
         "Ross"),
    case("output.collaborator.name_variants", "collaborators", "name", "Rachel Ross",
         "name_variants", ["RACHEL ROSS", "Rachel Ross"]),
    case("output.collaborator.authorships", "collaborators", "name", "Rachel Ross",
         "authorships", [{"work_id": "id-external-2019", "position": 3},
                         {"work_id": "id-grouping", "position": 2}]),
    case("output.collaborator.work_ids", "collaborators", "name", "Quentin Quinn",
         "work_ids", ["id-external-2023", "id-external-2019"]),
    case("output.collaborator.last_year", "collaborators", "name", "Quentin Quinn",
         "last_year", 2023),
    case("output.collaborator.derived", "collaborators", "name", "Quentin Quinn",
         "derived", {}),
]


@pytest.mark.parametrize("case_id, section, key, value, path, expected", OUTPUT_FIELDS)
def test_output_fields(valid_output, case_id, section, key, value, path, expected):
    obj = item(valid_output, section, key, value) if section else valid_output
    assert_field(obj, path, expected, where=f"{section} {value}: ")


# Covers output.collaborators.order
def test_collaborators_order(valid_output):
    """Most recent first, then most works, then name, then key.

    `name` is the tie-break it has always been. `key` follows it rather than
    replacing it, because two keys can carry the same readable name -- a
    parsed and a brace-protected spelling of one string are two keys -- so
    the name alone is no longer total.
    """
    rows = [(c["last_year"] is None, -(c["last_year"] or 0), -len(c["work_ids"]),
             c["name"], c["key"]) for c in valid_output["collaborators"]]
    assert rows == sorted(rows)
    assert valid_output["collaborators"][0]["name"] == "Quentin Quinn"

    # Three that share a year and a work count, so only the name and the key
    # decide. Their two orders disagree, which is what makes this a test of
    # which one is used rather than of a coincidence.
    tied = [(c["name"], c["key"]) for c in valid_output["collaborators"]
            if c["last_year"] == 2014]
    assert [name for name, _ in tied] == ["Ada Zima", "Ada \u00dcnal", "Ada \u00dcnal"]
    keys = [key for _, key in tied]
    assert keys != sorted(keys), keys
    # The two that share a name are separated by their keys, ascending, and
    # the entries wrote them the other way round -- so a sort that stopped at
    # the name would leave them in the order the input happened to use.
    assert tied[1][1] < tied[2][1], tied


# Covers identity.alike_authorships
def test_two_authorships_written_alike_stay_apart(valid_output):
    """Two different people written identically on one work stay two records.

    Not two contributors: any grouping by a name puts them together, and the
    key is a grouping by a name. What survives the grouping is the
    occurrence, addressed by `(work.bib_id, position)` -- which is why the
    counts differ, one work and two authorships, and why a consumer that
    distrusts the grouping can still tell there were two.
    """
    alike = [a for a in work(valid_output, "id-alike")["authors"]
             if a["family"] == "Young"]
    assert len(alike) == 2, alike
    assert [a["position"] for a in alike] == [2, 3]
    assert len({a["collaborator_key"] for a in alike}) == 1, alike

    entry = item(valid_output, "collaborators", "key", alike[0]["collaborator_key"])
    assert entry["work_ids"] == ["id-alike"]
    assert entry["authorships"] == [{"work_id": "id-alike", "position": 2},
                                    {"work_id": "id-alike", "position": 3}]


# The two codes, restated rather than imported: a published code is a
# permanent interface (SPEC.md, "Diagnostic codes"), and outside tests/unit
# the suite uses only sslabdata's public names.
SPANS_SPELLINGS = "ID-GROUPING-SPANS-SPELLINGS"
INITIALS_AMBIGUOUS = "ID-GROUPING-INITIALS-AMBIGUOUS"

# (label, the initials-only spelling, the fuller one it could be). One row
# per thing the check compares -- the initials, the family name, the
# particles and the lineage suffix -- and each is a shape that a check
# pattern-matching the normalised key cannot see, except `Q. Quinn`, which is
# the one initial and one plain family name that such a check could match.
INITIALS_SHADOWS = [
    ("a surname particle", "A. van der Meer", "Anna van der Meer"),
    ("two initials", "A. J. Smithson", "Anna Jane Smithson"),
    ("a hyphenated family name", "B. Smith-Jones", "Bella Smith-Jones"),
    ("a name outside ASCII", "\u00c7. A. \u00d6zt\u00fcrk",
     "\u00c7i\u011fdem Ay\u015fe \u00d6zt\u00fcrk"),
    ("one initial and one family name", "Q. Quinn", "Quentin Quinn"),
    ("a lineage suffix that agrees", "T. Tate Jr.", "Tobias Tate Jr."),
    ("a lineage suffix on one side only", "V. Vance", "Victor Vance Jr."),
]


# The complete set of pairs the corpus produces, by readable name. Every
# name the corpus writes in initials is here, with exactly the fuller names
# it could be -- so a check that compared one thing less would add a pair and
# a check that compared one thing more would drop one. The five names under
# `id-grouping-distinct` appear in no list on purpose: each differs from an
# initials-only key above in exactly one of the things the check compares --
# the particle, the family name, the second initial, the second half of a
# hyphenated given name, and a lineage suffix that disagrees.
INITIALS_PAIRS = {
    "A. van der Meer": ["Anna van der Meer"],
    "A. J. Smithson": ["Anna Jane Smithson"],
    "B. Smith-Jones": ["Bella Smith-Jones"],
    "\u00c7. A. \u00d6zt\u00fcrk": ["\u00c7i\u011fdem Ay\u015fe \u00d6zt\u00fcrk"],
    "Q. Quinn": ["Quentin Quinn"],
    "T. Tate Jr.": ["Tobias Tate Jr."],
    "V. Vance": ["Victor Vance Jr."],
}


def reported_initials_keys(output):
    """The collaborator key each initials-only warning is about."""
    return {line.split("'")[1] for line in output.splitlines()
            if INITIALS_AMBIGUOUS in line}


def reported_initials_pairs(output, valid_output):
    """{name: [fuller names]} for every initials-only warning, by readable name."""
    by_key = {c["key"]: c["name"] for c in valid_output["collaborators"]}
    pairs = {}
    for line in output.splitlines():
        if INITIALS_AMBIGUOUS not in line:
            continue
        quoted = [part for index, part in enumerate(line.split("'")) if index % 2]
        pairs[by_key[quoted[0]]] = sorted(by_key[key] for key in quoted[1:])
    return pairs


# Covers identity.grouping_initials, identity.grouping_distinct,
# identity.grouping_suffix
def test_the_initials_warnings_are_exactly_these_pairs(valid_validate, valid_output):
    """Both directions at once, over the whole corpus.

    Comparing one thing less -- dropping the particles, the family name, the
    second initial, the second half of a hyphenated one, or a lineage suffix
    that disagrees -- adds a pair that is not there. Comparing one thing more
    drops a pair that is: treating a suffix against none as a disagreement is
    the case that does it. A test that only asserted the pairs it wanted
    would catch the second and not the first, which is the direction a
    warning gets wrong most easily.
    """
    assert reported_initials_pairs(valid_validate.output, valid_output) == INITIALS_PAIRS


@pytest.mark.parametrize("label,initials,fuller",
                         [pytest.param(*row, id=row[0]) for row in INITIALS_SHADOWS])
# Covers identity.grouping_initials, identity.grouping_suffix
def test_an_initials_only_key_that_could_be_a_fuller_one_is_reported(
        valid_validate, valid_output, label, initials, fuller):
    """Each shape a check over the normalised key would miss.

    The test is on the structured parts -- the initials of the given name
    against a fuller given name, with the family name and the particles equal
    -- so a particle, a second initial, a hyphen in the family name and a
    letter outside ASCII are all seen. Both keys are asserted to exist and to
    differ, so each row is about a real pair rather than about a message.
    """
    short = item(valid_output, "collaborators", "name", initials)
    fuller_entry = item(valid_output, "collaborators", "name", fuller)
    assert short["key"] != fuller_entry["key"], label

    named = [line for line in valid_validate.output.splitlines()
             if INITIALS_AMBIGUOUS in line and short["key"] in line]
    assert len(named) == 1, (label, valid_validate.output)
    assert fuller_entry["key"] in named[0], (label, named[0])


# Covers identity.grouping_spellings, identity.grouping_initials
def test_grouping_risks_are_reported(valid_validate, valid_output):
    """The two ways the key can be wrong are said out loud, not left silent.

    One key spans two spellings of a name; another is initials only and could
    be either of two fuller keys. Neither is an error -- an external
    co-author never is -- and both are reported so the merge risk is visible.
    """
    output = valid_validate.output
    assert valid_validate.code == 0, output
    spanning = item(valid_output, "collaborators", "name", "Rachel Ross")
    initials = item(valid_output, "collaborators", "name", "Q. Quinn")
    fuller = item(valid_output, "collaborators", "name", "Quentin Quinn")

    assert len(spanning["name_variants"]) == 2, spanning
    assert f"{SPANS_SPELLINGS} ./names.bib:id-external-2019:author" in output
    assert spanning["key"] in output

    assert f"{INITIALS_AMBIGUOUS} ./names.bib:id-grouping:author" in output
    assert initials["key"] in output and fuller["key"] in output
    # The two keys really are different, which is the instability being
    # recorded: a consumer must not build a URL on one and expect the other.
    assert initials["key"] != fuller["key"]

    # The warning is about the pair, so the fuller key is not reported as
    # though it were the ambiguous one, and a key with no fuller counterpart
    # is not reported at all.
    reported = reported_initials_keys(output)
    assert fuller["key"] not in reported
    alone = item(valid_output, "collaborators", "name", "Yolanda Young")
    assert alone["key"] not in reported
