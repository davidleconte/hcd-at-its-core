"""Unit tests for scripts/driver-demo.py helper functions."""
import importlib
import subprocess
import sys

import pytest


# ─── Import the module despite its non-standard location ──────────────
def _import_driver_demo():
    """Import driver-demo.py as a module, handling the cassandra-driver dependency."""
    spec = importlib.util.spec_from_file_location(
        "driver_demo", "scripts/driver-demo.py"
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pytest.skip("cassandra-driver not installed — skipping driver_demo tests")
    return mod


driver_demo = _import_driver_demo()


# ─── parse_contact_points ─────────────────────────────────────────────

class TestParseContactPoints:
    def test_single_ip(self):
        assert driver_demo.parse_contact_points("172.28.0.2") == ["172.28.0.2"]

    def test_multiple_ips(self):
        result = driver_demo.parse_contact_points("172.28.0.2,172.28.0.3,172.28.0.4")
        assert result == ["172.28.0.2", "172.28.0.3", "172.28.0.4"]

    def test_whitespace_trimming(self):
        result = driver_demo.parse_contact_points(" 172.28.0.2 , 172.28.0.3 ")
        assert result == ["172.28.0.2", "172.28.0.3"]

    def test_single_with_whitespace(self):
        assert driver_demo.parse_contact_points("  10.0.0.1  ") == ["10.0.0.1"]


# ─── ip_to_dc ─────────────────────────────────────────────────────────

class TestIpToDc:
    def test_dc1_node1(self):
        assert driver_demo.ip_to_dc("172.28.0.2") == "dc1"

    def test_dc1_node3(self):
        assert driver_demo.ip_to_dc("172.28.0.4") == "dc1"

    def test_dc2_node4(self):
        assert driver_demo.ip_to_dc("172.28.0.5") == "dc2"

    def test_dc2_node6(self):
        assert driver_demo.ip_to_dc("172.28.0.7") == "dc2"

    def test_dc1_boundary(self):
        """Octet 4 is the last dc1 node."""
        assert driver_demo.ip_to_dc("172.28.0.4") == "dc1"

    def test_dc2_boundary(self):
        """Octet 5 is the first dc2 node."""
        assert driver_demo.ip_to_dc("172.28.0.5") == "dc2"


# ─── print_coordinator_summary ────────────────────────────────────────

class TestPrintCoordinatorSummary:
    def test_single_coordinator(self, capsys):
        driver_demo.print_coordinator_summary(["172.28.0.2"])
        captured = capsys.readouterr()
        assert "172.28.0.2" in captured.out
        assert "dc1" in captured.out
        assert "1" in captured.out

    def test_multiple_coordinators(self, capsys):
        ips = ["172.28.0.2", "172.28.0.2", "172.28.0.5"]
        driver_demo.print_coordinator_summary(ips)
        captured = capsys.readouterr()
        assert "172.28.0.2" in captured.out
        assert "172.28.0.5" in captured.out
        # node1 should show count 2
        assert "2" in captured.out

    def test_empty_list(self, capsys):
        driver_demo.print_coordinator_summary([])
        captured = capsys.readouterr()
        assert "SUMMARY" in captured.out


# ─── CLI argument parsing ─────────────────────────────────────────────

class TestCLIParsing:
    def test_help_flag(self):
        """Verify --help exits cleanly."""
        result = subprocess.run(
            [sys.executable, "scripts/driver-demo.py", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "token-aware" in result.stdout
        assert "speculative" in result.stdout
        assert "dc-failover" in result.stdout
        assert "retry-policies" in result.stdout

    def test_subcommand_help(self):
        """Verify subcommand --help works."""
        result = subprocess.run(
            [sys.executable, "scripts/driver-demo.py", "token-aware", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "token-aware" in result.stdout

    def test_invalid_subcommand(self):
        """Verify invalid subcommand produces error."""
        result = subprocess.run(
            [sys.executable, "scripts/driver-demo.py", "nonexistent"],
            capture_output=True, text=True
        )
        assert result.returncode != 0
