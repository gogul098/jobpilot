"""arq worker: pulls jobs from Redis, calls the model router, compiles LaTeX.

Run:  arq app.worker.WorkerSettings
Jobs survive an API restart (they live in Redis) and are retried if a worker dies.
"""
from __future__ import annotations

import logging

import httpx
from arq import Retry, cron
from arq.connections import RedisSettings

from . import pipeline, storage
from .config import settings
from .events import emit
from .llm.router import AllModelsBusy, ModelRouter

logging.basicConfig(level=logging.INFO)


async def startup(ctx):
    ctx["http"] = httpx.AsyncClient(timeout=settings.llm_timeout)
    ctx["router"] = ModelRouter(ctx["redis"], ctx["http"])


async def shutdown(ctx):
    await ctx["http"].aclose()


def _progress(ctx, job_id):
    async def p(stage, message):
        await emit(ctx["redis"], job_id, stage, "running", message)
    return p


async def _run(ctx, job_id, coro_factory):
    try:
        out = await coro_factory()
        extra = {k: v for k, v in out.items() if k != "stage"}
        await emit(ctx["redis"], job_id, out["stage"], "done", "", **extra)
        return out
    except AllModelsBusy as e:
        await emit(ctx["redis"], job_id, "queue", "waiting", f"Models busy, retrying in {e.retry_in:.0f}s")
        raise Retry(defer=e.retry_in + 1)
    except Exception as e:  # surface every failure to the user
        await emit(ctx["redis"], job_id, "error", "failed", str(e)[:2000])
        logging.exception("job %s failed", job_id)
        return {"stage": "error", "error": str(e)}


async def analyze_job(ctx, user: str, job_id: str, jd_text: str):
    return await _run(ctx, job_id, lambda: pipeline.analyze(ctx["router"], user, job_id, jd_text,
                                                            _progress(ctx, job_id)))


async def apply_job(ctx, user: str, job_id: str, edits: dict):
    return await _run(ctx, job_id, lambda: pipeline.apply(user, job_id, edits, _progress(ctx, job_id)))


async def sweep_tmp(ctx):
    removed = storage.sweep()
    if removed:
        logging.info("deleted %d expired job folder(s)", removed)


class WorkerSettings:
    functions = [analyze_job, apply_job]
    cron_jobs = [cron(sweep_tmp, minute=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
    max_tries = 5
    job_timeout = 300
