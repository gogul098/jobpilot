"""Reject revisions that invent facts. The resume can be reworded, never embellished."""
from __future__ import annotations

import re

from .ats.synonyms import variants
from .schemas import JDProfile, Revision

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
# Tech-looking tokens: CamelCase, ALLCAPS, or containing digits/+/# (PyTorch, AWS, YOLO11, C++)
_TECH = re.compile(r"\b(?:[A-Z][a-z]+[A-Z]\w*|[A-Z]{2,}\w*|\w*\d\w*|\w+[+#]+)")


def _in(term: str, hay: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", hay) is not None


def check_revision(rev: Revision, original: str, resume_text: str, jd: JDProfile,
                   confirmed: list[str] | tuple = (), kind: str = "bullet") -> str | None:
    """Return a rejection reason, or None if the revision is safe to show.

    `confirmed` are skills the user ticked as "I really have this"; they count as part of the resume.
    """
    new = rev.new_text.strip()
    if not new:
        return "empty text"
    if "\\" in new or re.search(r"\$.*\$", new):
        return "contains LaTeX markup"
    limit = max(450, int(len(original) * 1.6)) if kind == "summary" else max(60, int(len(original) * 1.35))
    if len(new) > limit:
        return "much longer than the original"
    extra = []
    for c in confirmed:
        extra += variants(c, [])
    hay = (resume_text + "\n" + "\n".join(extra)).lower()
    nums = set(_NUM.findall(resume_text))
    for n in _NUM.findall(new):
        if n not in nums:
            return f"adds a number not in your resume ({n})"
    for s in jd.hard_skills:
        vs = variants(s.name, s.aliases)
        if any(_in(v, new.lower()) for v in vs) and not any(_in(v, hay) for v in vs):
            return f"claims a skill your resume does not show ({s.name})"
    for tok in _TECH.findall(new):
        if not _in(tok, hay):
            return f"adds a term not in your resume ({tok})"
    return None
