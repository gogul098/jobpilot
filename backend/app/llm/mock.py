"""Deterministic stand-in for the LLM (LLM_MOCK=1) so the pipeline and UI run offline."""
from __future__ import annotations

import re


def mock_response(task: str, payload: dict) -> dict:
    if task == "jd_extract":
        text = payload["jd_text"]
        known = ["Python", "PyTorch", "TensorFlow", "Computer Vision", "NLP", "LLM", "SQL", "Docker",
                 "Kubernetes", "AWS", "FastAPI", "React", "Machine Learning", "Deep Learning", "Git",
                 "Transformers", "OpenCV", "Spark", "Statistics", "C++", "Java"]
        skills = [{"name": k, "importance": "must", "aliases": []} for k in known
                  if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", text, re.I)]
        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        first = text.strip().splitlines()[0][:80] if text.strip() else "Role"
        return {"title": first, "work_mode": "unknown", "hard_skills": skills,
                "keywords": [], "apply_email": email.group(0) if email else None,
                "responsibilities": [], "eligibility": [], "interview_focus": ["Mock mode: set GROQ_API_KEY"]}
    if task == "revise":
        missing = payload.get("missing_keywords", [])
        revs = []
        bullets = [b for b in payload["blocks"] if b["kind"] == "bullet"]
        for b in bullets:
            new = re.sub(r"^(Made|Created|Did)\b", "Developed", b["text"])
            if new != b["text"]:
                revs.append({"id": b["id"], "new_text": new, "keywords_added": [],
                             "reason": "Mock: stronger opening verb."})
        if bullets:  # an invented claim, to show the fact check blocking it
            b = bullets[0]
            revs.append({"id": b["id"], "new_text": b["text"] + ", deployed on Kubernetes",
                         "reason": "Mock: adds a JD keyword.", "keywords_added": ["Kubernetes"]})
        return {"revisions": revs, "missing_skills": missing, "general_advice": ["Mock mode is on."]}
    raise KeyError(task)
