"""
LaTeX → plain Unicode text, via pylatexenc.

One field value at a time. Math is left as TeX (``math_mode='verbatim'``) so
``$...$`` reaches KaTeX or MathJax untouched; everything else becomes plain
Unicode. Callers convert field by field and fall back to ``strip_braces`` when
a value cannot be converted, so a bad field never costs the whole entry.

Together with bibtex.py this is the adapter: no other module imports pybtex or
pylatexenc.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import re

from pylatexenc.latex2text import (
    LatexNodes2Text, MacroTextSpec, get_default_latex_context_db,
)
from pylatexenc.latexwalker import (
    LatexMacroNode, LatexMathNode, LatexWalker,
    get_default_latex_context_db as get_default_parsing_db,
)
from pylatexenc.macrospec import std_macro


# Common text macros the converter's own table lacks. Without a rule each
# would be dropped, so `The \TeX{} book 1990\emdash 2000` would read
# `The  book 19902000`.
_TEXT_MACROS = {
    "TeX": "TeX", "LaTeX": "LaTeX", "LaTeXe": "LaTeX2e", "BibTeX": "BibTeX",
    "emdash": "\u2014", "endash": "\u2013", "slash": "/",
}

# Marks a command that leaves nothing, or a parenthesis, where it stood: the
# spaces before it go too, so `planners~\cite{k}.` reads `planners.`.
# This marker and `_PLACEHOLDER` below are control characters, which cannot
# collide with the input: every control character is removed from a field
# value where it is read, before it is converted (`CONTROL_CHARACTER` in
# sslabdata/config.py).
_JOIN = '\x02'
_JOIN_RE = re.compile(f'[ \t\xa0]*{_JOIN}')


def _footnote(node, l2tobj):
    return f'{_JOIN} ({l2tobj.node_arg_to_text(node, 1).strip()})'


def _item(node, l2tobj):
    if node.nodeoptarg:
        return _JOIN + '\n' + l2tobj.nodelist_to_text([node.nodeoptarg])
    return _JOIN + '\n\u2022 '


# The converter's table renders these as syntax rather than text: `\url{u}`
# as the autolink `<u>`, `\footnote{n}` as `[n]`, a citation as `<cit.>`, a
# list item as a Markdown bullet. Each is replaced by plain text or by nothing
# (SPEC.md section 2).
_PLAIN_TEXT_RULES = [
    # A `\url` whose argument holds braces is not set aside by `_prepared()`.
    MacroTextSpec("url", "%s"),
    MacroTextSpec("footnote", _footnote),
    MacroTextSpec("item", _item),
    MacroTextSpec("textfrac", "%s/%s"),
] + [MacroTextSpec(name, _JOIN) for name in (
    "cite", "citep", "citet", "ref", "autoref", "cref", "Cref", "eqref",
    "includegraphics",
)] + [MacroTextSpec("maketitle", "")]

# Commands whose argument is the text itself, set in another face or box, or
# given as a document's title, author or date. Each becomes its argument, as
# `\textbf` does in the converter's own table; the converter's own rule for
# `\title`, `\author` and `\date` drops the argument.
_TEXT_ARGUMENT = ("texttt", "textsf", "textmd", "textup", "textnormal",
                  "mbox", "fbox", "hbox", "title", "author", "date")

# Commands whose arguments are not text: a citation, a label or a
# cross-reference becomes nothing and takes the spaces before it, as `\cite`
# does above; a colour, a package, a length, a counter or a phantom becomes
# nothing and leaves the text around it as it was (SPEC.md section 2).
_REFERENCES = ("citealp", "citealt", "citeauthor", "citefullauthor",
               "citenum", "citeyear", "citeyearpar", "citepalias",
               "citetalias", "Citealp", "Citealt", "Citeauthor", "Citep",
               "Citet", "nocite", "label", "pageref", "nameref")
_SETTINGS = ("color", "colorlet", "definecolor", "providecolor", "pagecolor",
             "nopagecolor", "rowcolors", "documentclass", "usepackage",
             "RequirePackage", "bibliography", "hypersetup", "selectlanguage",
             "setcounter", "addcounter", "setlength", "addlength",
             "defcitealias", "hphantom", "vphantom")

# The commands the converter has a rule for. A command outside it is dropped,
# and what follows it is read as plain text (`_WITHOUT_RULE` below).
_KNOWN = get_default_latex_context_db()
_KNOWN.add_context_category(
    "sslabdata-text",
    macros=[MacroTextSpec(name, text) for name, text in _TEXT_MACROS.items()]
    + _PLAIN_TEXT_RULES
    + [MacroTextSpec(name, "%s") for name in _TEXT_ARGUMENT]
    + [MacroTextSpec(name, _JOIN) for name in _REFERENCES]
    + [MacroTextSpec(name, "") for name in _SETTINGS],
    prepend=True)

# How the walker reads each command's arguments. `\textfrac` has a text rule
# but no argument spec, so without this its rule would print `%s/%s`; nor do
# `\textnormal`, `\fbox`, `\hbox`, `\nocite`, `\pageref` and `\nameref`.
_PARSING = get_default_parsing_db()
_PARSING.add_context_category(
    "sslabdata-arguments",
    macros=[std_macro("textfrac", False, 2)]
    + [std_macro(name, False, 1) for name in (
        "textnormal", "fbox", "hbox", "nocite", "pageref", "nameref")],
    prepend=True)

# A command the walker knows the arguments of but the converter has no rule
# for is read as taking no arguments, like a command the walker does not know
# at all: it is dropped and what follows it is kept, braced arguments included,
# so `\keywords{Tidy} Robots` reads `Tidy Robots`. Otherwise the converter
# would drop its arguments with it. This covers the commands that define
# another, too: `\newcommand zqx` would read `zq` as the name and body being
# defined, or a set-aside URL as one.
_WITHOUT_RULE = sorted({spec.macroname for spec in _PARSING.iter_macro_specs()
                        if _KNOWN.get_macro_spec(spec.macroname) is None})
_PARSING.add_context_category(
    "sslabdata-no-arguments",
    macros=[std_macro(name, False, 0) for name in _WITHOUT_RULE],
    prepend=True)

_CONVERTER = LatexNodes2Text(latex_context=_KNOWN, math_mode='verbatim')

# Two commands outside that table whose conversion sslabdata documents, so they
# are known rather than unknown (tests/COVERAGE.md, `names.equal_contribution`
# and `names.equal_contribution_escaped`): `\textsuperscript{...}` becomes its
# argument as plain text, and an escaped star `\*` is consumed.
_DOCUMENTED = frozenset({"textsuperscript", "*"})

# pylatexenc 2.11 raises IndexError on every \href, so the link is rewritten
# to "text (url)" before conversion. The URL itself is set aside first: it is
# not LaTeX, and characters such as _ or % would not survive the converter.
_HREF_URL_TEXT = re.compile(r'\\href\s*\{([^{}]*)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}')
_HREF_URL_ONLY = re.compile(r'\\href\s*\{([^{}]*)\}')
# `\url{u}` is emitted as `u` exactly: the URL is set aside the same way, so a
# `~`, `%`, `_`, `#` or `&` in it is kept rather than converted.
_URL = re.compile(r'\\url\s*\{([^{}]*)\}')

# An unescaped & in a BibTeX field is a literal ampersand, not an alignment tab.
_BARE_AMPERSAND = re.compile(r'(?<!\\)&')
# An unescaped % is a literal percent, not a comment: BibTeX keeps the rest of
# the value. It is escaped when an even run of backslashes (`\\`, a line
# break) or none comes before it, and left alone after `\%`.
_BARE_PERCENT = re.compile(r'(?<!\\)((?:\\\\)*)%')

_PLACEHOLDER = '\x01'
_PLACEHOLDER_RE = re.compile(f'{_PLACEHOLDER}(\\d+){_PLACEHOLDER}')


def latex_to_text(text: str) -> str:
    """Convert one LaTeX field value to plain Unicode text.

    Raises whatever pylatexenc raises, and ValueError when a marker survives
    conversion; callers decide what to do with a value that cannot be
    converted.
    """
    if not text:
        return text

    verbatim: list = []

    def set_aside(value: str) -> str:
        verbatim.append(value)
        return f'{_PLACEHOLDER}{len(verbatim) - 1}{_PLACEHOLDER}'

    converted = _CONVERTER.latex_to_text(_prepared(text, set_aside),
                                         latex_context=_PARSING)
    converted = _JOIN_RE.sub('', converted)
    converted = _PLACEHOLDER_RE.sub(lambda m: verbatim[int(m.group(1))],
                                    converted)
    # A command that read part of a placeholder as its argument leaves the
    # rest behind. The input holds no marker, so any left is one of ours.
    if _PLACEHOLDER in converted or _JOIN in converted:
        raise ValueError("a conversion marker survived")
    return converted


def _prepared(text: str, set_aside) -> str:
    """The value as the converter is given it: links rewritten, bare & and % escaped."""
    text = _HREF_URL_TEXT.sub(lambda m: f'{m.group(2)} ({set_aside(m.group(1))})', text)
    text = _HREF_URL_ONLY.sub(lambda m: set_aside(m.group(1)), text)
    text = _URL.sub(lambda m: set_aside(m.group(1)), text)
    text = _BARE_PERCENT.sub(r'\1\\%', text)
    return _BARE_AMPERSAND.sub(r'\&', text)


def unknown_commands(text: str) -> list:
    """The LaTeX commands in one value the converter has no rule for, in order.

    Math is not searched: it is left as TeX for the renderer. A value the
    walker cannot read at all yields nothing here; converting it is what
    reports that.
    """
    if not text:
        return []
    try:
        nodes, _, _ = LatexWalker(_prepared(text, lambda _: ''),
                                  latex_context=_PARSING,
                                  tolerant_parsing=True).get_latex_nodes()
    except Exception:  # noqa: BLE001 - finding nothing is the safe answer
        return []
    found: list = []

    def walk(nodelist):
        for node in nodelist or []:
            if node is None or isinstance(node, LatexMathNode):
                continue
            if (isinstance(node, LatexMacroNode)
                    and node.macroname not in _DOCUMENTED
                    and _KNOWN.get_macro_spec(node.macroname) is None
                    and node.macroname not in found):
                found.append(node.macroname)
            walk(getattr(node, 'nodelist', None))
            arguments = getattr(node, 'nodeargd', None)
            if arguments is not None:
                walk(arguments.argnlist)

    walk(nodes)
    return found


def strip_braces(text: str) -> str:
    """The fallback for a value pylatexenc cannot convert: keep it, lose the braces."""
    return text.replace('{', '').replace('}', '')
