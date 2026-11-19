"""Find the rewritable text blocks in a LaTeX resume.

Each block remembers its exact [start, end) character span in the source, so
revisions can be pasted back mechanically without touching anything else.
The LLM only ever sees the plain-text version of a block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

# Single-argument macros whose argument is a bullet / description line.
# Covers Jake's Resume, Awesome-CV style and common forks; extend as needed.
BULLET_MACROS = ("resumeItem", "resumeItemNoTitle", "cvitem", "item", "bullet")

# Environments whose \item entries are bullets.
LIST_ENVS = ("itemize", "enumerate", "cvitems", "highlights")

SUMMARY_SECTIONS = ("summary", "profile", "objective", "about")


@dataclass
class Block:
    id: str
    kind: str          # "bullet" | "summary"
    section: str       # section heading the block sits under
    start: int         # span of the editable content in the .tex source
    end: int
    source: str        # raw LaTeX of the content
    text: str          # plain text sent to the LLM
    context: str = ""  # nearest entry heading above it, e.g. "PlanForge | PyTorch, YOLO11, FastAPI"
    links: list[str] = field(default_factory=list)  # URLs in that heading (GitHub, demo...)

    def to_dict(self) -> dict:
        return asdict(self)


def strip_comments(tex: str) -> str:
    """Blank out % comments while keeping character offsets identical."""
    out = []
    for line in tex.split("\n"):
        i, cut = 0, None
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut] + " " * (len(line) - cut))
    return "\n".join(out)


def match_brace(tex: str, open_idx: int) -> int:
    """Index of the '}' matching the '{' at open_idx (escaped braces skipped)."""
    depth, i = 0, open_idx
    while i < len(tex):
        c = tex[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced brace at {open_idx}")


_HEADING_RE = re.compile(r"\\(resumeProjectHeading|resumeSubheading|resumeSubHeading|resumeSubSubheading|cventry)\s*\{")


def _headings(tex: str) -> list[tuple[int, str, list[str]]]:
    """(position, plain text of all brace args, URLs) for each project/job heading macro."""
    out = []
    for m in _HEADING_RE.finditer(tex):
        j, args, start = m.end() - 1, [], m.end() - 1
        while j < len(tex) and tex[j] == "{":
            close = match_brace(tex, j)
            args.append(to_plain(tex[j + 1:close]))
            j = close + 1
            while j < len(tex) and tex[j] in " \t\n":
                j += 1
        urls = [u for u in re.findall(r"\\(?:href|url)\{([^}]*)\}", tex[start:j]) if u.startswith("http")]
        out.append((m.start(), " | ".join(a for a in args if a), urls))
    return out


_SECTION_RE = re.compile(r"\\(?:section|cvsection|resumeSection)\*?\s*\{")
_ENV_RE = re.compile(r"\\(begin|end)\{(" + "|".join(LIST_ENVS) + r")\}")


def _sections(tex: str) -> list[tuple[int, str]]:
    out = []
    for m in _SECTION_RE.finditer(tex):
        close = match_brace(tex, m.end() - 1)
        out.append((m.start(), to_plain(tex[m.end():close]).strip()))
    return out


def _section_at(sections: list[tuple[int, str]], pos: int) -> str:
    name = ""
    for start, title in sections:
        if start > pos:
            break
        name = title
    return name


def _list_ranges(tex: str) -> list[tuple[int, int]]:
    """[begin, end) ranges of list environments, outermost only."""
    ranges, stack = [], []
    for m in _ENV_RE.finditer(tex):
        if m.group(1) == "begin":
            stack.append(m.end())
        elif stack:
            start = stack.pop()
            if not stack:
                ranges.append((start, m.start()))
    return ranges


def _balanced(seg: str) -> bool:
    depth, i = 0, 0
    while i < len(seg):
        c = seg[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "{") - (c == "}")
        if depth < 0:
            return False
        i += 1
    return depth == 0


def extract_blocks(tex: str) -> list[Block]:
    clean = strip_comments(tex)
    sections = _sections(clean)
    blocks: list[Block] = []
    seen: set[tuple[int, int]] = set()

    def add(kind: str, start: int, end: int):
        if (start, end) in seen or end <= start:
            return
        raw = tex[start:end]
        if not _balanced(clean[start:end]):
            return  # never offer a span whose replacement could unbalance the document
        # The Skills section is never rewritten: editing it is how invented skills sneak in.
        if "skill" in _section_at(sections, start).lower():
            return
        plain = to_plain(raw).strip()
        if len(plain) < 3:
            return
        seen.add((start, end))
        blocks.append(Block("", kind, _section_at(sections, start), start, end, raw, plain))

    # 1) Bullet macros with a braced argument: \resumeItem{...}
    for name in BULLET_MACROS:
        if name == "item":
            continue
        for m in re.finditer(r"\\" + name + r"\s*\{", clean):
            close = match_brace(clean, m.end() - 1)
            add("bullet", m.end(), close)

    # 2) Plain \item lines inside list environments
    for lo, hi in _list_ranges(clean):
        body = clean[lo:hi]
        items = [m for m in re.finditer(r"\\item\b(\[[^\]]*\])?", body)]
        for k, m in enumerate(items):
            start = lo + m.end()
            end = lo + (items[k + 1].start() if k + 1 < len(items) else len(body))
            seg = clean[start:end]
            # Skip items that only wrap other macros (e.g. \item\resumeSubheading{...})
            if re.match(r"\s*\\(resume|cv)\w*", seg):
                continue
            # Stop at nested list starts
            nested = re.search(r"\\begin\{", seg)
            if nested:
                end = start + nested.start()
            # Stop before a brace that closes an enclosing group (e.g. the "}" of a
            # \small{ ... } wrapping the whole list), so the span is always balanced.
            depth, k = 0, start
            while k < end:
                ch = clean[k]
                if ch == "\\":
                    k += 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        end = k
                        break
                k += 1
            # Trim trailing whitespace from the span
            while end > start and clean[end - 1].isspace():
                end -= 1
            while start < end and clean[start].isspace():
                start += 1
            add("bullet", start, end)

    # 3) Summary paragraph: text right after a Summary-like heading
    for idx, (pos, title) in enumerate(sections):
        if title.lower() not in SUMMARY_SECTIONS:
            continue
        head_end = match_brace(clean, clean.index("{", pos)) + 1
        stop = sections[idx + 1][0] if idx + 1 < len(sections) else clean.find("\\end{document}")
        para = clean[head_end:stop]
        lead = len(para) - len(para.lstrip())
        start = head_end + lead
        end = head_end + len(para.rstrip())
        if "\\begin{" not in tex[start:end]:
            add("summary", start, end)

    blocks.sort(key=lambda b: b.start)
    heads = _headings(clean)
    for n, b in enumerate(blocks, 1):
        b.id = f"b{n:02d}"
        prior = [h for h in heads if h[0] < b.start and _section_at(sections, h[0]) == b.section]
        if prior:
            b.context, b.links = prior[-1][1], prior[-1][2]
    return blocks


# ---------- LaTeX -> plain text ----------

_UNESCAPE = {r"\&": "&", r"\%": "%", r"\$": "$", r"\#": "#", r"\_": "_",
             r"\{": "{", r"\}": "}", r"\textasciitilde{}": "~", r"\textasciicircum{}": "^",
             r"\textbackslash{}": "\\", r"\textbar{}": "|", r"\ ": " "}
# Commands whose last argument is the visible text
_KEEP_LAST_ARG = ("href",)
_DROP = ("vspace", "hspace", "label", "footnote")


_SENTINELS = {k: chr(0xE000 + n) for n, k in enumerate(_UNESCAPE)}


def to_plain(src: str) -> str:
    s = src
    # Longest escapes first, swapped for private-use sentinels so the parser
    # below never mistakes an escaped brace for a group.
    for k in sorted(_UNESCAPE, key=len, reverse=True):
        s = s.replace(k, _SENTINELS[k])
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)\*?", s[i:])
            if not m:
                nxt = s[i + 1:i + 2]
                out.append(" " if nxt in ("\\", "") else nxt)
                i += 2
                continue
            name = m.group(1)
            j = i + m.end()
            args = []
            while j < len(s) and s[j] in "{[":
                if s[j] == "[":
                    k = s.find("]", j)
                    j = k + 1 if k != -1 else len(s)
                    continue
                close = match_brace(s, j)
                args.append(s[j + 1:close])
                j = close + 1
            if name in _DROP:
                pass
            elif name in _KEEP_LAST_ARG and args:
                out.append(to_plain(args[-1]))
            elif args:
                out.append(" ".join(to_plain(a) for a in args))
            elif name in ("LaTeX", "TeX"):
                out.append(name)
            elif name in ("newline", "linebreak", "par"):
                out.append(" ")
            i = j
            continue
        if c in "{}$":  # group braces and math-mode delimiters ($|$ separators)
            i += 1
            continue
        if c == "~":
            out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    text = "".join(out)
    for k, ch in _SENTINELS.items():
        text = text.replace(ch, _UNESCAPE[k])
    text = text.replace("---", "\u2014").replace("--", "\u2013").replace("``", '"').replace("''", '"')
    return re.sub(r"\s+", " ", text).strip()
