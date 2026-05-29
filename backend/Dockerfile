# MindMarket FastAPI backend — production image.
#
# Deliberately a separate Dockerfile from the root Streamlit one:
#
#   * Streamlit runs on Python 3.10 with the full pandas / streamlit /
#     plotly stack. The backend uses 3.12 features (`dict[str, Any]`,
#     etc.) and a much smaller dep set. One image, one Python.
#   * Streamlit's image stays byte-for-byte unchanged so production can
#     be rolled back by switching compose files (see
#     docs/aws/split-stack-deployment.md §7).
#
# Build context is the repo ROOT — the FastAPI app imports
# `engine.quant`, `domain.models`, `libs.auth.portfolios`,
# `data_provider`, etc., so we need the whole tree available at
# import time. Build context is restricted via `.dockerignore` to
# keep the layer small.
#
# Layer order is tuned for cache friendliness: requirements files
# first (rarely change), then code (changes every commit).

FROM python:3.12-slim

# Don't write .pyc, flush stdout immediately so docker logs are live,
# don't ask pip to check for updates (CI does that), don't cache pip
# downloads inside the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools needed for pandas/numpy wheels that don't ship pre-built
# for 3.12 on slim. Removed after install to keep the runtime image
# lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first — these layers are reused across most code-only
# rebuilds.
COPY requirements.txt /app/requirements.txt
COPY backend/requirements-backend.txt /app/backend/requirements-backend.txt
RUN pip install -r /app/requirements.txt \
 && pip install -r /app/backend/requirements-backend.txt

# Application code. `.dockerignore` excludes node_modules, .git,
# .venv, tests-only artifacts, secrets, etc. Anything an import
# might reach must NOT be ignored.
COPY . /app

EXPOSE 8000

# Healthcheck via stdlib so we don't need curl in the image. Mirrors
# the pattern compose.aws.yml uses for the Streamlit image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0) if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4).getcode() == 200 else sys.exit(1)"

# Uvicorn directly — no shell wrapper so signals (SIGTERM from docker
# stop) reach the worker cleanly and graceful shutdown works.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
