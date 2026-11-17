"""The two jobs the worker runs: analyze (JD + resume -> score + suggested revisions) and apply."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .ats import score as ats
from .guard import check_revision
from .latex.apply import apply_revisions
from .latex.compile import compile_pdf
from .latex.extract import Block, extract_blocks
from .llm.router import ModelRouter
from .schemas import JDProfile, RevisionSet
from . import storage

Progress = Callable[[str, str], Awaitable[None]]


class PipelineError(RuntimeError):
    pass


async def _compile(tex: str) -> bytes:
    res = await asyncio.to_thread(compile_pdf, tex)
    if not res.ok:
        raise PipelineError("LaTeX did not compile:\n" + res.log)
    return res.pdf


async def analyze(router: ModelRouter, user: str, job_id: str, jd_text: str, progress: Progress) -> dict:
    tex = storage.read(user, job_id, "original.tex").decode("utf-8")

    await progress("jd", "Reading the job description")
    jd, jd_model = await router.complete_json("jd_extract", {"jd_text": jd_text[:20000]}, JDProfile)

    await progress("parse", "Finding the editable text in your LaTeX")
    blocks = extract_blocks(tex)
    if not blocks:
        raise PipelineError("No bullets or summary found. Supported: \\item, \\resumeItem{...}, \\cvitem{...}.")
    bullets = [b.text for b in blocks if b.kind == "bullet"]

    await progress("compile", "Compiling your current resume")
    pdf = await _compile(tex)
    storage.write(user, job_id, "original.pdf", pdf)

    await progress("score", "Scoring your current resume")
    before = ats.score(jd, pdf, bullets)

    await progress("revise", "Asking the model for revisions")
    payload = {"job": jd.model_dump(exclude_none=True),
               "blocks": [{"id": b.id, "kind": b.kind, "section": b.section, "text": b.text} for b in blocks],
               "missing_keywords": before.missing}
    revs, rev_model = await router.complete_json("revise", payload, RevisionSet)

    await progress("guard", "Checking revisions for invented facts")
    by_id = {b.id: b for b in blocks}
    resume_text = "\n".join(b.text for b in blocks) + "\n" + ats.pdf_facts(pdf)["text"]
    suggestions, rejected = [], []
    for r in revs.revisions:
        b = by_id.get(r.id)
        if not b or r.new_text.strip() == b.text:
            continue
        why = check_revision(r, b.text, resume_text, jd)
        item = {"id": r.id, "section": b.section, "kind": b.kind, "old": b.text,
                "new": r.new_text.strip(), "reason": r.reason, "keywords_added": r.keywords_added}
        (rejected if why else suggestions).append({**item, **({"rejected_because": why} if why else {})})

    result = {"jd": jd.model_dump(), "blocks": [b.to_dict() for b in blocks],
              "score_before": before.to_dict(), "suggestions": suggestions, "rejected": rejected,
              "missing_skills": revs.missing_skills, "advice": revs.general_advice,
              "models": {"jd": jd_model, "revise": rev_model}}
    storage.write(user, job_id, "analysis.json", result)
    return {"stage": "analyzed", "suggestions": len(suggestions), "score_before": before.total}


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
    by_id = {b.id: b for b in blocks}
    bullets = [edits.get(b.id, b.text) for b in blocks if b.kind == "bullet"]
    after = ats.score(JDProfile(**analysis["jd"]), pdf, bullets)
    result = {"score_before": analysis["score_before"]["total"], "score_after": after.to_dict(),
              "applied": sorted(edits)}
    storage.write(user, job_id, "result.json", result)
    return {"stage": "applied", "score_after": after.total}
