"""Automatic fixes for common template mistakes that some TeX versions tolerate and others don't.

Used only when the uploaded file fails to compile. Each fix returns (new_tex, description)
or None. The pipeline keeps a fix only if the file then compiles.
"""
from __future__ import annotations

import re

from .extract import match_brace


def _args(tex: str, pos: int, n: int) -> list[tuple[int, int]] | None:
    """Spans (inside braces) of the next n brace arguments starting at pos."""
    spans = []
    for _ in range(n):
        while pos < len(tex) and tex[pos] in " \t\n":
            pos += 1
        if pos >= len(tex) or tex[pos] != "{":
            return None
        close = match_brace(tex, pos)
        spans.append((pos + 1, close))
        pos = close + 1
    return spans


def uppercase_in_titleformat(tex: str):
    r"""\titleformat{\section}{...\MakeUppercase}{label}{sep}{}  ->  move \MakeUppercase to the before-code.

    In titlesec the before-code's last command receives the title; \MakeUppercase in the
    format argument instead swallows titlesec's internals ("\ttl@row@i doesn't match").
    """
    out, changed, i = tex, False, 0
    while True:
        m = re.compile(r"\\titleformat\s*").search(out, i)
        if not m:
            break
        spans = _args(out, m.end(), 5)
        i = m.end()
        if not spans:
            continue
        _, (fs, fe), _, _, (bs, be) = spans   # {\section}{format}{label}{sep}{before}
        fmt = out[fs:fe]
        mm = re.search(r"\\(MakeUppercase|uppercase|MakeTextUppercase)\s*$", fmt)
        if not mm or out[bs:be].strip():
            continue
        cmd = "\\" + mm.group(1)
        new_fmt = fmt[:mm.start()].rstrip()
        out = out[:fs] + new_fmt + out[fe:bs] + cmd + out[be:]
        changed = True
    return (out, "Moved \\MakeUppercase in \\titleformat to the title argument, where titlesec expects it.") if changed else None


FIXES = [uppercase_in_titleformat]


def candidates(tex: str):
    """Yield (repaired_tex, [descriptions]) for each fix that changes something, then all together."""
    applied, cur = [], tex
    for fix in FIXES:
        r = fix(cur)
        if r:
            cur, desc = r
            applied.append(desc)
            yield cur, list(applied)
