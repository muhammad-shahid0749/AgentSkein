# =============================================================================
#  AgentSkein image
#
#  Single multi-stage Dockerfile that powers three roles in docker-compose.yml:
#    * api          (FastAPI server on :8765)
#    * test-runner  (executes the scenario suite, writes results to /results)
#    * sandbox      (interactive shell for ad-hoc experiments)
#
#  The role is selected at runtime via the entrypoint command.
#  Works identically on Windows Docker Desktop and Ubuntu Docker.
# =============================================================================

# ───────── Stage 1: build the Rust merge engine + wheel ─────────
FROM python:3.12-slim AS builder
WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl build-essential pkg-config \
 && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
 && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"

COPY pyproject.toml Cargo.toml README.md ./
COPY core/ ./core/
COPY agentskein/ ./agentskein/

RUN pip install --no-cache-dir maturin \
 && maturin build --release -o /dist

# ───────── Stage 2: runtime image ─────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# Runtime OS deps for testcontainers / curl-based healthchecks
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install the AgentSkein wheel
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
 && pip install --no-cache-dir \
        fastapi==0.111.* uvicorn[standard]==0.30.* \
        redis==5.0.* aiosqlite==0.20.* \
        httpx==0.27.* pydantic==2.7.* anyio==4.3.* \
        rich==13.7.* structlog==24.1.* ulid-py==1.1.* \
        pytest==8.2.* pytest-asyncio==0.23.*

# Copy runtime source (server, scenarios, agents reference pipeline)
COPY agentskein/ ./agentskein/
COPY examples/ ./examples/
COPY agents/ ./agents/
COPY tests/ ./tests/
# README.md quickstart says `python quickstart.py` from repo root, so the
# file has to be inside /app too (the docs-experiment harness invokes it
# as a subprocess from /app).
COPY quickstart.py ./
# Project-layout audit (README L420-L447) walks these paths from inside the
# container. We ship them so the layout claim verifies under Docker too.
COPY README.md CONTEXT.md AGENTS_INTEGRATION_GUIDE.md LICENSE ./
COPY core/ ./core/
COPY docs/ ./docs/

# /results is the mount point where scenarios write JSONL + Markdown
RUN mkdir -p /results
ENV AGENTSKEIN_RESULTS_DIR=/results

# Default = launch the API. Override in docker-compose.yml per service.
EXPOSE 8765
CMD ["python", "examples/n8n_api_server/server.py"]
