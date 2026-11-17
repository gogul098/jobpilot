"""Deterministic ATS score (0-100). Same input -> same score; no LLM involved.

Real ATSs (Workday, Greenhouse, Lever...) parse the PDF into fields and recruiters
search those fields. So the score measures two things: does the compiled PDF parse
cleanly, and does it contain what a recruiter for this job will search for.

    parseability   30   text layer, contact info, single column, no images, clean glyphs
    keywords       35   JD hard skills (must x2, nice x1) + JD phrases (x0.5), placement-aware
    sections       10   standard headings, dates present
    bullets        15   action verb, number, sensible length, no first person
    length         10   page count, word count, typos-ish hygiene
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import pymupdf

from ..schemas import JDProfile
from .synonyms import variants

STANDARD_HEADINGS = {
    "education": ["education", "academic"],
    "skills": ["skills", "technical skills", "technologies"],
    "experience": ["experience", "work experience", "employment", "internships",
                   "projects", "research experience", "research"],
}
ACTION_VERBS = set("""achieved analyzed architected automated benchmarked built collaborated compiled
created cut debugged decreased delivered deployed designed developed drove engineered evaluated
fine-tuned flagged forecast generated implemented improved increased integrated launched led
maintained merged migrated modeled optimized orchestrated packaged parsed predicted processed
prototyped published reached recovered redesigned reduced refactored researched resolved scaled
shipped simplified solved streamlined tested trained transformed tuned vectorised vectorized wrote
converts predicts ran recovered combined categorizes explains audits reached""".split())
FIRST_PERSON = re.compile(r"\b(I|me|my|mine|we|our)\b")


@dataclass
class Component:
    name: str
    score: float
    max: float
    findings: list[str] = field(default_factory=list)


@dataclass
class ATSReport:
    total: float
    components: list[Component]
    matched: list[str]
    missing: list[str]
    weak_placement: list[str]   # only found in the Skills list, not shown in any bullet

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- PDF analysis ----------

def pdf_facts(pdf: bytes) -> dict:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    text = "\n".join(p.get_text("text") for p in doc)
    pages = len(doc)
    images = sum(len(p.get_images(full=True)) for p in doc)
    side_by_side = 0.0
    total_chars = max(1, len(text))
    for p in doc:
        w = p.rect.width
        blocks = [b for b in p.get_text("blocks") if b[4].strip()]
        left = [b for b in blocks if b[2] < w * 0.55 and (b[2] - b[0]) < w * 0.5]
        right = [b for b in blocks if b[0] > w * 0.45 and (b[2] - b[0]) < w * 0.5]
        for r in right:
            if any(l[1] < r[3] and r[1] < l[3] for l in left):
                side_by_side += len(r[4])
    head = text[: max(400, len(text) // 6)]
    return {
        "text": text,
        "pages": pages,
        "images": images,
        "column_ratio": side_by_side / total_chars,
        "email_top": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", head)),
        "phone_top": bool(re.search(r"(\+?\d[\d\s-]{8,}\d)", head)),
        "garbled": len(re.findall(r"\(cid:\d+\)|[ﬀ-ﬆ]|�", text)),
    }


# ---------- keyword matching ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _found(term_variants: list[str], hay: str) -> bool:
    for v in term_variants:
        v = _norm(v)
        if not v:
            continue
        if re.search(r"(?<![a-z0-9+#])" + re.escape(v) + r"(?![a-z0-9+#])", hay):
            return True
    return False


def keyword_component(jd: JDProfile, full_text: str, bullet_text: str) -> tuple[Component, list, list, list]:
    hay, bhay = _norm(full_text), _norm(bullet_text)
    items: list[tuple[str, list[str], float]] = []
    for s in jd.hard_skills:
        items.append((s.name, variants(s.name, s.aliases), 2.0 if s.importance == "must" else 1.0))
    have = {_norm(n) for n, _, _ in items}
    for k in jd.keywords:
        if _norm(k) not in have:
            items.append((k, variants(k, []), 0.5))
    if not items:
        return Component("keywords", 35, 35, ["No skills found in the job description."]), [], [], []
    got = total = 0.0
    matched, missing, weak = [], [], []
    for name, vs, w in items:
        total += w
        if _found(vs, bhay):
            got += w
            matched.append(name)
        elif _found(vs, hay):
            got += w * 0.7
            matched.append(name)
            weak.append(name)
        else:
            missing.append(name)
    score = 35 * got / total
    f = [f"Matched {len(matched)} of {len(items)} job terms."]
    if missing:
        f.append("Missing: " + ", ".join(missing[:12]))
    if weak:
        f.append("Only in Skills list (show them in a bullet): " + ", ".join(weak[:8]))
    return Component("keywords", round(score, 1), 35, f), matched, missing, weak


# ---------- other components ----------

def parse_component(facts: dict) -> Component:
    s, f = 30.0, []
    if len(facts["text"].strip()) < 300:
        return Component("parseability", 0, 30, ["Almost no text could be extracted: the PDF may be an image."])
    if not facts["email_top"]:
        s -= 5; f.append("Email not found near the top.")
    if not facts["phone_top"]:
        s -= 3; f.append("Phone number not found near the top.")
    if facts["column_ratio"] > 0.15:
        s -= 10; f.append(f"Multi-column layout ({facts['column_ratio']:.0%} of text side by side); many ATSs read columns out of order.")
    if facts["images"]:
        s -= min(6, 2 * facts["images"]); f.append(f"{facts['images']} image(s): text inside images is invisible to an ATS.")
    if facts["garbled"]:
        s -= min(6, facts["garbled"]); f.append(f"{facts['garbled']} unreadable glyph(s) (ligatures or missing font maps); add \\pdfgentounicode=1 / \\input{{glyphtounicode}}.")
    if not f:
        f.append("Parses cleanly: single column, readable text, contact details at the top.")
    return Component("parseability", max(0, s), 30, f)


def section_component(text: str) -> Component:
    low = text.lower()
    s, f = 0.0, []
    for key, names in STANDARD_HEADINGS.items():
        if any(re.search(r"(^|\n)\s*" + re.escape(n) + r"\s*(\n|$)", low) for n in names):
            s += 2.5
        else:
            f.append(f"No standard '{key.title()}' heading found.")
    if re.search(r"\b(19|20)\d{2}\b", text):
        s += 2.5
    else:
        f.append("No dates found; add years to education and projects.")
    if not f:
        f.append("Standard headings and dates present.")
    return Component("sections", s, 10, f)


def bullet_component(bullets: list[str]) -> Component:
    if not bullets:
        return Component("bullets", 0, 15, ["No bullet points detected."])
    verb = num = length = person = 0
    for b in bullets:
        first = re.sub(r"[^a-z-]", "", b.split()[0].lower()) if b.split() else ""
        verb += first in ACTION_VERBS or first.endswith("ed")
        num += bool(re.search(r"\d", b))
        length += 50 <= len(b) <= 230
        person += not FIRST_PERSON.search(b)
    n = len(bullets)
    s = 15 * (0.3 * verb / n + 0.35 * num / n + 0.2 * length / n + 0.15 * person / n)
    f = [f"{verb}/{n} start with an action verb, {num}/{n} include a number, {length}/{n} are 1-2 lines."]
    if person < n:
        f.append(f"{n - person} bullet(s) use first person (I/my/we).")
    return Component("bullets", round(s, 1), 15, f)


def length_component(facts: dict) -> Component:
    words = len(facts["text"].split())
    s, f = 0.0, []
    s += 5 if facts["pages"] == 1 else 3 if facts["pages"] == 2 else 0
    if facts["pages"] > 1:
        f.append(f"{facts['pages']} pages; one page is the norm for students and interns.")
    s += 3 if 300 <= words <= 850 else 1
    if not 300 <= words <= 850:
        f.append(f"{words} words; aim for 300-850.")
    dup = re.findall(r"\b(\w+)\s+\1\b", facts["text"], re.I)
    dup = [d for d in dup if not d.isdigit()]
    s += 2 if not dup else 0
    if dup:
        f.append("Repeated words: " + ", ".join(sorted(set(dup))[:5]))
    if not f:
        f.append(f"{facts['pages']} page, {words} words.")
    return Component("length", s, 10, f)


def score(jd: JDProfile, pdf: bytes, bullets: list[str]) -> ATSReport:
    facts = pdf_facts(pdf)
    kw, matched, missing, weak = keyword_component(jd, facts["text"], "\n".join(bullets))
    comps = [parse_component(facts), kw, section_component(facts["text"]),
             bullet_component(bullets), length_component(facts)]
    total = round(sum(c.score for c in comps), 1)
    return ATSReport(total, comps, matched, missing, weak)
