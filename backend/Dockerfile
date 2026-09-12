# ------------------------------------------------------------------ #
# Builder — compiles wheels (sqlcipher3 needs a C toolchain).
# Finding M3: the previous single-stage image shipped gcc and the -dev
# headers into production. They stay here now and never reach the runtime.
# ------------------------------------------------------------------ #
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlcipher-dev \
    libsqlite3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /usr/local/bin/uv

WORKDIR /app
# uv.lock is required, not optional. The previous `uv.lock*` glob let a missing
# lockfile through to `uv sync --frozen`, which then failed with a confusing
# error; a bare filename fails here instead, naming the actual problem.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# ------------------------------------------------------------------ #
# Runtime — no compiler, no headers, non-root, read-only friendly.
# ------------------------------------------------------------------ #
FROM python:3.12-slim AS runtime

# Runtime libraries only — the -dev headers and the compiler stay in the builder.
# The package providing libsqlcipher.so is named libsqlcipher0 on Debian bookworm
# (which python:3.12-slim is based on) but libsqlcipher1 on newer Ubuntu, so
# resolve whichever this base actually offers rather than hard-coding a guess.
RUN apt-get update && \
    SQLCIPHER_PKG="$(apt-cache show libsqlcipher0 >/dev/null 2>&1 && echo libsqlcipher0 || echo libsqlcipher1)" && \
    echo "Using runtime package: ${SQLCIPHER_PKG}" && \
    apt-get install -y --no-install-recommends \
        "${SQLCIPHER_PKG}" \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install sops — pinned version, verify checksum
ARG SOPS_VERSION=3.9.4
ARG SOPS_SHA256=5b0249fdb539d90f5a37bc6ccbc08abd8fc2bcda3e2e5e86fef07ed82988ffdb
RUN curl -sSfL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
    -o /usr/local/bin/sops \
    && echo "${SOPS_SHA256}  /usr/local/bin/sops" | sha256sum -c - \
    && chmod 755 /usr/local/bin/sops \
    && apt-get purge -y --auto-remove curl

# Create non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Pre-built virtualenv from the builder stage
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV="/app/.venv"

# Fail the BUILD, not the first container start, if the compiled sqlcipher3
# extension cannot find its shared library in this slimmer runtime image.
RUN python -c "import sqlcipher3.dbapi2; print('sqlcipher3 runtime link OK')"

# Copy application source.
# There is no `COPY scripts/` here: backend/scripts/ does not exist, so that line
# (and the chmod that followed it) failed every build. The repo's two shell
# scripts live at the repo root and are host-side setup tools — they are not
# needed inside the image.
COPY app/ ./app/
COPY alembic.ini ./

# Copy and secure entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    chown -R appuser:appgroup /app /entrypoint.sh

EXPOSE 8000

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
