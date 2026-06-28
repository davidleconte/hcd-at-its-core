"""Fast structural tests for the audit-arena v2 (invariants + manifest).

These do NOT run the heavy Oracle/invariant battery (that is exercised by `make audit`,
kept out of the suite so the pre-push gate stays fast). They check the invariant spec,
the finding↔invariant linkage, and the reference-facts integrity — all pure/offline.
"""
import importlib.util
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_arena():
    spec = importlib.util.spec_from_file_location(
        "arena", os.path.join(REPO, "audit_arena", "bin", "arena.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # safe: dispatch only runs under __main__
    return mod


def test_invariant_spec_is_complete():
    """Exactly 7 invariants HCD-I1..I7, each with an evaluator."""
    arena = _load_arena()
    inv = arena.INVARIANTS
    ids = [i["id"] for i in inv]
    assert ids == [f"HCD-I{n}" for n in range(1, 8)], f"unexpected invariant ids: {ids}"
    for i in inv:
        assert i.get("dim") and i.get("statement"), f"{i['id']} missing dim/statement"
        assert "offline_cmd" in i or ("live_cmd" in i and "proxy_cmd" in i), \
            f"{i['id']} needs offline_cmd OR live_cmd+proxy_cmd"


def test_seed_findings_carry_invariant():
    """Every seed finding maps to a named invariant (the Definition-of-Done linkage)."""
    d = json.load(open(os.path.join(REPO, "audit_arena/state/findings_r1.json")))
    valid = {f"HCD-I{n}" for n in range(1, 8)} | {"—"}
    for f in d["findings"]:
        assert f.get("invariant") in valid, f"{f['id']} has bad invariant {f.get('invariant')!r}"
    # the seed should actually exercise several invariants, not all be unmapped
    mapped = {f["invariant"] for f in d["findings"]} - {"—"}
    assert len(mapped) >= 3, f"seed maps too few invariants: {mapped}"


def test_reference_facts_valid():
    """HCD-I7's pinned facts file loads and lists the key version facts."""
    rf = json.load(open(os.path.join(REPO, "audit_arena/reference_facts.json")))
    facts = rf["facts"]
    assert isinstance(facts, list) and len(facts) >= 5
    for must in ("Cassandra 5.0", "Java 17", "2.0.6"):
        assert must in facts, f"reference_facts missing {must!r}"


def test_manifest_matches_invariants_if_generated():
    """Self-check: if `make audit` has run, the manifest's invariant map agrees with
    invariants_r1.json (no drift between the two generated artefacts)."""
    sdir = os.path.join(REPO, "audit_arena/state")
    mp = os.path.join(sdir, "manifest_r1.json")
    ip = os.path.join(sdir, "invariants_r1.json")
    if not (os.path.exists(mp) and os.path.exists(ip)):
        import pytest
        pytest.skip("manifest/invariants not generated (run `make audit`)")
    man = json.load(open(mp))
    inv = {i["id"]: i["status"] for i in json.load(open(ip))["invariants"]}
    assert man["invariants"] == inv, "manifest invariant map drifted from invariants_r1.json"
