#!/bin/bash
# Compatible with both Docker and Podman container runtimes
set -e

# Set defaults for required environment variables
: "${CASSANDRA_CLUSTER_NAME:=HCDCluster}"
: "${CASSANDRA_SEEDS:=172.28.0.2,172.28.0.5}"
: "${CASSANDRA_LISTEN_ADDRESS:=127.0.0.1}"
: "${CASSANDRA_BROADCAST_ADDRESS:=$CASSANDRA_LISTEN_ADDRESS}"
: "${CASSANDRA_RPC_ADDRESS:=0.0.0.0}"
: "${CASSANDRA_ENDPOINT_SNITCH:=GossipingPropertyFileSnitch}"
: "${CASSANDRA_DC:=dc1}"
: "${CASSANDRA_RACK:=rack1}"

export CASSANDRA_CLUSTER_NAME CASSANDRA_SEEDS CASSANDRA_LISTEN_ADDRESS CASSANDRA_BROADCAST_ADDRESS CASSANDRA_RPC_ADDRESS CASSANDRA_ENDPOINT_SNITCH CASSANDRA_DC CASSANDRA_RACK
export CASSANDRA_CONF=${CASSANDRA_CONF:-/opt/hcd/resources/cassandra/conf}
export HCD_CONF=${HCD_CONF:-/opt/hcd/resources/cassandra/conf}

# Diagnostic trap: log useful info on unexpected failure
on_error() {
    echo "ERROR: Entrypoint failed at line $1. Environment:"
    echo "  LISTEN_ADDRESS=${CASSANDRA_LISTEN_ADDRESS}"
    echo "  SEEDS=${CASSANDRA_SEEDS}"
    echo "  DC=${CASSANDRA_DC} RACK=${CASSANDRA_RACK}"
    echo "  HEAP=${MAX_HEAP_SIZE:-unset}"
}
trap 'on_error $LINENO' ERR

# Validate critical configuration
if [ "${CASSANDRA_LISTEN_ADDRESS}" = "127.0.0.1" ] && [ "${CASSANDRA_SEEDS}" != "127.0.0.1" ]; then
    echo "ERROR: CASSANDRA_LISTEN_ADDRESS is 127.0.0.1 but seeds point to remote nodes."
    echo "  This node will be unreachable by peers. Set CASSANDRA_LISTEN_ADDRESS to"
    echo "  the node's container IP address (e.g., 172.28.0.X)."
    exit 1
fi

# Validate heap size values (allow only digits followed by optional k/m/g suffix)
validate_heap_value() {
    local name="$1" value="$2"
    if [ -n "$value" ] && ! echo "$value" | grep -qE '^[0-9]+[kKmMgG]?$'; then
        echo "ERROR: $name contains invalid characters: '$value' (expected format: 512M, 100M, etc.)"
        exit 1
    fi
}
validate_heap_value "MAX_HEAP_SIZE" "${MAX_HEAP_SIZE:-}"
validate_heap_value "HEAP_NEWSIZE" "${HEAP_NEWSIZE:-}"

# Generate cassandra.yaml from template
TEMPLATE="/opt/hcd/resources/cassandra/conf/cassandra.yaml.template"
CONF_OUTPUT="/opt/hcd/resources/cassandra/conf/cassandra.yaml"
if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template file not found: $TEMPLATE"
    exit 1
fi
if ! command -v envsubst >/dev/null 2>&1; then
    echo "ERROR: envsubst not found. Install gettext-base package."
    exit 1
fi
if ! envsubst < "$TEMPLATE" > "$CONF_OUTPUT"; then
    echo "ERROR: envsubst failed to process template."
    exit 1
fi
if [ ! -s "$CONF_OUTPUT" ]; then
    echo "ERROR: Generated cassandra.yaml is empty. Check template variables."
    exit 1
fi

# HCD 2.0 secure profile (Modules 86-92): append the security fragment when requested.
# Default 'open' leaves AllowAllAuthenticator; modules 86-92 enforce only under 'secure'.
: "${HCD_SECURITY_PROFILE:=open}"
SECURE_FRAGMENT="/opt/hcd/resources/cassandra/conf/cassandra-secure.yaml.fragment"
if [ "$HCD_SECURITY_PROFILE" = "secure" ]; then
    if [ -f "$SECURE_FRAGMENT" ]; then
        echo "HCD_SECURITY_PROFILE=secure -> appending security configuration (auth, authz, CIDR)."
        printf '\n' >> "$CONF_OUTPUT"
        envsubst < "$SECURE_FRAGMENT" >> "$CONF_OUTPUT"
    else
        echo "ERROR: HCD_SECURITY_PROFILE=secure but fragment not found: $SECURE_FRAGMENT" >&2
        exit 1
    fi
else
    echo "HCD_SECURITY_PROFILE=open (default) -> no authentication enforced."
fi

# Generate cassandra-rackdc.properties if GossipingPropertyFileSnitch is used
if [ "$CASSANDRA_ENDPOINT_SNITCH" = "GossipingPropertyFileSnitch" ]; then
    echo "dc=$CASSANDRA_DC" > /opt/hcd/resources/cassandra/conf/cassandra-rackdc.properties
    echo "rack=$CASSANDRA_RACK" >> /opt/hcd/resources/cassandra/conf/cassandra-rackdc.properties
    echo "prefer_local=true" >> /opt/hcd/resources/cassandra/conf/cassandra-rackdc.properties
fi

# Heap sizing is handled by cassandra-env.sh, which reads MAX_HEAP_SIZE / HEAP_NEWSIZE from the
# environment and sets -Xmx/-Xms/-Xmn once. We deliberately DO NOT also write them into
# jvm-server.options: HCD 2.0's stock options use G1 (which auto-sizes the young gen), and adding a
# second, file-level -Xmn produced a conflicting/duplicate -Xmn under G1 that aborts the JVM at
# launch — before logback — with no error in the container log (confirmed on a live HCD 2.0.6 boot,
# 2026-06-28). Let cassandra-env own the heap; if you must pin it, set the env vars (compose does).

# Extract first seed from comma-separated list, trimming whitespace
FIRST_SEED=$(echo "${CASSANDRA_SEEDS}" | cut -d',' -f1 | tr -d '[:space:]')

if [ -z "$FIRST_SEED" ]; then
    echo "ERROR: CASSANDRA_SEEDS is empty or malformed: '${CASSANDRA_SEEDS}'"
    exit 1
fi

# Do not wait if we are a seed node (check all seeds, not just the first)
if echo ",${CASSANDRA_SEEDS}," | tr -d '[:space:]' | grep -q ",${CASSANDRA_LISTEN_ADDRESS},"; then
    echo "Starting as seed node..."
else
    echo "This node ($CASSANDRA_LISTEN_ADDRESS) is not a seed. Waiting for seed node at $FIRST_SEED..."
    
    # Phase 1: Wait for TCP port to be open (exponential backoff: 1s, 2s, 4s, ... capped at 10s)
    MAX_RETRIES=30
    COUNT=0
    DELAY=1
    while ! nc -z "$FIRST_SEED" 9042 2>/dev/null; do
        COUNT=$((COUNT + 1))
        if [ $COUNT -ge $MAX_RETRIES ]; then
            echo "ERROR: Seed node $FIRST_SEED port 9042 not reachable after $COUNT retries."
            exit 1
        fi
        echo "Waiting for seed node TCP port... ($COUNT/$MAX_RETRIES, next retry in ${DELAY}s)"
        sleep $DELAY
        DELAY=$((DELAY * 2))
        [ $DELAY -gt 10 ] && DELAY=10
    done
    echo "Seed node TCP port is open."

    # Phase 2: Wait for CQL to be ready (exponential backoff: 2s, 4s, 8s, ... capped at 15s)
    MAX_CQL_RETRIES=20
    CQL_COUNT=0
    CQL_DELAY=2
    while ! cqlsh "$FIRST_SEED" -e "SELECT release_version FROM system.local" >/dev/null 2>&1; do
        CQL_COUNT=$((CQL_COUNT + 1))
        if [ $CQL_COUNT -ge $MAX_CQL_RETRIES ]; then
            echo "ERROR: Seed node $FIRST_SEED CQL not ready after $CQL_COUNT retries."
            exit 1
        fi
        echo "Waiting for seed node CQL readiness... ($CQL_COUNT/$MAX_CQL_RETRIES, next retry in ${CQL_DELAY}s)"
        sleep $CQL_DELAY
        CQL_DELAY=$((CQL_DELAY * 2))
        [ $CQL_DELAY -gt 15 ] && CQL_DELAY=15
    done
    echo "Seed node CQL is ready."
    
    # Add jitter delay to prevent thundering herd when multiple nodes join simultaneously
    JITTER=$((RANDOM % 5 + 1))
    echo "Adding ${JITTER}s jitter delay before joining cluster..."
    sleep $JITTER
fi

# JMX Prometheus exporter via JVM_EXTRA_OPTS. IMPORTANT: HCD's cassandra-env.sh already appends
# $JVM_EXTRA_OPTS to JVM_OPTS (resources/cassandra/conf/cassandra-env.sh:323), so we must NOT add it
# again — doing so loaded the -javaagent TWICE and the JVM aborted at premain with
# "jmx_exporter_build_info is already in use by another Collector" (confirmed on a live HCD 2.0.6
# boot, 2026-06-28). Here we only validate the jar: if it's missing, unset JVM_EXTRA_OPTS so
# cassandra-env doesn't reference a non-existent agent and fail startup.
if [ -n "$JVM_EXTRA_OPTS" ]; then
    if [ -f /opt/hcd/jmx_prometheus_javaagent.jar ]; then
        echo "JMX exporter enabled on port 9404 (applied once by cassandra-env.sh)"
    else
        echo "JMX agent jar not found — disabling JVM_EXTRA_OPTS to avoid a broken -javaagent"
        unset JVM_EXTRA_OPTS
    fi
fi

echo "Starting HCD..."
# Start HCD in foreground
exec /opt/hcd/bin/hcd cassandra -f
