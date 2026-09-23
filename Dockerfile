# Local Mission Control. No secrets are copied or baked into this image.
# Unconfigured providers still fail closed (HTTP 503 on mission create).

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SWARM_DATABASE_PATH=/data/swarm.db \
    SWARM_WORKSPACE_ROOT=/data/workspaces

WORKDIR /opt/swarm

# Base package only. The Playwright extra is not installed.
COPY pyproject.toml ./
COPY app ./app

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && mkdir -p /data/workspaces \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin swarm \
    && chown -R swarm:swarm /data

USER swarm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
