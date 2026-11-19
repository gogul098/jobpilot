"""Temporary per-job files. Nothing is kept: a job's folder is deleted when the user
clicks Done, when they start a new analysis, or JOB_TTL seconds after its last write
(a cleanup task in the worker sweeps every few minutes).

Files live in TMP_DIR (default: <system temp>/jobpilot/<user>/<job>/). The API and the
worker must see the same folder: true on Render (one container); in docker-compose the
folder is a shared volume.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FILES = {"original.tex", "original.pdf", "revised.tex", "revised.pdf", "analysis.json", "result.json", "email.json"}
ROOT = Path(os.getenv("TMP_DIR") or Path(tempfile.gettempdir()) / "jobpilot")
TTL = int(os.getenv("JOB_TTL", "3600"))


def _dir(user: str, job_id: str) -> Path:
    if not (_SAFE.match(user) and _SAFE.match(job_id)):
        raise ValueError("bad id")
    return ROOT / user / job_id


def job_dir(user: str, job_id: str) -> Path:
    return _dir(user, job_id)


def write(user: str, job_id: str, name: str, data: bytes | str | dict):
    assert name in FILES
    d = _dir(user, job_id)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    if isinstance(data, str):
        data = data.encode("utf-8")
    (d / name).write_bytes(data)


def read(user: str, job_id: str, name: str) -> bytes | None:
    if name not in FILES:
        return None
    p = _dir(user, job_id) / name
    return p.read_bytes() if p.exists() else None


def read_json(user: str, job_id: str, name: str) -> dict | None:
    b = read(user, job_id, name)
    return json.loads(b) if b else None


def delete(user: str, job_id: str):
    shutil.rmtree(_dir(user, job_id), ignore_errors=True)


def sweep(ttl: int = TTL) -> int:
    """Delete job folders whose newest file is older than ttl seconds. Returns how many."""
    if not ROOT.exists():
        return 0
    now, removed = time.time(), 0
    for user_dir in ROOT.iterdir():
        for job in user_dir.iterdir() if user_dir.is_dir() else []:
            try:
                newest = max((f.stat().st_mtime for f in job.iterdir()), default=job.stat().st_mtime)
            except FileNotFoundError:
                continue
            if now - newest > ttl:
                shutil.rmtree(job, ignore_errors=True)
                removed += 1
    return removed
