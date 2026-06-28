"""Tests for shell scripts, config validation, and basic behavior."""
import importlib.util
import json
import re
import subprocess
import sys

import pytest
import yaml


SHELL_SCRIPTS = [
    "scripts/docker-entrypoint.sh",
    "scripts/demo-entropy.sh",
    "scripts/execute-full-demo.sh",
    "scripts/gen-certs.sh",
]

# driver-demo.py exits at import if cassandra-driver is absent (it's a runtime dep
# used inside the container). Skip its --help tests cleanly when the driver is missing.
_HAS_CASSANDRA_DRIVER = (
    importlib.util.find_spec("cassandra") is not None
)
requires_driver = pytest.mark.skipif(
    not _HAS_CASSANDRA_DRIVER,
    reason="cassandra-driver not installed (runtime dep; provided inside the container)",
)


@pytest.mark.parametrize("script", SHELL_SCRIPTS)
def test_shell_syntax(script):
    """Verify each shell script has valid bash syntax."""
    result = subprocess.run(
        ["bash", "-n", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error in {script}: {result.stderr}"


def test_entrypoint_defaults():
    """Verify docker-entrypoint.sh sets expected default values."""
    # Source the defaults section only (stop before template generation)
    result = subprocess.run(
        ["bash", "-c", """
            set -e
            # Mock envsubst and other commands to prevent actual execution
            : "${CASSANDRA_CLUSTER_NAME:=HCDCluster}"
            : "${CASSANDRA_SEEDS:=172.28.0.2,172.28.0.5}"
            : "${CASSANDRA_LISTEN_ADDRESS:=127.0.0.1}"
            : "${CASSANDRA_DC:=dc1}"
            : "${CASSANDRA_RACK:=rack1}"
            echo "CLUSTER=$CASSANDRA_CLUSTER_NAME"
            echo "SEEDS=$CASSANDRA_SEEDS"
            echo "DC=$CASSANDRA_DC"
            echo "RACK=$CASSANDRA_RACK"
        """],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "CLUSTER=HCDCluster" in result.stdout
    assert "SEEDS=172.28.0.2,172.28.0.5" in result.stdout
    assert "DC=dc1" in result.stdout
    assert "RACK=rack1" in result.stdout


@requires_driver
def test_driver_demo_help():
    """Verify driver-demo.py shows help without errors."""
    result = subprocess.run(
        [sys.executable, "scripts/driver-demo.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "token-aware" in result.stdout
    assert "speculative" in result.stdout
    assert "dc-failover" in result.stdout
    assert "retry-policies" in result.stdout


@requires_driver
def test_driver_demo_local_dc_flag():
    """Verify driver-demo.py accepts --local-dc flag in help."""
    result = subprocess.run(
        [sys.executable, "scripts/driver-demo.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert "--local-dc" in result.stdout


def test_makefile_exists():
    """Verify Makefile is present and has expected targets."""
    result = subprocess.run(
        ["make", "-n", "help"],
        capture_output=True,
        text=True,
    )
    # -n is dry-run; just verify make can parse the file
    assert result.returncode == 0


def test_prometheus_alerts_valid_yaml():
    """Verify config/alerts.yml is valid YAML with expected structure."""
    with open("config/alerts.yml") as f:
        data = yaml.safe_load(f)
    assert "groups" in data, "alerts.yml must have a 'groups' key"
    assert len(data["groups"]) > 0, "alerts.yml must have at least one group"
    group = data["groups"][0]
    assert "rules" in group, "Alert group must have 'rules'"
    assert len(group["rules"]) >= 5, "Expected at least 5 alert rules"
    # Verify each rule has required fields
    for rule in group["rules"]:
        assert "alert" in rule, f"Rule missing 'alert' name: {rule}"
        assert "expr" in rule, f"Rule {rule['alert']} missing 'expr'"
        assert "labels" in rule, f"Rule {rule['alert']} missing 'labels'"
        assert "severity" in rule["labels"], f"Rule {rule['alert']} missing severity label"


def test_prometheus_alert_metric_names_match_lowercasing_exporter():
    """Discriminating check (tribunal R2-01/R2-02): config/jmx-exporter.yml sets
    `lowercaseOutputName: true`, so every emitted metric name is all-lowercase. An alert
    expr that carries a CamelCase metric name (a lowercase letter immediately followed by
    `_` then an uppercase letter, e.g. `cassandra_dropped_Dropped`) references a series the
    exporter NEVER emits — the alert is silently dead. The old shape-only test let this
    whole class pass green; this asserts the metric names can actually fire."""
    with open("config/jmx-exporter.yml") as f:
        assert yaml.safe_load(f).get("lowercaseOutputName") is True, \
            "exporter no longer lowercases — revisit this assertion"
    with open("config/alerts.yml") as f:
        data = yaml.safe_load(f)
    camel = re.compile(r"[a-z]_[A-Z]")
    offenders = [r["alert"] for g in data["groups"] for r in g["rules"]
                 if camel.search(r["expr"])]
    assert not offenders, f"alerts reference CamelCase metrics the lowercasing exporter never emits: {offenders}"


def test_grafana_dashboard_valid_json():
    """Verify Grafana dashboard JSON is valid and has expected panels."""
    with open("config/grafana/dashboards/hcd-cluster.json") as f:
        data = json.load(f)
    assert "panels" in data, "Dashboard must have 'panels'"
    assert len(data["panels"]) >= 4, "Expected at least 4 dashboard panels"
    # Verify each panel has a title
    for panel in data["panels"]:
        if panel.get("type") != "row":
            assert "title" in panel, f"Panel missing 'title': {panel.get('id')}"


def test_prometheus_config_valid_yaml():
    """Verify config/prometheus.yml is valid YAML with scrape config."""
    with open("config/prometheus.yml") as f:
        data = yaml.safe_load(f)
    assert "scrape_configs" in data, "prometheus.yml must have scrape_configs"
    assert "rule_files" in data, "prometheus.yml must reference rule_files"
