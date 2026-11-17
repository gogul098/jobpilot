"""Route LLM calls across several models so one model's rate limit never blocks the user.

- Groq models are tried in preference order; each has its own RPM/TPM/TPD budget.
- Rate-limit headers (and 429 retry-after) put a model on cooldown in Redis, shared by all workers.
- Output must parse as JSON and validate against a pydantic schema, else the next model is tried.
- Identical requests are served from a Redis cache.
- Gemini (OpenAI-compatible endpoint) is an optional last-resort provider.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from ..config import settings

log = logging.getLogger("router")
T = TypeVar("T", bound=BaseModel)
CONTEXT_DIR = Path(__file__).parent / "context"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


class AllModelsBusy(RuntimeError):
    def __init__(self, retry_in: float):
        super().__init__(f"all models rate-limited; retry in {retry_in:.0f}s")
        self.retry_in = retry_in


@dataclass(frozen=True)
class Target:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_duration(s: str | None) -> float:
    """Groq reset headers look like '2m59.56s', '7.66s', '120ms'."""
    if not s:
        return 0.0
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        pass
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", s):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def load_context(name: str) -> str:
    return (CONTEXT_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


class ModelRouter:
    def __init__(self, redis: Redis, client: httpx.AsyncClient | None = None):
        self.redis = redis
        self.client = client or httpx.AsyncClient(timeout=settings.llm_timeout)

    def targets(self) -> list[Target]:
        out = []
        if settings.groq_api_key:
            out += [Target("groq", m) for m in settings.groq_models]
        if settings.gemini_api_key:
            out += [Target("gemini", m) for m in settings.gemini_models]
        return out

    async def _cooldown_left(self, t: Target) -> float:
        until = await self.redis.get(f"rl:{t.key}")
        return max(0.0, float(until) - time.time()) if until else 0.0

    async def _cool(self, t: Target, seconds: float, why: str):
        seconds = max(1.0, min(seconds, 24 * 3600))
        await self.redis.set(f"rl:{t.key}", time.time() + seconds, ex=int(seconds) + 1)
        log.warning("cooldown %s for %.0fs (%s)", t.key, seconds, why)

    async def _call(self, t: Target, system: str, user: str) -> tuple[str, httpx.Response]:
        url, key = (GROQ_URL, settings.groq_api_key) if t.provider == "groq" else (GEMINI_URL, settings.gemini_api_key)
        body = {"model": t.model, "temperature": 0.2,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        r = await self.client.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"] or "", r
        return "", r

    async def _record_headers(self, t: Target, r: httpx.Response):
        h = r.headers
        rem_req, rem_tok = h.get("x-ratelimit-remaining-requests"), h.get("x-ratelimit-remaining-tokens")
        if rem_req is not None and int(float(rem_req)) <= 0:
            await self._cool(t, parse_duration(h.get("x-ratelimit-reset-requests")), "requests exhausted")
        elif rem_tok is not None and int(float(rem_tok)) < 1500:
            await self._cool(t, parse_duration(h.get("x-ratelimit-reset-tokens")), "tokens low")

    async def complete_json(self, task: str, payload: dict, schema: type[T],
                            max_wait: float = 30.0, job_id: str | None = None) -> tuple[T, str]:
        """Run one task (a context file name) and return (validated object, model used)."""
        system = load_context(task)
        user = json.dumps(payload, ensure_ascii=False)
        cache_key = "llmcache:" + hashlib.sha256(f"{task}\n{user}".encode()).hexdigest()
        if (hit := await self.redis.get(cache_key)) is not None:
            return schema.model_validate_json(hit), "cache"

        if settings.llm_mock:
            from .mock import mock_response
            obj = schema.model_validate(mock_response(task, payload))
            return obj, "mock"

        targets = self.targets()
        if not targets:
            raise RuntimeError("no LLM provider configured: set GROQ_API_KEY")
        deadline = time.time() + max_wait
        errors: list[str] = []
        while True:
            waits = []
            for t in targets:
                left = await self._cooldown_left(t)
                if left > 0:
                    waits.append(left)
                    continue
                try:
                    text, r = await self._call(t, system, user)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    await self._cool(t, 20, f"network: {type(e).__name__}")
                    errors.append(f"{t.key}: network")
                    continue
                if r.status_code == 429:
                    await self._cool(t, parse_duration(r.headers.get("retry-after")) or 60, "429")
                    waits.append(parse_duration(r.headers.get("retry-after")) or 60)
                    continue
                if r.status_code in (400, 404) and "model" in r.text.lower():
                    await self._cool(t, 3600, f"model unavailable {r.status_code}")
                    errors.append(f"{t.key}: unavailable")
                    continue
                if r.status_code >= 400:
                    await self._cool(t, 15, f"http {r.status_code}")
                    errors.append(f"{t.key}: http {r.status_code}")
                    continue
                await self._record_headers(t, r)
                try:
                    obj = schema.model_validate(extract_json(text))
                except (ValueError, ValidationError) as e:
                    errors.append(f"{t.key}: bad output ({str(e)[:80]})")
                    continue  # try the next model, no cooldown
                await self.redis.set(cache_key, obj.model_dump_json(), ex=settings.llm_cache_ttl)
                return obj, t.key
            soonest = min(waits) if waits else 0
            if not waits or time.time() + soonest > deadline:
                if waits:
                    raise AllModelsBusy(soonest)
                raise RuntimeError("every model failed: " + "; ".join(errors[-6:]))
            await asyncio.sleep(soonest + 0.5)
