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
        revs = []
        terms = payload.get("skills_not_shown", []) + payload.get("confirmed_skills", [])
        bullets = [b for b in payload["blocks"] if b["kind"] == "bullet"]
        for b in bullets:
            new = re.sub(r"^(Made|Created|Did)\b", "Developed", b["text"])
            if new != b["text"]:
                revs.append({"id": b["id"], "new_text": new, "keywords_added": [],
                             "reason": "Mock: stronger opening verb."})
        for t, b in zip(terms, reversed(bullets)):
            revs.append({"id": b["id"], "new_text": b["text"].rstrip(".") + f" using {t}",
                         "reason": f"Mock: shows {t} in a bullet.", "keywords_added": [t]})
        if bullets:  # an invented claim, to show the fact check blocking it
            b = bullets[0]
            revs.append({"id": b["id"], "new_text": b["text"] + ", deployed on Kubernetes",
                         "reason": "Mock: adds a JD keyword.", "keywords_added": ["Kubernetes"]})
        return {"revisions": revs, "missing_skills": payload.get("missing_skills", []),
                "general_advice": ["Mock mode is on."]}
    if task == "email_draft":
        job, cand, projects = payload["job"], payload["candidate"], payload["projects"][:2]
        greet = f"Hi {payload['recipient_name']}," if payload.get("recipient_name") else f"Hello {job.get('company') or 'hiring'} team,"
        lines = [f"- {p['name']}: {p['bullets'][0] if p['bullets'] else ''} {p['links'][0] if p['links'] else ''}".strip()
                 for p in projects]
        body = (f"{greet}\n\n{cand['education']}. I'm applying for the {job['title']} role.\n\n"
                + "\n".join(lines) + "\n\nMy resume is attached. Happy to walk you through either project on a call.\n\n"
                + f"{cand['name']}\n" + "\n".join(cand["links"]))
        return {"subject": f"Application: {job['title']} - {cand['name']}", "body": body,
                "projects_used": [p["name"] for p in projects]}
    raise KeyError(task)


def mock_jobs(jd) -> list[dict]:
    """Fake search results for offline demos (JOBS_MOCK=1)."""
    rows = [("ML Engineer Intern", "Northwind AI", "Bengaluru, Karnataka, India", "Python, PyTorch, Docker, computer vision, SQL"),
            ("AI Engineer Intern - LLM Agents", "Contoso Labs", "Chennai, Tamil Nadu, India", "Python, LangGraph, RAG, FastAPI, LLM evaluation"),
            ("Data Science Intern", "Fabrikam Analytics", "Hyderabad, Telangana, India", "Python, SQL, Pandas, Statistics, Tableau"),
            ("Backend Developer Intern", "Tailspin Tech", "Coimbatore, Tamil Nadu, India", "Java, Spring, Kubernetes, AWS, Kafka"),
            ("Computer Vision Research Intern", "Adatum Robotics", "Bengaluru, Karnataka, India", "PyTorch, OpenCV, segmentation, Deep Learning")]
    out = []
    for i, (t, c, l, d) in enumerate(rows):
        out.append({"id": f"mock{i}", "title": t, "company": c, "location": l, "source": "Mock",
                    "url": f"https://example.com/jobs/{i}", "posted": f"2026-11-{18 - i:02d}",
                    "description": f"{t} at {c}. Requirements: {d}.",
                    "linkedin_url": f"https://www.linkedin.com/jobs/view/{4000000000 + i}/" if i % 2 == 0 else ""})
    return out
