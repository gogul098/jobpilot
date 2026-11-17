# One image for both the API and the worker (different start commands).
FROM python:3.12-slim

# Tectonic: self-contained LaTeX engine, fetches only the packages a resume needs.
ARG TECTONIC_VERSION=0.15.0
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates fontconfig \
 && curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin \
 && apt-get purge -y curl && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
COPY start.sh /srv/start.sh
RUN chown -R app /srv
USER app

# Warm Tectonic's package cache at build time so compiles are fast and need no network later.
RUN cd /tmp && tectonic --keep-logs /srv/backend/tests/fixtures/jake_resume.tex || true

WORKDIR /srv/backend
ENV TMP_DIR=/tmp/jobpilot LATEX_ENGINE=tectonic PYTHONUNBUFFERED=1
EXPOSE 8000
# Default: API + worker in one container (Render free tier). Compose overrides the worker command.
CMD ["sh", "/srv/start.sh"]
