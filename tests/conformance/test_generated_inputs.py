"""Generated inputs: invariants every run keeps, whatever it is given.

The corpus pins the cases someone thought of. This test builds inputs nobody
wrote down -- `.bib` entries and `lab.yaml`, people, projects and
collaborators values -- from a fixed seed, runs each one through
``sslabdata.cli.main()`` with `--validate` and `--output` in both formats,
and checks what must hold for every input:

1. no run raises an uncaught exception;
2. a run that exits 0 writes a document that validates against
   `schema/v7/output.schema.json`, and the YAML and JSON documents hold the
   same data;
3. a run that exits 1 reports at least one coded diagnostic;
4. `--validate` exits 0 only where `--output` in the same format writes;
5. no text is silently lost: a sentinel word placed after special characters
   in a field value reaches that field's place in the document and the
   work's `bibtex`, which also carries each field value as written;
6. no input is silently read as something else: a year that is not an
   unsigned run of ASCII digits is not a number, an `eprint` is filed under
   the repository its entry names, `and others` is not an author, an award
   takes the year its `YYYY:` prefix wrote or else the work's, a prefix that
   is not a year stays in the award's name and is reported, an empty award is
   reported, a person's `bio` keeps every word and line break it was written
   with, in NFC and with no control character, its control characters are
   reported, a `bio` that is not a string is reported and emitted as null,
   an empty file path, a repeated YAML key or a path that is a
   directory is reported, and LaTeX conversion does not invent markup (`<`,
   `>`, `[`, `]`).

"Reported" means a coded diagnostic at the place: the key and field for a
work, the configuration key or the file. A run is deterministic, so the
failures are too; each distinct failure is reduced to a small input that
still shows it, and with SSLABDATA_GENERATED_FAILURES set the reduced inputs
and their outcomes are written there as JSON. tests/COVERAGE.md,
"Generated inputs", says how to reproduce and read it.
"""

import contextlib
import copy
import io
import json
import os
import random
import re
import shutil
import traceback
import unicodedata
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

import jsonschema
import yaml

import sslabdata
from sslabdata.cli import main

from .support import SCHEMA_PATH, working_dir, write_atomically

SEED = 143
CASES_ENV = "SSLABDATA_GENERATED_CASES"
DEFAULT_CASES = 1000
FAILURES_ENV = "SSLABDATA_GENERATED_FAILURES"
# Candidate inputs tried while reducing one failure, so a run on a broken
# tree stays bounded. A count, not a time, so the artifact is repeatable.
REDUCE_BUDGET = 400
# Distinct causes reported for one class of failure, at most.
CAUSES_PER_CLASS = 6

PACKAGE = Path(sslabdata.__file__).resolve().parent
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


# --- The input model -------------------------------------------------------------
#
# Inputs are held as data and written out as text, so that a failing input
# can be reduced one element at a time and every YAML shape can be written,
# repeated keys included, which a YAML dumper cannot.

@dataclass
class Raw:
    """YAML written as it is: `.nan`, `2010-01-01`, `!!set {a, b}`."""
    text: str


@dataclass
class Pair:
    key: object
    value: object


@dataclass
class Mapping:
    pairs: list


@dataclass
class Seq:
    items: list


@dataclass
class Sentinel:
    """Text that must reach the output: a word, or a name or a LaTeX command
    holding one. `form` is the name form it was written in, the command whose
    braced argument it is (`\\texttt`), or `text`."""
    word: str
    form: str


@dataclass
class Award(Sentinel):
    """One award of an `award` field, with the year prefix written before it:
    `year` for a prefix that is one, `malformed` for one that reads as a year
    and is not, `none` for no prefix, or text braces protect."""
    kind: str = "none"
    prefix: str = ""


def bare_words(p: Sentinel) -> list:
    """The sentinel words themselves, without the name or command around
    them: one, or one per braced argument of a command."""
    return re.findall(r"(?<![\\A-Za-z])[Zz]q[a-z]+", p.word)


@dataclass
class Field:
    name: str
    parts: list            # strings and Sentinels, joined by `joiner`
    delim: str = "{"       # "{", '"', or "" for a bare value
    joiner: str = " "


@dataclass
class Entry:
    type: str
    key: str
    fields: list


@dataclass
class Case:
    config: list           # [Pair], lab.yaml, one key per line
    bibs: dict             # file path -> [Entry]
    data: dict             # file path -> [record] or Raw (the whole text)


# Directories every case has, so a path can name a directory that exists.
DIRS = ("sub", "pdfs")


def yaml_text(value) -> str:
    if isinstance(value, Raw):
        return value.text
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{yaml_text(p.key)}: {yaml_text(p.value)}"
                               for p in value.pairs) + "}"
    if isinstance(value, Seq):
        return "[" + ", ".join(yaml_text(v) for v in value.items) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value)


def value_text(f: Field) -> str:
    return f.joiner.join(p.word if isinstance(p, Sentinel) else p for p in f.parts)


def bib_text(entries) -> str:
    out = []
    for e in entries:
        body = ",\n".join(f"  {f.name} = {_delimited(f)}" for f in e.fields)
        out.append(f"@{e.type}{{{e.key},\n{body}\n}}\n")
    return "\n".join(out)


def _delimited(f: Field) -> str:
    text = value_text(f)
    return {"{": f"{{{text}}}", '"': f'"{text}"', "": text}[f.delim]


def files_of(case: Case) -> dict:
    """Every file of the case, by path, as text."""
    files = {"lab.yaml": "".join(f"{yaml_text(p.key)}: {yaml_text(p.value)}\n"
                                 for p in case.config)}
    for path, entries in case.bibs.items():
        files[path] = bib_text(entries)
    for path, records in case.data.items():
        files[path] = (records.text if isinstance(records, Raw) else
                       "".join(f"- {yaml_text(r)}\n" for r in records))
    return files


def materialize(case: Case, where: Path) -> None:
    if where.exists():
        shutil.rmtree(where)
    for d in DIRS:
        (where / d).mkdir(parents=True)
    (where / "pdfs" / "k1.pdf").write_bytes(b"%PDF-1.4\n")
    for path, text in files_of(case).items():
        (where / path).parent.mkdir(parents=True, exist_ok=True)
        (where / path).write_text(text, encoding="utf-8")


# --- Generating inputs -----------------------------------------------------------

# Field-value pieces, by what they exercise. Each is placed before a
# sentinel word, so a piece that swallows the rest of a value shows.
SNIPPETS = {
    "escaped": [r"\%", r"20\% gain", r"\&", r"R\&D", r"\#", r"\_", r"\$",
                r"\~{}", r"\^{}", r"\textbackslash{}", r"\{\}"],
    "bare": ["%", "50% off", "&", "A & B", "#", "C#", "_", "snake_case", "$",
             "~", "a~b", "^", "\\", "a\\1"],
    "unbalanced": ["{", "}", "\\{", "\\}", "{a}}", "{{a}"],
    "known": [r"\textbf{bold}", r"\emph{it}", r"\'e", r"\"o", r"{\ss}",
              r"\c{c}", r"\TeX{}", r"\LaTeX{}", r"\emdash", "--", "---",
              r"\textsuperscript{2}", r"{\o}", r"\v{s}", r"\ldots", "``q''"],
    "unknown": [r"\foo{bar}", r"\frobnicate", r"\cite{k}", r"\footnote{n}",
                r"\newcommand", r"\begin{itemize}\item x\end{itemize}",
                r"\verb|x|"],
    "link": [r"\url{https://x.org/a%20b_c}", r"\url{https://x.org/~u/#f}",
             r"\href{https://x.org/a_b%20c}{site}", r"\href{https://x.org}{}",
             r"\href{https://x.org/x}", "https://x.org/q?a=1&b=2"],
    "math": ["$x^2_i$", r"$\alpha$", r"\(a+b\)", "$$E=mc^2$$", r"\[x\]",
             "$a % b$", r"$50\%$"],
    "unicode": ["café", "e\u0301", "שלום", "مرحبا", "a\u200fb", "a\u200bb",
                "a\u200db", "😀", "ﬁ", "中文", "Ω", "Ä"],
    "space": ["\n", "\t", "  "],
    "other": ["@", "user@example.org", '"q"', "'s", "<b>x</b>", "[x](y)",
              "**b**", ",", "=", "0"],
}

# The snippets a generated `bio` is made of: plain text, not BibTeX. The
# control characters are written as YAML escapes, since a raw one is not YAML.
BIO_GROUPS = ["bare", "unicode", "space", "other", "known"]
CONTROLS = ["\x00", "\x01", "\x08", "\x0b", "\x1f"]
_CONTROL_IN_TEXT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Sentinel words are also placed inside the braced arguments of LaTeX
# commands, as `\cmd{word}`, so that text lost with an argument shows.
#
# Commands whose argument is the text itself, in another face or box or as a
# document's title, author or date: SPEC.md section 2 keeps the argument as
# plain text. A generated unknown name keeps
# its braced argument too (LATEX-COMMAND-UNKNOWN, issue #174).
KEEPS_ARGUMENT = (r"\texttt", r"\textsf", r"\textsc", r"\emph", r"\underline",
                  r"\mbox", r"\hbox", r"\fbox", r"\title", r"\author",
                  r"\date")
# The only commands whose arguments may leave nothing in the document, with
# the number of braced arguments LaTeX gives each. This is SPEC.md section 2,
# written out here rather than imported so that it checks the code: the rules
# that emit "nothing" (`\cite` ... `\includegraphics`), then the citations,
# labels and cross-references, then the settings whose arguments are not text.
# A word inside one must still reach the work's `bibtex`, and the text after
# it must survive. `\nopagecolor` takes no argument, so a braced group after
# it is text and must survive.
DROPS_ARGUMENT = {
    r"\cite": 1, r"\citep": 1, r"\citet": 1, r"\ref": 1, r"\autoref": 1,
    r"\cref": 1, r"\Cref": 1, r"\eqref": 1, r"\includegraphics": 1,
    r"\citealp": 1, r"\citealt": 1, r"\citeauthor": 1, r"\citefullauthor": 1,
    r"\citenum": 1, r"\citeyear": 1, r"\citeyearpar": 1, r"\citepalias": 1,
    r"\citetalias": 1, r"\Citealp": 1, r"\Citealt": 1, r"\Citeauthor": 1,
    r"\Citep": 1, r"\Citet": 1, r"\nocite": 1, r"\label": 1, r"\pageref": 1,
    r"\nameref": 1,
    r"\color": 1, r"\colorlet": 2, r"\definecolor": 3, r"\providecolor": 3,
    r"\pagecolor": 1, r"\nopagecolor": 0, r"\rowcolors": 3,
    r"\documentclass": 1, r"\usepackage": 1, r"\RequirePackage": 1,
    r"\bibliography": 1, r"\hypersetup": 1, r"\selectlanguage": 1,
    r"\setcounter": 2, r"\addcounter": 2, r"\setlength": 2, r"\addlength": 2,
    r"\defcitealias": 2, r"\hphantom": 1, r"\vphantom": 1,
}
# The form every generated command name is recorded under, so that they are
# one cause when a failure is reduced.
GENERATED_COMMAND = r"\<generated>"


def drops(form: str) -> bool:
    """Whether a sentinel's words may be missing from the document."""
    return DROPS_ARGUMENT.get(form, 0) > 0

# An unbalanced brace changes where a value ends, so the rest of its entry
# reads differently; it is drawn rarely enough that most entries have none.
GROUP_WEIGHTS = {"unbalanced": 0.15}

TEXT_FIELDS = ("title", "abstract", "note", "journal", "booktitle", "school",
               "institution", "publisher", "series", "address",
               "organization", "type")
RAW_FIELDS = ("volume", "number", "pages", "edition", "chapter", "month",
              "howpublished")
CONTAINERS = ("journal", "booktitle", "school", "institution")

YEARS = ["2020", "1999", "02020", " 2021 ", "-5", "0", "99999999999999999999",
         "２０２０", "٢٠٢٠", "+2020", "2_020", "2020a", "{2020}", "", "  ",
         "1e3", "MMXX", "20 20", "-0"]

# The repository each `archivePrefix` / `eprinttype` value names, as the
# identifier scheme it should give; a blank value names none.
REPOSITORIES = {"arXiv": "arxiv", "{arXiv}": "arxiv", "ARXIV": "arxiv",
                "hal": "hal", "HAL": "hal", "pubmed": "pubmed", "": None,
                "  ": None}

# What an award may start with, and what sslabdata must read it as: the year
# prefix is four ASCII digits, a colon and whitespace (SPEC.md section 5).
AWARD_PREFIXES = [
    ("", "none"), ("", "none"), ("2026: ", "year"), ("1999:\n", "year"),
    ("0042:  ", "year"), ("26: ", "malformed"), ("2026 ", "malformed"),
    ("2026:", "malformed"), ("2026 : ", "malformed"), ("20261: ", "malformed"),
    ("\uff12\uff10\uff12\uff16: ", "malformed"), ("{2026}: ", "none"),
]
# The separators between awards, and the awards that are empty.
AWARD_JOINERS = [" and ", " AND ", "\nand ", " And\t"]
EMPTY_AWARDS = ["", " ", "{}"]

NAME_FORMS = [
    ("plain", "Ann {S}"), ("comma", "{S}, Ann"), ("jr", "{S}, Jr., Ann"),
    ("von", "Ann van der {S}"), ("von-comma", "van {S}, Ann"),
    ("literal", "{{{S} Consortium}}"), ("accent", "{{\\'E}}mile {S}"),
    ("initials", "A. B. {S}"), ("unicode", "José {S}"), ("star", "Ann {S}*"),
    ("mononym", "{S}"), ("braced-family", "Ann {{{S}}}"),
    ("cyrillic", "Мария {S}"), ("spaced", "  Ann   {S}  "),
    ("tex-star", "Ann {S}\\textsuperscript{{*}}"),
]


class Generator:
    def __init__(self, index: int):
        self.r = random.Random(f"{SEED}:{index}")
        # Most cases keep lab.yaml and the data files well formed, so that
        # the run writes a document and the .bib values are checked in it;
        # the rest draw every configuration value from the whole range.
        self.hostile = self.r.random() < 0.3
        self.used = set()
        self.names = []    # plain author names, for people and collaborators
        # Awards are drawn from their own stream (`award_field`), and so
        # are bios (`bio`).
        self.ra = random.Random(f"{SEED}:{index}:award")
        self.rb = random.Random(f"{SEED}:{index}:bio")

    def word(self, capital=False) -> str:
        while True:
            w = "zq" + "".join(self.r.choice("bcdfghjkmnpqrstvwx")
                               for _ in range(6))
            if w not in self.used:
                self.used.add(w)
                return w.capitalize() if capital else w

    def pick(self, weighted, config=False):
        """One value from [(weight, value)]; a callable value is called. A
        configuration value is the first, well-formed one unless the case is
        hostile."""
        if config and not self.hostile:
            weighted = weighted[:1]
        total = sum(w for w, _ in weighted)
        x = self.r.uniform(0, total)
        for w, v in weighted:
            x -= w
            if x <= 0:
                break
        return v() if callable(v) else v

    # BibTeX -------------------------------------------------------------------

    def text(self, delim) -> list:
        r = self.r
        if r.random() < 0.06:
            return [r.choice(["", "  ", "\n"])]
        parts = []
        for _ in range(r.randint(0, 3)):
            group = r.choices(list(SNIPPETS),
                              [GROUP_WEIGHTS.get(g, 1) for g in SNIPPETS])[0]
            snippet = r.choice(SNIPPETS[group])
            if delim == '"' and '"' in snippet:
                continue
            parts.append(snippet)
        if r.random() < 0.3:
            parts.insert(r.randint(0, len(parts)), self.in_command())
        return parts + [Sentinel(self.word(), "text")]

    def in_command(self) -> Sentinel:
        """Sentinel words as the braced arguments of a LaTeX command: one
        each, or one for a command that takes none."""
        r = self.r
        kind = r.choice(["keeps", "keeps", "drops", "drops", "generated"])
        if kind == "generated":
            # `zq` starts no real command, so the name is surely unknown.
            name = "\\zq" + "".join(r.choice("bcdfghjkmnpqrstvwxyz")
                                    for _ in range(r.randint(1, 6)))
            return Sentinel(f"{name}{{{self.word()}}}", GENERATED_COMMAND)
        if kind == "keeps":
            command, count = r.choice(KEEPS_ARGUMENT), 1
        else:
            command = r.choice(sorted(DROPS_ARGUMENT))
            count = max(DROPS_ARGUMENT[command], 1)
        return Sentinel(command + "".join(f"{{{self.word()}}}"
                                          for _ in range(count)), command)

    def names_field(self, name) -> Field:
        r = self.r
        parts = []
        for _ in range(r.randint(1, 4)):
            label, form = r.choice(NAME_FORMS)
            w = self.word(capital=True)
            parts.append(Sentinel(form.format(S=w), f"name {label}"))
            if label in ("plain", "initials", "unicode"):
                self.names.append(form.format(S=w).strip())
        if r.random() < 0.25:
            parts.insert(r.randint(0, len(parts)), "others")
        if r.random() < 0.05:
            parts.insert(r.randint(0, len(parts)), r.choice(["", " "]))
        return Field(name, parts, joiner=" and ")

    def entry(self, key, projects) -> Entry:
        r = self.r
        etype = r.choice(["article", "inproceedings", "misc", "book",
                          "phdthesis", "techreport", "incollection",
                          "unpublished", "online", "ARTICLE"])
        fs = [self.names_field("author")]
        if r.random() < 0.15:
            fs.append(self.names_field("editor"))
        fs.append(Field("title", self.text("{")))
        if r.random() < 0.95:
            y = r.choice(YEARS)
            fs.append(Field("year", [y], "" if y.isascii() and y.isdigit()
                            and r.random() < 0.3 else "{"))
        for name in r.sample(CONTAINERS, r.randint(0, 2)):
            delim = r.choice(["{", "{", '"'])
            fs.append(Field(name, self.text(delim), delim))
        for name in r.sample(TEXT_FIELDS[:3] + TEXT_FIELDS[7:],
                             r.randint(0, 3)):
            if name != "title":
                fs.append(Field(name, self.text("{")))
        for name in r.sample(RAW_FIELDS, r.randint(0, 2)):
            fs.append(Field(name, self.text("{")))
        if r.random() < 0.4:
            fs.append(Field("doi", self.pick([
                (4, lambda: ["10.1234/" + self.word()]),
                (1, lambda: ["https://doi.org/10.1/" + self.word()]),
                (1, lambda: ["HTTPS://DX.DOI.ORG/10.1/" + self.word()]),
                (1, lambda: ["doi:10.1/" + self.word()]),
                (1, lambda: ["10.1/a%20b_" + self.word()]),
                (1, ["https://doi.org/"]), (1, ["http://dx.doi.org/"]),
                (1, ["  "]), (1, [""])])))
        if r.random() < 0.4:
            fs.append(Field("url", self.pick([
                (3, lambda: ["https://example.org/" + self.word()]),
                (1, lambda: ["https://x.org/a%20b_c#" + self.word()]),
                (1, lambda: ["https://youtu.be/" + self.word()]),
                (1, lambda: ["https://evil.org/youtube.com/" + self.word()]),
                (1, lambda: ["javascript:" + self.word()]),
                (1, lambda: ["example.org/" + self.word()]),
                (1, lambda: ["https://x.org/?q=a&b=" + self.word()]),
                (1, ["  "]), (1, [""])])))
        if r.random() < 0.1:
            fs.append(Field(r.choice(["video", "pdf"]),
                            ["https://x.org/" + self.word()]))
        if r.random() < 0.35:
            fs.append(Field("eprint", self.pick([
                (3, lambda: ["2101." + self.word()]),
                (2, lambda: ["hal-" + self.word()]),
                (1, lambda: ["  " + self.word() + "  "]),
                (1, ["  "]), (1, [""])])))
            for name in ("archivePrefix", "eprinttype"):
                if r.random() < 0.45:
                    fs.append(Field(name, [r.choice(list(REPOSITORIES))]))
        if r.random() < 0.1:
            fs.append(Field("isbn", [r.choice(["978-3-16-148410-0", "", "  "])]))
        if projects and r.random() < 0.3:
            ids = r.sample(projects + ["missing", ""], r.randint(1, 2))
            fs.append(Field("project", ids, joiner=", "))
        if r.random() < 0.05:
            fs.append(copy.deepcopy(r.choice(fs)))
        if r.random() < 0.05:
            fs[0], fs[-1] = fs[-1], fs[0]
        if self.ra.random() < 0.3:
            # Never last, as the other text fields are not: a brace the
            # value closes too early then shows in the field after it.
            # Until #211, a mismatch that ends the last field is not reported.
            fs.insert(self.ra.randint(0, len(fs) - 1), self.award_field())
        return Entry(etype, key, fs)

    def award_field(self) -> Field:
        """An `award` field, drawn from a stream of its own so that adding it
        leaves every other generated value as it was."""
        r, self.r = self.r, self.ra
        try:
            items = [self.award() for _ in range(self.r.randint(1, 3))]
            return Field("award", items, joiner=self.r.choice(AWARD_JOINERS))
        finally:
            self.r = r

    def award(self):
        r = self.r
        if r.random() < 0.1:
            return r.choice(EMPTY_AWARDS)
        prefix, kind = r.choice(AWARD_PREFIXES)
        sentinel = (self.in_command() if r.random() < 0.3
                    else Sentinel(self.word(), "award"))
        # A prefix with no space after it is followed by the name at once,
        # so that whitespace cannot turn it into a year prefix.
        pieces = [] if prefix == "2026:" else [
            r.choice(SNIPPETS[g]) for g in r.choices(
                list(SNIPPETS), [GROUP_WEIGHTS.get(g, 1) for g in SNIPPETS],
                k=r.randint(0, 2))]
        text = " ".join(pieces + [sentinel.word])
        if r.random() < 0.2:
            text = f"{{{text} and {self.word()}}}"
        return Award(prefix + text, sentinel.form, kind, prefix)

    # YAML ---------------------------------------------------------------------

    def odd(self, p) -> bool:
        """A malformed configuration choice, made only in a hostile case."""
        return self.hostile and self.r.random() < p

    def repeat_a_key(self, pairs) -> None:
        if pairs and self.r.random() < 0.05:
            first = self.r.choice(pairs)
            again = (self.r.choice(["other value", Raw("5"), Raw("null")])
                     if self.hostile else
                     "other value" if isinstance(first.value, str) else
                     copy.deepcopy(first.value))
            pairs.append(Pair(first.key, again))

    def lab(self):
        r = self.r
        pool = [
            lambda: Pair("name", self.pick([(6, "Corpus Lab"), (1, ""),
                                            (1, Raw("5")), (1, Raw("null")),
                                            (1, "Lab & Co. 50% \u200f")])),
            lambda: Pair("description", "Robots " + r.choice(SNIPPETS["unicode"])),
            lambda: Pair("website", r.choice(["https://example.org", ""])),
            lambda: Pair("email", "lab@example.org"),
            lambda: Pair("institution", r.choice(["Example U", Raw("[a]")])),
            lambda: Pair("links", self.pick([
                (3, Mapping([Pair("github", "https://github.com/x")])),
                (1, "not a map"),
                (1, Mapping([Pair("since", Raw("2010-01-01"))])),
                (1, Mapping([Pair(Raw("2019"), "x")]))])),
            lambda: Pair("founded", Raw(r.choice(["2010-01-01", "2010-1-1",
                                                  "!!timestamp 2001-12-14"]))),
            lambda: Pair("updated", Raw(r.choice(["2024-05-01T09:30:00Z",
                                                  "2024-05-01 09:30:00"]))),
            lambda: Pair("ratio", Raw(r.choice([".nan", ".inf", "-.inf", "1e400",
                                                "-0.0", "1.5", ".NaN"]))),
            lambda: Pair("tags", r.choice([Raw("!!set {a, b}"), Seq(["a", "b"]),
                                           Raw("!!omap [a: 1]")])),
            lambda: Pair("nested", Mapping([Pair("a", Mapping([Pair("b", Seq(
                [1, 2.5, True, None, Raw("2010-01-01"), Raw(".inf")]))]))])),
            lambda: Pair(Raw(r.choice(["2019", "true", "null", "1.5",
                                       "2010-01-01", "[1, 2]"])), "x"),
            lambda: Pair("blob", Raw("!!binary aGVsbG8=")),
            lambda: Pair("big", Raw("123456789012345678901234567890")),
            lambda: Pair("flags", Raw(r.choice(["0o17", "yes", "~", "0x1F",
                                                "!!python/tuple [1, 2]"]))),
            lambda: Pair("text", "a " + r.choice(SNIPPETS["bare"])),
        ]
        if not self.hostile:
            pool = [
                lambda: Pair("name", "Corpus Lab"),
                lambda: Pair("description", "Robots " + r.choice(SNIPPETS["unicode"])),
                lambda: Pair("website", "https://example.org"),
                lambda: Pair("links", Mapping([Pair("github", "https://github.com/x")])),
                lambda: Pair("founded", Raw("2010-01-01")),
                lambda: Pair("updated", Raw("2024-05-01T09:30:00Z")),
                lambda: Pair("nested", Mapping([Pair("a", Seq([1, 2.5, True, None]))])),
                lambda: Pair("text", "a " + r.choice(SNIPPETS["bare"])),
            ]
        pairs = [f() for f in r.sample(pool, r.randint(0, min(5, len(pool))))]
        self.repeat_a_key(pairs)
        return self.pick([(20, Mapping(pairs)), (1, Raw("null")),
                          (1, "a string"), (1, Seq(["a"]))], config=True)

    def path(self, name):
        if not self.hostile:
            return self.pick([(12, name), (3, None), (1, "")])
        return self.pick([(6, name), (3, None), (1, ""), (1, "  "), (1, "."),
                          (1, "sub"), (1, "sub/"), (1, "missing.yaml"),
                          (1, Raw("null")), (1, Raw("5"))])

    def person(self, i, ids):
        r = self.r
        pid = self.pick([(12, f"p{i}"), (1, ""), (1, Raw("5")),
                         (1, lambda: r.choice(ids) if ids else "p0"),
                         (1, "ümlaut")], config=True)
        name = (r.choice(self.names) if self.names and r.random() < 0.7
                else "Ann " + self.word(capital=True))
        pairs = [Pair("id", pid), Pair("name", self.pick(
            [(12, name), (1, ""), (1, Raw("null")), (1, Raw("5"))], config=True))]
        if r.random() < 0.5:
            pairs.append(Pair("role", self.pick([(5, "phd_student"), (1, ""),
                                                 (1, Raw("5"))], config=True)))
        if r.random() < 0.5:
            pairs.append(Pair("status", self.pick([(1, "current"), (1, "alumni"),
                                                   (1, "bogus"), (1, Raw("5"))],
                                                  config=True)))
        if r.random() < 0.3:
            pairs.append(Pair(r.choice(["start_year", "end_year"]), Raw(self.pick(
                [(1, "2020"), (1, "2020.0"), (1, "true"), (1, "-1"), (1, "'2020'"),
                 (1, "99999999999999999999"), (1, "2020-01-01")], config=True))))
        if r.random() < 0.3:
            pairs.append(Pair("aliases", self.pick([
                (1, Seq(["A. " + name.split()[-1]])), (1, "A. Able"), (1, Seq([""])),
                (1, Seq([Raw("5")]))], config=True)))
        if r.random() < 0.2:
            pairs.append(Pair(r.choice(["website", "email", "photo", "degree"]),
                              self.pick([(1, "https://x.org"), (1, ""), (1, Raw("5"))],
                                        config=True)))
        if self.odd(0.2):
            pairs.append(Pair(r.choice(["webiste", Raw("1"), Raw("true")]), "x"))
        bio = self.bio()
        if bio is not None:
            pairs.append(Pair("bio", bio))
        self.repeat_a_key(pairs)
        return Mapping(pairs)

    def bio(self):
        """A person's `bio`, or None for none, drawn from a stream of its own
        so that adding it leaves every other generated value as it was."""
        r, self.r = self.r, self.rb
        try:
            rb = self.r
            if rb.random() < 0.5:
                return None
            if self.odd(0.3):
                return rb.choice([Raw("5"), Raw("true"), Raw("null"), Seq(["a"]),
                                  Mapping([Pair("a", "b")])])
            if rb.random() < 0.1:
                return rb.choice(["", "  ", "\n"])
            lines = []
            for _ in range(rb.randint(1, 3)):
                pieces = [rb.choice(SNIPPETS[g]) for g in rb.choices(
                    BIO_GROUPS, k=rb.randint(0, 3))]
                if rb.random() < 0.2:
                    pieces.insert(rb.randint(0, len(pieces)), rb.choice(CONTROLS))
                lines.append(" ".join(pieces + [self.word()]))
            return rb.choice(["\n", "\n\n", "\r\n", " "]).join(lines)
        finally:
            self.r = r

    def project(self, pid):
        r = self.r
        pairs = [Pair("id", pid), Pair("title", self.pick(
            [(10, "Project " + self.word()), (1, ""), (1, Raw("5"))], config=True))]
        if r.random() < 0.5:
            pairs.append(Pair("status", self.pick(
                [(1, "active"), (1, "completed"), (1, "bogus"), (1, Raw("5"))],
                config=True)))
        if r.random() < 0.4:
            pairs.append(Pair(r.choice(["description", "website", "image"]),
                              self.pick([(1, "text " + self.word()), (1, ""),
                                         (1, Raw("5"))], config=True)))
        self.repeat_a_key(pairs)
        return Mapping(pairs)

    def collaborator(self):
        name = (self.r.choice(self.names) if self.names and self.r.random() < 0.7
                else "Cy " + self.word(capital=True))
        pairs = [Pair("name", self.pick([(10, name), (1, ""), (1, Raw("5"))],
                                        config=True))]
        if self.r.random() < 0.3:
            pairs.append(Pair("aliases", Seq(["C. " + name.split()[-1]])))
        self.repeat_a_key(pairs)
        return Mapping(pairs)

    def records_file(self, make, count):
        return self.pick([(20, lambda: [make(i) for i in range(count)]),
                          (1, Raw("")), (1, Raw("just text\n")),
                          (1, Raw("{a: 1}\n")), (1, Raw("- [unclosed\n")),
                          (1, Raw("- x\n- y\n"))], config=True)

    def case(self) -> Case:
        r = self.r
        in_sub = r.random() < 0.15
        bib_dir = self.pick([(16, "bib" if in_sub else "."), (1, ""),
                             (1, "./"), (1, Raw("5")), (1, None)], config=True)
        prefix = "bib/" if in_sub else ""
        projects = [f"proj{i}" for i in range(r.randint(0, 3))]

        bibs, keys = {}, []
        for f in range(r.choice([1, 1, 1, 2])):
            entries = []
            for _ in range(r.randint(1, 3)):
                key = f"k{len(keys) + 1}"
                if keys and r.random() < 0.08:
                    key = r.choice(keys)
                elif r.random() < 0.1:
                    key = r.choice(["Key_1", "k:1", "ключ1", "k.1/x", "K1", "k-1"])
                keys.append(key)
                entries.append(self.entry(key, projects))
            bibs[f"{prefix}{'ab'[f]}.bib"] = entries

        bib_files = [Mapping([Pair("name", Path(p).name),
                              Pair("category", self.pick([(10, "Papers"), (1, ""),
                                                          (1, Raw("5"))], config=True))])
                     for p in bibs]
        if self.odd(0.2):
            bib_files.append(Mapping([Pair("name", r.choice([".", "sub", "missing.bib",
                                                             "", "a.bib "])),
                                      Pair("category", "X")]))

        config = []
        if not self.odd(0.1):
            config.append(Pair("lab", self.lab()))
        if bib_dir is not None:
            config.append(Pair("bib_dir", bib_dir))
        config.append(Pair("bib_files", Seq(bib_files)))
        if r.random() < 0.1:
            config.append(Pair("site", Mapping([Pair("url", "https://example.org")])))
        data = {}
        for key, name, make, count in (
                ("people_file", "people.yaml",
                 lambda i: self.person(i, [f"p{j}" for j in range(i)]), r.randint(0, 4)),
                ("projects_file", "projects.yaml",
                 lambda i: self.project(projects[i]), len(projects)),
                ("collaborators_file", "collaborators.yaml",
                 lambda i: self.collaborator(), r.randint(0, 2))):
            value = self.path(name)
            if value is not None:
                config.append(Pair(key, value))
            if value == name:
                data[name] = self.records_file(make, count)
        pdf = self.pick([(10, None), (4, "pdfs"), (2, "https://x.org/p/"), (1, ""),
                         (1, "http://"), (1, "pdfs/"), (1, Raw("5"))]
                        if self.hostile else [(10, None), (4, "pdfs"),
                                              (2, "https://x.org/p/")])
        if pdf is not None:
            config.append(Pair("pdf_base_url", pdf))
        if self.odd(0.1):
            config.append(Pair("people_fil", "x"))
        self.repeat_a_key(config)
        r.shuffle(config)
        return Case(config, bibs, data)


# --- Running a case ---------------------------------------------------------------

MODES = [("validate", "json"), ("validate", "yaml"),
         ("output", "json"), ("output", "yaml")]
CODED = r"[A-Z]+(?:-[A-Z]+)+ "


def run(args, cwd: Path) -> dict:
    """One in-process run: exit code, streams, and any uncaught exception
    with the last sslabdata frame it passed through."""
    out, err = io.StringIO(), io.StringIO()
    result = {"exit": 0, "crash": None}
    with working_dir(cwd), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            main(args)
        except SystemExit as e:
            result["exit"] = e.code if isinstance(e.code, int) else (e.code is not None)
        except Exception as e:  # noqa: BLE001 - a crash is a result to report
            frames = [f for f in traceback.extract_tb(e.__traceback__)
                      if Path(f.filename).resolve().is_relative_to(PACKAGE)]
            at = (f"{Path(frames[-1].filename).resolve().relative_to(PACKAGE.parent)}:"
                  f"{frames[-1].lineno}" if frames else "?")
            result["crash"] = {"type": type(e).__name__, "at": at,
                               "message": str(e).replace(str(cwd), "<case>")}
    result["stdout"], result["stderr"] = out.getvalue(), err.getvalue()
    return result


def observe(where: Path) -> dict:
    seen = {}
    for mode, fmt in MODES:
        if mode == "validate":
            seen[f"validate-{fmt}"] = run(["--config", "lab.yaml", "--validate",
                                           "--format", fmt], where)
        else:
            out = where / f"_out.{fmt}"
            got = run(["--config", "lab.yaml", "--format", fmt, "--output",
                       out.name], where)
            got["document"] = None
            if got["exit"] == 0 and got["crash"] is None and out.exists():
                text = out.read_text(encoding="utf-8")
                got["document"] = json.loads(text) if fmt == "json" else yaml.safe_load(text)
            seen[f"output-{fmt}"] = got
    try:
        seen["records"] = json.loads(seen["validate-json"]["stdout"])
    except ValueError:
        seen["records"] = None
    return seen


# --- The invariants -------------------------------------------------------------

def check(case: Case, seen: dict, where: Path) -> list:
    """Every violation of the invariants, as (class, detail, evidence). The
    class names the failure without the case's own words, so equal failures
    group; the evidence is the input pieces a text failure involved, so that
    one class can be reduced once per distinct cause."""
    found = []

    def fail(cls, detail, evidence=()):
        found.append((cls, detail, frozenset(evidence)))

    # 1. No uncaught exception, and no exit status but 0 or 1.
    for mode, got in seen.items():
        if mode == "records":
            continue
        if got["crash"]:
            c = got["crash"]
            fail(f"1 crash: {c['type']} at {c['at']}", f"{mode}: {c['message']}")
        elif got["exit"] not in (0, 1):
            fail(f"1 exit {got['exit']}", mode)
    if any(got["crash"] for m, got in seen.items() if m != "records"):
        return found

    # 2. A document that validates, the same in both formats.
    for fmt in ("json", "yaml"):
        got = seen[f"output-{fmt}"]
        if got["exit"] == 0 and got["document"] is None:
            fail("2 exit 0 wrote no document", f"output-{fmt}")
        if got["document"] is not None:
            for error in VALIDATOR.iter_errors(got["document"]):
                place = "/".join("*" if isinstance(p, int) else str(p)
                                 for p in error.absolute_path)
                fail(f"2 schema: {place} {error.validator}",
                     f"{fmt}: {error.message[:300]}")
    docs = [seen[f"output-{f}"]["document"] for f in ("json", "yaml")]
    if None not in docs and docs[0] != docs[1]:
        fail("2 YAML and JSON documents differ", _first_difference(*docs))

    # 3. Exit 1 carries a coded diagnostic.
    records = seen["records"]
    if records is None or not isinstance(records, list):
        fail("3 --validate --format json printed no JSON array",
             seen["validate-json"]["stdout"][:300])
        records = []
    if seen["validate-json"]["exit"] == 1 and not any(
            r.get("severity") == "error" and r.get("code") for r in records):
        fail("3 exit 1 without a coded error", "validate-json")
    text = seen["validate-yaml"]
    if text["exit"] == 1 and not (
            re.search(f"(?m)^(Error: |Error loading configuration: )?{CODED}",
                      text["stderr"])
            or re.search(f"(?m)^  - {CODED}",
                         text["stdout"].partition("Bibliography errors")[2])):
        fail("3 exit 1 without a coded error", "validate-yaml")
    for fmt in ("json", "yaml"):
        got = seen[f"output-{fmt}"]
        if got["exit"] == 1 and not re.search(
                f"(?m)^(Error: |Error loading configuration: )?{CODED}", got["stderr"]):
            fail("3 exit 1 without a coded error", f"output-{fmt}")

    # 4. --validate passes only what --output writes.
    for fmt in ("json", "yaml"):
        if seen[f"validate-{fmt}"]["exit"] == 0 and seen[f"output-{fmt}"]["exit"] != 0:
            fail(f"4 --validate passes, --output fails ({fmt})",
                 seen[f"output-{fmt}"]["stderr"][:300])

    # 6. Messages that say a path does not exist are true.
    config = _loaded(where / "lab.yaml")
    for r in records:
        m = re.search(r"'([^']*)' does not exist", r.get("message", ""))
        if m and _exists(m.group(1), where, config):
            fail(f"6 says an existing path does not exist ({r.get('code')})",
                 f"{r.get('key')}: {m.group(1)!r}")

    doc = seen["output-json"]["document"]
    if doc is None or not isinstance(config, dict):
        return found

    # 6. On a run that writes, nothing given was silently ignored.
    for key in ("people_file", "projects_file", "collaborators_file"):
        value = config.get(key)
        if isinstance(value, str) and not value.strip() and not any(
                r.get("key") == key for r in records):
            fail(f"6 empty {key} is not reported", repr(value))
    for path, keys in _repeated_keys(case).items():
        for key in keys:
            if not any(_names(r, path, key) for r in records):
                fail(f"6 repeated YAML key is not reported ({_kind_of(path)})",
                     f"{path}: {key}")

    _check_bios(case, config, doc, records, fail)

    counts = {}
    for entries in case.bibs.values():
        for e in entries:
            counts[e.key] = counts.get(e.key, 0) + 1
    works = {}
    for w in doc.get("works", []):
        works.setdefault(w.get("bib_id"), []).append(w)
    listed = _listed_bibs(config)
    for path, entries in case.bibs.items():
        if os.path.normpath(path) not in listed:
            continue
        for e in entries:
            if counts[e.key] > 1:
                continue
            excused = _excuse(records, Path(path).name, e.key)
            report = fail
            if any(value_text(f).count("{") != value_text(f).count("}")
                   for f in e.fields):
                # BibTeX counts every brace, `\{` too, so an unbalanced value
                # ends elsewhere and moves the fields after it: one cause.
                def report(cls, detail, evidence=(), key=e.key):
                    if not cls.startswith("5 "):
                        return fail(cls, detail, evidence)
                    fail("5 text lost silently in an entry with an unbalanced "
                         "brace", f"{key}: {cls[2:]}: {detail}"[:400])
            got = works.get(e.key, [])
            if not got:
                if not excused(None):
                    report("5 entry silently dropped", e.key)
                continue
            _check_work(e, got[0], excused, report)
    return found


def _check_bios(case: Case, config: dict, doc: dict, records, fail) -> None:
    """Each emitted person's `bio` against the one its record wrote: every
    word and line break kept, NFC, no control character, and each thing
    removed or refused reported at the person's `bio`."""
    people = case.data.get("people.yaml")
    if config.get("people_file") != "people.yaml" or not isinstance(people, list):
        return
    written = [{yaml_text(p.key): p.value for p in r.pairs} for r in people
               if len({yaml_text(p.key) for p in r.pairs}) == len(r.pairs)]
    ids = [w.get('"id"') for w in written]
    emitted = {}
    for person in doc.get("people", []):
        emitted.setdefault(person.get("id"), []).append(person)
    for w in written:
        pid = w.get('"id"')
        if (not isinstance(pid, str) or ids.count(pid) != 1
                or len(emitted.get(pid, [])) != 1):
            continue
        bio, got = w.get('"bio"'), emitted[pid][0].get("bio")
        reported = {r.get("code") for r in records if r.get("key") == pid
                    and r.get("field") == "bio"}
        if bio is None or bio == Raw("null"):
            if got is not None:
                fail("6 absent bio is not null", f"{pid}: {got!r}")
        elif not isinstance(bio, str):
            if got is not None:
                fail("6 bio that is not a string is emitted", f"{pid}: {got!r}")
            if "RECORD-TYPE-INVALID" not in reported:
                fail("6 bio that is not a string is not reported", pid)
        elif not isinstance(got, str):
            fail("5 string bio is not emitted", f"{pid}: {got!r}")
        else:
            lost = [word for word in re.findall(r"[Zz]q[a-z]+", bio)
                    if word not in got]
            if lost:
                fail("5 bio text lost", f"{pid}: {lost} of {bio!r} in {got!r}")
            if got.count("\n") != bio.count("\n"):
                fail("5 bio line breaks changed", f"{pid}: {bio!r} -> {got!r}")
            if not unicodedata.is_normalized("NFC", got):
                fail("5 bio is not NFC", f"{pid}: {got!r}")
            if _CONTROL_IN_TEXT.search(got):
                fail("5 bio keeps a control character", f"{pid}: {got!r}")
            if _CONTROL_IN_TEXT.search(bio):
                if "TEXT-CONTROL-CHARACTER" not in reported:
                    fail("6 bio control character is not reported", f"{pid}: {bio!r}")
            elif unicodedata.is_normalized("NFC", bio) and got != bio:
                fail("5 bio is not emitted as written", f"{pid}: {bio!r} -> {got!r}")


def _check_work(e: Entry, w: dict, excused, fail) -> None:
    by_name = {}
    for f in e.fields:
        by_name.setdefault(f.name.lower(), []).append(f)
    repeated = {n for n, fs in by_name.items() if len(fs) > 1}
    bibtex = w.get("bibtex") or ""

    for f in e.fields:
        name = f.name.lower()
        if name in repeated:
            continue
        places = _places(name, w, by_name)
        pieces = [p for p in f.parts if not isinstance(p, Sentinel)]
        for p in f.parts:
            if not isinstance(p, Sentinel):
                continue
            names = name in ("author", "editor", "award")
            argument = p.form.startswith("\\")
            evidence = [p.form] if names or argument else pieces
            for word in bare_words(p):
                if places is not None \
                        and not any(word in (v or "") for v in places) \
                        and not drops(p.form) \
                        and not excused(name, LOSS_EXPLAINED):
                    fail(f"5 {_group(name)} loses "
                         f"{'a command argument' if argument else 'text'}",
                         f"{e.key}.{name}: {value_text(f)!r}: {word!r} not in "
                         f"{places!r}"[:400], evidence)
                if word not in bibtex and not excused(name, LOSS_EXPLAINED):
                    fail("5 bibtex loses text",
                         f"{e.key}.{name}: {value_text(f)!r}"[:400], evidence)
        if f.delim and name not in ("author", "editor") \
                and not excused(name, LOSS_EXPLAINED):
            # The record is written from the value as read, which is NFC
            # (SPEC.md §2), so `e` + U+0301 comes back as `é`.
            source = unicodedata.normalize("NFC", " ".join(value_text(f).split()))
            if source and source not in " ".join(bibtex.split()):
                fail(f"5 bibtex rewrites {_specials(source)}",
                     f"{e.key}.{name}: {source!r}"[:400])
        if (name in TEXT_FIELDS or name == "award") and places:
            source = value_text(f)
            # Math is left as TeX with a bare `%` or `&` escaped (SPEC.md), so
            # a URL is checked only in a value with no bare `$`.
            urls = ([] if re.search(r"(?<!\\)\$", source) else
                    re.findall(r"\\(?:url|href)\s*\{([^{}]*)\}", source))
            for url in urls:
                if not any(url in (v or "") for v in places) \
                        and not excused(name, LOSS_EXPLAINED):
                    fail("5 a URL in \\url or \\href is changed",
                         f"{e.key}.{name}: {url!r} not in {places!r}"[:400],
                         [p for p in pieces if url in p])
            for v in places:
                invented = sorted({c for c in "<>[]" if c in (v or "")
                                   and c not in source})
                if invented and not excused(name, LOSS_EXPLAINED):
                    fail(f"6 conversion invents markup {''.join(invented)}",
                         f"{e.key}.{name}: {source!r} -> {v!r}"[:400], pieces)

    # A year is a number only when it is an unsigned run of ASCII digits.
    if "year" in by_name and "year" not in repeated:
        raw = value_text(by_name["year"][0]).strip()
        year = w.get("year")
        if year is not None and not (raw.isascii() and raw.isdigit()
                                     and int(raw) == year):
            fail("6 malformed year read as a number", f"{e.key}: {raw!r} -> {year!r}")
        if year is None and not excused("year"):
            fail("6 year dropped without a diagnostic", f"{e.key}: {raw!r}")

    # An award's year is the one its prefix wrote, or the work's; a prefix
    # that is not a year stays in the name and is reported; an empty award is
    # reported. An unbalanced brace moves where the awards end, so such an
    # entry is left to the text checks above.
    awards = by_name.get("award")
    if awards and "award" not in repeated and not excused("award", LOSS_EXPLAINED) \
            and all(value_text(f).count("{") == value_text(f).count("}")
                    for f in e.fields):
        _check_awards(e.key, awards[0], w, excused, fail)

    # An eprint is filed under the repository its entry names, arXiv by default.
    eprint = by_name.get("eprint")
    if eprint and len(eprint) == 1 and value_text(eprint[0]).strip() \
            and not excused("eprint"):
        named = {REPOSITORIES.get(value_text(fs[0]))
                 for n, fs in by_name.items() if n in ("archiveprefix", "eprinttype")}
        named.discard(None)
        if len(named) <= 1 and not ({"archiveprefix", "eprinttype"} & repeated):
            scheme = named.pop() if named else "arxiv"
            schemes = set(w.get("identifiers", {})) - {"doi", "isbn", "issn"}
            has_link = "arxiv" in w.get("links", {})
            if schemes != {scheme} or has_link != (scheme == "arxiv"):
                given = {n: value_text(fs[0]) for n, fs in by_name.items()
                         if n in ("archiveprefix", "eprinttype")}
                fail(f"6 eprint of {scheme} filed as {sorted(schemes)}"
                     f"{', linked to arXiv' if has_link else ''}",
                     f"{e.key}: {given} -> identifiers {sorted(schemes)}, "
                     f"arxiv link {has_link}")

    # `others` stands for authors not named; it is never an author.
    for role, plural in (("author", "authors"), ("editor", "editors")):
        if any((a.get("name") or "").strip().lower() == "others"
               for a in w.get(plural, [])) and not excused(role):
            fail(f"6 {role} named 'others'", e.key)


def _check_awards(key, f: Field, w: dict, excused, report) -> None:
    """The award invariants of section 6, for one entry's `award` field."""
    def fail(cls, detail):
        report(cls, f"{key}: {value_text(f)!r}: {detail}"[:400])

    reported = {code: excused("award", {code})
                for code in ("BIB-AWARD-EMPTY", "BIB-AWARD-YEAR-MALFORMED")}
    if any(not isinstance(p, Award) for p in f.parts) and not reported["BIB-AWARD-EMPTY"]:
        fail("6 empty award not reported", "no BIB-AWARD-EMPTY")
    for p in f.parts:
        if not isinstance(p, Award) or drops(p.form):
            continue
        word = bare_words(p)[0]
        found = [a for a in w.get("awards", []) if word in a.get("name", "")]
        if len(found) != 1:
            continue  # a lost word is the text check's to report
        name, year = found[0]["name"], found[0]["year"]
        if p.kind == "year":
            if year != int(p.prefix[:4]) or name.startswith(p.prefix[:5]):
                fail("6 award year prefix not read", f"{name!r}, {year!r}")
        elif year != w.get("year"):
            fail(f"6 award with a {p.kind} prefix does not take the work's year",
                 f"{name!r}, {year!r}")
        if p.kind == "malformed":
            if p.prefix.split(":")[0].strip() not in name:
                fail("6 malformed award prefix dropped from the name", repr(name))
            if not reported["BIB-AWARD-YEAR-MALFORMED"]:
                fail("6 malformed award prefix not reported", repr(name))


def _places(name, w, by_name):
    """The values a field reaches in the document, or None where it has no
    one place to check (a container field another one outranks)."""
    if name in ("title", "abstract", "note") or name in RAW_FIELDS or name in (
            "publisher", "series", "address", "organization", "type"):
        return [w.get(name)]
    if name in CONTAINERS:
        present = [c for c in CONTAINERS
                   if c in by_name and value_text(by_name[c][0]).strip()]
        if present and present[0] == name:
            return [(w.get("venue") or {}).get("name")]
        return None
    if name in ("author", "editor"):
        return [a.get("name") for a in w.get(name + "s", [])]
    if name in ("url", "video", "pdf"):
        return [link.get("url") for links in w.get("links", {}).values()
                for link in links if link.get("origin") == "input"]
    if name == "doi":
        return w.get("identifiers", {}).get("doi", [])
    if name == "award":
        return [a.get("name") for a in w.get("awards", [])]
    if name == "eprint":
        return [v for vs in w.get("identifiers", {}).values() for v in vs]
    return None


def _group(name):
    if name in ("author", "editor"):
        return "name"
    if name == "award":
        return "award"
    if name in TEXT_FIELDS:
        return "text field"
    return name if name in ("url", "doi", "eprint") else "raw field"


def _specials(source):
    """The one special character in a value, which names the failure; a
    value with several is reduced until it has one."""
    found = set(re.findall(r"\\?[%&_#$~^]", source))
    return f"a value with {found.pop()}" if len(found) == 1 else "a value"


# The diagnostics that explain text missing from a field: the value could not
# be read as BibTeX or as LaTeX, its braces moved it into another field,
# control characters were removed from it, or a word in it was read as an
# undefined `@string` macro. A command reported unknown is
# dropped with a braced argument kept (SPEC.md), which loses no text.
LOSS_EXPLAINED = frozenset({"BIB-SYNTAX-ERROR", "BIB-PARSER-MESSAGE",
                            "BIB-BRACE-MISMATCH", "TEXT-CONTROL-CHARACTER",
                            "BIB-STRING-UNDEFINED",
                            "LATEX-CONVERSION-FAILED", "BIB-WRITE-BACK-FAILED"})


def _excuse(records, file, key):
    """Whether a diagnostic explains a change to this entry: a syntax error in
    its file, or one at the entry and field (any field for None), of `codes`
    when given. A brace mismatch is reported once per entry, at the first
    field it moved (SPEC.md), so it explains every field of its entry."""
    def excused(field_name, codes=None):
        for r in records:
            if r.get("code") == "BIB-SYNTAX-ERROR" and (r.get("file") or "").endswith(file):
                return True
            if r.get("code") == "BIB-BRACE-MISMATCH" and r.get("key") == key \
                    and (codes is None or r.get("code") in codes):
                return True
            if (r.get("key") == key and (codes is None or r.get("code") in codes)
                    and (field_name is None
                         or (r.get("field") or "").lower() == field_name)):
                return True
        return False
    return excused


def _repeated_keys(case: Case) -> dict:
    """The keys written twice in one YAML mapping, by file."""
    found = {}

    def walk(value, path):
        if isinstance(value, Mapping):
            walk_pairs(value.pairs, path)
        elif isinstance(value, Seq):
            for v in value.items:
                walk(v, path)

    def walk_pairs(pairs, path):
        seen = set()
        for p in pairs:
            k = yaml_text(p.key)
            if k in seen:
                found.setdefault(path, []).append(p.key.text if isinstance(p.key, Raw)
                                                  else p.key)
            seen.add(k)
            walk(p.value, path)

    walk_pairs(case.config, "lab.yaml")
    for path, records in case.data.items():
        if not isinstance(records, Raw):
            for r in records:
                walk(r, path)
    return found


def _names(record, path, key):
    where = (record.get("file") or "").endswith(Path(path).name)
    return where and key in " ".join(str(record.get(n) or "") for n in
                                     ("key", "field", "message"))


def _kind_of(path):
    return "lab.yaml" if path == "lab.yaml" else "data file"


def _listed_bibs(config) -> set:
    """The .bib files lab.yaml lists, as paths from the case directory."""
    bib_dir = config.get("bib_dir")
    listed = config.get("bib_files")
    if not isinstance(bib_dir, str) or not isinstance(listed, list):
        return set()
    return {os.path.normpath(os.path.join(bib_dir, bf["name"])) for bf in listed
            if isinstance(bf, dict) and isinstance(bf.get("name"), str)}


def _loaded(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, ValueError):
        return None


def _exists(named, where, config):
    bib_dir = config.get("bib_dir") if isinstance(config, dict) else None
    bases = [where] + ([where / bib_dir] if isinstance(bib_dir, str) and bib_dir else [])
    return any((base / named).exists() for base in bases if named.strip())


def _first_difference(a, b, path=""):
    if type(a) is not type(b):
        return f"{path or '/'}: {a!r} != {b!r}"[:300]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if a.get(k) != b.get(k):
                return _first_difference(a.get(k), b.get(k), f"{path}/{k}")
    if isinstance(a, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_difference(x, y, f"{path}/{i}")
    return f"{path or '/'}: {a!r} != {b!r}"[:300]


# --- Reducing a failure -----------------------------------------------------------

def _element_paths(case: Case) -> list:
    """The path to every list element and file of a case, outermost first."""
    paths = []

    def walk(obj, path):
        if isinstance(obj, (list, dict)):
            for k, v in (enumerate(obj) if isinstance(obj, list) else obj.items()):
                paths.append(path + (k,))
                walk(v, path + (k,))
        elif is_dataclass(obj):
            for f in fields(obj):
                walk(getattr(obj, f.name), path + (f.name,))

    walk(case, ())
    return sorted(paths, key=len)


def _without(case: Case, path) -> Case:
    smaller = copy.deepcopy(case)
    parent = smaller
    for step in path[:-1]:
        parent = getattr(parent, step) if is_dataclass(parent) else parent[step]
    del parent[path[-1]]
    return smaller


def _shows(violations, cls, known) -> list:
    """The violations of `cls` whose evidence names no known cause."""
    return [(d, ev) for c, d, ev in violations if c == cls and not ev & known]


def reduce(case: Case, cls: str, known: set, where: Path):
    """A smaller case that still fails with `cls` by a cause not in `known`:
    each element is removed in turn and stays removed while the failure
    persists, in passes until one removes nothing or REDUCE_BUDGET tries are
    spent."""
    tries, changed = 0, True
    while changed and tries < REDUCE_BUDGET:
        changed, i = False, 0
        while tries < REDUCE_BUDGET:
            paths = _element_paths(case)
            if i >= len(paths):
                break
            smaller = _without(case, paths[i])
            tries += 1
            materialize(smaller, where)
            if _shows(check(smaller, observe(where), where), cls, known):
                case, changed = smaller, True
            else:
                i += 1
    materialize(case, where)
    seen = observe(where)
    return case, seen, check(case, seen, where)


def _report_run(got):
    report = {"exit": got["exit"]}
    if got["crash"]:
        report["crash"] = got["crash"]
    lines = [l for l in (got["stdout"] + got["stderr"]).splitlines()
             if re.search(CODED, l)]
    report["coded_lines"] = lines[:20]
    return report


# --- The test ---------------------------------------------------------------------

def test_generated_inputs_keep_the_invariants(tmp_path):
    """Every generated input keeps every invariant in the module docstring."""
    count = int(os.environ.get(CASES_ENV) or DEFAULT_CASES)
    where = tmp_path / "case"
    seen_in = {}      # class -> [(index, case, evidence)]
    for index in range(count):
        case = Generator(index).case()
        materialize(case, where)
        for cls, _, evidence in check(case, observe(where), where):
            seen_in.setdefault(cls, []).append((index, case, evidence))

    # Each class is reduced once per distinct cause: a failure whose evidence
    # holds a piece an earlier reduction isolated is taken to be that cause.
    failures = []
    for cls in sorted(seen_in):
        known = set()
        while len(known) < CAUSES_PER_CLASS:
            first = next(((i, c) for i, c, ev in seen_in[cls] if not ev & known), None)
            if first is None:
                break
            small, seen, violations = reduce(first[1], cls, known, where)
            shown = _shows(violations, cls, known)
            detail, evidence = shown[0] if shown else ("not reproduced", frozenset())
            failures.append({
                "class": cls,
                "case": first[0],
                "detail": detail,
                "input": files_of(small),
                "directories": list(DIRS) + ["pdfs/k1.pdf"],
                "observed": {mode: _report_run(got) for mode, got in seen.items()
                             if mode != "records"},
                "diagnostics": [{k: r.get(k) for k in ("code", "severity", "file",
                                                        "key", "field")}
                                for r in (seen["records"] or [])],
            })
            if not evidence:
                break
            known |= evidence

    if os.environ.get(FAILURES_ENV):
        write_atomically(os.environ[FAILURES_ENV], json.dumps(
            {"format": 1, "seed": SEED, "cases": count, "failures": failures},
            indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    assert not failures, (
        f"{len(failures)} distinct failures over {count} generated inputs "
        f"(set {FAILURES_ENV} to write the reduced inputs):\n" +
        "\n".join(f"  case {f['case']}: {f['class']}: {f['detail']}"[:300]
                  for f in failures))
