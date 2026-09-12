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
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev


# ------------------------------------------------------------------ #
# Runtime — no compiler, no headers, non-root, read-only friendly.
# ------------------------------------------------------------------ #
FROM python:3.12-slim AS runtime

# Runtime libraries only: libsqlcipher0 provides the shared object the
# compiled sqlcipher3 extension links against; the -dev headers are not needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlcipher0 \
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

# Copy application source
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic.ini ./

# Copy and secure entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    chmod +x /app/scripts/*.sh && \
    chown -R appuser:appgroup /app /entrypoint.sh

EXPOSE 8000

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
