import asyncio
import base64
import email
import json

import httpx
import pytest

from app import gmail, jobs_search, pipeline
from app.config import settings
from app.schemas import JDProfile, Skill

JD = JDProfile(title="AI Engineer Intern - LLM", location="Bengaluru, India", employment_type="Internship",
               hard_skills=[Skill(name="Python"), Skill(name="LangGraph"), Skill(name="FastAPI", importance="nice")])
RESUME = "Python, FastAPI, PyTorch, Docker. Built a FastAPI service."


def test_linkedin_search_link():
    url = jobs_search.linkedin_search_url(JD)
    assert url.startswith("https://www.linkedin.com/jobs/search/?")
    assert "keywords=AI+Engineer+Intern+Python+LangGraph" in url
    assert "location=Bengaluru" in url and "f_JT=I" in url


def test_rank_orders_by_resume_coverage():
    hits = [jobs_search.JobHit(id="a", title="Java Dev", company="X", location="", url="u1", source="t",
                               description="Java, Kubernetes, Kafka"),
            jobs_search.JobHit(id="b", title="AI Engineer Intern", company="Y", location="", url="u2", source="t",
                               description="Python, FastAPI, LangGraph")]
    ranked = jobs_search.rank(hits, JD, RESUME)
    assert ranked[0].id == "b" and ranked[0].match > ranked[1].match
    assert "LangGraph" in ranked[0].missing and "Python" in ranked[0].matched


def test_jsearch_parsing_and_linkedin_link(monkeypatch):
    payload = {"data": [{"job_title": "ML Intern", "employer_name": "Acme", "job_city": "Bengaluru",
                         "job_country": "IN", "job_apply_link": "https://acme.example/apply",
                         "job_description": "Python FastAPI", "job_publisher": "LinkedIn",
                         "job_posted_at_datetime_utc": "2026-11-15T10:00:00Z",
                         "apply_options": [{"publisher": "LinkedIn", "apply_link": "https://www.linkedin.com/jobs/view/1/"}]}]}

    def handler(req: httpx.Request):
        assert req.headers["X-RapidAPI-Key"] == "k"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(settings, "jsearch_key", "k")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hits = asyncio.run(jobs_search._jsearch(client, "ML Intern", "Bengaluru"))
    assert hits[0].linkedin_url == "https://www.linkedin.com/jobs/view/1/" and hits[0].posted == "2026-11-15"


def test_gmail_send_builds_mime_with_attachment(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "sec")
    monkeypatch.setattr(settings, "gmail_refresh_token", "rt")
    monkeypatch.setattr(settings, "gmail_mock", False)
    gmail._cache.update(token=None, exp=0, address=None)
    seen = {}

    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        if req.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "me@gmail.com"})
        assert req.headers["Authorization"] == "Bearer at"
        seen["raw"] = base64.urlsafe_b64decode(json.loads(req.content)["raw"])
        return httpx.Response(200, json={"id": "m1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(gmail.send("hr@acme.example", "Application: ML Intern", "Hello", b"%PDF-1.4", "R.pdf", client))
    assert res["id"] == "m1"
    msg = email.message_from_bytes(seen["raw"])
    assert msg["To"] == "hr@acme.example" and msg["From"] == "me@gmail.com"
    att = [p for p in msg.walk() if p.get_filename() == "R.pdf"]
    assert att and att[0].get_payload(decode=True) == b"%PDF-1.4"


@pytest.mark.parametrize("to,subject", [("not-an-email", "Hi"), ("a@b.co", "two\nlines"), ("a@b.co", "")])
def test_gmail_rejects_bad_input(to, subject, monkeypatch):
    monkeypatch.setattr(settings, "gmail_mock", True)
    with pytest.raises(gmail.GmailError):
        asyncio.run(gmail.send(to, subject, "body", None, "r.pdf"))


def test_email_fact_check():
    known = "Reached 0.635 micro-F1 on 100 sections"
    links = {"https://github.com/gogul098/planforge"}
    ok = pipeline.check_email("Got 0.635 F1. https://github.com/gogul098/planforge", "Hi", known, links)
    bad = pipeline.check_email("Got 0.95 F1. See https://evil.example/x", "Hi", known, links)
    assert ok == [] and len(bad) == 2
