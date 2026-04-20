# Playwright's official Python image ships Chromium + every OS dep the
# browser needs, for both linux/amd64 and linux/arm64. That saves ~300MB
# of apt installs plus the usual "missing libnss3" fight.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    DATA_DIR=/data

WORKDIR ${APP_HOME}

# Deps first so requirement-only changes hit the layer cache.
COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt \
 && pip install playwright==1.47.0

# The base image already installed Chromium for root. `playwright install`
# here is a no-op in normal runs but guards against base-image drift.
RUN python -m playwright install chromium --with-deps || true

# App code
COPY app ./app

# Runtime data lives in a mounted volume so the sqlite db + playwright
# session cookies persist across container restarts.
RUN mkdir -p ${DATA_DIR} \
 && useradd --create-home --uid 1001 app \
 && chown -R app:app ${APP_HOME} ${DATA_DIR}

USER app

EXPOSE 8000

# Simple healthcheck: /api/health returns 200 once the app is up.
# (We proxy through /api in nginx; the backend itself serves /health.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
