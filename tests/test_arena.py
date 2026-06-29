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
    """Self-check: if `make audit` has run, the manifest's invariant map agrees with the invariants
    of the SAME round. `make audit` refreshes the LATEST round (not round 1), so compare that one —
    checking a hardcoded round 1 would drift once the tribunal advances."""
    import glob
    sdir = os.path.join(REPO, "audit_arena/state")
    mans = sorted(glob.glob(os.path.join(sdir, "manifest_r*.json")),
                  key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    if not mans:
        import pytest
        pytest.skip("manifest not generated (run `make audit`)")
    rnd = re.search(r"_r(\d+)\.", mans[-1]).group(1)  # latest round, the one make audit refreshes
    ip = os.path.join(sdir, f"invariants_r{rnd}.json")
    if not os.path.exists(ip):
        import pytest
        pytest.skip("invariants for the latest manifest round not generated")
    man = json.load(open(mans[-1]))
    inv = {i["id"]: i["status"] for i in json.load(open(ip))["invariants"]}
    assert man["invariants"] == inv, f"manifest invariant map drifted from invariants_r{rnd}.json"


def test_judge_brief_strips_severity():
    """The Judge brief carries surviving findings but NO structured severity field."""
    r = _arena("judge-brief", "1")
    assert r.returncode == 0, r.stderr
    brief = open(os.path.join(REPO, "audit_arena/state/judge_brief_r1.md")).read()
    assert "## R1-" in brief, "brief has no findings"
    # no leaked severity field (header prose may mention the word; a FIELD must not appear)
    assert not re.search(r'(?m)^- severity|"severity"\s*:', brief), "severity field leaked to Judge"


def test_latest_round_resolves_highest_round():
    """`make audit` defaults oracle/invariants/manifest to _latest_round() so it refreshes the SAME
    round the courtroom renders. The helper must return the highest round present, never below it."""
    arena = _load_arena()
    r = arena._latest_round()
    assert r.isdigit(), f"_latest_round must be a numeric string, got {r!r}"
    sdir = os.path.join(REPO, "audit_arena/state")
    present = [int(re.search(r"_r(\d+)\.", f).group(1))
               for f in __import__("glob").glob(os.path.join(sdir, "findings_r*.json"))]
    if present:
        assert int(r) == max(present), f"_latest_round {r} != max findings round {max(present)}"


def test_pre_push_hook_refreshes_courtroom_on_success():
    """The pre-push hook refreshes the courtroom snapshot (manifest + render) so the dashboard's git
    provenance never lags HEAD — but only on the SUCCESS path, after the gate's fail-exit, and only
    touching gitignored artefacts (never a tracked file, so the push stays clean)."""
    hook = open(os.path.join(REPO, "audit_arena/bin/pre-merge-hook.sh")).read()
    assert "arena.py render" in hook, "hook must refresh the courtroom (render)"
    assert "arena.py manifest" in hook, "hook must refresh the manifest provenance SHA"
    assert hook.index("arena.py render") > hook.index("BLOCKED"), \
        "courtroom refresh must be on the success path (after the gate's fail-exit)"


def test_make_audit_not_hardcoded_to_round_one():
    """Regression for the stale-courtroom bug: `make audit` rendered the LATEST round but only
    regenerated round 1, so the manifest provenance silently lagged once the tribunal advanced.
    The audit target must call oracle/invariants/manifest with NO hardcoded round."""
    mk = open(os.path.join(REPO, "Makefile")).read()
    for cmd in ("oracle", "invariants", "manifest"):
        assert f"arena.py {cmd} 1" not in mk, f"make audit must not hardcode round 1 for {cmd}"


def test_last_live_pass_persists_and_promotes():
    """A live PASS must survive offline renders: _record_last_live stores it and _last_live_pass
    returns it so an offline check renders as a green PASS (with timestamp), not amber DEFERRED.
    A check never run live -> None (stays DEFERRED); a recorded FAIL -> None (never promotes)."""
    arena = _load_arena()
    real = arena._LAST_LIVE
    bak = open(real).read() if os.path.exists(real) else None
    try:
        arena._record_last_live("PROBE-PASS", "PASS", "UN nodes: 6")
        p = arena._last_live_pass("PROBE-PASS")
        assert p and p["status"] == "PASS" and p.get("ts"), "a recorded live PASS must be retrievable"
        assert arena._last_live_pass("NEVER-RAN") is None, "no record -> stays DEFERRED"
        arena._record_last_live("PROBE-FAIL", "FAIL", "x")
        assert arena._last_live_pass("PROBE-FAIL") is None, "a live FAIL must not promote to green"
    finally:
        if bak is not None:
            open(real, "w").write(bak)
        else:
            d = arena._load_last_live()
            d.pop("PROBE-PASS", None)
            d.pop("PROBE-FAIL", None)
            json.dump(d, open(real, "w"))


def test_gate_does_not_block_on_oracle_timeout():
    """A TIMEOUT oracle check (couldn't run — e.g. CPU contention from a live cluster) is
    inconclusive, NOT a failure: the gate must pass (it blocks on FAIL). Prevents `make audit`
    against a live cluster from reading as a hard pytest failure."""
    sdir = os.path.join(REPO, "audit_arena/state")
    probe = os.path.join(sdir, "oracle_r999.json")  # highest round -> _latest picks it
    try:
        json.dump({"checks": [{"check": "pytest (no fail)", "dimension": "D4",
                               "status": "TIMEOUT", "detail": "timed out"}]}, open(probe, "w"))
        r = _arena("gate")
        assert r.returncode == 0, f"gate blocked on a TIMEOUT (should be inconclusive): {r.stdout}{r.stderr}"
        assert "timed out" in (r.stdout + r.stderr).lower(), "gate should surface the timed-out check"
    finally:
        if os.path.exists(probe):
            os.remove(probe)


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


def _mode_b_paths(rnd):
    sdir = os.path.join(REPO, "audit_arena/state")
    return (os.path.join(sdir, f"findings_r{rnd}.json"),
            os.path.join(sdir, f"verdicts_r{rnd}.json"),
            os.path.join(sdir, f"_modeb_defender_r{rnd}_prompt.md"))


def test_mode_b_builds_validates_and_writes(tmp_path):
    """Mode B wiring: with a MOCK provider (no real egress/key), the orchestrator assembles the
    prompt, captures the (fenced) response, extracts the JSON, and writes a valid role artifact."""
    rnd = "901"
    findings, out, promptf = _mode_b_paths(rnd)
    mock = tmp_path / "mock_llm.sh"
    mock.write_text("#!/usr/bin/env bash\n"
                    "printf '%s\\n' '```json' "
                    "'{\"verdicts\":[{\"id\":\"R901-01\",\"verdict\":\"CONFIRMED\","
                    "\"adjusted_severity\":\"LOW\",\"counter_evidence\":\"x:1\",\"reasoning\":\"ok\"}],"
                    "\"missed_strengths\":[]}' '```'\n")
    mock.chmod(0o755)
    try:
        json.dump({"findings": [{"id": "R901-01", "dimension": "D4", "invariant": "HCD-I6",
                                 "finding": "t", "severity": "LOW", "evidence": "Makefile:1"}]},
                  open(findings, "w"))
        env = dict(os.environ, ARENA_LLM_CMD=str(mock))
        r = subprocess.run([sys.executable, ARENA, "mode-b", "defender", rnd],
                           cwd=REPO, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        v = json.load(open(out))
        assert v["verdicts"][0]["id"] == "R901-01", "Mode B did not write the validated verdict"
    finally:
        for f in (findings, out, promptf):
            if os.path.exists(f):
                os.remove(f)


def test_mode_b_propagates_egress_fallback(tmp_path):
    """If the provider adapter exits 2 (egress off / no key), Mode B must propagate exit 2 (so the
    orchestrator uses Mode A) and write NO artifact."""
    rnd = "902"
    findings, out, promptf = _mode_b_paths(rnd)
    mock = tmp_path / "deny_llm.sh"
    mock.write_text("#!/usr/bin/env bash\nprintf '[mode-B] disabled\\n' >&2\nexit 2\n")
    mock.chmod(0o755)
    try:
        json.dump({"findings": []}, open(findings, "w"))
        env = dict(os.environ, ARENA_LLM_CMD=str(mock))
        r = subprocess.run([sys.executable, ARENA, "mode-b", "defender", rnd],
                           cwd=REPO, capture_output=True, text=True, env=env)
        assert r.returncode == 2, f"expected egress fallback exit 2, got {r.returncode}: {r.stderr}"
        assert not os.path.exists(out), "Mode B wrote an artifact despite egress fallback"
    finally:
        for f in (findings, out, promptf):
            if os.path.exists(f):
                os.remove(f)


# ─── F1 honesty reconciler (DESIGN_v2_roadmap.md Tier 0) ───────────────────────────────────────────
SDIR = os.path.join(REPO, "audit_arena/state")
COURT = os.path.join(REPO, "audit_arena/courtroom.html")
RECON = os.path.join(SDIR, "reconciliation.json")


def test_reconcile_rejects_score_wiring():
    """G1: a numeric score on a grades artefact is forbidden — a score is advisory and must never be a
    disposition surface. reconcile() must REJECT (exit 2), so there is no score->ship/block wiring."""
    probe = os.path.join(SDIR, "grades_r999.json")
    try:
        json.dump({"one_line_verdict": "looks great", "score": 9.5}, open(probe, "w"))
        r = _arena("reconcile")
        assert r.returncode == 2, f"reconcile must reject a score-wired grades artefact (got {r.returncode})"
        assert "score" in (r.stdout + r.stderr).lower()
    finally:
        if os.path.exists(probe):
            os.remove(probe)
        _arena("reconcile")


def test_reconcile_amber_on_deferred_invariant():
    """G2: no FAIL but a live invariant DEFERRED -> AMBER 'green-on-deferred', and AMBER NEVER blocks
    (honest deferral is not a failure)."""
    op = os.path.join(SDIR, "oracle_r999.json")
    ip = os.path.join(SDIR, "invariants_r999.json")
    try:
        json.dump({"checks": [{"check": "x", "dimension": "D1", "status": "PASS", "detail": ""}]}, open(op, "w"))
        json.dump({"invariants": [{"id": "HCD-I2", "status": "DEFERRED", "statement": "live"}]}, open(ip, "w"))
        r = _arena("reconcile")
        assert r.returncode == 0, f"AMBER must not block: {r.stdout}{r.stderr}"
        assert "AMBER" in r.stdout
        rec = json.load(open(RECON))
        assert rec["verdict"] == "AMBER" and "HCD-I2" in rec["invariant_deferred"]
    finally:
        for f in (op, ip):
            if os.path.exists(f):
                os.remove(f)
        _arena("reconcile")


def test_reconcile_red_and_flags_judge_contradiction():
    """G2: a ship-leaning judge co-existing with an Oracle FAIL is RED + recorded as a
    judge-contradicts-Oracle row — the Oracle wins regardless of the judge's opinion."""
    op = os.path.join(SDIR, "oracle_r999.json")
    gp = os.path.join(SDIR, "grades_r999.json")
    try:
        json.dump({"checks": [{"check": "ddm", "dimension": "D1", "status": "FAIL", "detail": "broke"}]}, open(op, "w"))
        # REAL judge schema (lenses.sre.disposition), not a synthetic top-level `disposition` the judge
        # never emits — otherwise the contradiction path could be dead on real output and this test blind.
        json.dump({"one_line_verdict": "ship it", "lenses": {"sre": {"disposition": "SHIP"}}}, open(gp, "w"))
        _arena("reconcile")
        rec = json.load(open(RECON))
        assert rec["verdict"] == "RED"
        assert "judge-ships-over-FAIL" in [c["kind"] for c in rec["contradictions"]], f"not flagged: {rec}"
    finally:
        for f in (op, gp):
            if os.path.exists(f):
                os.remove(f)
        _arena("reconcile")


def test_render_honesty_banner_leads_with_oracle():
    """G3 / honesty banner: the rendered dashboard leads with the BINDING (Oracle) verdict, dominant
    over any judge opinion, and states the score is advisory + read by no gate — 'Oracle beats
    advocates' as an executable assertion on the rendered output."""
    op = os.path.join(SDIR, "oracle_r999.json")
    gp = os.path.join(SDIR, "grades_r999.json")
    try:
        json.dump({"checks": [{"check": "ddm", "dimension": "D1", "status": "FAIL", "detail": "broke"}]}, open(op, "w"))
        json.dump({"one_line_verdict": "ship it", "lenses": {"sre": {"disposition": "SHIP"}}}, open(gp, "w"))
        _arena("reconcile")
        _arena("render")
        page = open(COURT, encoding="utf-8").read()
        assert "HONESTY: RED" in page, "banner must lead with the binding Oracle verdict"
        assert "advisory" in page and "read by no gate" in page, "banner must mark scores advisory"
        assert "judge contradicts Oracle" in page, "a ship-over-FAIL contradiction must surface"
    finally:
        for f in (op, gp):
            if os.path.exists(f):
                os.remove(f)
        _arena("reconcile")
        _arena("render")


def test_make_audit_runs_reconcile_before_gate():
    """reconcile must run in `make audit` AFTER manifest and BEFORE gate, so the honesty verdict and
    the score-wiring rejection are enforced on every audit and render shows the fresh banner."""
    mk = open(os.path.join(REPO, "Makefile")).read()
    seg = mk.split("audit:", 1)[1].split("\naudit-tribunal", 1)[0]
    assert "arena.py reconcile" in seg, "make audit must run the honesty reconciler"
    assert seg.index("arena.py reconcile") > seg.index("arena.py manifest"), "reconcile must run after manifest"
    assert seg.index("arena.py reconcile") < seg.index("arena.py gate"), "reconcile must run before gate"


def test_honesty_guardrails_doc_states_binding_rule():
    """The honesty discipline must be a documented contract, not tribal prose in a charter."""
    doc = os.path.join(REPO, "audit_arena/DESIGN_honesty_guardrails.md")
    assert os.path.exists(doc), "missing DESIGN_honesty_guardrails.md"
    t = open(doc).read().lower()
    assert "advisory" in t and "binding" in t and "read by no gate" in t


# ─── F2 contract spine (DESIGN_v2_roadmap.md Tier 0) ──────────────────────────────────────────────
def test_contract_is_authoritative_source():
    """arena LOADS the Definition-of-Done from the contract spine — INVARIANTS / SEV / _DUPKEY are
    DERIVED from it (one source of truth), not hardcoded literals."""
    arena = _load_arena()
    c = arena.CONTRACT
    for k in ("meta", "dimensions", "severity_scale", "invariants"):
        assert k in c, f"contract missing {k}"
    assert arena.INVARIANTS is c["invariants"], "INVARIANTS must be the contract's invariants"
    assert [i["id"] for i in arena.INVARIANTS] == [f"HCD-I{n}" for n in range(1, 8)]
    assert arena.SEV is c["severity_scale"], "SEV must come from the contract"
    i3 = next(i for i in c["invariants"] if i["id"] == "HCD-I3")
    assert arena._DUPKEY == i3["offline_cmd"], "_DUPKEY must be derived from contract HCD-I3 (no drift)"


def test_contract_content_sha256_is_self_consistent():
    """The contract carries a content hash over its own body; editing the contract without rehashing
    must be detectable (the `contract` subcommand FAILs on mismatch)."""
    arena = _load_arena()
    c = arena.CONTRACT
    assert c["meta"]["content_sha256"] == arena._contract_digest(c), \
        "content_sha256 does not match the contract body — regenerate the hash"


def test_contract_subcommand_validates():
    """`arena.py contract` validates semver + hash integrity + invariant well-formedness, exit 0 OK."""
    r = _arena("contract")
    assert r.returncode == 0, f"contract validation failed: {r.stdout}{r.stderr}"
    assert "CONTRACT OK" in r.stdout and "verified" in r.stdout


def test_contract_every_invariant_well_formed():
    """Every invariant carries id/dim/statement/mode and a runnable command for its mode, and its dim
    is one of the declared dimensions."""
    arena = _load_arena()
    c = arena.CONTRACT
    dims = {d["id"] for d in c["dimensions"]}
    for inv in c["invariants"]:
        for k in ("id", "dim", "statement", "mode"):
            assert inv.get(k), f"{inv.get('id', '?')} missing {k}"
        assert inv["dim"] in dims, f"{inv['id']} dim {inv['dim']} not declared"
        assert inv["mode"] in ("offline", "live")
        if inv["mode"] == "offline":
            assert inv.get("offline_cmd"), f"{inv['id']} offline without offline_cmd"
        else:
            assert inv.get("live_cmd") and inv.get("proxy_cmd"), f"{inv['id']} live without live_cmd+proxy_cmd"


def test_make_audit_validates_contract():
    """make audit must validate the contract spine (so an edited-without-rehash contract fails fast)."""
    mk = open(os.path.join(REPO, "Makefile")).read()
    seg = mk.split("audit:", 1)[1].split("\naudit-tribunal", 1)[0]
    assert "arena.py contract" in seg, "make audit must validate the contract spine"


# ─── F3 artefact lineage (DESIGN_v2_roadmap.md Tier 0) ────────────────────────────────────────────
def test_lineage_emits_oracle_dominant_provenance():
    """`lineage` emits one provenance object per finding with an Oracle-dominant status ladder."""
    r = _arena("lineage")
    assert r.returncode == 0, f"lineage failed: {r.stderr}"
    lin = json.load(open(sorted(__import__("glob").glob(os.path.join(SDIR, "lineage_r*.json")))[-1]))
    assert lin["findings"], "lineage produced no provenance objects"
    ladder = {"FILED", "VERIFIED", "ADJUDICATED", "REMEDIATED", "LIVE_CONFIRMED"}
    for o in lin["findings"]:
        assert {"id", "lineage_status", "layer_refs", "content_digests"} <= set(o), f"thin object: {o}"
        assert o["lineage_status"] in ladder


def test_lineage_status_follows_oracle_over_defender():
    """When the Defender (L4) says CONFIRMED but the Oracle (L5) says FIXED/PASS, the lineage status
    follows the Oracle and the disagreement is recorded — 'Oracle beats advocates' in provenance."""
    fp = os.path.join(SDIR, "findings_r999.json")
    vp = os.path.join(SDIR, "verdicts_r999.json")
    lp = os.path.join(SDIR, "lineage_r999.json")
    try:
        json.dump([{"id": "R9-01", "dimension": "D1", "invariant": "-", "finding": "probe",
                    "evidence": "x", "oracle_cmd": "true"}], open(fp, "w"))  # 'true' -> rc 0 -> FIXED
        json.dump([{"id": "R9-01", "verdict": "CONFIRMED"}], open(vp, "w"))
        _arena("lineage", "999")
        lin = json.load(open(lp))
        o = next(x for x in lin["findings"] if x["id"] == "R9-01")
        assert o["oracle_result"] == "FIXED" and o["status"] == "FIXED", o
        assert o["lineage_status"] == "ADJUDICATED", o
        assert "l4_l5_disagreement" in o, "Defender-vs-Oracle disagreement must be recorded"
    finally:
        for f in (fp, vp, lp):
            if os.path.exists(f):
                os.remove(f)


def test_render_consumes_lineage_not_subprocess():
    """render() must single-source the per-finding resolution from the gated lineage pass, NOT re-run
    each oracle_cmd at render time (the integrity win — computed once, in the gated step)."""
    src = open(ARENA).read()
    start = src.index("def render(")
    rbody = src[start:src.index("\ndef ", start)]
    assert '_latest("lineage_r*.json")' in rbody, "render must consume lineage_r*.json"
    assert "subprocess.run(cmd" not in rbody, "render must not re-execute oracle_cmd; it consumes lineage"


def test_manifest_has_audit_root_merkle():
    """manifest pins a single Merkle-style root over the binding layers (repo/oracle/invariants/lineage/
    contract) so any layer change moves one auditable digest."""
    _arena("lineage")
    r = _arena("manifest")
    assert r.returncode == 0, r.stderr
    man = json.loads(r.stdout)
    assert "audit_root_sha256" in man and man["audit_root_sha256"], "manifest missing audit_root_sha256"
    assert "lineage_sha256" in man, "manifest missing lineage_sha256"
    assert man["contract"]["content_sha256"], "manifest must pin the contract hash"


def test_make_audit_runs_lineage_before_manifest():
    """make audit must run lineage AFTER invariants and BEFORE manifest+render, so the manifest can hash
    it and render can consume it."""
    mk = open(os.path.join(REPO, "Makefile")).read()
    seg = mk.split("audit:", 1)[1].split("\naudit-tribunal", 1)[0]
    assert "arena.py lineage" in seg, "make audit must run lineage"
    assert seg.index("arena.py lineage") > seg.index("arena.py invariants"), "lineage after invariants"
    assert seg.index("arena.py lineage") < seg.index("arena.py manifest"), "lineage before manifest"
    assert seg.index("arena.py lineage") < seg.index("arena.py render"), "lineage before render"


# ─── Tier 0 verification fixes (adversarial review of the foundation) ──────────────────────────────
CONTRACT_FILE = os.path.join(REPO, "audit_arena/contract/contract.v1.json")


def test_reconcile_reads_real_judge_disposition_schema():
    """The judge emits lenses.sre.disposition (SHIP|CONDITIONAL-SHIP|BLOCK) or integrated_disposition prose
    — NOT a top-level `disposition`. The reconciler must read the real schema, incl. CONDITIONAL-SHIP, or
    the contradiction surface is dead on production output."""
    arena = _load_arena()
    assert arena._judge_disposition({"lenses": {"sre": {"disposition": "SHIP"}}}) == "ship"
    assert arena._judge_disposition({"integrated_disposition": "Disposition: CONDITIONAL-SHIP — ok"}) == "conditional-ship"
    assert arena._judge_disposition({"lenses": {"sre": "free text, no token"}}) == ""  # r2/r3 shape
    assert "conditional-ship" in arena._SHIP_LEANING, "CONDITIONAL-SHIP must count as ship-leaning"


def test_contract_tamper_without_rehash_is_detected():
    """Editing the contract body WITHOUT recomputing meta.content_sha256 must make `contract` FAIL —
    the integrity check has real teeth (committed regression, not just a manual check)."""
    original = open(CONTRACT_FILE, encoding="utf-8").read()
    try:
        c = json.loads(original)
        c["invariants"][0]["statement"] = "TAMPERED — should be caught"  # body changed, hash NOT updated
        json.dump(c, open(CONTRACT_FILE, "w"), indent=2)
        r = _arena("contract")
        assert r.returncode == 1, f"tamper not detected (exit {r.returncode}): {r.stdout}"
        assert "content_sha256 mismatch" in r.stdout
    finally:
        open(CONTRACT_FILE, "w", encoding="utf-8").write(original)


def test_contract_missing_degrades_gracefully():
    """A missing/corrupt contract must degrade to a clean, actionable error per subcommand — NOT a raw
    import-time traceback that takes down every subcommand (incl. the `contract` validator)."""
    original = open(CONTRACT_FILE, encoding="utf-8").read()
    try:
        os.remove(CONTRACT_FILE)
        r = _arena("contract")
        assert r.returncode == 2, f"expected clean exit 2, got {r.returncode}"
        assert "CONTRACT UNAVAILABLE" in r.stdout and "Traceback" not in (r.stdout + r.stderr)
    finally:
        open(CONTRACT_FILE, "w", encoding="utf-8").write(original)


def test_audit_root_is_deterministic_and_change_sensitive():
    """The manifest audit_root_sha256 is a Merkle root over the binding layers: stable when nothing
    changes, and it MOVES when any layer (here, the oracle results) changes."""
    _arena("lineage")
    base = json.loads(_arena("manifest").stdout)["audit_root_sha256"]
    again = json.loads(_arena("manifest").stdout)["audit_root_sha256"]
    assert base == again, "audit_root must be deterministic when nothing changes"
    op = os.path.join(SDIR, "oracle_r999.json")
    mp = os.path.join(SDIR, "manifest_r999.json")  # manifest defaults to _latest_round -> 999 while op exists
    try:
        json.dump({"checks": [{"check": "z", "dimension": "D1", "status": "FAIL", "detail": "x"}],
                   "passed": 0, "failed": 1, "deferred": 0}, open(op, "w"))
        moved = json.loads(_arena("manifest").stdout)["audit_root_sha256"]
        assert moved != base, "audit_root must change when a binding layer (oracle) changes"
    finally:
        for f in (op, mp):  # remove BOTH so _latest_round falls back to the real latest round
            if os.path.exists(f):
                os.remove(f)


def test_render_consumes_lineage_behaviorally():
    """render() must NOT execute any finding's oracle_cmd: after lineage runs the command once, render
    must not re-trigger its observable side effect (proves single-sourcing, not a literal grep)."""
    fp = os.path.join(SDIR, "findings_r998.json")
    lp = os.path.join(SDIR, "lineage_r998.json")
    sentinel = os.path.join(SDIR, "sentinel_998")
    try:
        json.dump([{"id": "R8-01", "dimension": "D1", "invariant": "-", "finding": "probe", "evidence": "x",
                    "oracle_cmd": f"touch {sentinel}"}], open(fp, "w"))
        _arena("lineage", "998")            # lineage runs the cmd -> sentinel created
        assert os.path.exists(sentinel), "lineage should have executed the oracle_cmd once"
        os.remove(sentinel)
        _arena("render")                    # render consumes lineage -> must NOT re-run the cmd
        assert not os.path.exists(sentinel), "render re-executed oracle_cmd (must consume lineage instead)"
    finally:
        for f in (fp, lp, sentinel):
            if os.path.exists(f):
                os.remove(f)
        _arena("render")


def test_lineage_stale_live_does_not_mask_current_oracle_fail():
    """Oracle dominance: a finding with a recorded live PASS but a CURRENT Oracle FAIL must cap at
    ADJUDICATED (never LIVE_CONFIRMED) and record an l5_l7 disagreement — a stale green cannot hide a fail."""
    fp = os.path.join(SDIR, "findings_r997.json")
    lp = os.path.join(SDIR, "lineage_r997.json")
    try:
        # invariant 'HCD-I1' has a recorded last_live PASS; pair it with an oracle_cmd that FAILs now.
        json.dump([{"id": "R7-01", "dimension": "D1", "invariant": "HCD-I1", "finding": "probe",
                    "evidence": "x", "oracle_cmd": "false"}], open(fp, "w"))
        _arena("lineage", "997")
        o = next(x for x in json.load(open(lp))["findings"] if x["id"] == "R7-01")
        assert o["oracle_result"] == "FAIL", o
        assert o["lineage_status"] == "ADJUDICATED", f"stale live PASS masked a current FAIL: {o}"
        assert "l5_l7_disagreement" in o, "the stale-live vs current-FAIL conflict must be recorded"
    finally:
        for f in (fp, lp):
            if os.path.exists(f):
                os.remove(f)


def test_lineage_records_false_positive_vs_oracle_fail_disagreement():
    """When the Defender dismissed a finding (FALSE_POSITIVE) but the Oracle FAILs, the disagreement is
    recorded (both directions) — the Oracle still wins."""
    fp = os.path.join(SDIR, "findings_r996.json")
    vp = os.path.join(SDIR, "verdicts_r996.json")
    lp = os.path.join(SDIR, "lineage_r996.json")
    try:
        json.dump([{"id": "R6-01", "dimension": "D1", "invariant": "-", "finding": "probe",
                    "evidence": "x", "oracle_cmd": "false"}], open(fp, "w"))
        json.dump([{"id": "R6-01", "verdict": "FALSE_POSITIVE"}], open(vp, "w"))
        _arena("lineage", "996")
        o = next(x for x in json.load(open(lp))["findings"] if x["id"] == "R6-01")
        assert "l4_l5_disagreement" in o and "FALSE_POSITIVE" in o["l4_l5_disagreement"], o
    finally:
        for f in (fp, vp, lp):
            if os.path.exists(f):
                os.remove(f)


# ─── T1 scored judge panel — Oracle ceiling re-derived in code (DESIGN_v2_roadmap.md Tier 1) ───────
def _panel(rnd, grades, oracle, invariants):
    """Drive panel-aggregate with probe artefacts at a high round; return the panel_rN.json dict."""
    gp = os.path.join(SDIR, f"grades_r{rnd}.json")
    op = os.path.join(SDIR, f"oracle_r{rnd}.json")
    ip = os.path.join(SDIR, f"invariants_r{rnd}.json")
    pp = os.path.join(SDIR, f"panel_r{rnd}.json")
    json.dump(grades, open(gp, "w"))
    json.dump(oracle, open(op, "w"))
    json.dump(invariants, open(ip, "w"))
    _arena("panel-aggregate", rnd)
    return json.load(open(pp)), (gp, op, ip, pp)


def test_panel_score_capped_at_5_on_invariant_fail():
    """A judge's 9.5 self-score is capped at 5 in CODE when any invariant FAILs — the Oracle ceiling is
    a verified fact, not a prompt request."""
    p, files = _panel("995", {"panel_scores": {"self_score": 9.5}},
                       {"checks": [{"check": "x", "status": "PASS"}]},
                       {"invariants": [{"id": "HCD-I3", "status": "FAIL"}]})
    try:
        assert p["judge_claimed"] == 9.5 and p["capped_to"] == 5.0 and p["ceiling_applied"] is True
    finally:
        for f in files:
            if os.path.exists(f):
                os.remove(f)


def test_panel_score_capped_at_7_on_oracle_fail():
    """An Oracle check FAIL (no invariant FAIL) caps the advisory score at 7."""
    p, files = _panel("994", {"panel_scores": {"self_score": 9.5}},
                       {"checks": [{"check": "ddm", "status": "FAIL"}]},
                       {"invariants": [{"id": "HCD-I3", "status": "PASS"}]})
    try:
        assert p["capped_to"] == 7.0 and p["ceiling_applied"] is True and "ddm" in p["ceiling_reason"]
    finally:
        for f in files:
            if os.path.exists(f):
                os.remove(f)


def test_panel_score_not_capped_when_clean():
    """No binding failure -> the judge's score stands (ceiling 10, not applied)."""
    p, files = _panel("993", {"panel_scores": {"self_score": 8.0}},
                       {"checks": [{"check": "x", "status": "PASS"}]},
                       {"invariants": [{"id": "HCD-I3", "status": "PASS"}]})
    try:
        assert p["capped_to"] == 8.0 and p["ceiling_applied"] is False and p["ceiling"] == 10.0
    finally:
        for f in files:
            if os.path.exists(f):
                os.remove(f)


def test_panel_score_is_advisory_never_reaches_gate():
    """The advisory score must be decoupled from the binding gate: a perfect score cannot rescue an
    Oracle FAIL, and a low score cannot block a clean run."""
    op = os.path.join(SDIR, "oracle_r992.json")
    pp = os.path.join(SDIR, "panel_r992.json")
    try:
        json.dump({"capped_to": 10.0, "judge_claimed": 10.0}, open(pp, "w"))  # perfect advisory score
        json.dump({"checks": [{"check": "x", "dimension": "D1", "status": "FAIL", "detail": "y"}]}, open(op, "w"))
        assert _arena("gate").returncode == 1, "a perfect advisory score must not rescue an Oracle FAIL"
    finally:
        for f in (op, pp):
            if os.path.exists(f):
                os.remove(f)


def test_panel_scores_block_allowed_top_level_score_still_rejected():
    """The sanctioned home for an advisory score is the `panel_scores` block (G1 allows it); a bare
    top-level `score` remains forbidden."""
    gp = os.path.join(SDIR, "grades_r991.json")
    try:
        json.dump({"panel_scores": {"self_score": 9.5}}, open(gp, "w"))
        assert _arena("reconcile").returncode == 0, "panel_scores block must be allowed by G1"
        json.dump({"score": 9.5}, open(gp, "w"))
        assert _arena("reconcile").returncode == 2, "a top-level score must still be rejected by G1"
    finally:
        if os.path.exists(gp):
            os.remove(gp)
        _arena("reconcile")


def test_make_audit_runs_panel_aggregate():
    """make audit must run panel-aggregate (after invariants, before reconcile/render)."""
    mk = open(os.path.join(REPO, "Makefile")).read()
    seg = mk.split("audit:", 1)[1].split("\naudit-tribunal", 1)[0]
    assert "arena.py panel-aggregate" in seg
    assert seg.index("arena.py panel-aggregate") < seg.index("arena.py render")


# ─── T2 routine multi-vendor panel (DESIGN_v2_roadmap.md Tier 1) ───────────────────────────────────
def _clean_panel(role="defender", rnd="1"):
    import glob as _g
    for f in (_g.glob(os.path.join(SDIR, f"vendor_panel_r{rnd}_{role}.json"))
              + _g.glob(os.path.join(SDIR, f"verdicts_r{rnd}__*.json"))
              + _g.glob(os.path.join(SDIR, f"grades_r{rnd}__*.json"))
              + _g.glob(os.path.join(SDIR, "_modeb_*"))):
        if os.path.exists(f):
            os.remove(f)


def _run_vendor_panel(env_extra, role="defender", rnd="1"):
    env = dict(os.environ)
    env.pop("ARENA_MODE_B", None)
    env.update(env_extra)
    subprocess.run([sys.executable, ARENA, "vendor-panel", role, rnd], cwd=REPO,
                   capture_output=True, text=True, env=env)
    return json.load(open(os.path.join(SDIR, f"vendor_panel_r{rnd}_{role}.json")))


def test_vendor_panel_egress_gated_all_abstain():
    """Without ARENA_MODE_B=1, every vendor is egress-gated and ABSTAINS — the panel still completes
    (never aborts) and records the abstentions. Egress discipline intact."""
    try:
        p = _run_vendor_panel({"ARENA_PANEL": "glm,gemini"})
        assert p["participated"] == [], f"no vendor should participate without egress opt-in: {p}"
        assert {a["vendor"] for a in p["abstained"]} == {"glm", "gemini"}
        assert all(a["kind"] == "egress_off" for a in p["abstained"])
    finally:
        _clean_panel()


def test_vendor_panel_detects_inter_vendor_dissent():
    """With mock vendors that disagree on a finding's verdict, the deterministic variance artifact flags
    the dissent — the inter-vendor divergence signal (the Oracle still settles it)."""
    mock = os.path.join(SDIR, "_mock_vendor.sh")
    try:
        with open(mock, "w") as fh:
            fh.write('#!/usr/bin/env bash\ncase "$ARENA_PROVIDER" in\n'
                     '  glm) echo \'{"verdicts":[{"id":"R1-01","verdict":"CONFIRMED"}]}\' ;;\n'
                     '  gemini) echo \'{"verdicts":[{"id":"R1-01","verdict":"FALSE_POSITIVE"}]}\' ;;\n'
                     '  *) echo \'{"verdicts":[{"id":"R1-01","verdict":"CONFIRMED"}]}\' ;;\nesac\n')
        os.chmod(mock, 0o755)
        p = _run_vendor_panel({"ARENA_PANEL": "glm,gemini", "ARENA_LLM_CMD": mock})
        assert set(p["participated"]) == {"glm", "gemini"}, p
        assert p["variance"]["agree"] is False
        assert "R1-01" in p["variance"]["dissent"], f"dissent not detected: {p['variance']}"
    finally:
        if os.path.exists(mock):
            os.remove(mock)
        _clean_panel()


def test_vendor_panel_abstain_does_not_abort_panel():
    """A vendor returning invalid JSON ABSTAINS; the other vendor still participates — one bad vendor
    must not sink the whole panel."""
    mock = os.path.join(SDIR, "_mock_vendor.sh")
    try:
        with open(mock, "w") as fh:
            fh.write('#!/usr/bin/env bash\ncase "$ARENA_PROVIDER" in\n'
                     '  glm) echo \'{"verdicts":[{"id":"R1-01","verdict":"CONFIRMED"}]}\' ;;\n'
                     '  *) echo \'not json at all\' ;;\nesac\n')
        os.chmod(mock, 0o755)
        p = _run_vendor_panel({"ARENA_PANEL": "glm,gemini", "ARENA_LLM_CMD": mock})
        assert p["participated"] == ["glm"], p
        assert any(a["vendor"] == "gemini" and a["kind"] == "invalid_json" for a in p["abstained"]), p
    finally:
        if os.path.exists(mock):
            os.remove(mock)
        _clean_panel()


def test_mode_b_call_helper_returns_status_without_exiting():
    """The extracted _mode_b_call helper returns a (status, payload) tuple and never sys.exits — so the
    panel driver can map a failure to 'abstain' instead of aborting."""
    arena = _load_arena()
    status, payload = arena._mode_b_call("defender", "99999")  # no findings_r99999 -> precondition error
    assert status == "error" and "findings" in str(payload), (status, payload)


# ─── Tier 1 verification fixes (adversarial review of T1/T2) ───────────────────────────────────────
def test_llm_sh_honors_arena_provider_override():
    """vendor-panel routes per-vendor via ARENA_PROVIDER; llm.sh must let it OVERRIDE the role default,
    else defender/judge collapse to one provider regardless of vendor (a single-vendor 'multi-vendor'
    panel). Discriminating: a sentinel provider must surface as 'unknown provider <sentinel>', NOT the
    role's glm default. This test FAILS against the pre-fix llm.sh."""
    llm = os.path.join(REPO, "audit_arena/bin/llm.sh")
    promptf = os.path.join(SDIR, "_p_routing.md")
    try:
        open(promptf, "w").write("test")
        env = dict(os.environ, ARENA_MODE_B="1", ARENA_PROVIDER="ZZSENTINEL")
        r = subprocess.run(["bash", llm, "defender", promptf], cwd=REPO, capture_output=True, text=True, env=env)
        out = (r.stdout + r.stderr).lower()
        assert "zzsentinel" in out, f"ARENA_PROVIDER override ignored for defender role: {out}"
        assert "glm" not in out, f"defender collapsed to its glm default despite ARENA_PROVIDER: {out}"
    finally:
        if os.path.exists(promptf):
            os.remove(promptf)


def test_llm_sh_anthropic_is_recognized_and_key_gated():
    """`anthropic` (Claude Opus 4.8, high effort) is a first-class vendor: a RECOGNIZED provider that,
    with no ANTHROPIC_API_KEY, exits 2 (the key-gated abstain path the panel relies on) — NOT exit 1
    'unknown provider'. Hermetic by construction: HOME is redirected to an empty dir so llm.sh's
    `source ~/.secrets.env` finds nothing, and ANTHROPIC_API_KEY is blanked — no real egress regardless
    of host env. Discriminating: FAILS against a pre-change llm.sh, where 'anthropic' falls through to
    the unknown-provider branch (exit 1)."""
    llm = os.path.join(REPO, "audit_arena/bin/llm.sh")
    import shutil
    import tempfile
    promptf = os.path.join(SDIR, "_p_anthropic.md")
    fakehome = tempfile.mkdtemp(prefix="arena_nohome_")
    try:
        open(promptf, "w").write("test")
        # HOME→empty dir defeats `source ~/.secrets.env` (which carries the real key); blank the var too.
        env = dict(os.environ, HOME=fakehome, ARENA_MODE_B="1",
                   ARENA_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
        r = subprocess.run(["bash", llm, "judge", promptf], cwd=REPO, capture_output=True, text=True, env=env)
        out = (r.stdout + r.stderr).lower()
        assert r.returncode == 2, f"anthropic with no key must exit 2 (abstain), got {r.returncode}: {out}"
        assert "anthropic_api_key" in out, f"expected key-gated message naming the missing key: {out}"
        assert "unknown provider" not in out, f"anthropic not recognized as a provider: {out}"
    finally:
        if os.path.exists(promptf):
            os.remove(promptf)
        shutil.rmtree(fakehome, ignore_errors=True)


def test_panel_score_floored_at_zero():
    """A negative advisory self_score is clamped to the rubric floor (0), not rendered as a grade — and
    it is a rubric clamp, not an Oracle ceiling (no binding failure occurred)."""
    p, files = _panel("988", {"panel_scores": {"self_score": -3.0}},
                       {"checks": [{"check": "x", "status": "PASS"}]},
                       {"invariants": [{"id": "HCD-I3", "status": "PASS"}]})
    try:
        assert p["capped_to"] == 0.0 and p["rubric_clamped"] is True and p["ceiling_applied"] is False
    finally:
        for f in files:
            if os.path.exists(f):
                os.remove(f)


def test_per_vendor_artifacts_excluded_from_binding_pipelines():
    """Per-vendor advisory artifacts (`__<vendor>`) must NOT leak into the canonical _by_round globs that
    feed the binding/aggregation pipelines (converge/render/lineage) — vendor diversity stays advisory."""
    arena = _load_arena()
    vp = os.path.join(SDIR, "verdicts_r3__glm.json")
    try:
        json.dump([{"id": "X", "verdict": "CONFIRMED"}], open(vp, "w"))
        got = arena._by_round("verdicts_r*.json")
        assert not any("__" in os.path.basename(f) for f in got), \
            "per-vendor __<vendor> artifact leaked into the binding verdicts glob"
    finally:
        if os.path.exists(vp):
            os.remove(vp)


def test_vendor_variance_handles_verdict_without_id():
    """A vendor verdict missing 'id' must not crash variance (a None key would break the cross-vendor
    sorted({ids}) with a TypeError)."""
    arena = _load_arena()
    part = [{"vendor": "glm", "view": arena._vendor_view("defender", [{"verdict": "CONFIRMED"}])}]
    v = arena._vendor_variance("defender", part)  # must not raise
    assert v["findings_compared"] == 0 and v["agree"] is True


# ─── T2 / G1 generative forge battle (DESIGN_v2_roadmap.md Tier 2) ─────────────────────────────────
def test_forge_contract_rejects_degenerate_and_harness_predicates():
    """A contract's acceptance predicates must EXERCISE a target_path (no vacuous `true`) and must NOT
    test the verification harness (no grading its own grader). The committed example is well-formed."""
    arena = _load_arena()
    deg = {"target_paths": ["README.md"], "acceptance": [{"clause": "v", "accept_cmd": "true"}]}
    har = {"target_paths": ["README.md"], "acceptance": [{"clause": "h", "accept_cmd": "grep x tests/test_arena.py"}]}
    assert any("vacuous" in e for e in arena._forge_validate(deg)), "vacuous predicate must be rejected"
    assert any("harness" in e for e in arena._forge_validate(har)), "harness predicate must be rejected"
    ex = json.load(open(os.path.join(REPO, "audit_arena/forge/example-version-pin.contract.json")))
    assert arena._forge_validate(ex) == [], "the committed example contract must be well-formed"


def test_forge_status_enforces_human_freeze():
    """The human-freeze: a machine-stubbed (unsigned) contract NEVER auto-promotes to ACCEPTED, even when
    every predicate passes — it caps at PROVISIONAL. ACCEPTED requires signed + pass + clean."""
    arena = _load_arena()
    assert arena._forge_status(True, [], [], True) == "ACCEPTED"
    assert arena._forge_status(False, [], [], True) == "PROVISIONAL"  # unsigned -> never ACCEPTED
    assert arena._forge_status(True, ["audit_arena/x"], [], True) == "UNTRUSTED"  # touches harness
    assert arena._forge_status(True, [], ["HCD-I1"], True) == "REJECTED"  # regressed an invariant
    assert arena._forge_status(True, [], [], False) == "REJECTED"  # a clause failed


def test_forge_signature_detects_acceptance_tamper():
    """Signing pins a digest over the acceptance block; editing acceptance changes the digest, so the
    signature goes stale (a signed contract whose predicates were altered cannot pass as signed)."""
    arena = _load_arena()
    c = {"target_paths": ["README.md"], "acceptance": [{"clause": "a", "accept_cmd": "grep x README.md"}],
         "must_not_regress": []}
    d = arena._acceptance_digest(c)
    c2 = json.loads(json.dumps(c))
    c2["acceptance"].append({"clause": "b", "accept_cmd": "grep y README.md"})
    assert arena._acceptance_digest(c2) != d, "editing acceptance must invalidate the signature digest"


def test_forge_converge_requires_two_accepted_rounds():
    """forge-converge is the K=2 analog gated on the ACCEPTANCE predicate: ACCEPTED iff the last 2 rounds
    are ACCEPTED with zero open defects — not converge()'s new==0 heuristic."""
    arena = _load_arena()
    fd = arena.FORGE_STATE
    os.makedirs(fd, exist_ok=True)
    fid = "test-converge-probe"
    f1, f2 = os.path.join(fd, f"{fid}_r1.json"), os.path.join(fd, f"{fid}_r2.json")
    try:
        json.dump({"contract": fid, "round": 1, "status": "ACCEPTED", "open_defects": 0}, open(f1, "w"))
        json.dump({"contract": fid, "round": 2, "status": "REJECTED", "open_defects": 1}, open(f2, "w"))
        assert arena.forge_converge(fid)["converged"] is False, "a rejected last round must not converge"
        json.dump({"contract": fid, "round": 2, "status": "ACCEPTED", "open_defects": 0}, open(f2, "w"))
        assert arena.forge_converge(fid)["converged"] is True, "2 consecutive ACCEPTED + 0 defects converges"
    finally:
        for f in (f1, f2):
            if os.path.exists(f):
                os.remove(f)


def test_forge_state_gitignored_but_contracts_tracked():
    """Per-run forge state is gitignored; the contracts (the human-signed TRUST ROOT) are tracked."""
    r1 = subprocess.run(["git", "check-ignore", "audit_arena/state/forge/x_r1.json"],
                        cwd=REPO, capture_output=True, text=True)
    assert r1.returncode == 0, "audit_arena/state/forge must be gitignored"
    r2 = subprocess.run(["git", "check-ignore", "audit_arena/forge/example-version-pin.contract.json"],
                        cwd=REPO, capture_output=True, text=True)
    assert r2.returncode != 0, "forge contracts (trust root) must be TRACKED, not ignored"


# ─── T2 / G2 pupitre console + replay (DESIGN_v2_roadmap.md Tier 2) ────────────────────────────────
def test_replay_runs_stored_command_by_id():
    """replay re-runs the STORED oracle_cmd for a finding that has one, reporting PASS/FAIL."""
    arena = _load_arena()
    fid = next((f["id"] for fp in arena._by_round("findings_r*.json")
                for f in json.load(open(fp)).get("findings", json.load(open(fp)) if isinstance(json.load(open(fp)), list) else [])
                if isinstance(f, dict) and f.get("oracle_cmd")), None)
    if not fid:
        import pytest
        pytest.skip("no committed finding carries an oracle_cmd")
    r = _arena("replay", fid)
    assert fid in r.stdout and ("PASS" in r.stdout or "FAIL" in r.stdout), r.stdout


def test_replay_argued_only_when_no_command():
    """Guard (a): a finding with no oracle_cmd is reported argued-only and never executed."""
    r = _arena("replay", "R1-01")  # R1-01 is argued-only (no binding command)
    assert "argued-only" in r.stdout, r.stdout


def test_replay_never_executes_a_command_string_only_ids():
    """Guard (b): replay looks up the STORED command by id and NEVER executes a passed string — a
    shell-injection 'id' resolves to an unknown id (NOT FOUND); nothing runs. The decisive security test."""
    sentinel = os.path.join(SDIR, "replay_pwned")
    try:
        r = _arena("replay", f"; touch {sentinel}")
        assert "NOT FOUND" in r.stdout, r.stdout
        assert not os.path.exists(sentinel), "replay EXECUTED an injected command string — guard (b) breached"
    finally:
        if os.path.exists(sentinel):
            os.remove(sentinel)


def test_pupitre_renders_with_guards():
    """The pupitre renders a 3-mode console over a valid JSON blob; guard (a) marks argued-only findings;
    the JS execution affordance is `replay <id>` (ids), with no in-browser command execution."""
    _arena("render")
    page = open(COURT, encoding="utf-8").read()
    assert 'id="pupitre"' in page and "Comprendre · Exécuter · Naviguer" in page
    assert "argued-only" in page, "guard (a): argued-only state must render for oracle_cmd-less findings"
    m = re.search(r"window.__PUPITRE__=(.*?);</script>", page, re.S)
    assert m, "embedded pupitre blob missing"
    blob = json.loads(m.group(1))  # must be valid JSON
    assert blob["findings"] and any(f["oracle_cmd"] is None for f in blob["findings"])
    src = open(ARENA).read()
    js = src[src.index("_PUPITRE_JS = r"):src.index("def replay(")]
    assert "replay '+ids.join" in js, "Exécuter must emit `replay <ids>` (ids, not a command string)"
    assert "eval(" not in js, "the pupitre must not eval anything in the browser"


# ─── Tier 2 verification fixes (adversarial review of forge + pupitre) ─────────────────────────────
def test_pupitre_blob_is_script_breakout_safe():
    """Stored-XSS regression: a finding field containing a close-script tag must NOT break out of the
    embedded <script> blob — render escapes HTML-significant chars to \\uXXXX, so no raw close-script or
    <img can appear. This test FAILS against the pre-fix raw-json.dumps embedding."""
    probe = os.path.join(SDIR, "findings_r987.json")
    payload = "pwn </script><img src=x onerror=alert(1)>"
    try:
        json.dump([{"id": "X987", "dimension": "D1", "finding": payload, "evidence": payload,
                    "invariant": "-"}], open(probe, "w"))
        _arena("render")
        page = open(COURT, encoding="utf-8").read()
        blob = page.split("window.__PUPITRE__=", 1)[1].split(";</script>", 1)[0]
        assert "</script>" not in blob, "script-breakout: a raw close-script tag reached the embedded blob"
        assert "<img" not in blob, "a raw <img reached the embedded blob"
        assert "\\u003c" in blob, "HTML-significant chars must be escaped to \\uXXXX"
    finally:
        if os.path.exists(probe):
            os.remove(probe)
        _arena("render")


def test_pupitre_esc_escapes_attribute_quotes():
    """The JS esc() is used in double-quoted data-* attributes; it must escape quotes, else an id/command
    containing a quote breaks out of the attribute."""
    src = open(ARENA).read()
    esc_line = [ln for ln in src.splitlines() if "function esc(s)" in ln][0]
    assert "&quot;" in esc_line and "&#39;" in esc_line, "esc() must escape both quote characters"


def test_forge_validate_rejects_path_namedropping_noops():
    """Defense-in-depth: a no-op that merely name-drops the target_path (in a comment or as a bare string)
    is rejected — a vacuous predicate certifies nothing. The human signature remains the trust boundary."""
    arena = _load_arena()
    for cmd in ("true # README.md", "echo README.md", "test -n README.md", ": README.md"):
        c = {"target_paths": ["README.md"], "acceptance": [{"clause": "x", "accept_cmd": cmd}]}
        assert arena._forge_validate(c), f"no-op predicate not rejected: {cmd!r}"
    ok = {"target_paths": ["README.md"], "acceptance": [{"clause": "x", "accept_cmd": "grep -q '2.0.6' README.md"}]}
    assert arena._forge_validate(ok) == [], "a real grep check must still pass"


# ─── v2 holistic-challenge fixes (forge end-to-end coverage + CLI dispatch smoke) ─────────────────
def test_forge_verify_signed_contract_reaches_accepted(tmp_path, monkeypatch):
    """End-to-end (the claim 'forge proven end-to-end' must mean THIS): a SIGNED contract + a candidate
    that satisfies every acceptance clause + a clean battery -> ACCEPTED via forge_verify. The SAME
    candidate on an UNSIGNED contract -> PROVISIONAL (human-freeze); a post-sign acceptance edit ->
    signature stale -> not ACCEPTED. (_battery_in is stubbed so the test doesn't re-run the full suite.)"""
    arena = _load_arena()
    monkeypatch.setattr(arena, "_battery_in", lambda cwd: {"overall": "PASS", "invariant_fail": []})
    fid = "test-e2e-accept"
    cpath = os.path.join(REPO, f"audit_arena/forge/{fid}.contract.json")
    cand = str(tmp_path / "cand.diff")
    probe = "_forge_e2e_probe.txt"
    open(cand, "w").write(f"diff --git a/{probe} b/{probe}\nnew file mode 100644\n--- /dev/null\n"
                          f"+++ b/{probe}\n@@ -0,0 +1 @@\n+ARENA_E2E_OK\n")
    c = {"id": fid, "target_paths": [probe],
         "acceptance": [{"clause": "probe present", "accept_cmd": f"grep -q ARENA_E2E_OK {probe}"}],
         "must_not_regress": [], "human_signed": False, "signed_sha256": None}
    try:
        json.dump(c, open(cpath, "w"))
        v = arena.forge_verify(fid, cand)
        assert v["status"] == "PROVISIONAL", f"unsigned must cap at PROVISIONAL: {v.get('status')}"
        assert all(cl["status"] == "PASS" for cl in v["acceptance"]), v
        c["human_signed"] = True
        c["signed_sha256"] = arena._acceptance_digest(c)
        json.dump(c, open(cpath, "w"))
        v2 = arena.forge_verify(fid, cand)
        assert v2["status"] == "ACCEPTED", f"signed + all-pass + clean must be ACCEPTED: {v2.get('status')}"
        c["acceptance"].append({"clause": "extra", "accept_cmd": f"grep -q ARENA_E2E_OK {probe}"})
        json.dump(c, open(cpath, "w"))
        v3 = arena.forge_verify(fid, cand)
        assert v3["contract_signed"] is False and v3["status"] != "ACCEPTED", \
            f"a post-sign acceptance edit must invalidate the signature: {v3.get('status')}"
    finally:
        if os.path.exists(cpath):
            os.remove(cpath)


def test_forge_cli_dispatch_arms_wired():
    """The forge CLI dispatch arms are wired (not just the functions) — forge-contract validates the
    committed example, forge-converge handles an unknown id without crashing."""
    assert _arena("forge-contract", "example-version-pin").returncode == 0
    r = _arena("forge-converge", "no-such-contract")
    assert r.returncode == 0 and '"converged": false' in r.stdout, r.stdout
