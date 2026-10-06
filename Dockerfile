# D&D VTT — canonical runtime. Single image, two stages: runtime + test.
# IMPORTANT: the app keeps room/WebSocket state in memory -> exactly ONE
# uvicorn process (no --workers, no replicas). See README "Deployment".

# ---- test stage: full dev deps + sources, runs pytest --------------------
FROM python:3.12-slim AS test
WORKDIR /srv
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app ./app
COPY tests ./tests
COPY pytest.ini ./
ENV VTT_DATA_DIR=/tmp/vtt-data
CMD ["pytest"]

# ---- runtime stage -------------------------------------------------------
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -r -u 1000 -d /srv vtt \
 && mkdir -p /srv/data && chown -R vtt:vtt /srv
COPY --chown=vtt:vtt app ./app
USER vtt
ENV VTT_DATA_DIR=/srv/data PORT=8000 VTT_LOG_LEVEL=INFO
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,sys,urllib.request as u; \
sys.exit(0 if u.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=4).status==200 else 1)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
