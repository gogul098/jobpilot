"""Paste revised plain text back into the LaTeX source, mechanically."""
from __future__ import annotations

import re

from .extract import Block, to_plain

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def escape_latex(text: str) -> str:
    text = text.replace("\u2014", "---").replace("\u2013", "--")
    return "".join(_ESC.get(c, c) for c in text)


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
