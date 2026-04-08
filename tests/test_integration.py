"""Integration tests requiring a live 6-node HCD cluster (2 DCs, 3 nodes each).

These tests validate that the demo modules produce correct results against a
real running cluster. They are SKIPPED by default in CI — run them with:

    make test-integration
    # or: pytest tests/test_integration.py -v --run-integration

Prerequisites:
    - 6-node cluster running: make up && make wait
    - All nodes UN (Up/Normal)
    - No prior test keyspaces (or run make destroy first)
"""
from __future__ import annotations

import subprocess
import sys

import pytest


# ─── Skip unless --run-integration is passed ──────────────────────────
def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests against a live HCD cluster",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        skip_marker = pytest.mark.skip(reason="needs --run-integration flag and a live cluster")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_marker)


# ─── Helpers ──────────────────────────────────────────────────────────
def cqlsh(cql: str, node: str = "hcd-node1") -> subprocess.CompletedProcess:
    """Execute a CQL statement via docker exec and return the result."""
    return subprocess.run(
        ["docker", "exec", node, "cqlsh", "-e", cql],
        capture_output=True, text=True, timeout=30,
    )


def nodetool(cmd: str, node: str = "hcd-node1") -> subprocess.CompletedProcess:
    """Execute a nodetool command via docker exec and return the result."""
    return subprocess.run(
        ["docker", "exec", node, "nodetool", cmd],
        capture_output=True, text=True, timeout=60,
    )


def run_module(module_id: int) -> subprocess.CompletedProcess:
    """Run a single demo module with --no-pause against the live cluster."""
    return subprocess.run(
        ["bash", "scripts/demo-entropy.sh", "--no-pause", str(module_id)],
        capture_output=True, text=True, timeout=300,
    )


# ─── Fixtures ─────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def verify_cluster_health():
    """Verify all 6 nodes are UN before running any integration test."""
    result = nodetool("status")
    if result.returncode != 0:
        pytest.skip("Cluster not reachable — is it running? (make up && make wait)")
    un_count = result.stdout.count("UN ")
    if un_count < 6:
        pytest.skip(f"Only {un_count}/6 nodes are UN — wait for cluster to stabilize")


@pytest.fixture(scope="session")
def rf_prod_keyspace():
    """Ensure rf_prod keyspace exists for integration tests."""
    cqlsh("""
        CREATE KEYSPACE IF NOT EXISTS rf_prod
        WITH replication = {
            'class': 'NetworkTopologyStrategy',
            'dc1': 3, 'dc2': 3
        };
    """)
    cqlsh("""
        CREATE TABLE IF NOT EXISTS rf_prod.health (
            id int PRIMARY KEY, status text
        );
    """)
    return "rf_prod"


# ═══════════════════════════════════════════════════════════════════════
# CLUSTER HEALTH
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestClusterHealth:
    """Validate baseline cluster topology matches the expected 2-DC, 6-node layout."""

    def test_all_nodes_up_normal(self):
        result = nodetool("status")
        assert result.returncode == 0
        assert result.stdout.count("UN ") == 6, "Expected 6 nodes in UN state"

    def test_two_datacenters_present(self):
        result = nodetool("status")
        assert "dc1" in result.stdout
        assert "dc2" in result.stdout

    def test_schema_agreement(self):
        result = nodetool("describecluster")
        assert result.returncode == 0
        assert "Schema versions:" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# REPLICATION & CONSISTENCY (Modules 1-3)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestReplicationConsistency:
    """Validate RF=3 replication and consistency level behavior."""

    def test_write_and_read_at_local_quorum(self, rf_prod_keyspace):
        cqlsh("INSERT INTO rf_prod.health (id, status) VALUES (1, 'integration-test');")
        result = cqlsh("CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.health WHERE id = 1;")
        assert result.returncode == 0
        assert "integration-test" in result.stdout

    def test_write_visible_from_dc2(self, rf_prod_keyspace):
        cqlsh("INSERT INTO rf_prod.health (id, status) VALUES (2, 'cross-dc-test');")
        result = cqlsh("CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.health WHERE id = 2;", node="hcd-node4")
        assert result.returncode == 0
        assert "cross-dc-test" in result.stdout

    def test_endpoints_show_rf3(self, rf_prod_keyspace):
        result = nodetool("getendpoints rf_prod health 1")
        assert result.returncode == 0
        # RF=3 per DC = up to 6 endpoints total, at least 3
        endpoints = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        assert len(endpoints) >= 3, f"Expected at least 3 endpoints, got {len(endpoints)}"


# ═══════════════════════════════════════════════════════════════════════
# WRITE & READ PATH (Modules 8-9)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestWriteReadPath:
    """Validate write path (commitlog + memtable) and read path (SSTable + bloom)."""

    def test_tracing_write_path(self, rf_prod_keyspace):
        result = cqlsh("TRACING ON; INSERT INTO rf_prod.health (id, status) VALUES (100, 'trace-test');")
        assert result.returncode == 0
        # Trace output should contain coordinator activity
        assert "Tracing session" in result.stdout or "activity" in result.stdout.lower()

    def test_tracing_read_path(self, rf_prod_keyspace):
        result = cqlsh("TRACING ON; SELECT * FROM rf_prod.health WHERE id = 100;")
        assert result.returncode == 0
        assert "trace-test" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# NODE FAILURE & RECOVERY (Modules 3-4, 10)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestNodeFailure:
    """Validate cluster survives node failure and recovers via hinted handoff."""

    def test_write_survives_node_down(self, rf_prod_keyspace):
        """Stop node3, write data, verify it's readable at LOCAL_QUORUM."""
        subprocess.run(["docker", "compose", "stop", "hcd-node3"],
                       capture_output=True, timeout=30)
        try:
            cqlsh("INSERT INTO rf_prod.health (id, status) VALUES (200, 'node-down-test');")
            result = cqlsh("CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.health WHERE id = 200;")
            assert result.returncode == 0
            assert "node-down-test" in result.stdout
        finally:
            subprocess.run(["docker", "compose", "start", "hcd-node3"],
                           capture_output=True, timeout=30)
            # Wait for node to rejoin
            import time
            for _ in range(30):
                status = nodetool("status")
                if status.stdout.count("UN ") >= 6:
                    break
                time.sleep(5)


# ═══════════════════════════════════════════════════════════════════════
# SAI INDEXING (Module 18)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestSAI:
    """Validate Storage-Attached Indexing works for non-PK queries."""

    def test_sai_index_query(self, rf_prod_keyspace):
        cqlsh("""
            CREATE TABLE IF NOT EXISTS rf_prod.sai_test (
                id uuid PRIMARY KEY, category text, value int
            );
        """)
        cqlsh("CREATE CUSTOM INDEX IF NOT EXISTS ON rf_prod.sai_test (category) USING 'StorageAttachedIndex';")
        cqlsh("INSERT INTO rf_prod.sai_test (id, category, value) VALUES (uuid(), 'electronics', 100);")
        cqlsh("INSERT INTO rf_prod.sai_test (id, category, value) VALUES (uuid(), 'books', 50);")
        result = cqlsh("SELECT * FROM rf_prod.sai_test WHERE category = 'electronics';")
        assert result.returncode == 0
        assert "electronics" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# BACKUP & RESTORE (Module 37)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestBackupRestore:
    """Validate snapshot creation and listing."""

    def test_snapshot_creation(self, rf_prod_keyspace):
        result = nodetool("snapshot rf_prod -t integration_test_snap")
        assert result.returncode == 0
        list_result = nodetool("listsnapshots")
        assert "integration_test_snap" in list_result.stdout
        # Cleanup
        nodetool("clearsnapshot -t integration_test_snap -- rf_prod")


# ═══════════════════════════════════════════════════════════════════════
# DEMO MODULE EXECUTION (smoke test)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.integration
class TestDemoModuleExecution:
    """Smoke-test a selection of key demo modules against the live cluster."""

    @pytest.mark.parametrize("module_id", [0, 1, 2, 7, 13])
    def test_foundation_modules(self, module_id):
        """Run foundation modules and verify non-zero output."""
        result = run_module(module_id)
        assert result.returncode == 0, f"Module {module_id} failed: {result.stderr}"
        assert f"Module {module_id}:" in result.stdout

    def test_module_scorecard_subset(self):
        """Verify score mode works for a quick subset."""
        result = subprocess.run(
            ["bash", "-c", """
                source scripts/demo-entropy.sh --dry-run --score 2>/dev/null
            """],
            capture_output=True, text=True, timeout=120,
        )
        # Score mode runs all modules in dry-run; we just verify it completes
        assert result.returncode == 0 or "PASS" in result.stdout
