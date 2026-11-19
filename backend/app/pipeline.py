"""The jobs the worker runs.

analyze: JD -> JSON, LaTeX -> blocks, compile + score, then suggest revisions.
suggest: (re)generate revisions, optionally with skills the user confirmed they have.
apply:   paste accepted text into the LaTeX, compile, re-score.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable

from .ats import score as ats
from .guard import check_revision
from .latex.apply import apply_revisions
from .latex.compile import compile_pdf
from .latex.extract import Block, extract_blocks
from .llm.router import ModelRouter
from .schemas import EmailDraft, JDProfile, RevisionSet
from . import storage

Progress = Callable[[str, str], Awaitable[None]]


class PipelineError(RuntimeError):
    pass


async def _compile(tex: str) -> bytes:
    res = await asyncio.to_thread(compile_pdf, tex)
    if not res.ok:
        raise PipelineError("LaTeX did not compile:\n" + res.log)
    return res.pdf


def _bullets(blocks: list[Block], edits: dict[str, str] | None = None) -> list[str]:
    edits = edits or {}
    return [edits.get(b.id, b.text) for b in blocks if b.kind == "bullet"]


async def analyze(router: ModelRouter, user: str, job_id: str, jd_text: str, progress: Progress) -> dict:
    tex = storage.read(user, job_id, "original.tex").decode("utf-8")

    await progress("jd", "Reading the job description")
    jd, jd_model = await router.complete_json("jd_extract", {"jd_text": jd_text[:20000]}, JDProfile)

    await progress("parse", "Finding the editable text in your LaTeX")
    blocks = extract_blocks(tex)
    if not blocks:
        raise PipelineError("No bullets or summary found. Supported: \\item, \\resumeItem{...}, \\cvitem{...}.")

    await progress("compile", "Compiling your current resume")
    pdf = await _compile(tex)
    storage.write(user, job_id, "original.pdf", pdf)

    await progress("score", "Scoring your current resume")
    before = ats.score(jd, pdf, _bullets(blocks))
    analysis = {"jd": jd.model_dump(), "blocks": [b.to_dict() for b in blocks],
                "pdf_text": ats.pdf_facts(pdf)["text"], "score_before": before.to_dict(),
                "confirmed_skills": [], "models": {"jd": jd_model}}
    storage.write(user, job_id, "analysis.json", analysis)
    return await _suggest(router, user, job_id, analysis, [], progress)


async def suggest(router: ModelRouter, user: str, job_id: str, confirmed: list[str], progress: Progress) -> dict:
    analysis = storage.read_json(user, job_id, "analysis.json")
    if not analysis:
        raise PipelineError("Run the analysis first.")
    return await _suggest(router, user, job_id, analysis, confirmed, progress)


async def _suggest(router: ModelRouter, user: str, job_id: str, analysis: dict,
                   confirmed: list[str], progress: Progress) -> dict:
    jd = JDProfile(**analysis["jd"])
    blocks = [Block(**b) for b in analysis["blocks"]]
    before = analysis["score_before"]
    confirmed = [c for c in confirmed if c in before["missing"]]
    still_missing = [m for m in before["missing"] if m not in confirmed]

    await progress("revise", "Writing revisions for this job"
                   + (f" (using {len(confirmed)} confirmed skill(s))" if confirmed else ""))
    payload = {"job": jd.model_dump(exclude_none=True),
               "blocks": [{"id": b.id, "kind": b.kind, "section": b.section, "context": b.context,
                           "text": b.text} for b in blocks],
               "skills_not_shown": before["weak_placement"],
               "confirmed_skills": confirmed,
               "missing_skills": still_missing}
    revs, rev_model = await router.complete_json("revise", payload, RevisionSet)

    await progress("guard", "Fact-checking every revision and measuring its gain")
    by_id = {b.id: b for b in blocks}
    resume_text = "\n".join(b.text for b in blocks) + "\n" + analysis["pdf_text"]
    base = ats.text_points(jd, resume_text, _bullets(blocks))
    suggestions, rejected = [], []
    for r in revs.revisions:
        b = by_id.get(r.id)
        if not b or r.new_text.strip() == b.text:
            continue
        new = r.new_text.strip()
        why = check_revision(r, b.text, resume_text, jd, confirmed, b.kind)
        item = {"id": r.id, "section": b.section, "context": b.context, "kind": b.kind, "old": b.text,
                "new": new, "reason": r.reason, "keywords_added": r.keywords_added}
        if why:
            rejected.append({**item, "rejected_because": why})
            continue
        gain = ats.text_points(jd, resume_text + "\n" + new, _bullets(blocks, {b.id: new})) - base
        suggestions.append({**item, "gain": round(gain, 1)})
    suggestions.sort(key=lambda s: -s["gain"])

    accepted = {s["id"]: s["new"] for s in suggestions}
    combined = round(ats.text_points(jd, resume_text + "\n" + "\n".join(accepted.values()),
                                     _bullets(blocks, accepted)) - base, 1)

    analysis.update({"suggestions": suggestions, "rejected": rejected, "confirmed_skills": confirmed,
                     "missing_skills": still_missing, "advice": revs.general_advice,
                     "projected_gain": combined})
    analysis["models"]["revise"] = rev_model
    storage.write(user, job_id, "analysis.json", analysis)
    return {"stage": "analyzed", "suggestions": len(suggestions), "score_before": before["total"],
            "projected_gain": combined}


async def apply(user: str, job_id: str, edits: dict[str, str], progress: Progress) -> dict:
    analysis = storage.read_json(user, job_id, "analysis.json")
    if not analysis:
        raise PipelineError("Run the analysis first.")
    tex = storage.read(user, job_id, "original.tex").decode("utf-8")
    blocks = [Block(**b) for b in analysis["blocks"]]

    await progress("apply", "Pasting your accepted changes into the LaTeX")
    new_tex = apply_revisions(tex, blocks, edits)
    storage.write(user, job_id, "revised.tex", new_tex)

    await progress("compile", "Compiling the revised PDF")
    pdf = await _compile(new_tex)
    storage.write(user, job_id, "revised.pdf", pdf)

    await progress("score", "Re-scoring")
    after = ats.score(JDProfile(**analysis["jd"]), pdf, _bullets(blocks, edits))
    result = {"score_before": analysis["score_before"]["total"], "score_after": after.to_dict(),
              "applied": sorted(edits)}
    storage.write(user, job_id, "result.json", result)
    return {"stage": "applied", "score_after": after.total}


# ---------------- phase 2: application email ----------------

_URL_RE = re.compile(r"https?://[^\s<>()\"']+")


def candidate_profile(tex: str, analysis: dict) -> dict:
    """Name, header links, education line and summary, read from the resume itself."""
    lines = [l.strip() for l in analysis["pdf_text"].splitlines() if l.strip()]
    body_start = max(0, tex.find("\\begin{document}"))
    head_end = tex.find("\\section", body_start)
    header = tex[body_start:head_end if head_end > 0 else body_start + 2000]
    links = [u for u in re.findall(r"\\(?:href|url)\{([^}]*)\}", header) if u.startswith("http")]
    edu = ""
    for i, l in enumerate(lines):
        if l.lower() == "education" and i + 1 < len(lines):
            edu = " ".join(lines[i + 1:i + 3])
            break
    summary = next((b["text"] for b in analysis["blocks"] if b["kind"] == "summary"), "")
    return {"name": lines[0] if lines else "", "links": links, "education": edu[:200], "summary": summary}


def resume_projects(analysis: dict) -> list[dict]:
    projects: dict[str, dict] = {}
    for b in analysis["blocks"]:
        if b["kind"] != "bullet" or not b.get("context"):
            continue
        name, *stack = b["context"].split(" | ")
        p = projects.setdefault(name, {"name": name, "stack": ", ".join(stack), "links": b.get("links", []),
                                       "bullets": []})
        p["bullets"].append(b["text"])
    return list(projects.values())


def check_email(body: str, subject: str, known_text: str, known_links: set[str]) -> list[str]:
    """Warnings for anything in the email that isn't backed by the resume."""
    warnings = []
    nums = set(re.findall(r"\d+(?:[.,]\d+)?", known_text))
    text = _URL_RE.sub(" ", subject + "\n" + body)   # digits inside links are checked as links
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", " ", text)
    for n in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", text):
        if n not in nums:
            warnings.append(f"The number {n} isn't in your resume.")
    for u in _URL_RE.findall(body):
        if u.rstrip(".,;") not in known_links:
            warnings.append(f"The link {u} isn't in your resume.")
    return sorted(set(warnings))


async def draft_email(router: ModelRouter, user: str, job_id: str, recipient: str, recipient_name: str,
                      tone: str, progress: Progress) -> dict:
    analysis = storage.read_json(user, job_id, "analysis.json")
    if not analysis:
        raise PipelineError("Run the analysis first.")
    tex = storage.read(user, job_id, "original.tex").decode("utf-8")
    jd = analysis["jd"]
    cand = candidate_profile(tex, analysis)
    projects = resume_projects(analysis)

    await progress("email", "Writing the email for this job")
    payload = {"job": {k: jd.get(k) for k in ("title", "company", "location", "employment_type",
                                               "responsibilities", "hard_skills", "keywords")},
               "candidate": cand, "projects": projects, "tone": tone, "recipient_name": recipient_name}
    draft, model = await router.complete_json("email_draft", payload, EmailDraft)

    known_text = analysis["pdf_text"] + "\n" + "\n".join(b["text"] for b in analysis["blocks"])
    known_links = set(cand["links"]) | {u for p in projects for u in p["links"]}
    has_revised = storage.read(user, job_id, "revised.pdf") is not None
    email = {"to": recipient or jd.get("apply_email") or "", "subject": draft.subject.strip(),
             "body": draft.body.strip(), "projects_used": draft.projects_used,
             "warnings": check_email(draft.body, draft.subject, known_text, known_links),
             "attachment": "revised.pdf" if has_revised else "original.pdf", "model": model, "sent": []}
    old = storage.read_json(user, job_id, "email.json") or {}
    email["sent"] = old.get("sent", [])
    storage.write(user, job_id, "email.json", email)
    return {"stage": "email_drafted", "warnings": len(email["warnings"])}
