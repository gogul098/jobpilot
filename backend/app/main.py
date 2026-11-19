"""REST + SSE API.

POST /api/analyze            form: jd_text, tex_file | tex_text   -> {job_id}
GET  /api/jobs/{id}          status + analysis/result JSON
GET  /api/jobs/{id}/events   Server-Sent Events (replays history, then live)
POST /api/jobs/{id}/suggest  {"confirmed_skills": ["Docker"]}  re-suggest using skills you really have
POST /api/jobs/{id}/apply    {"edits": {"b03": "new text", ...}}
GET  /api/jobs/{id}/files/{original.pdf|revised.pdf|revised.tex}
DELETE /api/jobs/{id}         delete the job's temporary files now
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import gmail, jobs_search, storage
from .config import settings
from .events import count, emit, history
from .latex.compile import UnsafeLatex, check_safe

app = FastAPI(title="JobPilot")

# The web app is hosted on Vercel, so the browser calls this API cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-App-Token"],
    max_age=86400,
)
MAX_JD = 30_000


@app.on_event("startup")
async def _startup():
    app.state.redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))


def current_user(x_app_token: str | None = Header(None), token: str | None = Query(None)) -> str:
    """Single-user today: a shared token. Replace with real auth (e.g. Clerk/Supabase JWT) for many users."""
    if settings.app_token:
        given = x_app_token or token or ""
        if not secrets.compare_digest(given, settings.app_token):
            raise HTTPException(401, "bad or missing token")
    return settings.default_user


async def rate_limit(request: Request):
    """Fixed-window limit per client IP on endpoints that spend LLM quota."""
    if settings.hourly_limit <= 0:
        return
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    key = f"rate:{ip}:{int(time.time() // 3600)}"
    n = await app.state.redis.incr(key)
    if n == 1:
        await app.state.redis.expire(key, 3700)
    if n > settings.hourly_limit:
        raise HTTPException(429, f"Hourly limit of {settings.hourly_limit} analyses reached. Try again next hour.")


def _check_job(user: str, job_id: str):
    try:
        storage.job_dir(user, job_id)
    except ValueError:
        raise HTTPException(404)
    if storage.read(user, job_id, "original.tex") is None:
        raise HTTPException(404, "no such job")


@app.post("/api/analyze")
async def analyze(jd_text: str = Form(...), tex_file: UploadFile | None = File(None),
                  tex_text: str | None = Form(None), user: str = Depends(current_user),
                  _rl: None = Depends(rate_limit)):
    if not jd_text.strip() or len(jd_text) > MAX_JD:
        raise HTTPException(400, "job description is empty or too long")
    tex = (await tex_file.read()).decode("utf-8", "replace") if tex_file else (tex_text or "")
    if "\\documentclass" not in tex:
        raise HTTPException(400, "upload the .tex source of your resume (it must contain \\documentclass)")
    try:
        check_safe(tex)
    except UnsafeLatex as e:
        raise HTTPException(400, str(e))
    job_id = uuid.uuid4().hex[:16]
    storage.write(user, job_id, "original.tex", tex)
    start = await count(app.state.redis, job_id)
    await emit(app.state.redis, job_id, "queue", "queued", "Waiting for a worker")
    await app.state.redis.enqueue_job("analyze_job", user, job_id, jd_text, _job_id=f"an-{job_id}")
    return {"job_id": job_id, "from": start}


class ApplyBody(BaseModel):
    edits: dict[str, str]


class SuggestBody(BaseModel):
    confirmed_skills: list[str]


@app.post("/api/jobs/{job_id}/suggest")
async def resuggest(job_id: str, body: SuggestBody, user: str = Depends(current_user),
                    _rl: None = Depends(rate_limit)):
    """Re-run revisions after the user confirms job skills they really have."""
    _check_job(user, job_id)
    if storage.read(user, job_id, "analysis.json") is None:
        raise HTTPException(409, "analysis not finished")
    start = await count(app.state.redis, job_id)
    await emit(app.state.redis, job_id, "queue", "queued", "Waiting for a worker")
    await app.state.redis.enqueue_job("suggest_job", user, job_id, body.confirmed_skills[:30],
                                      _job_id=f"sg-{job_id}-{uuid.uuid4().hex[:6]}")
    return {"job_id": job_id, "from": start}


@app.post("/api/jobs/{job_id}/apply")
async def apply(job_id: str, body: ApplyBody, user: str = Depends(current_user)):
    _check_job(user, job_id)
    if storage.read(user, job_id, "analysis.json") is None:
        raise HTTPException(409, "analysis not finished")
    if not body.edits:
        raise HTTPException(400, "no edits selected")
    start = await count(app.state.redis, job_id)
    await emit(app.state.redis, job_id, "queue", "queued", "Waiting for a worker")
    await app.state.redis.enqueue_job("apply_job", user, job_id, body.edits,
                                      _job_id=f"ap-{job_id}-{uuid.uuid4().hex[:6]}")
    return {"job_id": job_id, "from": start}


@app.get("/api/jobs/{job_id}")
async def job(job_id: str, user: str = Depends(current_user)):
    _check_job(user, job_id)
    state = await app.state.redis.hgetall(f"job:{job_id}")
    return {"state": {k.decode(): v.decode() for k, v in state.items()},
            "analysis": storage.read_json(user, job_id, "analysis.json"),
            "result": storage.read_json(user, job_id, "result.json"),
            "email": storage.read_json(user, job_id, "email.json")}


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str, from_: int = Query(0, alias="from", ge=0),
                 user: str = Depends(current_user)):
    _check_job(user, job_id)
    redis = app.state.redis

    async def gen():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"jobch:{job_id}")
        try:
            for ev in await history(redis, job_id, from_):
                yield {"data": json.dumps(ev)}
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"data": msg["data"].decode()}
        finally:
            await pubsub.unsubscribe(f"jobch:{job_id}")
            await pubsub.aclose()

    return EventSourceResponse(gen())


@app.get("/api/jobs/{job_id}/files/{name}")
async def file(job_id: str, name: str, user: str = Depends(current_user)):
    _check_job(user, job_id)
    if name not in {"original.pdf", "revised.pdf", "revised.tex"}:
        raise HTTPException(404)
    data = storage.read(user, job_id, name)
    if data is None:
        raise HTTPException(404, "not ready")
    media = "application/pdf" if name.endswith(".pdf") else "application/x-tex"
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ---------------- phase 2: similar jobs ----------------

@app.post("/api/jobs/{job_id}/similar")
async def similar(job_id: str, user: str = Depends(current_user), _rl: None = Depends(rate_limit)):
    """Jobs like this one from the configured job APIs, ranked by how well your resume covers them."""
    _check_job(user, job_id)
    analysis = storage.read_json(user, job_id, "analysis.json")
    if not analysis:
        raise HTTPException(409, "analysis not finished")
    from .schemas import JDProfile
    jd = JDProfile(**analysis["jd"])
    resume = analysis["pdf_text"]
    key = "jobsearch:" + jobs_search.search_query(jd).lower() + "|" + (jd.location or "").lower()
    cached = await app.state.redis.get(key)
    if cached:  # job APIs have small free quotas: reuse a search for 6 hours
        raw = json.loads(cached)
        hits = [jobs_search.JobHit(**h) for h in raw["jobs"]]
        raw["jobs"] = [h.to_dict() for h in jobs_search.rank(hits, jd, resume)]
        return raw
    result = await jobs_search.find_similar(jd, resume)
    if result["jobs"]:
        await app.state.redis.set(key, json.dumps(result), ex=6 * 3600)
    return result


# ---------------- phase 2: email ----------------

class DraftBody(BaseModel):
    to: str = ""
    recipient_name: str = ""
    tone: str = "warm"


class SendBody(BaseModel):
    to: str
    subject: str
    body: str
    attachment: str = "revised.pdf"   # or original.pdf


@app.get("/api/gmail/status")
async def gmail_status(user: str = Depends(current_user)):
    return {"connected": gmail.configured(), "address": await gmail.sender_address(),
            "daily_limit": settings.email_daily_limit}


@app.post("/api/jobs/{job_id}/email/draft")
async def email_draft(job_id: str, body: DraftBody, user: str = Depends(current_user),
                      _rl: None = Depends(rate_limit)):
    _check_job(user, job_id)
    if storage.read(user, job_id, "analysis.json") is None:
        raise HTTPException(409, "analysis not finished")
    tone = body.tone if body.tone in ("warm", "formal") else "warm"
    start = await count(app.state.redis, job_id)
    await emit(app.state.redis, job_id, "queue", "queued", "Waiting for a worker")
    await app.state.redis.enqueue_job("draft_email_job", user, job_id, body.to.strip()[:200],
                                      body.recipient_name.strip()[:80], tone,
                                      _job_id=f"em-{job_id}-{uuid.uuid4().hex[:6]}")
    return {"job_id": job_id, "from": start}


@app.post("/api/jobs/{job_id}/email/send")
async def email_send(job_id: str, body: SendBody, user: str = Depends(current_user)):
    """Send the email exactly as the user approved it, from their Gmail, with the resume attached."""
    _check_job(user, job_id)
    if body.attachment not in ("revised.pdf", "original.pdf"):
        raise HTTPException(400, "bad attachment")
    pdf = storage.read(user, job_id, body.attachment) or storage.read(user, job_id, "original.pdf")
    if pdf is None:
        raise HTTPException(409, "No resume PDF for this job yet. Run the analysis first.")
    day = time.strftime("%Y%m%d")
    sent_key = f"emails:{user}:{day}"
    if int(await app.state.redis.get(sent_key) or 0) >= settings.email_daily_limit:
        raise HTTPException(429, f"Daily email limit ({settings.email_daily_limit}) reached. "
                                 "Sending many cold emails in a day gets Gmail accounts flagged.")
    try:
        res = await gmail.send(body.to, body.subject, body.body, pdf, _resume_filename(user, job_id))
    except gmail.GmailError as e:
        raise HTTPException(400, str(e))
    await app.state.redis.incr(sent_key)
    await app.state.redis.expire(sent_key, 2 * 86400)
    email = storage.read_json(user, job_id, "email.json") or {}
    email.setdefault("sent", []).append({"to": body.to.strip(), "subject": body.subject.strip(),
                                         "at": int(time.time()), "id": res.get("id")})
    storage.write(user, job_id, "email.json", email)
    return {"sent": True, **res}


def _resume_filename(user: str, job_id: str) -> str:
    analysis = storage.read_json(user, job_id, "analysis.json") or {}
    name = (analysis.get("pdf_text") or "Resume").strip().splitlines()[0]
    safe = "".join(c if c.isalnum() else "_" for c in name).strip("_")[:40] or "Resume"
    return f"{safe}_Resume.pdf"


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, user: str = Depends(current_user)):
    try:
        storage.delete(user, job_id)
    except ValueError:
        raise HTTPException(404)
    await app.state.redis.delete(f"job:{job_id}", f"jobev:{job_id}")
    return {"deleted": True}


@app.get("/api/health")
async def health():
    return {"ok": True}


_FRONT = Path(__file__).resolve().parents[2] / "frontend"
if _FRONT.exists():
    app.mount("/", StaticFiles(directory=_FRONT, html=True), name="frontend")
