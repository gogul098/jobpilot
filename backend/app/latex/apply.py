"""Paste revised plain text back into the LaTeX source, mechanically."""
from __future__ import annotations

import re
import unicodedata

from .extract import Block, to_plain

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


# Characters models like to emit that pdflatex cannot typeset, mapped to safe LaTeX.
_UNICODE = {
    "\u00a0": "~", "\u202f": "~", "\u2007": "~", "\u2009": " ", "\u200a": " ", "\u2002": " ",
    "\u2003": " ", "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2008": " ", "\u205f": " ",
    "\u3000": " ", "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\ufeff": "", "\u00ad": "",
    "\u2018": "`", "\u2019": "'", "\u201a": ",", "\u201b": "'", "\u201c": "``", "\u201d": "''",
    "\u201e": ",,", "\u2032": "'", "\u2033": "''",
    "\u2010": "-", "\u2011": "-", "\u2012": "--", "\u2013": "--", "\u2014": "---", "\u2015": "---",
    "\u2212": "$-$", "\u2026": "\\ldots{}", "\u2022": "\\textbullet{}", "\u00b7": "\\textperiodcentered{}",
    "\u00d7": "$\\times$", "\u2248": "$\\approx$", "\u2264": "$\\leq$", "\u2265": "$\\geq$",
    "\u00b1": "$\\pm$", "\u2192": "$\\rightarrow$", "\u2190": "$\\leftarrow$", "\u2194": "$\\leftrightarrow$",
    "\u21d2": "$\\Rightarrow$", "\u00b0": "$^\\circ$", "\u00b5": "$\\mu$", "\u03bc": "$\\mu$",
    "\u2122": "\\texttrademark{}", "\u00ae": "\\textregistered{}", "\u00a9": "\\copyright{}",
    "\u20b9": "Rs.", "\u20ac": "EUR", "\u00a3": "\\pounds{}", "\u2713": "", "\u2714": "",
}


def _safe_char(c: str) -> str:
    """Escape one character, or replace it with something pdflatex can print."""
    if c in _ESC:
        return _ESC[c]
    if c in _UNICODE:
        return _UNICODE[c]
    if ord(c) < 128:
        return c if c.isprintable() or c in "\n\t" else " "
    if ord(c) < 256 and unicodedata.category(c).startswith("L"):
        return c  # accented Latin-1 letters (é, ü...) work with the default utf8 input
    folded = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
    if folded:
        return "".join(_ESC.get(x, x) for x in folded)
    return " " if unicodedata.category(c).startswith("Z") else ""


def escape_latex(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"  +", " ", "".join(_safe_char(c) for c in text))


def _bold_terms(source: str) -> list[str]:
    """Plain-text terms that were bold in the original block."""
    return [to_plain(m) for m in re.findall(r"\\textbf\{([^{}]*)\}", source) if to_plain(m)]


def render_block(original: Block, new_text: str, keep_bold: bool = True) -> str:
    """Escaped LaTeX for a revised block; re-bolds terms that were bold before."""
    out = escape_latex(new_text.strip())
    if keep_bold:
        for term in sorted(_bold_terms(original.source), key=len, reverse=True):
            esc = escape_latex(term)
            out = re.sub(r"(?<![\w{])" + re.escape(esc) + r"(?![\w}])",
                         lambda _m: r"\textbf{" + esc + "}", out, count=1)
    return out


def apply_revisions(tex: str, blocks: list[Block], new_texts: dict[str, str],
                    keep_bold: bool = True) -> str:
    """Replace each block's span with its revision, last block first so offsets stay valid."""
    by_id = {b.id: b for b in blocks}
    for bid in new_texts:
        if bid not in by_id:
            raise KeyError(f"unknown block id {bid}")
        b = by_id[bid]
        if tex[b.start:b.end] != b.source:
            raise ValueError(f"source changed under block {bid}; re-extract before applying")
    for b in sorted((by_id[i] for i in new_texts), key=lambda b: b.start, reverse=True):
        tex = tex[:b.start] + render_block(b, new_texts[b.id], keep_bold) + tex[b.end:]
    return tex
