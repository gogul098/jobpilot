# One image for the API and the worker (Render runs both via start.sh).
FROM python:3.12-slim

# TeX Live from Debian: every package is installed at build time, so compiles never
# download anything and finish in a few seconds even on a small CPU.
# latex-extra covers titlesec, enumitem, tabularx, fullpage... (Jake's Resume, Deedy, most Overleaf CVs).
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended lmodern cm-super \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/*

RUN useradd -m -u 1000 app
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
COPY start.sh /srv/start.sh
RUN chown -R app /srv
USER app

# Fail the build early if the sample resume can't compile.
RUN mkdir -p /tmp/chk && cd /tmp/chk \
 && pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error /srv/backend/tests/fixtures/jake_resume.tex >/dev/null \
 && rm -rf /tmp/chk

WORKDIR /srv/backend
ENV TMP_DIR=/tmp/jobpilot LATEX_ENGINE=pdflatex PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "/srv/start.sh"]
