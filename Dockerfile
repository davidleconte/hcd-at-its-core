# To pin by digest for reproducible builds, run: make pin-digests
# This will update this file with the current digest automatically.
# FORMAT: FROM eclipse-temurin:17-jre@sha256:<digest>
# HCD 2.0 adds Java 17 support (release 2.0.6, on Apache Cassandra 5.0); the demo
# standardizes on JDK 17 so Module 82 (JVM/GC) and the new Module 93 (Java 17/ZGC)
# run on the supported runtime.
FROM eclipse-temurin:17-jre

LABEL maintainer="HCD Docker Cluster" \
      description="IBM HCD 2.0 multi-node cluster for development and demos" \
      version="2.0.6" \
      org.opencontainers.image.title="HCD Docker Cluster" \
      org.opencontainers.image.description="IBM HCD (Hyper-Converged Database) - multi-node cluster for development, testing, and demos" \
      org.opencontainers.image.vendor="IBM" \
      org.opencontainers.image.source="https://github.com/davidleconte/hcd-at-its-core"

# Install dependencies:
# - gettext-base for envsubst
# - netcat-openbsd for seed checking
# - procps for cassandra startup scripts
# - curl/ca-certificates for uv installation
# Note: Netty native epoll warning (UnsatisfiedLinkError) on ARM64 is harmless; 
# the service automatically falls back to NIO.
# demo image: apt versions intentionally unpinned for portability
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    gettext-base \
    netcat-openbsd \
    procps \
    curl \
    ca-certificates \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv and setup Python environment
# Pin by digest: run make pin-digests to update automatically
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Create virtual environment with a specific Python version
# UV_PYTHON_INSTALL_DIR ensures Python is installed in a shared location
# accessible to the non-root cassandra user at runtime
RUN uv venv $VIRTUAL_ENV --python 3.11 && \
    uv pip install cassandra-driver==3.29.2

# Create cassandra user and directories with fixed IDs for Podman/Rootless consistency
# Fixed UIDs ensure that file ownership remains consistent when mapping volumes in rootless mode
RUN groupadd -r cassandra --gid=999 && \
    useradd -r -g cassandra --uid=999 cassandra

# Install HCD from local tarball
# We use a specific directory to avoid clobbering /opt
# NOTE: hcd-2.0.6-bin.tar.gz must be obtained from IBM Passport Advantage (part M1442EN)
# and placed in the project root before building. See README.md Prerequisites.
# deliberate COPY+manual extract (not ADD) to control --strip-components
# hadolint ignore=DL3010
COPY hcd-2.0.6-bin.tar.gz /tmp/hcd.tar.gz
RUN mkdir -p /opt/hcd && \
    tar -xzf /tmp/hcd.tar.gz -C /opt/hcd --strip-components=1 && \
    rm /tmp/hcd.tar.gz

# Create wrapper scripts that set HCD_CONF for docker exec compatibility.
# Resolve each command's REAL path: nodetool/cqlsh/hcd live in /opt/hcd/bin, but the
# sstable* tools live under resources/cassandra/{bin,tools/bin} in Cassandra 5.0 — so
# search candidate dirs instead of assuming /opt/hcd/bin (which would break sstabledump
# used by Module 85's "masking is presentation-only" proof and Module 37's restore).
RUN for cmd in nodetool cqlsh hcd sstableloader sstabledump sstablemetadata; do \
        rm -f /usr/local/bin/$cmd; \
        target="/opt/hcd/bin/$cmd"; \
        for d in /opt/hcd/bin /opt/hcd/resources/cassandra/bin /opt/hcd/resources/cassandra/tools/bin; do \
            if [ -x "$d/$cmd" ]; then target="$d/$cmd"; break; fi; \
        done; \
        printf '#!/bin/bash\nexport HCD_CONF=/opt/hcd/resources/cassandra/conf\nexport CASSANDRA_CONF=/opt/hcd/resources/cassandra/conf\nexec %s "$@"\n' "$target" > /usr/local/bin/$cmd; \
        chmod +x /usr/local/bin/$cmd; \
    done

# Download JMX Prometheus exporter (optional: for --profile monitoring)
ARG JMX_EXPORTER_VERSION=0.20.0
RUN if curl -fsSL -o /tmp/jmx_exporter.jar \
    "https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/${JMX_EXPORTER_VERSION}/jmx_prometheus_javaagent-${JMX_EXPORTER_VERSION}.jar" 2>/dev/null; then \
        mv /tmp/jmx_exporter.jar /opt/hcd/jmx_prometheus_javaagent.jar; \
        echo "JMX Prometheus exporter ${JMX_EXPORTER_VERSION} installed."; \
    else \
        echo "WARNING: JMX exporter download failed (no internet?). Monitoring profile will be unavailable." >&2; \
    fi
COPY config/jmx-exporter.yml /opt/hcd/jmx-exporter.yml

WORKDIR /opt/hcd

ENV CASSANDRA_CONF=/opt/hcd/resources/cassandra/conf
ENV HCD_CONF=/opt/hcd/resources/cassandra/conf

# Copy configuration template and entrypoint script
COPY config/cassandra.yaml.template /opt/hcd/resources/cassandra/conf/cassandra.yaml.template
# Secure-profile fragment (appended at runtime when HCD_SECURITY_PROFILE=secure) — Modules 86-92
COPY config/cassandra-secure.yaml.fragment /opt/hcd/resources/cassandra/conf/cassandra-secure.yaml.fragment
COPY --chmod=755 scripts/docker-entrypoint.sh /docker-entrypoint.sh
COPY --chmod=755 scripts/generate-topology.py /usr/local/bin/generate-topology
COPY --chmod=755 scripts/demo-entropy.sh /usr/local/bin/demo-entropy
COPY --chmod=755 scripts/driver-demo.py /usr/local/bin/driver-demo

# Default cqlsh credentials for the secure profile's bootstrap superuser.
# CRITICAL for secure-profile cluster formation: under PasswordAuthenticator, the
# Docker healthcheck (cqlsh -e ...) and the entrypoint seed-wait both connect with no
# -u/-p and would fail, so the cluster would never go healthy and nodes 2-6 would never
# join. A baked cqlshrc makes every in-container cqlsh authenticate as cassandra/cassandra.
# Harmless under the open profile — AllowAllAuthenticator ignores supplied credentials.
ENV HOME=/home/cassandra
RUN mkdir -p /home/cassandra/.cassandra && \
    printf '[authentication]\nusername = cassandra\npassword = cassandra\n' > /home/cassandra/.cassandra/cqlshrc

# Ensure permissions for cassandra user
RUN mkdir -p /var/lib/cassandra /var/log/cassandra && \
    chown -R cassandra:cassandra /var/lib/cassandra /var/log/cassandra /opt/hcd /opt/venv /opt/python /home/cassandra

# Set default JVM Heap sizes (Lowered for demo/local laptop portability)
ENV MAX_HEAP_SIZE="512M"
ENV HEAP_NEWSIZE="100M"

USER cassandra

EXPOSE 9042 7000 7001 9404

HEALTHCHECK --interval=30s --timeout=10s --retries=10 --start-period=180s \
    CMD cqlsh -e 'SELECT release_version FROM system.local' || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
