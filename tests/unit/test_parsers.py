"""Tests for the BibTeX parsing pipeline.

Isolated on purpose: each class names the boundary the conformance corpus would
need a fixture per case to reach."""

import re

import pytest

from sslabdata.parsers.bibtex import (
    CROSSREF_UNSUPPORTED,
    DUPLICATE_CITATION_KEY,
    ENTRY_TYPE_UNSUPPORTED,
    LATEX_COMMAND_UNKNOWN,
    LATEX_CONVERSION_FAILED,
    PARSER_MESSAGE,
    WRITE_BACK_FAILED,
    STRING_REDEFINED,
    STRING_UNDEFINED,
    SYNTAX_ERROR,
    VENUE_MISSING,
    YEAR_INVALID,
    YEAR_MISSING,
    _Parser,
    bare_doi,
    build_links,
    build_venue,
    extract_note,
    parse_project_ids,
    parse_all_works,
    pdf_link,
)
from sslabdata.parsers.latex import unknown_commands


class TestBuildVenue:
    """One field name, two kinds of container: the entry type and the field order
    decide the venue. The corpus writes one entry per type, not their collisions."""

    def test_incollection_is_a_book_not_a_conference(self):
        """One field name, two kinds of container: the entry type decides."""
        venue = build_venue({"ENTRYTYPE": "incollection",
                             "booktitle": "Handbook of Robots"})
        assert venue.to_dict() == {"kind": "book", "name": "Handbook of Robots"}

    def test_misc_arxiv_without_a_prefix(self):
        venue = build_venue({"ENTRYTYPE": "misc", "eprint": "2301.12345"})
        assert venue.to_dict() == {"kind": "repository", "name": "arXiv"}

    def test_journal_wins_over_booktitle(self):
        """The precedence is the field order, so one entry gets one venue."""
        venue = build_venue({"ENTRYTYPE": "article", "journal": "J",
                             "booktitle": "B"})
        assert venue.name == "J"


class TestBareDoi:
    """Only registered resolver prefixes are stripped; stripping any other URL would
    corrupt an identifier. The corpus writes two spellings."""

    def test_written_as_a_dx_resolver_url(self):
        assert bare_doi("http://dx.doi.org/10.1/x") == "10.1/x"

    def test_some_other_url_is_left_alone(self):
        """Only the registered resolvers are stripped; nothing else is guessed."""
        assert bare_doi("https://example.org/10.1/x") == "https://example.org/10.1/x"


class TestBuildLinks:
    """A `url` is classified by its parsed host. Lookalike hosts (in a path, a query, a
    fragment, as userinfo, or with a malformed authority) must never become video
    links: an escape matrix too wide to write as fixtures."""

    def test_no_base_and_no_fields(self):
        assert build_links({}, "k", {}, None) == {}

    @pytest.mark.parametrize("url, kind", [
        ("https://www.youtube.com/watch?v=abc", "video"),
        ("https://youtu.be/abc", "video"),
        ("https://vimeo.com/123", "video"),
        ("https://player.vimeo.com/video/123", "video"),
        ("https://WWW.YouTube.COM:443/watch?v=abc", "video"),
        ("https://notyoutube.com/paper", "url"),
        ("https://youtube.com.example.org/paper", "url"),
        ("https://example.org/youtube.com/paper", "url"),
        ("https://example.org/?next=youtube.com", "url"),
        ("https://example.org/#vimeo.com", "url"),
        ("https://youtube.com@example.org/paper", "url"),
        ("https://[youtube.com/paper", "url"),
    ])
    def test_url_is_a_video_only_when_its_host_is_a_video_host(self, url, kind):
        links = build_links({"url": url}, "k", {}, None)
        assert [link.url for link in links[kind]] == [url]
        assert list(links) == [kind]


class TestPdfLink:
    """A remote `pdf_base_url` is labelled `unchecked`, because a build never fetches.

    Read as a local path, every remote PDF would be labelled `missing`. The
    conformance case for verifying a remote link (#20) is an expected
    failure, so only this test pins the `unchecked` label."""

    def test_a_remote_base_is_never_fetched(self):
        link = pdf_link("k", "https://example.org/pdfs")
        assert link.url == "https://example.org/pdfs/k.pdf"
        assert link.status == "unchecked"


class TestExtractNote:
    """Note text at its boundaries: a trailing period is dropped, and a blank note is
    no note."""

    def test_with_note(self):
        entry = {"note": "Best Paper Award."}
        assert extract_note(entry) == "Best Paper Award"

    def test_no_note(self):
        assert extract_note({}) is None
        assert extract_note({"note": ""}) is None
        assert extract_note({"note": "   "}) is None


class TestParseProjectIds:
    """The `project` field at its boundaries: brace-wrapped and empty values."""

    def test_braces(self):
        assert parse_project_ids({"project": "{gardenbot, planning}"}) == [
            "gardenbot", "planning"
        ]

    def test_empty(self):
        assert parse_project_ids({}) == []
        assert parse_project_ids({"project": ""}) == []


class TestParseAllWorks:
    """A work with no year sorts last, and its year is null rather than 0.

    The corpus asserts the missing-year diagnostic, not the position."""

    def test_a_work_with_no_year_sorts_last_and_says_so(self, tmp_path):
        """Null rather than 0: the position is the same, the meaning is not."""
        (tmp_path / "y.bib").write_text(
            "@article{no-year,\n  title = {No Year},\n"
            "  author = {Adams, Alice},\n  journal = {J}\n}\n"
            "@article{old,\n  title = {Old},\n"
            "  author = {Adams, Alice},\n  journal = {J},\n  year = {1999}\n}\n",
            encoding="utf-8")
        warnings = []
        works = parse_all_works(bib_dir=str(tmp_path),
                                bib_files=[{"name": "y.bib", "category": "T"}],
                                diagnostics=warnings)
        assert [w.bib_id for w in works] == ["old", "no-year"]
        assert works[-1].year is None
        assert len(warnings) == 1
        assert warnings[0].code == YEAR_MISSING
        assert "y.bib:no-year:year" in str(warnings[0])


class TestCrossref:
    """An entry carrying a crossref is rejected rather than resolved.

    Resolving it silently would emit a child with no author of its own. The
    corpus proves the fatal outcome of three fixtures; only this class sees the
    parse itself (the parent still compiles, no author-less work exists) and
    the field's case-insensitive spelling."""

    CHILD = ("@proceedings{a-parent,\n"
             "  title  = {Proceedings of the Fictional Workshop},\n"
             "  author = {Adams, Alice},\n"
             "  year   = {2024}\n"
             "}\n"
             "@inproceedings{a-child,\n"
             "  title    = {A Child Paper},\n"
             "  crossref = {a-parent}\n"
             "}\n")

    def parse(self, tmp_path, text, errors):
        (tmp_path / "child.bib").write_text(text, encoding="utf-8")
        return parse_all_works(
            bib_dir=str(tmp_path),
            bib_files=[{"name": "child.bib", "category": "Test Papers"}],
            diagnostics=errors)

    def test_the_child_is_rejected_and_the_parent_still_compiles(self, tmp_path):
        errors = []
        works = self.parse(tmp_path, self.CHILD, errors)
        assert [w.bib_id for w in works] == ["a-parent"]
        assert len(errors) == 1
        assert errors[0].code == CROSSREF_UNSUPPORTED
        assert "child.bib:a-child:crossref" in str(errors[0])
        assert "a-parent" in errors[0].message

    EMPTY = ("@inproceedings{empty-child,\n"
             "  title    = {A Child With an Empty Crossref},\n"
             "  author   = {Adams, Alice},\n"
             "  year     = {2024},\n"
             "  crossref = {}\n"
             "}\n")

    @pytest.mark.parametrize("field", ["crossref = {}", "crossref = {   }",
                                       "CROSSREF = {}"])
    def test_the_field_is_rejected_on_its_presence_not_on_its_value(self, tmp_path,
                                                                    field):
        """An empty crossref is a field the entry carries, so it is an error.

        pybtex keeps `crossref = {}` as a present field whose value is the
        empty string. Rejecting on the value would let it through and put the
        silent path back under a different spelling.
        """
        errors = []
        works = self.parse(tmp_path, self.EMPTY.replace("crossref = {}", field),
                           errors)
        assert works == []
        assert len(errors) == 1, errors
        assert errors[0].code == CROSSREF_UNSUPPORTED
        assert "child.bib:empty-child:crossref" in str(errors[0])

    def test_an_empty_crossref_is_not_reported_as_a_blank_parent(self, tmp_path):
        """The diagnostic says the entry names no parent rather than quoting one.

        Asserted on shape rather than on wording: a pair of empty quotes is a
        diagnostic that reads as though it had found a parent called "".
        """
        errors = []
        self.parse(tmp_path, self.EMPTY, errors)
        assert "''" not in errors[0].message and '""' not in errors[0].message, errors[0]
        # A named parent is still quoted, so the check above is about the
        # empty case and not about quoting in general.
        named = []
        self.parse(tmp_path, self.CHILD, named)
        assert "'a-parent'" in named[0].message, named[0]


class TestDuplicateCitationKeys:
    """Duplicate keys compare without case across files, and the first spelling is the
    one the diagnostic keeps."""

    def test_cross_file_duplicate_preserves_the_first_key_spelling(self, tmp_path):
        """Citation keys compare without case, but diagnostics retain both sources."""
        first = tmp_path / "first.bib"
        second = tmp_path / "second.bib"
        first.write_text(entry("FirstKey"), encoding="utf-8")
        second.write_text(entry("firstkey"), encoding="utf-8")

        errors = []
        parse_all_works(
            bib_dir=str(tmp_path),
            bib_files=[
                {"name": first.name, "category": "Test Papers"},
                {"name": second.name, "category": "Test Papers"},
            ],
            diagnostics=errors,
        )

        assert [str(e) for e in errors] == [
            f"{DUPLICATE_CITATION_KEY} {second}:firstkey:citation_key: "
            f"duplicate citation key; first defined in "
            f"{first}:FirstKey:citation_key"
        ]


def entry(key: str, title: str = "A Fictional Title") -> str:
    return (f"@article{{{key},\n"
            f"  title   = {{{title}}},\n"
            "  author  = {Adams, Alice},\n"
            "  journal = {Journal of Fictional Robots},\n"
            "  year    = {2024}\n"
            "}\n")


# Inputs around @comment handling. Each case names every key the file defines,
# split into the ones that must be read and the ones that must not: "the entry
# I named survives" would pass just as happily while a neighbour vanished or a
# commented-out entry leaked, which is how the quoted-value defect got through.
#
# sslabdata differs from pybtex on exactly one thing: a balanced @comment group
# is a comment, so entries inside it are not works. Everywhere else the
# expectations below are pybtex's own reading of the file.
#
# (label, source, keys that must be read, keys that must not be)
COMMENT_HAZARDS = [
    ("a balanced @comment block hides what is inside it",
     "@comment{not a publication: @article{hidden, title = {H}}}\n" + entry("kept"),
     {"kept"}, {"hidden"}),
    ("@comment spelled with a space before its brace",
     "@comment {@article{hidden, title = {H}}}\n" + entry("kept"),
     {"kept"}, {"hidden"}),
    ("@comment written with parentheses",
     "@comment(not a publication: @article{hidden, title = {H}})\n" + entry("kept"),
     {"kept"}, {"hidden"}),
    ("a % comment line that only mentions the command",
     "% Documentation mentions @comment{ syntax here\n" + entry("real"),
     {"real"}, set()),
    ("an @comment that never closes",
     "@comment{never closes\n" + entry("kept"),
     {"kept"}, set()),
    ("an unclosed brace inside @comment at the end of the file",
     entry("kept") + "@comment{x {unclosed\n",
     {"kept"}, set()),
    ("an @comment inside a braced field value",
     "@article{host, title = {Braces around @comment{x} keep it text},"
     " year = {2024}}\n" + entry("kept"),
     {"host", "kept"}, set()),
    ("an @comment inside a quoted field value",
     '@article{host, title = "Quotes around @comment{x} keep it text",'
     ' year = {2024}}\n' + entry("kept"),
     {"host", "kept"}, set()),
    ("a paren-delimited entry whose quoted value holds ) and a command",
     '@article(host,title="Host ) @comment(unclosed", author="Adams, Alice",'
     ' journal="J", year=2024)\n' + entry("real"),
     {"host", "real"}, set()),
    ("a % comment inside an entry body",
     "@article{host,\n  title = {T},  % a note to self\n  year  = {2024}\n}\n"
     + entry("kept"),
     {"host", "kept"}, set()),
    ("an unterminated quote at the end of the file",
     entry("kept") + '@article{broken, title = "never closed\n',
     {"broken", "kept"}, set()),
    ("an unclosed brace inside a quote at the end of the file",
     entry("kept") + '@article{broken, title = "a {b\n',
     {"broken", "kept"}, set()),
    ("an @ that starts no command",
     "@ not a command at all\n" + entry("kept"),
     {"kept"}, set()),
    ("a bare @ at the end of the file",
     entry("kept") + "\n@",
     {"kept"}, set()),
    # Braces are counted as pybtex counts them, which is BibTeX's own rule: a
    # brace is a brace whether it is escaped or quoted. These three pin that,
    # because the group then ends earlier than a reader might expect and what
    # follows is exposed — matching the library rather than second-guessing it.
    ("an escaped brace ends the group, as pybtex counts it",
     "@comment{ignored \\} " + entry("fake") + "}\n" + entry("real"),
     {"fake", "real"}, set()),
    ("a quoted closing brace ends the group, as pybtex counts it",
     '@comment{note "}" @article{hidden, title={H}}}\n' + entry("kept"),
     {"hidden", "kept"}, set()),
    ("a quoted opening brace keeps the group open, as pybtex counts it",
     '@comment{note "{" ignored}\n' + entry("kept"),
     {"kept"}, set()),
]


def read_source(tmp_path, source, name="hazard.bib"):
    (tmp_path / name).write_text(source, encoding="utf-8")
    return parse_all_works(
        bib_dir=str(tmp_path),
        bib_files=[{"name": name, "category": "Test Papers"}],
        diagnostics=[],
    )


class TestCommentHandling:
    """What a @comment group hides, and what it must never take with it.

    A comment group that swallows the entries after it loses works with no
    diagnostic. Each hazard is a distinct byte layout, too many to write as
    fixtures."""

    @pytest.mark.parametrize("label, source, present, absent",
                             COMMENT_HAZARDS,
                             ids=[case[0] for case in COMMENT_HAZARDS])
    def test_exactly_the_expected_entries_are_read(self, tmp_path, label, source,
                                                   present, absent):
        read = {pub.bib_id for pub in read_source(tmp_path, source)}
        assert read == present, label
        assert not (read & absent), label

    def test_a_quoted_value_does_not_end_a_paren_entry(self, tmp_path):
        """A ) inside "..." does not end an @article(...) entry.

        Were entry boundaries found by scanning the file rather than by the
        parser, the entry would lose every field and the entry after it would
        disappear.
        """
        source = ('@article(host,title="Host ) @comment(unclosed",'
                  ' author="Adams, Alice", journal="J", year=2024)\n' + entry("real"))
        works = {work.bib_id: work for work in read_source(tmp_path, source)}
        assert sorted(works) == ["host", "real"]
        host = works["host"]
        assert host.title == "Host ) @comment(unclosed"
        assert host.year == 2024
        assert [a.name for a in host.authors] == ["Alice Adams"]
        assert host.venue.name == "J"


class TestLatexFallback:
    """A field pylatexenc cannot read costs that field's markup, never the entry."""

    def test_the_entry_is_still_published(self, tmp_path):
        """End to end: the entry is read, with the raw text of the bad field."""
        found, works = located(tmp_path, entry("kept", title=r"Speed: \verb"))
        assert list(works) == ["kept"]
        assert works["kept"].title == r"Speed: \verb"
        assert works["kept"].year == 2024
        assert [a.name for a in works["kept"].authors] == ["Alice Adams"]
        [line] = found[LATEX_CONVERSION_FAILED]
        assert (line.key, line.field) == ("kept", "title")


class TestEntryFiltering:
    """pybtex raises SkipEntry for a filtered entry too, not only for @comment.

    sslabdata sets no `wanted_entries` filter, so no user input reaches this;
    the test keeps the SkipEntry recovery in `_Parser` from swallowing the entry
    after a filtered one, silently, if the filter is ever used."""

    REJECTED = "@article{drop, title = {D}, year = {2024}}\n"
    WANTED = "@article{keep, title = {K}, year = {2024}}\n"

    def parse(self, text):
        return _Parser(wanted_entries=["keep"]).parse_string(text)

    def test_a_filtered_entry_does_not_swallow_the_next_one(self):
        data = self.parse(self.REJECTED + "@article(keep, title = {K}, year = {2024})\n")
        assert list(data.entries) == ["keep"]

    def test_a_filtered_entry_does_not_swallow_a_preamble(self):
        data = self.parse(self.REJECTED + '@preamble("a preamble")\n' + self.WANTED)
        assert list(data.entries) == ["keep"]
        assert data.preamble == "a preamble"


def located(tmp_path, source, name="hazard.bib"):
    """The warnings one file produces, by code, and the works it yields."""
    (tmp_path / name).write_text(source, encoding="utf-8")
    warnings = []
    works = parse_all_works(bib_dir=str(tmp_path),
                            bib_files=[{"name": name, "category": "Test"}],
                            diagnostics=warnings)
    by_code = {}
    for warning in warnings:
        by_code.setdefault(warning.code, []).append(warning)
    return by_code, {work.bib_id: work for work in works}


class TestLocatedParserDiagnostics:
    """What the parser library finds is located at `<file>:<key>:<field>`.

    The corpus checks each finding's location from the CLI and that the entry
    is kept; this pairs it with the value the parser leaves behind (a null year
    or venue, a kept entry type) and covers spellings no fixture carries (`%`
    comment lines, a `:` in a citation key)."""

    def test_an_undefined_macro_inside_a_string_names_no_entry(self, tmp_path):
        found, _ = located(tmp_path, "@string{alias = nosuchmacro}\n" + entry("e"))
        [line] = found[STRING_UNDEFINED]
        assert str(line).startswith(f"{STRING_UNDEFINED} {tmp_path}/hazard.bib::: ")

    def test_an_error_inside_an_entry_before_any_field(self, tmp_path):
        found, _ = located(tmp_path, "@article{early, = {x}}\n" + entry("after"))
        [line] = found[SYNTAX_ERROR]
        assert f"{tmp_path}/hazard.bib:early::" in str(line)
        assert "after the value" not in line.message

    def test_text_outside_any_entry_is_located_at_the_file(self, tmp_path):
        found, works = located(tmp_path, "@article with no body\n" + entry("e"))
        [line] = found[SYNTAX_ERROR]
        assert f"{tmp_path}/hazard.bib::: " in str(line) and "line 1" in line.message
        assert list(works) == ["e"]

    @pytest.mark.parametrize("comment", [
        "% mentions @article in prose",
        "  % indented, and mentions @string{ too",
        "%@misc",
    ])
    def test_a_percent_comment_line_is_ignored(self, tmp_path, comment):
        found, works = located(tmp_path, f"{comment}\n" + entry("e"))
        assert found == {}
        assert list(works) == ["e"]

    def test_a_well_formed_command_on_a_percent_line_is_read(self, tmp_path):
        """A well-formed entry on a `%` line is an entry.

        The parser library has no `%` comment outside an entry, as classic
        BibTeX has none. Only a syntax error on such a line goes unreported;
        an entry lost to a `%` prefix would vanish without a diagnostic.
        """
        source = ("% @article{hidden, title = {H}, journal = {J}, year = 2024}\n"
                  + entry("visible"))
        found, works = located(tmp_path, source)
        assert found == {}
        assert sorted(works) == ["hidden", "visible"]

    def test_other_parser_messages_are_coded_in_the_librarys_words(self, tmp_path,
                                                                   capsys):
        """A repeated field and a name list the library cannot split are not
        syntax errors, and are not swallowed: each is located at its entry."""
        source = ("@article{twice, title = {A}, title = {B}, year = 2024}\n"
                  "@article{commas, title = {T}, author = {Brown, Bob, Jr, X},"
                  " journal = {J}, year = 2024}\n")
        found, works = located(tmp_path, source)
        assert SYNTAX_ERROR not in found
        twice, commas = found[PARSER_MESSAGE]
        assert (twice.file, twice.key, twice.field) == (
            f"{tmp_path}/hazard.bib", "twice", None)
        assert twice.message == "entry with key twice has a duplicate title field"
        assert commas.key == "commas" and "Too many commas" in commas.message
        assert capsys.readouterr().err == ""
        assert works["twice"].title == "A"

    def test_a_year_that_is_not_a_number_is_null(self, tmp_path):
        found, works = located(tmp_path, entry("e").replace("{2024}", "{in press}"))
        [line] = found[YEAR_INVALID]
        assert f"{tmp_path}/hazard.bib:e:year:" in str(line) and "in press" in line.message
        assert works["e"].year is None

    @pytest.mark.parametrize("entry_type, field", [
        ("article", "journal"), ("inproceedings", "booktitle")])
    def test_a_missing_container_is_named(self, tmp_path, entry_type, field):
        found, works = located(
            tmp_path, f"@{entry_type}{{e, title = {{T}}, year = 2024}}\n")
        [line] = found[VENUE_MISSING]
        assert f"{tmp_path}/hazard.bib:e:{field}:" in str(line)
        assert works["e"].venue is None

    @pytest.mark.parametrize("entry_type", [
        "book", "inbook", "manual", "misc", "proceedings", "conference",
        "incollection", "phdthesis", "mastersthesis", "techreport"])
    def test_a_type_with_no_required_container_is_not_reported(self, tmp_path,
                                                               entry_type):
        found, _ = located(tmp_path, f"@{entry_type}{{e, title = {{T}}, year = 2024}}\n")
        assert VENUE_MISSING not in found and ENTRY_TYPE_UNSUPPORTED not in found

    def test_an_undocumented_type_is_kept_and_named(self, tmp_path):
        found, works = located(tmp_path, "@booklet{e, title = {T}, year = 2024}\n")
        [line] = found[ENTRY_TYPE_UNSUPPORTED]
        assert f"{tmp_path}/hazard.bib:e:entry_type:" in str(line) and "@booklet" in line.message
        assert works["e"].entry_type == "booklet"

    def test_an_unknown_command_is_named_once_per_field(self, tmp_path):
        source = entry("e", title=r"\fictional{A} and \fictional{B}").replace(
            "{Adams, Alice}", r"{Adams\strange, Alice}")
        found, works = located(tmp_path, source)
        lines = found[LATEX_COMMAND_UNKNOWN]
        assert len(lines) == 2, lines
        assert any(":e:title:" in str(l) and "\\fictional" in l.message for l in lines)
        assert any(":e:author:" in str(l) and "\\strange" in l.message for l in lines)
        assert works["e"].title == "A and B"

    def test_a_citation_key_with_a_colon_keeps_its_parts(self, tmp_path):
        found, _ = located(tmp_path, entry("smith:2024").replace(
            "{A Fictional Title}", r"{\fictional{A}}"))
        [line] = found[LATEX_COMMAND_UNKNOWN]
        assert (line.file, line.key, line.field) == (
            f"{tmp_path}/hazard.bib", "smith:2024", "title")


class TestUnknownCommands:
    """Which LaTeX commands count as unknown, each named once and in order. The corpus
    holds one unknown macro; this holds the boundary between known and unknown."""

    def test_known_commands_math_and_links_are_not_reported(self):
        value = r"\textbf{a} \'e \v c $\alpha$ \href{http://x_y}{site} 50\%"
        assert unknown_commands(value) == []

    def test_xspace_is_unknown_so_it_never_silently_joins_words(self):
        assert unknown_commands(r"Foo\xspace bar") == ["xspace"]

    def test_each_unknown_command_is_named_once_in_order(self):
        assert unknown_commands(r"\zz{x} \yy \zz") == ["zz", "yy"]

    def test_empty_and_unreadable_values_yield_nothing(self, monkeypatch):
        assert unknown_commands("") == []
        import sslabdata.parsers.latex as latex

        def broken(*args, **kwargs):
            raise ValueError("unreadable")
        monkeypatch.setattr(latex, "LatexWalker", broken)
        assert unknown_commands(r"\anything") == []


class TestRedefinedStringSummary:
    """Every redefined @string macro of a run is reported in one line.

    One line per redefinition would bury a run in warnings, and a summary built
    per file would miss a macro redefined across files; the corpus has one file."""

    def run(self, tmp_path, files):
        for name, text in files.items():
            (tmp_path / name).write_text(text, encoding="utf-8")
        warnings = []
        parse_all_works(bib_dir=str(tmp_path), diagnostics=warnings,
                        bib_files=[{"name": n, "category": "C"} for n in files])
        return [w for w in warnings if w.code == STRING_REDEFINED]

    @staticmethod
    def sites(line, tmp_path):
        """The `<file>:<line>` sites a summary lists, in the order it lists them."""
        return re.findall(rf"{re.escape(str(tmp_path))}/\w+\.bib:\d+", str(line))

    def test_one_line_across_files_with_every_site(self, tmp_path):
        [line] = self.run(tmp_path, {
            "a.bib": "@string{b = 1}\n@string{a = 1}\n@string{B = 2}\n@string{b = 3}\n",
            "c.bib": "@string{a = 1}\n@string{a = 2}\n@string{once = 1}\n",
        })
        assert str(line).startswith(f"{STRING_REDEFINED} ::: ") and line.file is None
        assert "a, b" in line.message and "once" not in line.message
        assert self.sites(line, tmp_path) == [
            f"{tmp_path}/a.bib:3", f"{tmp_path}/a.bib:4", f"{tmp_path}/c.bib:2"]


class TestRedefinitionsFollowTheParser:
    """Only what the parser reads as an @string definition is counted.

    A commented-out definition, a BOM or CRLF line endings must neither add a
    false redefinition nor shift the reported line numbers."""

    def parse(self, tmp_path, data: bytes):
        path = tmp_path / "strings.bib"
        path.write_bytes(data)
        warnings = []
        works = parse_all_works(bib_dir=str(tmp_path), diagnostics=warnings,
                                bib_files=[{"name": "strings.bib", "category": "C"}])
        return str(path), warnings, {work.bib_id: work for work in works}

    def test_exact_lines_with_bom_crlf_comments_and_a_commented_definition(self, tmp_path):
        lines = [
            "% the @string definitions below give rss three values",
            '@comment{ @string{rss = "Commented"} }',
            '@string{rss = "One"}',
            "",
            '@string{RSS = "Two"}',
            '@string{rss = "Three"}',
            "@inproceedings{e, title = {T}, booktitle = rss, year = 2024}",
        ]
        data = b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8") + b"\r\n"
        path, warnings, works = self.parse(tmp_path, data)
        [line] = warnings
        assert str(line).startswith(f"{STRING_REDEFINED} {path}::: ") and "rss" in line.message
        assert re.findall(rf"{re.escape(path)}:\d+", str(line)) == [f"{path}:5", f"{path}:6"]
        assert works["e"].venue.name == "Three"

    def test_a_commented_out_and_a_real_definition_say_nothing(self, tmp_path):
        data = ('@comment{@string{x = "old"}}\n@string{x = "new"}\n'
                "@article{e, title = {T}, journal = x, year = 2024}\n").encode()
        _, warnings, works = self.parse(tmp_path, data)
        assert warnings == []
        assert works["e"].venue.name == "new"
