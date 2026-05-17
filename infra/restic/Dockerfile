FROM restic/restic:0.16.4

# Install sops and age so backup.sh can decrypt secrets at runtime
# restic image is Alpine-based
RUN apk add --no-cache age

ARG SOPS_VERSION=3.9.4
ARG SOPS_SHA256=5b0249fdb539d90f5a37bc6ccbc08abd8fc2bcda3e2e5e86fef07ed82988ffdb
RUN wget -qO /usr/local/bin/sops \
    "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
    && echo "${SOPS_SHA256}  /usr/local/bin/sops" | sha256sum -c - \
    && chmod 755 /usr/local/bin/sops

COPY backup.sh /backup.sh
RUN chmod +x /backup.sh

ENTRYPOINT ["/bin/sh", "/backup.sh"]
