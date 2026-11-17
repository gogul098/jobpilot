from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    app_token: str = os.getenv("APP_TOKEN", "")          # required header for every API call
    default_user: str = os.getenv("DEFAULT_USER", "me")  # single-user today; real auth later
    # Browser origins allowed to call the API (the Vercel site). Comma-separated.
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173"))
    # Also allow this regex, e.g. Vercel preview URLs of this project.
    cors_origin_regex: str = os.getenv("CORS_ORIGIN_REGEX", r"https://jobpilot[a-z0-9-]*\.vercel\.app")

    # Requests per IP per hour that start LLM work (analyze/suggest). Protects your Groq quota
    # when the access key is built into the public web app.
    hourly_limit: int = int(os.getenv("HOURLY_LIMIT", "20"))

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    # Ordered by preference. Each model has its own rate-limit budget on Groq.
    groq_models: list[str] = field(default_factory=lambda: _list(
        "GROQ_MODELS",
        "llama-3.3-70b-versatile,openai/gpt-oss-120b,qwen/qwen3-32b,"
        "meta-llama/llama-4-scout-17b-16e-instruct,llama-3.1-8b-instant"))
    # Optional second provider used only when every Groq model is cooling down.
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_models: list[str] = field(default_factory=lambda: _list("GEMINI_MODELS", "gemini-2.5-flash"))

    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "60"))
    llm_cache_ttl: int = int(os.getenv("LLM_CACHE_TTL", "3600"))  # cached model output expires with the job
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "4"))

    latex_engine: str = os.getenv("LATEX_ENGINE", "pdflatex")  # pdflatex | tectonic
    compile_timeout: int = int(os.getenv("COMPILE_TIMEOUT", "25"))

    llm_mock: bool = os.getenv("LLM_MOCK", "") == "1"  # offline demo / tests


settings = Settings()
