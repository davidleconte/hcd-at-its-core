FROM ubuntu:22.04

# Install required dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-11-jdk \
    curl \
    procps \
    python3 \
    ca-certificates \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Create directory structure
RUN mkdir -p /opt/hcd /var/lib/cassandra /var/log/cassandra \
    && useradd -m -s /bin/bash cassandra \
    && chown -R cassandra:cassandra /opt/hcd /var/lib/cassandra /var/log/cassandra

WORKDIR /opt/hcd

# Copy configuration template and entrypoint script
COPY config/cassandra.yaml.template /opt/hcd/conf/cassandra.yaml.template
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh

# Ensure scripts are executable and owned by cassandra
RUN chmod +x /docker-entrypoint.sh \
    && chown cassandra:cassandra /docker-entrypoint.sh /opt/hcd/conf/cassandra.yaml.template

USER cassandra

# Expose required ports
# 7000: intra-node communication
# 7001: TLS intra-node communication
# 7199: JMX
# 9042: CQL
EXPOSE 7000 7001 7199 9042

ENTRYPOINT ["/docker-entrypoint.sh"]
