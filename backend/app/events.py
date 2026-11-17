"""Job progress events in Redis: a replayable list plus pub/sub for live SSE.

Because events are stored, a browser that reconnects (or a server restart)
still sees everything that happened to the job.
"""
from __future__ import annotations

import json
import time

from redis.asyncio import Redis

TTL = 2 * 3600


async def emit(redis: Redis, job_id: str, stage: str, status: str, message: str = "", **extra):
    ev = {"t": time.time(), "stage": stage, "status": status, "message": message, **extra}
    raw = json.dumps(ev)
    await redis.rpush(f"jobev:{job_id}", raw)
    await redis.expire(f"jobev:{job_id}", TTL)
    await redis.hset(f"job:{job_id}", mapping={"stage": stage, "status": status, "message": message})
    await redis.expire(f"job:{job_id}", TTL)
    await redis.publish(f"jobch:{job_id}", raw)


async def history(redis: Redis, job_id: str, start: int = 0) -> list[dict]:
    return [json.loads(x) for x in await redis.lrange(f"jobev:{job_id}", start, -1)]


async def count(redis: Redis, job_id: str) -> int:
    return await redis.llen(f"jobev:{job_id}")
