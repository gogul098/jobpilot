# JobPilot

Paste a job description, upload your **LaTeX** resume, and get:

1. The job broken into structured JSON: role, must-have and nice-to-have skills, eligibility, pay, red flags, what to prepare.
2. A deterministic **ATS score** (0–100) of your compiled PDF against that job, with reasons.
3. Suggested wording revisions. Every one is fact-checked, and you can edit or reject it.
4. A recompiled PDF. Only the accepted text changes inside your `.tex`; your template, macros and spacing stay byte-for-byte the same.

The LLM never sees or writes LaTeX.

## Flow

```
browser ──REST──► FastAPI ──enqueue──► Redis (arq queue + event log + LLM cache + rate-limit state)
   ▲                 │                         │
   └──── SSE ◄───────┘  (replays events, then live)   ▼
                                           worker(s)
                                     1 JD -> JSON          (Groq model router)
                                     2 .tex -> text blocks (mechanical, offsets kept)
                                     3 compile original    (sandboxed LaTeX)
                                     4 ATS score           (deterministic, no LLM)
                                     5 revisions JSON      (Groq model router)
                                     6 fact-check guard    (rejects invented facts)
                    user picks/edits revisions
                                     7 paste text back into .tex -> compile -> re-score
```

### Model router (`app/llm/router.py`)
- One Groq key, several models (`GROQ_MODELS`), tried in order. On Groq, each model has its own requests-per-minute and tokens-per-day budget.
- `x-ratelimit-*` headers and 429 `retry-after` put a model on cooldown in Redis, which every worker shares.
- Model output must be valid JSON that passes the pydantic schema (`app/schemas.py`). Otherwise the next model is tried.
- Identical requests are served from cache (`LLM_CACHE_TTL`).
- If every model is cooling down, the job is re-queued (`arq.Retry`) rather than failed. Optionally, Gemini acts as a last-resort provider.
- Don't use extra Groq accounts to get more quota: Groq's terms forbid it. For more headroom, use the paid Developer tier.

### Context files (`app/llm/context/*.md`)
Each task's instructions and exact output JSON live in a markdown file that is sent as the system prompt. Edit the prompt there, not in code.

### LaTeX engine (`app/latex/`)
- `extract.py` finds `\item` bullets in list environments, `\resumeItem{}` / `\cvitem{}` style macros, and the Summary paragraph. It records exact source offsets and converts each block to plain text. Comments are ignored. The **Skills section is never editable**, so new skills can't be slipped in.
- `apply.py` escapes `& % $ # _ { } ~ ^ \`, re-applies `\textbf{}` to terms that were bold, and splices the new text into the recorded span, last block first.
- `compile.py`:
  - Runs pdflatex `-no-shell-escape` with paranoid file access (TeX Live is preinstalled in the image, so nothing downloads at runtime). Tectonic `--untrusted` is optional via `LATEX_ENGINE=tectonic`.
  - Blocks `\write18`, `\openin`/`\openout`, absolute and `..` inputs, `\directlua` and `\catcode`.
  - Has a timeout and a size limit.
  - In production, run the worker in its own container.

### ATS score (`app/ats/score.py`)
| Component | Max | Measured from |
|---|---|---|
| Parseability | 30 | Compiled PDF: text layer, email and phone at top, column layout, images, unreadable glyphs |
| Keywords | 35 | JD hard skills (must ×2, nice ×1) plus JD phrases (×0.5), synonym-aware; a term found only in the Skills list earns 70% |
| Sections | 10 | Standard Education, Skills and Experience/Projects headings; dates |
| Bullets | 15 | Action verb, contains a number, 1–2 lines, no first person |
| Length | 10 | Page count, word count, repeated words |

Real ATSs don't publish a score. They parse your PDF and recruiters search the fields. This score is a proxy for exactly those two things, and it is reproducible.

### Fact-check guard (`app/guard.py`)
A revision is rejected if it does any of these:
- adds a number that isn't in your resume
- names a JD skill your resume doesn't show
- adds a new tool-like term (CamelCase, ALLCAPS or digits)
- contains LaTeX
- grows past 135% of the original length

## Nothing is kept

Your `.tex` file, PDFs and analysis go to a temporary folder (`$TMP_DIR/<user>/<job>/`, default `/tmp/jobpilot`). A job's folder is deleted:
- when you click **Done, delete my files**,
- when you start a new analysis,
- or automatically one hour after last use (`JOB_TTL`). A cleanup task in the worker sweeps every 5 minutes.

Cached model output and progress events in Redis expire on their own, after 1 h and 2 h. In docker-compose the temp folder is an in-memory (tmpfs) volume that the API and the worker share.

## Run locally

```bash
cp .env.example .env              # add GROQ_API_KEY and APP_TOKEN
docker compose up --build         # http://localhost:8000
```

Without Docker you need Redis, Python 3.11+ and pdflatex or tectonic:
```bash
cd backend && pip install -r requirements.txt
redis-server &                                       # or set REDIS_URL
LATEX_ENGINE=pdflatex arq app.worker.WorkerSettings &
LATEX_ENGINE=pdflatex uvicorn app.main:app --port 8000
LATEX_ENGINE=pdflatex pytest -q                      # engine tests
```
`LLM_MOCK=1` runs everything offline with a fake model.

## Web app on Vercel

The website lives in `web/` (Vite + React, neo-brutalist design). It calls the Render API.

1. On vercel.com: **Add New → Project**, import **gogul098/jobpilot**.
2. Set **Root Directory** to `web`. Vercel detects Vite automatically.
3. Under **Environment Variables**, add `VITE_API_URL` = your Render URL, e.g. `https://jobpilot-xxxx.onrender.com` (no trailing slash).
4. Deploy. Then copy the Vercel URL (e.g. `https://jobpilot.vercel.app`) into Render → jobpilot → Environment → `CORS_ORIGINS`, and save.
   Preview deployments named `jobpilot-*.vercel.app` are already allowed by `CORS_ORIGIN_REGEX`.
5. Access key, pick one:
   - **Automatic (no typing):** add `VITE_APP_TOKEN` in Vercel with the same value as `APP_TOKEN` in Render, then redeploy. The key box disappears. The key is then visible in the site's JavaScript, so anyone with the URL can use the app; `HOURLY_LIMIT` (default 20 analyses per IP per hour) protects your Groq quota.
   - **Private:** leave `VITE_APP_TOKEN` empty and open `https://your-site.vercel.app/?key=YOUR_APP_TOKEN` once per browser. The key is saved and removed from the address bar.

Local dev: `cd web && npm install && npm run dev`. `/api` is proxied to `http://localhost:8000`, so no CORS setup is needed.

## Deploy the API on Render (free)

`render.yaml` is a Render Blueprint. It creates:
- **jobpilot**: one Docker web service that runs the API and the queue worker together (`start.sh`). Render's free plan has no background workers and no shared disk, so both run in one container. The worker restarts by itself if it ever crashes.
- **jobpilot-redis**: a free Render Key Value (Redis) instance for the queue, progress events, the short-lived LLM cache and rate-limit state. No files are stored there.

Steps:
1. Push this folder to a GitHub repo.
2. Render dashboard → **New → Blueprint** → pick the repo → **Apply**.
3. When asked, paste your `GROQ_API_KEY`. `GEMINI_API_KEY` is optional, so leave it empty if you don't have one.
4. After the deploy finishes, open **jobpilot → Environment**, copy the generated `APP_TOKEN`, open the site and paste it into **Access token**.

Free-tier notes:
- The service sleeps after about 15 minutes idle, so the first visit takes 30–60 s to wake.
- The first build takes several minutes, because it installs TeX Live into the image.
- 512 MB RAM, so `WORKER_CONCURRENCY` is 2.
- Free Key Value doesn't persist across restarts. That only clears the queue and the cache.
- For something always on, move the service to the Starter plan, or use Upstash Redis and point `REDIS_URL` to it.

Local Docker uses `docker compose up` (separate API and worker containers, Redis with persistence).

## Supported resume templates
Jake's Resume (`\resumeItem`), plain `itemize`/`enumerate` resumes, Awesome-CV (`\cvitem`). For a custom bullet macro, add its name to `BULLET_MACROS` in `app/latex/extract.py`.

## Multi-user later
- `current_user()` in `main.py` is the only auth hook. Swap the shared token for a Clerk or Supabase JWT.
- Temp files are already per-user (`$TMP_DIR/<user>/<job>/`).
- Add per-user rate limits in Redis before opening sign-ups.

## Phase 2 (planned)
Find similar jobs through job APIs, plus assisted apply: draft an email per company and send it from your Gmail with your resume attached, only after you approve it.
