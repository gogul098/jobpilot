"""Compile untrusted LaTeX to PDF in a locked-down temp directory.

Defences: no shell escape, paranoid file access (no absolute paths or ..),
a denylist of dangerous primitives, a hard timeout and a size limit.
In production run the worker in its own container with no network.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from ..config import settings

MAX_TEX_BYTES = 200_000
_DENY = [r"\\write18", r"\\immediate\s*\\write", r"\\openout", r"\\openin", r"\\read\s*\d",
         r"\\input\s*\{?\s*/", r"\\include\s*\{\s*/", r"\\input\s*\{?[^}]*\.\.", r"\\usepackage\s*\{shellesc\}",
         r"\\directlua", r"\\catcode", r"\\ShellEscape", r"\\pdffiledump", r"\\pdfobj\s+file"]


class UnsafeLatex(ValueError):
    pass


@dataclass
class CompileResult:
    ok: bool
    pdf: bytes | None
    log: str


def check_safe(tex: str) -> None:
    if len(tex.encode()) > MAX_TEX_BYTES:
        raise UnsafeLatex("file too large")
    for pat in _DENY:
        if re.search(pat, tex):
            raise UnsafeLatex(f"blocked LaTeX command: {pat.replace(chr(92) * 2, chr(92))}")


def compile_pdf(tex: str, timeout: int | None = None) -> CompileResult:
    check_safe(tex)
    timeout = timeout or settings.compile_timeout
    work = tempfile.mkdtemp(prefix="tex-")
    try:
        with open(os.path.join(work, "resume.tex"), "w", encoding="utf-8") as f:
            f.write(tex)
        # Keep the real HOME / cache dir: Tectonic's package cache lives there (warmed at
        # build time). Pointing HOME at the temp dir forced a full re-download on every compile.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", work),
               "openin_any": "p", "openout_any": "p", "shell_escape": "f", "TEXMFOUTPUT": work}
        for k in ("TECTONIC_CACHE_DIR", "XDG_CACHE_HOME", "SSL_CERT_FILE", "HTTPS_PROXY", "https_proxy"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        engine = settings.latex_engine
        if engine == "tectonic" and shutil.which("tectonic"):
            cmd = ["tectonic", "--untrusted", "--keep-logs", "--outdir", work, "resume.tex"]
        else:
            cmd = ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                   "-output-directory", work, "resume.tex"]
        log = ""
        passes = 1 if cmd[0] == "tectonic" else 2
        for _ in range(passes):
            try:
                p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return CompileResult(False, None, "LaTeX compile timed out")
            log = (p.stdout + p.stderr).decode("utf-8", "replace")
            if p.returncode != 0:
                return CompileResult(False, None, _tail_errors(log))
        pdf_path = os.path.join(work, "resume.pdf")
        if not os.path.exists(pdf_path):
            return CompileResult(False, None, _tail_errors(log))
        with open(pdf_path, "rb") as f:
            return CompileResult(True, f.read(), "")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _tail_errors(log: str) -> str:
    errs = [l for l in log.splitlines() if l.startswith("!") or "error" in l.lower()]
    return "\n".join(errs[-8:]) or log[-1500:]
