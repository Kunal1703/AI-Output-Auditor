# AI Trust & Quality Auditor — backend image (Document 4, §2: Docker).
#
# Two stages, and the split exists for one reason: sentence-transformers pulls
# torch, which is ~2GB of build-time weight that the runtime does not need to
# rebuild. Installing into a venv in the builder and copying the venv forward
# keeps the final image free of pip's caches and build toolchain.
#
# The embedding model is baked in at build time. Downloading it on first request
# would put a multi-hundred-megabyte fetch inside the first audit — on the event
# loop, in front of the user — and would make the container useless in an
# air-gapped or rate-limited network. A model that ships with the image is a
# model that cannot fail at 3am.

# --------------------------------------------------------------------------- #
# Stage 1 — build the virtualenv
# --------------------------------------------------------------------------- #
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build tooling for the few packages without wheels for slim. Dropped in the
# final stage — a runtime image with a C compiler is a runtime image with more
# attack surface than it needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Requirements first, so a source edit does not re-run the torch install.
COPY requirements.txt requirements-m2.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements-m2.txt

# Bake the embedding model into the image. `all-MiniLM-L6-v2` is ~90MB and is
# the only model the auditor loads locally (Document 4, §2).
ENV HF_HOME=/opt/models
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

# --------------------------------------------------------------------------- #
# Stage 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.11-slim

LABEL org.opencontainers.image.title="AI Trust & Quality Auditor — backend" \
      org.opencontainers.image.description="Evidence-backed trust and quality audits of AI-generated content." \
      org.opencontainers.image.source="https://github.com/your-org/ai-trust-auditor"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/models \
    # The model is already in the image; never reach for the network for it.
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/models /opt/models

# Non-root. The auditor reads submitted content and calls out to an LLM; it has
# no reason to be able to write to its own image.
RUN useradd --create-home --uid 1000 auditor
WORKDIR /app

# config/ lives at the repo root, one level above backend/. `core.config`
# resolves it as PROJECT_ROOT/config, i.e. the parent of the app's directory —
# so the layout inside the image must mirror the repo, not flatten it.
COPY --chown=auditor:auditor backend/app /app/backend/app
COPY --chown=auditor:auditor config /app/config
COPY --chown=auditor:auditor datasets /app/datasets

USER auditor
WORKDIR /app/backend

EXPOSE 8000

# The health endpoint is the readiness contract (Document 4, §7). It reports
# provider identity and configuration, so an unhealthy container is one you can
# diagnose from `docker ps` rather than from logs.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health', timeout=5).status_code==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
