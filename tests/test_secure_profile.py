"""Tests for the HCD 2.0 secure-profile artifacts (PR-4/PR-5).

These run WITHOUT Docker — they validate the certs tooling, the config fragment,
the compose overlay, the entrypoint gating, and the Grafana dashboard at the
syntax/YAML/JSON/shellcheck level.
"""
import collections
import json
import os
import re
import shutil
import subprocess

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── gen-certs.sh ─────────────────────────────────────────────────────
@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_gen_certs_produces_ca_and_san_certs(tmp_path):
    """gen-certs.sh produces a CA, SAN-bearing node certs, and spiffe client certs."""
    env = {**os.environ, "CERT_DIR": str(tmp_path)}
    r = subprocess.run(
        ["bash", "scripts/gen-certs.sh"], cwd=REPO, env=env,
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ca.crt").exists()
    # node cert carries DNS hostname + container IP in its SAN
    node_san = subprocess.run(
        ["openssl", "x509", "-in", str(tmp_path / "hcd-node1.crt"),
         "-noout", "-ext", "subjectAltName"],
        capture_output=True, text=True,
    ).stdout
    assert "DNS:hcd-node1" in node_san and "172.28.0.2" in node_san
    # client cert carries the spiffe identity used by ADD IDENTITY
    cli_san = subprocess.run(
        ["openssl", "x509", "-in", str(tmp_path / "analyst.crt"),
         "-noout", "-ext", "subjectAltName"],
        capture_output=True, text=True,
    ).stdout
    assert "spiffe://hcd/role/analyst" in cli_san
    # leaf chains to the CA
    v = subprocess.run(
        ["openssl", "verify", "-CAfile", str(tmp_path / "ca.crt"),
         str(tmp_path / "hcd-node1.crt")],
        capture_output=True, text=True,
    )
    assert v.returncode == 0, v.stdout + v.stderr


# ─── secure fragment ──────────────────────────────────────────────────
def test_secure_fragment_no_dup_keys_when_appended():
    """Appending the secure fragment to the base template yields valid YAML with
    no duplicate top-level keys (the base auth/encryption keys are commented)."""
    tmpl = open(os.path.join(REPO, "config/cassandra.yaml.template")).read()
    frag = open(os.path.join(REPO, "config/cassandra-secure.yaml.fragment")).read()
    combined = re.sub(r"\$\{[^}]+\}", "x", tmpl + "\n" + frag)
    parsed = yaml.safe_load(combined)
    assert parsed.get("authenticator") == "PasswordAuthenticator"
    assert parsed.get("authorizer") == "CassandraAuthorizer"
    assert "network_authorizer" in parsed  # core DC-level RBAC stays enabled
    # cidr_authorizer is DELIBERATELY disabled (commented) in the base secure profile: enabling
    # CassandraCIDRAuthorizer crashes every node at first boot (NPE in AuthCacheService.register,
    # confirmed on a live HCD 2.0.6 boot 2026-06-28). Module 86 enables it AFTER the cluster is up
    # and system_auth.cidr_groups is populated.
    assert "cidr_authorizer" not in parsed, \
        "CIDR authorizer must stay disabled in the base secure profile (it crashes first boot)"
    top_keys = re.findall(r"^([A-Za-z_]\w*):", combined, re.M)
    dups = [k for k, c in collections.Counter(top_keys).items() if c > 1]
    assert not dups, f"duplicate top-level keys after append: {dups}"


def test_secure_fragment_uses_unit_suffixed_durations():
    """Cassandra 5.0 requires unit-suffixed durations (roles_validity: 2000ms),
    not the legacy *_in_ms keys."""
    frag = open(os.path.join(REPO, "config/cassandra-secure.yaml.fragment")).read()
    assert "roles_validity_in_ms" not in frag
    assert re.search(r"roles_validity:\s*\d+ms", frag)


# ─── compose overlay ──────────────────────────────────────────────────
def test_secure_overlay_sets_profile_and_mounts_certs():
    """Every node in the overlay gets HCD_SECURITY_PROFILE=secure and the certs mount."""
    overlay = yaml.safe_load(
        open(os.path.join(REPO, "docker-compose.secure.yml"))
    )
    services = overlay["services"]
    for n in range(1, 7):
        svc = services[f"hcd-node{n}"]  # PyYAML resolves the <<: *secure merge key
        assert svc["environment"]["HCD_SECURITY_PROFILE"] == "secure"
        assert any("/opt/hcd/certs:ro" in v for v in svc["volumes"])


# ─── entrypoint gating ────────────────────────────────────────────────
def test_entrypoint_gates_on_security_profile():
    """The entrypoint appends the fragment only under HCD_SECURITY_PROFILE=secure."""
    ep = open(os.path.join(REPO, "scripts/docker-entrypoint.sh")).read()
    assert 'HCD_SECURITY_PROFILE:=open' in ep  # safe default
    assert "cassandra-secure.yaml.fragment" in ep
    assert re.search(r'HCD_SECURITY_PROFILE.*=.*"secure"', ep)


# ─── Grafana dashboard (PR-5 panels) ──────────────────────────────────
def test_grafana_has_paxos_and_auth_panels():
    """The 2 PR-5 panels exist and every non-row panel has a non-empty query expr."""
    dash = json.load(
        open(os.path.join(REPO, "config/grafana/dashboards/hcd-cluster.json"))
    )
    titles = [p.get("title", "") for p in dash["panels"]]
    assert any("Paxos v2" in t for t in titles), "missing LWT/CAS Paxos v2 panel"
    assert any("auth" in t.lower() for t in titles), "missing auth-load panel"
    for p in dash["panels"]:
        if p.get("type") == "row":
            continue
        exprs = [t.get("expr", "") for t in p.get("targets", [])]
        assert any(e.strip() for e in exprs), f"panel '{p.get('title')}' has no query expr"
