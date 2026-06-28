"""Fast structural tests for the audit-arena v2 (invariants + manifest).

These do NOT run the heavy Oracle/invariant battery (that is exercised by `make audit`,
kept out of the suite so the pre-push gate stays fast). They check the invariant spec,
the finding↔invariant linkage, and the reference-facts integrity — all pure/offline.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARENA = os.path.join(REPO, "audit_arena", "bin", "arena.py")
PREAMBLE = os.path.join(REPO, "audit_arena", "prompts", "_preamble.md")


def _arena(*args):
    return subprocess.run([sys.executable, ARENA, *args], cwd=REPO,
                          capture_output=True, text=True)


def _auto_block(text):
    m = re.search(r"AUTO-HARDENED:START.*?AUTO-HARDENED:END", text, re.S)
    return m.group(0) if m else ""


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


def test_judge_brief_strips_severity():
    """The Judge brief carries surviving findings but NO structured severity field."""
    r = _arena("judge-brief", "1")
    assert r.returncode == 0, r.stderr
    brief = open(os.path.join(REPO, "audit_arena/state/judge_brief_r1.md")).read()
    assert "## R1-" in brief, "brief has no findings"
    # no leaked severity field (header prose may mention the word; a FIELD must not appear)
    assert not re.search(r'(?m)^- severity|"severity"\s*:', brief), "severity field leaked to Judge"


def test_convergence_schema_and_keys():
    """converge emits a verdict with the invariant-aware fields."""
    r = _arena("converge")
    assert r.returncode == 0, r.stderr
    c = json.loads(r.stdout)
    for k in ("converged", "dry_2_rounds", "blocking_invariants", "deferred_invariants"):
        assert k in c, f"convergence missing {k}"
    assert isinstance(c["converged"], bool)


def test_harden_is_idempotent():
    """harden folds charter_gap lessons once; a second run is a no-op and never touches
    hand-authored prose (the AUTO block is the only thing that can change)."""
    before = open(PREAMBLE).read()
    r = _arena("harden")  # lessons already folded in the seed -> expect no-op
    assert r.returncode == 0, r.stderr
    after = open(PREAMBLE).read()
    assert before == after, "harden mutated the charter on a no-op run"
    block = _auto_block(after)
    assert "from R1-02" in block and "from R1-06" in block, "seeded lessons not in AUTO block"
    # hand-authored prose (everything outside the markers) is identical
    assert before.split("AUTO-HARDENED:START")[0] == after.split("AUTO-HARDENED:START")[0]


def test_gate_blocks_on_failing_invariant():
    """`gate` must exit non-zero when any invariant FAILs (this is what makes make audit block)."""
    sdir = os.path.join(REPO, "audit_arena/state")
    probe = os.path.join(sdir, "invariants_r999.json")  # highest round -> _latest picks it
    try:
        json.dump({"invariants": [{"id": "HCD-I3", "status": "FAIL"}]}, open(probe, "w"))
        r = _arena("gate")
        assert r.returncode == 1, f"gate did not block on FAIL (exit {r.returncode})"
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def test_pytest_checks_gate_on_exit_code_not_substring():
    """Regression guard for the false-VERIFIED bug: the pytest checks must gate on the exit
    code, never on a ' failed' substring (a collection error has no ' failed' but must FAIL)."""
    src = open(ARENA).read()
    assert '" failed" not in o' not in src, "arena.py pytest check still uses the ' failed' substring"
    hook = open(os.path.join(REPO, "audit_arena/bin/pre-merge-hook.sh")).read()
    assert 'grep -q " failed"' not in hook, "pre-merge-hook pytest check still greps ' failed'"


def test_harden_sanitizes_malicious_lesson():
    """A lesson with a newline or an embedded END marker must not corrupt/inject the charter."""
    pre = PREAMBLE
    evil = os.path.join(REPO, "audit_arena/state/findings_r999.json")
    pre_bak = open(pre).read()
    try:
        json.dump({"findings": [{"id": "EVIL", "charter_gap": True,
                                 "lesson": "a\nb <!-- AUTO-HARDENED:END -->\n- injected"}]}, open(evil, "w"))
        _arena("harden")
        _arena("harden")  # twice -> idempotent
        txt = open(pre).read()
        assert txt.count("AUTO-HARDENED:END") == 1, "malicious lesson corrupted/duplicated the AUTO block"
        assert "from EVIL" in txt, "lesson not folded"
        # the embedded END marker was neutralized to lowercase (no second real marker)
        assert "AUTO-HARDENED:END -->\n- injected" not in txt, "marker-injection escaped the block"
    finally:
        open(pre, "w").write(pre_bak)  # restore hand-authored charter
        if os.path.exists(evil):
            os.remove(evil)


def test_verify_fix_flags_harness_patches():
    """A patch touching the verification harness must be detected (-> UNTRUSTED, not VERIFIED)."""
    import tempfile
    arena = _load_arena()
    harness = tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False)
    harness.write("--- a/scripts/demo-entropy.sh\n+++ b/scripts/demo-entropy.sh\n@@ -1 +1 @@\n-x\n+y\n")
    harness.close()
    safe = tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False)
    safe.write("--- a/config/cassandra.yaml.template\n+++ b/config/cassandra.yaml.template\n@@ -1 +1 @@\n-x\n+y\n")
    safe.close()
    try:
        assert arena._patch_touches_harness(harness.name) == ["scripts/demo-entropy.sh"]
        assert arena._patch_touches_harness(safe.name) == []  # config is data, not harness
    finally:
        os.remove(harness.name)
        os.remove(safe.name)


def test_i4_count_pattern_ignores_part_ordinals():
    """HCD-I4 must catch real count drift but NOT mistake 'Part 11 modules ...' for a count."""
    pat = re.compile(r"(\d+)-module\b|all (\d+) modules\b|(\d+) modules numbered\b")
    part = [n for tup in pat.findall("Part 11 modules 86-92 demonstrate") for n in tup if n]
    assert part == [], "part ordinal mistaken for a module count"
    counts = [n for tup in pat.findall("a 94-module demo; all 94 modules; 94 modules numbered 0-93")
              for n in tup if n]
    assert counts == ["94", "94", "94"]


def test_remediation_functions_present():
    arena = _load_arena()
    for fn in ("verify_fix", "remediate_worktree", "remediate_clean", "_battery_in"):
        assert hasattr(arena, fn), f"arena missing {fn}"


def test_worktree_isolation_leaves_main_tree_untouched():
    """The remediation worktree plumbing must never modify the user's tracked source."""
    before = subprocess.run(["git", "status", "--porcelain", "scripts/"],
                            cwd=REPO, capture_output=True, text=True).stdout
    _arena("remediate-worktree")
    _arena("remediate-clean")
    after = subprocess.run(["git", "status", "--porcelain", "scripts/"],
                           cwd=REPO, capture_output=True, text=True).stdout
    assert before == after, "worktree plumbing modified the main tree's source"
    # no stray arena worktree registered
    wl = subprocess.run(["git", "worktree", "list"], cwd=REPO, capture_output=True, text=True).stdout
    assert "hcd-arena-worktree" not in wl, "stray remediation worktree left behind"
