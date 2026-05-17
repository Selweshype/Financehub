FROM python:3.12-slim AS base

# System deps: libsqlcipher-dev for sqlcipher3, sops for secrets decryption
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlcipher-dev \
    libsqlite3-dev \
    gcc \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install sops — pinned version, verify checksum
ARG SOPS_VERSION=3.9.4
ARG SOPS_SHA256=5b0249fdb539d90f5a37bc6ccbc08abd8fc2bcda3e2e5e86fef07ed82988ffdb
RUN curl -sSfL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
    -o /usr/local/bin/sops \
    && echo "${SOPS_SHA256}  /usr/local/bin/sops" | sha256sum -c - \
    && chmod 755 /usr/local/bin/sops

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /usr/local/bin/uv

# Create non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Install dependencies (cached layer) — as root so uv cache is writable
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

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
