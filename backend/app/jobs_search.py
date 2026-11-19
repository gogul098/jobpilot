"""Find jobs similar to the one being analysed, and rank them against the user's resume.

Providers (each optional, set its key to enable):
- JSearch (RapidAPI): aggregates Google for Jobs, which includes LinkedIn, Indeed, Naukri,
  Glassdoor and company career pages. Often returns a direct LinkedIn apply link.
- Adzuna: free official API with India coverage.
Without keys, only the LinkedIn search link is offered.

We never log in to LinkedIn or submit applications automatically: that breaks LinkedIn's
user agreement and gets accounts restricted. The user opens the link and applies.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlencode

import httpx

from .ats.synonyms import variants
from .config import settings
from .schemas import JDProfile


@dataclass
class JobHit:
    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    posted: str = ""
    description: str = ""
    linkedin_url: str = ""
    match: int = 0                    # 0-100, how well your resume covers this job's skills
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["description"] = self.description[:6000]
        return d


def linkedin_search_url(jd: JDProfile) -> str:
    """A LinkedIn job search for similar roles posted in the last week (no login needed to open)."""
    params = {"keywords": search_query(jd), "f_TPR": "r604800"}
    if jd.location:
        params["location"] = jd.location.split(",")[0]
    if (jd.employment_type or "").lower().startswith("intern"):
        params["f_JT"] = "I"
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def search_query(jd: JDProfile) -> str:
    title = re.sub(r"[\(\[].*?[\)\]]", "", jd.title).split(" - ")[0].split(",")[0].strip()
    title = re.sub(r"\s+", " ", title)[:60]
    must = [s.name for s in jd.hard_skills if s.importance == "must"][:2]
    return " ".join([title, *must]).strip()


def _hid(*parts: str) -> str:
    return hashlib.sha1("|".join(p.lower().strip() for p in parts).encode()).hexdigest()[:12]


async def _jsearch(client: httpx.AsyncClient, query: str, location: str) -> list[JobHit]:
    q = f"{query} in {location}" if location else query
    r = await client.get("https://jsearch.p.rapidapi.com/search",
                         params={"query": q, "page": 1, "num_pages": 1, "country": settings.jobs_country,
                                 "date_posted": "month"},
                         headers={"X-RapidAPI-Key": settings.jsearch_key,
                                  "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
    r.raise_for_status()
    hits = []
    for j in r.json().get("data", []):
        opts = j.get("apply_options") or []
        li = next((o.get("apply_link", "") for o in opts if "linkedin" in (o.get("publisher") or "").lower()), "")
        loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if x)
        hits.append(JobHit(
            id=_hid(j.get("employer_name", ""), j.get("job_title", ""), loc),
            title=j.get("job_title", ""), company=j.get("employer_name", ""), location=loc,
            url=j.get("job_apply_link") or li, source=j.get("job_publisher") or "JSearch",
            posted=(j.get("job_posted_at_datetime_utc") or "")[:10],
            description=j.get("job_description") or "", linkedin_url=li))
    return hits


async def _adzuna(client: httpx.AsyncClient, query: str, location: str) -> list[JobHit]:
    params = {"app_id": settings.adzuna_id, "app_key": settings.adzuna_key, "what": query,
              "results_per_page": 25, "max_days_old": 30, "content-type": "application/json"}
    if location:
        params["where"] = location.split(",")[0]
    r = await client.get(f"https://api.adzuna.com/v1/api/jobs/{settings.jobs_country}/search/1", params=params)
    r.raise_for_status()
    hits = []
    for j in r.json().get("results", []):
        company = (j.get("company") or {}).get("display_name", "")
        loc = (j.get("location") or {}).get("display_name", "")
        hits.append(JobHit(id=_hid(company, j.get("title", ""), loc),
                           title=re.sub(r"<[^>]+>", "", j.get("title", "")), company=company, location=loc,
                           url=j.get("redirect_url", ""), source="Adzuna",
                           posted=(j.get("created") or "")[:10],
                           description=re.sub(r"<[^>]+>", "", j.get("description", ""))))
    return hits


def _found(term: str, aliases: list[str], hay: str) -> bool:
    return any(re.search(r"(?<![a-z0-9+#])" + re.escape(v) + r"(?![a-z0-9+#])", hay) for v in variants(term, aliases))


def rank(hits: list[JobHit], jd: JDProfile, resume_text: str) -> list[JobHit]:
    """Deterministic match: how much of each job's skill vocabulary your resume shows.

    The vocabulary is the analysed job's skills plus your resume's tools, so a job that asks
    for things you have scores high, and one built around tools you lack scores low.
    """
    res = resume_text.lower()
    vocab: dict[str, list[str]] = {s.name: s.aliases for s in jd.hard_skills}
    for term in settings_vocab():
        vocab.setdefault(term, [])
    out = []
    for h in hits:
        text = f"{h.title}\n{h.description}".lower()
        wanted = [t for t, al in vocab.items() if _found(t, al, text)]
        if not wanted:
            h.match = 0
        else:
            have = [t for t in wanted if _found(t, vocab[t], res)]
            h.matched, h.missing = have, [t for t in wanted if t not in have]
            title_bonus = 10 if any(w in h.title.lower() for w in re.findall(r"[a-z]{3,}", jd.title.lower())) else 0
            h.match = min(100, round(90 * len(have) / len(wanted)) + title_bonus)
        out.append(h)
    out.sort(key=lambda h: h.posted, reverse=True)   # newest first among equal matches
    out.sort(key=lambda h: h.match, reverse=True)
    return out


def settings_vocab() -> list[str]:
    """Common tech terms used to judge any job, beyond the analysed job's own skills."""
    return ["Python", "Java", "C++", "JavaScript", "TypeScript", "SQL", "Go", "Rust", "React", "Node.js",
            "FastAPI", "Django", "Flask", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "PyTorch",
            "TensorFlow", "Scikit-learn", "Pandas", "NumPy", "Spark", "Hadoop", "Kafka", "Redis",
            "PostgreSQL", "MongoDB", "LangChain", "LangGraph", "RAG", "LLM", "NLP", "Computer Vision",
            "OpenCV", "Machine Learning", "Deep Learning", "Transformers", "Hugging Face", "MLOps",
            "Git", "Linux", "REST API", "Microservices", "Tableau", "Power BI", "Excel", "Statistics"]


async def find_similar(jd: JDProfile, resume_text: str, limit: int = 20) -> dict:
    query = search_query(jd)
    location = jd.location or settings.jobs_default_location
    result = {"query": query, "location": location, "linkedin_search": linkedin_search_url(jd),
              "jobs": [], "providers": [], "errors": []}
    if settings.jobs_mock:
        from .llm.mock import mock_jobs
        hits = [JobHit(**h) for h in mock_jobs(jd)]
        result["providers"].append("mock")
    else:
        hits = []
        async with httpx.AsyncClient(timeout=20) as client:
            for name, enabled, fn in [("JSearch", bool(settings.jsearch_key), _jsearch),
                                      ("Adzuna", bool(settings.adzuna_id and settings.adzuna_key), _adzuna)]:
                if not enabled:
                    continue
                try:
                    hits += await fn(client, query, location)
                    result["providers"].append(name)
                except Exception as e:  # one provider failing shouldn't hide the others
                    result["errors"].append(f"{name}: {str(e)[:120]}")
    seen, unique = set(), []
    for h in hits:
        if h.id not in seen and h.url:
            seen.add(h.id)
            unique.append(h)
    result["jobs"] = [h.to_dict() for h in rank(unique, jd, resume_text)[:limit]]
    return result
