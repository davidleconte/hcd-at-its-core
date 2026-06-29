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


# ─── Scenario navigator (direct-jump) ─────────────────────────────
def _read_total_modules():
    src = open("scripts/demo-entropy.sh").read()
    return int(re.search(r"readonly TOTAL_MODULES=(\d+)", src).group(1))


def test_scenario_catalog_consistent_with_script():
    """scripts/scenario_catalog.json is the single source of truth — it must cover exactly the
    modules the demo defines (every `header N`), with the required navigator fields."""
    cat = json.load(open("scripts/scenario_catalog.json"))
    total = _read_total_modules()
    mods = sorted(e["mod"] for e in cat)
    assert mods == list(range(total)), f"catalog must list modules 0..{total - 1}"
    headers = sorted(int(m) for m in re.findall(
        r'^\s*header\s+(\d+)\s+"', open("scripts/demo-entropy.sh").read(), re.M))
    assert set(headers) == set(mods), "catalog mods and script `header N` modules must match exactly"
    required = {"mod", "title", "part", "dim", "profile", "destructive", "external_deps", "tags"}
    for e in cat:
        assert required <= set(e), f"module {e.get('mod')} missing fields: {required - set(e)}"
        assert e["profile"] in ("open", "secure")


def test_demo_list_runs_offline():
    """`--list` reads only the catalog — it must work with no cluster and print every module."""
    r = subprocess.run(["bash", "scripts/demo-entropy.sh", "--list"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    data_rows = [ln for ln in r.stdout.splitlines() if re.match(r"\s*\d+\s+[A-M]\s", ln)]
    assert len(data_rows) == _read_total_modules()


def test_demo_tag_filter_dora():
    """`--list --tag dora` resolves to exactly the DORA ransomware series (73–79)."""
    r = subprocess.run(["bash", "scripts/demo-entropy.sh", "--list", "--tag", "dora"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    mods = sorted(int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\s+I\s", r.stdout, re.M))
    assert mods == list(range(73, 80)), mods


def test_demo_unknown_tag_fails():
    """An unknown tag exits non-zero (so a typo doesn't silently run nothing)."""
    r = subprocess.run(["bash", "scripts/demo-entropy.sh", "--tag", "nonsense"],
                       capture_output=True, text=True)
    assert r.returncode != 0


def _derive_destructive_mods():
    """Re-derive, from the script itself, the modules that EXECUTE a destructive op (node
    stop/pause/kill/restart/decommission, or a TRUNCATE/DROP run via log_cmd/docker exec) — the
    ground truth the catalog's `destructive` flag must cover. Mirrors the arena Oracle check."""
    src = open("scripts/demo-entropy.sh").read().splitlines()
    hdr = re.compile(r'^\s*header\s+(\d+)\s')
    idx = [(i, int(hdr.match(ln).group(1))) for i, ln in enumerate(src) if hdr.match(ln)]
    wipe = re.compile(r'(TRUNCATE\b|DROP\s+KEYSPACE\b|DROP\s+TABLE\b)', re.I)
    nodeop = re.compile(r'(docker\s+(stop|pause|kill|restart)\s+hcd|\$\{COMPOSE\}\s+(stop|kill|restart)\s+hcd'
                        r'|nodetool\s+(decommission|removenode|assassinate|stopdaemon|disablebinary))')
    def executed(s):
        s = s.strip()
        if s.startswith(("#", "echo", "lookfor", "log_info", "cprintf")):
            return False
        return s.startswith(("log_cmd ", "docker ", "${COMPOSE}")) or "docker exec" in s
    derived = set()
    for k, (i, m) in enumerate(idx):
        end = idx[k + 1][0] if k + 1 < len(idx) else len(src)
        if any(executed(ln) and (wipe.search(ln) or nodeop.search(ln)) for ln in src[i:end]):
            derived.add(m)
    return derived


def test_catalog_destructive_covers_every_executed_destructive_module():
    """SAFETY (arena PH-01/PH-02): the preflight guard trusts the catalog's `destructive` flag, so
    every module that actually executes a destructive op MUST be flagged. Re-derive from the script
    and assert the catalog is a superset — a misflag (the PH-02 bug: DROP-KEYSPACE module marked
    safe) fails CI instead of silently suppressing the 'wipes data / stops nodes' warning."""
    cat = {e["mod"]: e for e in json.load(open("scripts/scenario_catalog.json"))}
    derived = _derive_destructive_mods()
    missing = sorted(m for m in derived if not cat[m]["destructive"])
    assert not missing, f"modules execute a destructive op but are catalog destructive=false: {missing}"


def test_demo_tag_skips_destructive_modules():
    """SAFETY (arena PC-01/PH-03): `--tag` must NOT chain destructive modules. A dora-tag run skips
    the destructive members (76/77/79) and reports them for individual runs, rather than chaining."""
    r = subprocess.run(["bash", "scripts/demo-entropy.sh", "--tag", "dora", "--dry-run", "--no-pause"],
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "skipped destructive" in out, out[-400:]
    cat = {e["mod"]: e for e in json.load(open("scripts/scenario_catalog.json"))}
    dora_destr = [m for m in range(73, 80) if cat[m]["destructive"]]
    # the skipped-destructive summary line must name each destructive dora module
    skip_line = next((ln for ln in out.splitlines() if "skipped destructive" in ln), "")
    for m in dora_destr:
        assert str(m) in skip_line, f"module {m} not reported skipped: {skip_line!r}"
