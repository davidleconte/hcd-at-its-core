# Use Ubuntu 22.04 as the base image
FROM ubuntu:22.04

# Set environment variables
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV CASSANDRA_HOME=/opt/hcd
ENV PATH="${CASSANDRA_HOME}/bin:${PATH}"

# Build argument for the HCD tarball URL
ARG HCD_TARBALL_URL="https://example.com/ibm-hcd.tar.gz"

# Install required dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-11-jdk \
    curl \
    procps \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user 'cassandra'
RUN groupadd -r cassandra && useradd -r -g cassandra cassandra

# Set up directory structure and permissions
RUN mkdir -p /opt/hcd /var/lib/cassandra /var/log/cassandra \
    && chown -R cassandra:cassandra /opt/hcd /var/lib/cassandra /var/log/cassandra

# Download and extract the IBM HCD tarball
# We use --strip-components=1 assuming the tarball contains a single root directory
RUN curl -L "${HCD_TARBALL_URL}" | tar xz -C /opt/hcd --strip-components=1 \
    && chown -R cassandra:cassandra /opt/hcd

# Expose required ports
# 7000: intra-node communication
# 7001: TLS intra-node communication
# 7199: JMX
# 9042: CQL native transport
# 9160: Thrift RPC service
EXPOSE 7000 7001 7199 9042 9160

# Switch to the non-root user
USER cassandra

# Set the entrypoint (script to be created in next task)
ENTRYPOINT ["/docker-entrypoint.sh"]
