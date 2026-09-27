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
from pylatexenc.latexwalker import LatexMacroNode, LatexMathNode, LatexWalker


# Common text macros the converter's own table lacks. Without a rule each
# would be dropped, so `The \TeX{} book 1990\emdash 2000` would read
# `The  book 19902000`.
_TEXT_MACROS = {
    "TeX": "TeX", "LaTeX": "LaTeX", "LaTeXe": "LaTeX2e", "BibTeX": "BibTeX",
    "emdash": "\u2014", "endash": "\u2013", "slash": "/",
}

# The commands the converter has a rule for. A command outside it is dropped,
# with any braced argument after it read as a group of plain text.
_KNOWN = get_default_latex_context_db()
_KNOWN.add_context_category(
    "sslabdata-text",
    macros=[MacroTextSpec(name, text) for name, text in _TEXT_MACROS.items()],
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

    Raises whatever pylatexenc raises; callers decide what to do with a value
    that cannot be converted.
    """
    if not text:
        return text

    verbatim: list = []

    def set_aside(value: str) -> str:
        verbatim.append(value)
        return f'{_PLACEHOLDER}{len(verbatim) - 1}{_PLACEHOLDER}'

    converted = _CONVERTER.latex_to_text(_prepared(text, set_aside))
    return _PLACEHOLDER_RE.sub(lambda m: verbatim[int(m.group(1))], converted)


def _prepared(text: str, set_aside) -> str:
    """The value as the converter is given it: links rewritten, bare & and % escaped."""
    text = _HREF_URL_TEXT.sub(lambda m: f'{m.group(2)} ({set_aside(m.group(1))})', text)
    text = _HREF_URL_ONLY.sub(lambda m: set_aside(m.group(1)), text)
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
