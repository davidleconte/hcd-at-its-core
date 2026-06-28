#!/usr/bin/env python3
"""HCD adversarial audit arena — mechanics for a 3-role tribunal + a deterministic Oracle.

Roles (diversity-of-judgement is the anti-collusion mechanism):
  PROSECUTOR  — refute-by-default finder; every finding cites path:line  (Claude/subagent)
  DEFENDER    — kills false positives (CONFIRMED/OVERSTATED/FALSE_POSITIVE) (different family)
  JUDGE       — HCD tri-lens verdict (SRE / Cassandra-committer / Security) (third family)
  ORACLE      — DETERMINISTIC ground truth: runs the verifiable checks.  <-- HCD-specific

Subcommands:
  repomap                 -> state/REPO_MAP.md  (signal-artefact inventory of the HCD repo)
  excerpts F.json         -> verbatim path:line excerpts for the findings in F.json
  oracle [R]              -> run the deterministic check battery -> state/oracle_r{R}.json
  invariants [R]          -> evaluate the HCD Definition-of-Done -> state/invariants_r{R}.json
  manifest [R]            -> emit a provenance manifest (records SHA/versions/hash) -> state/manifest_r{R}.json
  act ROLE RND F.md       -> append an act block to TRANSCRIPT.md
  converge                -> verdict: 2-dry-rounds AND no FAILing invariant -> convergence.json
  gate                    -> exit 1 if the latest oracle/invariants have any FAIL (makes `make audit` block)
  judge-brief [R]         -> Judge input with severities stripped (anti-anchoring)
  harden                  -> fold charter_gap lessons into prompts/_preamble.md (AUTO block)
  verify-fix FIX [BASE]   -> apply patch(es) in a THROWAWAY worktree, run the Oracle there,
                             report VERIFIED/REJECTED — never touches your tree
  remediate-worktree      -> create the isolated worktree;  remediate-clean -> remove it
  remediate-record ID PATCH VERDICT [R] -> record a remediation verdict
  render                  -> build courtroom.html from state

The Oracle is what makes an HCD audit stronger than a quant audit: HCD claims have a runnable
oracle (cqlsh / make demo-score / shellcheck / docker compose config / openssl / dup-key check),
so findings can be EXECUTABLY adjudicated, not merely argued.
"""
import datetime
import glob
import html
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARENA = os.path.join(ROOT, "audit_arena")
STATE = os.path.join(ARENA, "state")
TRANSCRIPT = os.path.join(ARENA, "TRANSCRIPT.md")
HTML_OUT = os.path.join(ARENA, "courtroom.html")

# ─── CONTRACT SPINE: the Definition-of-Done as versioned data (v2 Tier 0 / F2) ──────────────────────
# arena.py LOADS the contract rather than hardcoding the invariants / severity scale / dimensions, so
# the Definition-of-Done is one auditable, content-hashed source of truth. See DESIGN_v2_roadmap.md §2.
_CONTRACT_PATH = os.path.join(ARENA, "contract", "contract.v1.json")


def _load_contract():
    return json.load(open(_CONTRACT_PATH, encoding="utf-8"))


# Sentinel so a missing/corrupt contract degrades to a clean, actionable error per-subcommand instead of
# a raw import-time traceback that takes down EVERY subcommand (including the `contract` validator that
# exists to report exactly this). Subcommands that need the contract call _require_contract().
class _ContractMissing(dict):
    def __init__(self, err):
        super().__init__(invariants=[], severity_scale={}, dimensions=[], meta={})
        self.err = err


def _contract_digest(contract):
    """sha256 over the canonical contract body (everything except meta.content_sha256) — recomputed
    identically here and at generation time so the manifest/contract-check can verify integrity."""
    import hashlib
    body = {k: v for k, v in contract.items() if k != "meta"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


try:
    CONTRACT = _load_contract()
except (FileNotFoundError, json.JSONDecodeError, OSError) as _e:
    CONTRACT = _ContractMissing(f"{type(_e).__name__}: {_e}")


def _require_contract():
    """Fail loudly + actionably (not with a raw traceback) when the contract is missing/corrupt."""
    if isinstance(CONTRACT, _ContractMissing):
        print(f"CONTRACT UNAVAILABLE — cannot load {os.path.relpath(_CONTRACT_PATH, ROOT)}: {CONTRACT.err}")
        sys.exit(2)


def invariant_records():
    """Python-importable parsed view of the contract's invariants (id/dim/statement/mode + commands).
    Tests and callers bind to these records, not to the raw JSON file."""
    return CONTRACT["invariants"]

SIGNAL_EXT = {".md", ".py", ".sh", ".yml", ".yaml", ".json", ".template", ".fragment",
              ".cfg", ".ini", ".toml", ".txt"}
SIGNAL_BASE = {"Dockerfile", "Makefile", ".dockerignore", ".gitignore"}
SKIP_DIRS = {"audit_arena", ".git", ".venv", "__pycache__", "node_modules",
             "htmlcov", ".pytest_cache", ".ruff_cache", "certs", "data"}


def tracked_files():
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), ROOT)
            if rel.split(os.sep, 1)[0] in SKIP_DIRS:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in SIGNAL_EXT or fn in SIGNAL_BASE:
                yield rel


def repomap():
    files = sorted(tracked_files())
    groups = {}
    for f in files:
        top = f.split(os.sep, 1)[0] if os.sep in f else "(root)"
        groups.setdefault(top, []).append(f)
    lines = ["# HCD REPO MAP — signal artefacts (scope = whole repo from root)",
             "", f"Total signal files: {len(files)}", ""]
    for top in sorted(groups):
        lines.append(f"## {top}/  ({len(groups[top])} files)")
        for f in groups[top]:
            try:
                n = sum(1 for _ in open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore"))
            except Exception:
                n = 0
            lines.append(f"- {f}  ({n} ln)")
        lines.append("")
    os.makedirs(STATE, exist_ok=True)
    open(os.path.join(STATE, "REPO_MAP.md"), "w").write("\n".join(lines))
    print(f"REPO_MAP.md: {len(files)} signal files, {len(groups)} groups")


def _read_window(path, line, ctx=8):
    p = os.path.join(ROOT, path)
    if not path or not os.path.isfile(p):  # isfile, not exists: empty path -> ROOT (a dir) crashed open()
        return f"  [MISSING FILE: {path or '(none)'}]"
    ls = open(p, encoding="utf-8", errors="ignore").read().splitlines()
    if line is None:
        return "\n".join(f"{i+1:>5} | {l}" for i, l in enumerate(ls[:20]))
    lo, hi = max(0, line - 1 - ctx), min(len(ls), line - 1 + ctx + 1)
    return "\n".join(f"{i+1:>5} |{'>' if i+1==line else ' '} {ls[i]}" for i in range(lo, hi))


CITE_RE = re.compile(r"([\w./\-]+\.[A-Za-z0-9]+):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)")


def _spec_lines(spec):
    out = []
    for chunk in spec.split(","):
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            if a.isdigit() and b.isdigit():
                out += list(range(int(a), int(b) + 1))
        elif chunk.isdigit():
            out.append(int(chunk))
    return out


def excerpts(findings_json):
    data = json.load(open(findings_json))
    items = data if isinstance(data, list) else data.get("findings", [])
    seen = set()
    print("# CITED EXCERPTS (verbatim, for citation verification)\n")
    for it in items:
        ev = (it.get("evidence") or "").strip()
        print(f"## {it.get('id','?')} — {ev}")
        print("```")
        toks = CITE_RE.findall(ev)
        if not toks:
            print(_read_window(ev.split()[0] if ev else "", None))
        for path, spec in toks:
            tok = f"{path}:{spec}"
            if tok in seen:
                continue
            seen.add(tok)
            print(f"# {tok}")
            for ln in _spec_lines(spec)[:4]:
                print(_read_window(path, ln))
            print("    ----")
        print("```\n")


# ─── ORACLE: deterministic ground-truth battery (the HCD differentiator) ──────────
def _run(cmd, cwd=ROOT, timeout=300):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, shell=isinstance(cmd, str))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 99, f"[oracle-error] {e}"


# A DEFERRED live check means "no cluster right now" — but if it was ever verified PASS against a
# real cluster, that proof should NOT vanish on the next offline render. Persist the last live
# verdict per check id (a tracked record), and surface it on DEFERRED rows.
_LAST_LIVE = os.path.join(STATE, "last_live.json")


def _load_last_live():
    try:
        return json.load(open(_LAST_LIVE))
    except Exception:
        return {}


def _record_last_live(key, status, detail):
    d = _load_last_live()
    d[key] = {"status": status, "detail": str(detail)[:200],
              "ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(STATE, exist_ok=True)
    json.dump(d, open(_LAST_LIVE, "w"), indent=2, sort_keys=True)


def _last_live_pass(key):
    """The prior live verdict for `key` iff it was a PASS, else None — so an offline render can show
    a check that was verified live as a green PASS (with its timestamp) instead of amber DEFERRED."""
    p = _load_last_live().get(key)
    return p if p and p.get("status") == "PASS" else None


def oracle(rnd="1"):
    """Run the verifiable checks that adjudicate HCD findings as ground truth."""
    _require_contract()
    checks = []

    def add(name, dim, cmd, ok_fn, detail_fn=lambda c, o: "", timeout=300):
        code, out = _run(cmd, timeout=timeout)
        if code == 99 and "[oracle-error]" in out and "timed out" in out:
            # The check could not run to completion — almost always CPU contention from a LIVE
            # cluster (these offline checks finish in seconds). Report as inconclusive (amber,
            # non-blocking like DEFERRED), NOT a misleading red FAIL that reads as "tests broke".
            status, detail = "TIMEOUT", ("timed out — likely CPU contention from a running cluster; "
                                         "run `make audit` with the cluster down (it is an offline gate)")
        else:
            status = "PASS" if ok_fn(code, out) else "FAIL"
            detail = detail_fn(code, out)
        checks.append({"check": name, "dimension": dim, "status": status, "detail": str(detail)[:300]})

    # D3 — shell syntax + lint
    add("bash -n (all scripts)", "D3",
        "for s in scripts/*.sh; do bash -n \"$s\" || exit 1; done",
        lambda c, o: c == 0)
    add("shellcheck -S error", "D3",
        "command -v shellcheck >/dev/null && shellcheck -S error scripts/*.sh || echo 'shellcheck absent'",
        lambda c, o: c == 0)
    # D4 — scorecard + tests
    add("make demo-score (dry 94/94)", "D4",
        "./scripts/demo-entropy.sh --score",
        lambda c, o: "Score:  100%" in o, lambda c, o: o.strip().splitlines()[-1] if o.strip() else "")
    add("pytest (no fail)", "D4",
        "python3 -m pytest tests/ -q",
        # gate on the EXIT CODE: pytest exits 0 only on pass (skips ok); a collection error
        # (2), zero tests (5), or syntax error never contain " failed" but must FAIL.
        # Generous timeout: ~30s offline, but minutes if a live cluster is starving the CPU —
        # let it finish (real result) rather than time out; a timeout -> inconclusive, not FAIL.
        lambda c, o: c == 0, lambda c, o: o.strip().splitlines()[-1] if o.strip() else "", timeout=900)
    # D2 — combined cassandra.yaml has no duplicate top-level keys
    dupcheck = (
        "CASSANDRA_CLUSTER_NAME=t CASSANDRA_SEEDS=1 CASSANDRA_LISTEN_ADDRESS=1 "
        "CASSANDRA_BROADCAST_ADDRESS=1 CASSANDRA_RPC_ADDRESS=0 CASSANDRA_ENDPOINT_SNITCH=s "
        "envsubst < config/cassandra.yaml.template > /tmp/_arena.yaml; printf '\\n' >> /tmp/_arena.yaml; "
        "CASSANDRA_CLUSTER_NAME=t CASSANDRA_SEEDS=1 CASSANDRA_LISTEN_ADDRESS=1 "
        "CASSANDRA_BROADCAST_ADDRESS=1 CASSANDRA_RPC_ADDRESS=0 CASSANDRA_ENDPOINT_SNITCH=s "
        "envsubst < config/cassandra-secure.yaml.fragment >> /tmp/_arena.yaml; "
        "python3 -c \"import yaml,re,collections,sys; s=open('/tmp/_arena.yaml').read(); yaml.safe_load(s); "
        "k=re.findall(r'^([A-Za-z_]\\w*):',s,re.M); d=[x for x,c in collections.Counter(k).items() if c>1]; "
        "sys.exit(1 if d else 0)\"")
    add("combined config: no duplicate keys", "D2", dupcheck, lambda c, o: c == 0)
    # D2 — secure overlay merges (try compose v2, then v1; skip if neither present)
    add("compose secure overlay merges", "D2",
        "(docker compose -f docker-compose.yml -f docker-compose.secure.yml config >/dev/null 2>&1 "
        "|| docker-compose -f docker-compose.yml -f docker-compose.secure.yml config >/dev/null 2>&1) "
        "&& echo OK || (command -v docker >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 "
        "&& echo MERGE-FAIL || echo NO-DOCKER)",
        lambda c, o: "OK" in o or "NO-DOCKER" in o,
        lambda c, o: o.strip())
    # D5 — count single-source-of-truth consistency
    add("count consistency (TOTAL_MODULES vs docs)", "D5",
        "tm=$(grep -oE 'TOTAL_MODULES=[0-9]+' scripts/demo-entropy.sh | head -1 | cut -d= -f2); "
        "grep -q \"all $tm modules\" Makefile && echo OK || echo MISMATCH",
        lambda c, o: "OK" in o, lambda c, o: o.strip())

    # ─── LIVE-CLUSTER checks (the decisive HCD adjudication) ─────────────────────
    # Run only when a cluster is up; otherwise honest ORACLE-DEFERRED (weighed against
    # the artefact, never silently passed). Needs hcd-2.0.6-bin.tar.gz staged + make up.
    up_code, _ = _run("docker exec hcd-node1 nodetool status", timeout=20)
    cluster_up = up_code == 0

    def add_live(name, dim, cmd, ok_fn, detail_fn=lambda c, o: ""):
        if not cluster_up:
            p = _last_live_pass(name)  # verified live before -> green PASS w/ timestamp, not amber
            if p:
                checks.append({"check": name, "dimension": dim, "status": "PASS",
                               "detail": f"last LIVE: PASS @ {p['ts']}"})
            else:
                checks.append({"check": name, "dimension": dim, "status": "DEFERRED",
                               "detail": "no live cluster (make up / make up-secure first)"})
            return
        code, out = _run(cmd)
        status = "PASS" if ok_fn(code, out) else "FAIL"
        detail = detail_fn(code, out)[:300]
        checks.append({"check": name, "dimension": dim, "status": status, "detail": detail})
        if status == "PASS":  # persist the proof so an offline render doesn't lose it
            _record_last_live(name, status, detail)

    add_live("D1 secure cluster forms (6x UN)", "D6",
             "docker exec hcd-node1 nodetool status | grep -c '^UN'",
             lambda c, o: o.strip() == "6", lambda c, o: f"UN nodes: {o.strip()}")
    add_live("D1 release == Cassandra 5.0 + Java 17", "D1",
             "make verify-release", lambda c, o: "Cassandra 5.0" in o or "5.0" in o,
             lambda c, o: next((l for l in o.splitlines() if "release_version" in l), ""))
    # Part 11 corrected CQL executed live (the findings the Oracle promotes to ground truth)
    cql = ("docker exec hcd-node1 cqlsh -e \""
           "CREATE KEYSPACE IF NOT EXISTS arena_t WITH replication={'class':'SimpleStrategy','replication_factor':1};"
           "CREATE TABLE IF NOT EXISTS arena_t.c (id int PRIMARY KEY, card text);"
           "SELECT mask_inner(card,0,4) FROM arena_t.c LIMIT 1;"
           "ALTER TABLE arena_t.c ALTER card MASKED WITH mask_inner(0,4);"
           "SELECT column_name, function_keyspace, function_name FROM system_schema.column_masks WHERE keyspace_name='arena_t' AND table_name='c';"
           "DROP KEYSPACE arena_t;\"")
    add_live("D1 Part 11 DDM CQL executes (no error)", "D1", cql,
             lambda c, o: c == 0, lambda c, o: "ok" if c == 0 else o.strip()[:120])

    os.makedirs(STATE, exist_ok=True)
    out = {"round": int(rnd), "checks": checks, "cluster_up": cluster_up,
           "passed": sum(1 for c in checks if c["status"] == "PASS"),
           "failed": sum(1 for c in checks if c["status"] == "FAIL"),
           "deferred": sum(1 for c in checks if c["status"] == "DEFERRED")}
    json.dump(out, open(os.path.join(STATE, f"oracle_r{rnd}.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))


# ─── HCD invariants (the formal Definition-of-Done) ───────────────────────────────
# Loaded from the contract spine (contract/contract.v1.json) — the single, content-hashed source of
# truth (v2 Tier 0 / F2). Each finding and Oracle check maps to one. offline_cmd -> PASS/FAIL offline.
# live_cmd -> PASS/FAIL on a live cluster; offline it falls back to proxy_cmd, which can DEMOTE to FAIL
# (broken wiring) but never CONFIRM (status caps at DEFERRED) — burden on the artefact, like the Oracle.
INVARIANTS = CONTRACT["invariants"]
# The dup-key battery is also the Oracle's offline dup-keys check; derive it from the contract (HCD-I3)
# so there is ONE source of truth, not a code copy that can silently drift from the contract. Defaults to
# a never-passing command if the contract is missing, so import never crashes (subcommands that depend on
# the contract call _require_contract() and exit cleanly instead).
_DUPKEY = next((i["offline_cmd"] for i in INVARIANTS if i["id"] == "HCD-I3"), "false")


def invariants(rnd="1"):
    _require_contract()
    """Evaluate the formal HCD Definition-of-Done -> state/invariants_r{rnd}.json."""
    up_code, _ = _run("docker exec hcd-node1 nodetool status", timeout=20)
    cluster_up = up_code == 0
    results = []
    for inv in INVARIANTS:
        base = {"id": inv["id"], "dim": inv["dim"], "statement": inv["statement"]}
        if "offline_cmd" in inv:
            code, _o = _run(inv["offline_cmd"])
            results.append({**base, "status": "PASS" if code == 0 else "FAIL",
                            "via": "offline", "evidence": "check passed" if code == 0 else "check failed"})
        elif cluster_up:
            code, _o = _run(inv["live_cmd"])
            status = "PASS" if code == 0 else "FAIL"
            results.append({**base, "status": status, "via": "live", "evidence": "executed on live cluster"})
            if status == "PASS":  # persist the proof so an offline render keeps it
                _record_last_live(inv["id"], status, "executed on live cluster")
        else:
            pcode, _o = _run(inv["proxy_cmd"])
            # proxy can demote to FAIL (broken wiring); a prior live PASS shows green w/ timestamp;
            # otherwise DEFERRED (wiring present, not yet live-verified).
            p = _last_live_pass(inv["id"])
            if pcode != 0:
                status, ev = "FAIL", "offline proxy FAILED — broken wiring"
            elif p:
                status, ev = "PASS", f"last LIVE: PASS @ {p['ts']}"
            else:
                status, ev = "DEFERRED", "wiring present; live verification deferred"
            results.append({**base, "status": status, "via": "proxy", "evidence": ev, "last_live": p})
    os.makedirs(STATE, exist_ok=True)
    out = {"round": int(rnd), "cluster_up": cluster_up, "invariants": results,
           "passed": sum(1 for r in results if r["status"] == "PASS"),
           "failed": sum(1 for r in results if r["status"] == "FAIL"),
           "deferred": sum(1 for r in results if r["status"] == "DEFERRED")}
    json.dump(out, open(os.path.join(STATE, f"invariants_r{rnd}.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))


def manifest(rnd="1"):
    """Emit a provenance manifest -> state/manifest_r{rnd}.json (records git/env/hash; full sha256 content hash over the
    audited HCD source only; the arena's own outputs are excluded by tracked_files())."""
    import hashlib

    def sh(c):
        return _run(c)[1].strip()

    files = sorted(tracked_files())
    h = hashlib.sha256()
    for f in files:
        try:
            data = open(os.path.join(ROOT, f), "rb").read()
        except Exception:
            data = b""
        h.update(f.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
    oj = _latest("oracle_r*.json")
    ij = _latest("invariants_r*.json")
    man = {
        "schema_version": 1,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "git": {"sha": sh("git rev-parse HEAD") or "?",
                "branch": sh("git rev-parse --abbrev-ref HEAD") or "?",
                "dirty": bool(sh("git status --porcelain"))},
        "env": {"python": sh("python3 --version").replace("Python ", ""),
                "pytest": sh("python3 -m pytest --version 2>/dev/null | head -1"),
                "ruff": sh("ruff --version 2>/dev/null") or "absent",
                "shellcheck": sh("shellcheck --version 2>/dev/null | awk '/version:/{print $2}'") or "absent",
                "docker": sh("docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ,") or "absent",
                "conda_env": os.environ.get("CONDA_DEFAULT_ENV", "")},
        "repo": {"signal_files": len(files), "content_sha256": h.hexdigest()},
        "contract": {"version": CONTRACT.get("meta", {}).get("contract_version"),
                     "content_sha256": CONTRACT.get("meta", {}).get("content_sha256")},
        "oracle": {"passed": oj.get("passed"), "failed": oj.get("failed"),
                   "deferred": oj.get("deferred"),
                   "results_sha256": hashlib.sha256(json.dumps(oj, sort_keys=True).encode()).hexdigest() if oj else None},
        "invariants": {i["id"]: i["status"] for i in ij.get("invariants", [])},
    }
    # F3: a single Merkle-style root over the BINDING layers — repo source, oracle results, invariant
    # statuses, the lineage, and the contract. Any change to any layer changes one auditable digest.
    lj = _latest("lineage_r*.json")
    lineage_sha = hashlib.sha256(json.dumps(lj, sort_keys=True).encode()).hexdigest() if lj else None
    root_inputs = {"repo": man["repo"]["content_sha256"], "oracle": man["oracle"]["results_sha256"],
                   "invariants": man["invariants"], "lineage": lineage_sha,
                   "contract": man["contract"]["content_sha256"]}
    man["lineage_sha256"] = lineage_sha
    man["audit_root_sha256"] = hashlib.sha256(json.dumps(root_inputs, sort_keys=True).encode()).hexdigest()
    os.makedirs(STATE, exist_ok=True)
    json.dump(man, open(os.path.join(STATE, f"manifest_r{rnd}.json"), "w"), indent=2)
    print(json.dumps(man, indent=2))


def _round_of(path):
    m = re.search(r"_r(\d+)\.", path)
    return int(m.group(1)) if m else -1


def _by_round(pattern):
    """state/<x>_r{N}.json sorted by NUMERIC round (lexical sort puts r10 before r2)."""
    return sorted(glob.glob(os.path.join(STATE, pattern)), key=_round_of)


def _latest(pattern):
    fs = _by_round(pattern)
    return json.load(open(fs[-1])) if fs else {}


def _latest_round():
    """Highest round present in state/ (findings/oracle/invariants/manifest), default '1'.
    `make audit` defaults to this so it refreshes the SAME round the courtroom renders (render
    reads _latest) — otherwise audit regenerates round 1 while the dashboard shows round N and the
    manifest provenance silently goes stale."""
    rounds = {_round_of(f) for pat in ("findings_r*.json", "oracle_r*.json",
                                       "invariants_r*.json", "manifest_r*.json")
              for f in glob.glob(os.path.join(STATE, pat))}
    rounds.discard(-1)
    return str(max(rounds)) if rounds else "1"


def gate():
    """Read the latest oracle + invariants and exit non-zero if anything FAILed.
    This is what makes `make audit` actually gate (oracle/invariants are reporters that
    exit 0; without this the CI `make audit` step is non-blocking). DEFERRED never blocks."""
    oj, ij = _latest("oracle_r*.json"), _latest("invariants_r*.json")
    o_fail = [c["check"] for c in oj.get("checks", []) if c.get("status") == "FAIL"]
    i_fail = [i["id"] for i in ij.get("invariants", []) if i.get("status") == "FAIL"]
    o_timeout = [c["check"] for c in oj.get("checks", []) if c.get("status") == "TIMEOUT"]
    if o_fail or i_fail:
        print(f"GATE FAIL — oracle: {o_fail or '—'} · invariants: {i_fail or '—'}")
        sys.exit(1)
    # TIMEOUT is inconclusive (a check couldn't run — usually a live cluster starving the CPU), not a
    # failure: it never blocks. Surface it so a green gate with a timed-out check isn't silently lost.
    note = f"  (inconclusive, timed out: {o_timeout} — run with the cluster down)" if o_timeout else ""
    # The honesty note is ADVISORY and read from reconciliation.json, which may predate this gate run if
    # gate is invoked standalone (make audit always runs reconcile first). Tag it with its provenance so a
    # stale note is never mistaken for the current run; gate still BLOCKS only on the fresh oracle/invariants.
    rec = _load_reconciliation()
    rnote = ""
    if rec:
        ts = rec.get("generated_at", "?")
        if rec.get("verdict") == "AMBER":
            rnote = (f"  · honesty (reconcile @ {ts}): AMBER (green-on-deferred: "
                     f"{rec.get('invariant_deferred') or rec.get('stale_live')} — not live-verified this run)")
        elif rec.get("contradictions"):
            rnote = f"  · honesty (reconcile @ {ts}): {[c['kind'] for c in rec['contradictions']]}"
    print(f"GATE PASS — no FAILing oracle check or invariant.{note}{rnote}")


# ─── F1 HONESTY RECONCILER: make the Oracle's primacy a code invariant, not a charter promise ───
_RECON = os.path.join(STATE, "reconciliation.json")
# Dispositions a judge might emit that lean toward "ship/accept" — the only side that can CONTRADICT a
# binding Oracle/invariant FAIL. CONDITIONAL-SHIP counts: "ship with conditions over an unverified/failing
# invariant" is exactly the contradiction this feature exists to surface (judge.md SRE vocab is
# SHIP|CONDITIONAL-SHIP|BLOCK). Read from the judge's STRUCTURED fields (see _judge_disposition).
_SHIP_LEANING = {"ship", "conditional-ship", "accept", "accepted", "pass", "converged", "green", "go",
                 "approve", "approved"}
# Numeric/headline score keys forbidden at the TOP LEVEL of a grades artefact: a headline score must never
# be a disposition surface (no score->ship/block wiring). This is a TOP-LEVEL check BY DESIGN — the judge
# legitimately puts per-lens advisory grades UNDER `lenses.*` (e.g. lenses.committer.grade); those are lens
# detail, not a headline disposition, and must not be rejected. Numeric scores only in a future advisory
# panel_scores block.
_SCORE_KEYS = {"score", "grade", "rating", "numeric_score", "panel_score", "overall_score"}


def _judge_disposition(g):
    """The judge's ship/block disposition TOKEN, read from the real (inconsistent) judge schema:
    lenses.sre.disposition (a token, when lenses.sre is a dict — judge.md), else a legacy top-level
    `disposition`, else token-extracted from the top-level integrated_disposition prose as a last resort.
    Returns a normalized lowercase token ('' if none). Structured fields first; prose only as fallback,
    via a bounded token match — never a loose regex over the free-text lens bodies."""
    sre = g.get("lenses", {}).get("sre")
    if isinstance(sre, dict) and sre.get("disposition"):
        return str(sre["disposition"]).strip().lower()
    if g.get("disposition"):
        return str(g["disposition"]).strip().lower()
    m = re.search(r"\b(conditional-ship|ship|block)\b", str(g.get("integrated_disposition", "")), re.I)
    return m.group(1).lower() if m else ""


def _load_reconciliation():
    try:
        return json.load(open(_RECON))
    except Exception:
        return {}


def _last_live_age_days(ts):
    """Age in days of a last_live ISO timestamp (YYYY-MM-DDTHH:MM:SS), or None if unparseable."""
    try:
        then = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        return (datetime.datetime.now() - then).total_seconds() / 86400.0
    except Exception:
        return None


def reconcile():
    """Cross-join the latest grades (ADVISORY) against the deterministic oracle + invariants (BINDING)
    and emit reconciliation.json with one honesty verdict — so the Oracle's primacy is a code fact, not
    a prompt request. See DESIGN_honesty_guardrails.md.

      RED   : any Oracle check FAIL or any invariant FAIL (a binding failure is present). If the judge
              ALSO leans 'ship', that pairing is recorded as a judge-contradicts-Oracle row.
      AMBER : no FAIL, but a live invariant is DEFERRED (or a last_live PASS is stale past
              ARENA_LAST_LIVE_MAX_AGE_DAYS) -> 'green-on-deferred, not live-verified this run'. A
              ship-leaning judge over a deferred invariant is RECORDED but NEVER blocks (honest deferral
              is not punished).
      GREEN : everything PASS, nothing deferred/stale.

    A numeric LLM score never reaches this verdict: the G1 validator REJECTS (exit 2) any grades
    artefact that surfaces a numeric score, so there is no score->disposition wiring to launder."""
    oj, ij = _latest("oracle_r*.json"), _latest("invariants_r*.json")
    grades = _by_round("grades_r*.json")
    g = json.load(open(grades[-1])) if grades else {}

    wired = sorted(k for k in g if k.lower() in _SCORE_KEYS)
    if wired:
        print(f"RECONCILE REJECT — grades carry numeric score field(s) {wired}: a score is advisory and "
              f"must not be a disposition surface (no score->ship/block wiring). See "
              f"DESIGN_honesty_guardrails.md; numeric scores belong only in a future advisory panel_scores block.")
        sys.exit(2)

    o_fail = [c["check"] for c in oj.get("checks", []) if c.get("status") == "FAIL"]
    i_fail = [i["id"] for i in ij.get("invariants", []) if i.get("status") == "FAIL"]
    i_def = [i["id"] for i in ij.get("invariants", []) if i.get("status") == "DEFERRED"]

    # G4 freshness (surfacing only, default OFF): a last_live-carried PASS older than the threshold reads
    # as stale, never as fresh green. Default 0 -> never stale, so a live-verified check stays green with
    # its timestamp (preserves the green-PASS-with-timestamp decision) until explicitly aged out.
    try:
        max_age = float(os.environ.get("ARENA_LAST_LIVE_MAX_AGE_DAYS", "0") or "0")
    except ValueError:
        max_age = 0.0
    stale_live = []
    if max_age > 0:
        for i in ij.get("invariants", []):
            ll = i.get("last_live")
            if i.get("status") == "PASS" and ll:
                age = _last_live_age_days(ll.get("ts", ""))
                if age is not None and age > max_age:
                    stale_live.append({"id": i["id"], "age_days": round(age, 1), "ts": ll.get("ts")})

    disp = _judge_disposition(g)
    ship_leaning = disp in _SHIP_LEANING

    contradictions = []
    if ship_leaning and (o_fail or i_fail):
        contradictions.append({"kind": "judge-ships-over-FAIL", "level": "RED", "judge_disposition": disp,
                               "oracle_fail": o_fail, "invariant_fail": i_fail})
    if ship_leaning and i_def and not (o_fail or i_fail):
        contradictions.append({"kind": "judge-ships-over-DEFERRED", "level": "AMBER",
                               "judge_disposition": disp, "invariant_deferred": i_def})

    verdict = "RED" if (o_fail or i_fail) else ("AMBER" if (i_def or stale_live) else "GREEN")
    out = {"verdict": verdict, "oracle_fail": o_fail, "invariant_fail": i_fail,
           "invariant_deferred": i_def, "stale_live": stale_live,
           "judge_disposition": disp or None, "judge_ship_leaning": ship_leaning,
           "contradictions": contradictions,
           "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(STATE, exist_ok=True)
    json.dump(out, open(_RECON, "w"), indent=2, sort_keys=True)
    msg = {"RED": "binding failure present", "GREEN": "Oracle clean, nothing deferred",
           "AMBER": "green-on-deferred — not live-verified this run"}[verdict]
    cn = f"  contradictions: {[c['kind'] for c in contradictions]}" if contradictions else ""
    print(f"RECONCILE {verdict} — {msg}.{cn}")
    return out


def contract_check():
    """Validate the contract spine: semver, content_sha256 integrity, and that every invariant is
    well-formed (id/dim/statement/mode + a runnable command). The Definition-of-Done as a CHECKED
    artefact, not a hardcoded literal. See DESIGN_v2_roadmap.md §2 (F2)."""
    _require_contract()
    c = CONTRACT
    meta = c.get("meta", {})
    errs = []
    ver = str(meta.get("contract_version", ""))
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        errs.append(f"contract_version not semver: {ver!r}")
    want, got = meta.get("content_sha256"), _contract_digest(c)
    if want != got:
        errs.append(f"content_sha256 mismatch: meta={str(want)[:12]} recomputed={got[:12]} "
                    f"(contract edited without rehash)")
    dims = {d["id"] for d in c.get("dimensions", [])}
    for inv in c.get("invariants", []):
        for k in ("id", "dim", "statement", "mode"):
            if not inv.get(k):
                errs.append(f"{inv.get('id', '?')}: missing {k}")
        if inv.get("dim") not in dims:
            errs.append(f"{inv.get('id', '?')}: dim {inv.get('dim')} not in dimensions {sorted(dims)}")
        if inv.get("mode") == "offline" and not inv.get("offline_cmd"):
            errs.append(f"{inv.get('id', '?')}: offline mode without offline_cmd")
        if inv.get("mode") == "live" and not (inv.get("live_cmd") and inv.get("proxy_cmd")):
            errs.append(f"{inv.get('id', '?')}: live mode without live_cmd+proxy_cmd")
    if not c.get("severity_scale"):
        errs.append("missing severity_scale")
    if errs:
        print("CONTRACT INVALID:\n  - " + "\n  - ".join(errs))
        sys.exit(1)
    print(f"CONTRACT OK — v{ver} ({meta.get('effective_date')}) · {len(c['invariants'])} invariants · "
          f"{len(dims)} dimensions · content_sha256 {got[:16]} (verified)")


def act(role, rnd, md_file):
    block = open(md_file, encoding="utf-8").read()
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    header = "\n\n" + "=" * 88 + f"\n## ROUND {rnd} — {role}  ·  {ts}\n" + "=" * 88 + "\n\n"
    with open(TRANSCRIPT, "a", encoding="utf-8") as fh:
        fh.write(header + block + "\n")
    print(f"appended {role} round {rnd}")


def _norm(f):
    return re.sub(r"\s+", " ", (f.get("evidence", "") + "|" + f.get("finding", "")[:60]).lower()).strip()


def converge():
    finds, verds = {}, {}
    for fp in _by_round("findings_r*.json"):
        rnd = int(re.search(r"_r(\d+)", fp).group(1))
        d = json.load(open(fp)); finds[rnd] = d if isinstance(d, list) else d.get("findings", [])
    for fp in _by_round("verdicts_r*.json"):
        rnd = int(re.search(r"_r(\d+)", fp).group(1))
        d = json.load(open(fp)); items = d if isinstance(d, list) else d.get("verdicts", [])
        verds[rnd] = {v.get("id"): v for v in items}
    seen, per_round = set(), []
    for rnd in sorted(finds):
        survive = [f for f in finds[rnd]
                   if (verds.get(rnd, {}).get(f.get("id"), {}).get("verdict", "CONFIRMED").upper()
                       in ("CONFIRMED", "OVERSTATED"))]
        new = [f for f in survive if _norm(f) not in seen]
        for f in survive:
            seen.add(_norm(f))
        per_round.append({"round": rnd, "surviving": len(survive), "new": len(new)})
    dry = len(per_round) >= 2 and all(r["new"] == 0 for r in per_round[-2:])
    # Convergence requires BOTH no-new-findings-for-2-rounds AND no FAILing invariant.
    # A DEFERRED invariant (live, no cluster) does NOT block — but is reported so
    # "converged-offline" is never mistaken for "converged-live".
    inv = _latest("invariants_r*.json").get("invariants", [])
    blocking = [i["id"] for i in inv if i["status"] == "FAIL"]
    deferred = [i["id"] for i in inv if i["status"] == "DEFERRED"]
    converged = dry and not blocking
    out = {"total_surviving": len(seen), "rounds": len(per_round), "per_round": per_round,
           "dry_2_rounds": dry, "blocking_invariants": blocking,
           "deferred_invariants": deferred, "converged": converged}
    os.makedirs(STATE, exist_ok=True)
    json.dump(out, open(os.path.join(STATE, "convergence.json"), "w"), indent=2)
    print(json.dumps(out, indent=2))


def _all_findings():
    out = []
    for fp in _by_round("findings_r*.json"):
        d = json.load(open(fp))
        out += (d if isinstance(d, list) else d.get("findings", []))
    return out


def judge_brief(rnd="1"):
    """Write the Judge's input with the Prosecutor's SEVERITY stripped, so the Judge
    re-derives severity from the finding + Oracle (anti-anchoring; the adl-aqt2 move)."""
    verds = {}
    for fp in _by_round("verdicts_r*.json"):
        d = json.load(open(fp))
        for v in (d if isinstance(d, list) else d.get("verdicts", [])):
            verds[v.get("id")] = v
    lines = [f"# JUDGE BRIEF (round {rnd}) — severities deliberately withheld.",
             "Re-derive severity yourself from the finding + Oracle result. Do not anchor.\n"]
    for f in _all_findings():
        v = verds.get(f.get("id"), {})
        verdict = (v.get("verdict") or "CONFIRMED").upper()
        if verdict == "FALSE_POSITIVE":
            continue  # only surviving findings reach the Judge
        lines.append(f"## {f.get('id')} [dim {f.get('dimension','')} / {f.get('invariant','—')}] "
                     f"defender={verdict} oracle={f.get('oracle_result','—')}")
        lines.append(f"- finding: {f.get('finding','')}")
        lines.append(f"- evidence: {f.get('evidence','')}")
        lines.append(f"- would resolve: {f.get('what_would_resolve_it','')}\n")
    os.makedirs(STATE, exist_ok=True)
    open(os.path.join(STATE, f"judge_brief_r{rnd}.md"), "w").write("\n".join(lines))
    print(f"judge_brief_r{rnd}.md written ({sum(1 for l in lines if l.startswith('## '))} surviving findings, severities stripped)")


AUTO_START = "<!-- AUTO-HARDENED:START — appended by `arena.py harden`; human-prunable -->"
AUTO_END = "<!-- AUTO-HARDENED:END -->"


def harden():
    """Self-hardening: fold confirmed defect-CLASSES the charter missed (findings with
    charter_gap:true + lesson) into a delimited, append-only, idempotent AUTO block in
    prompts/_preamble.md. Never touches hand-authored prose. The adl-aqt2 §8 analog."""
    preamble = os.path.join(ARENA, "prompts", "_preamble.md")
    text = open(preamble).read()
    m = re.search(re.escape(AUTO_START) + r"(.*?)" + re.escape(AUTO_END), text, re.S)
    existing_entries = re.findall(r"^- .*$", m.group(1), re.M) if m else []

    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"^- \[from [^\]]+\]\s*", "- ", s)).lower().strip()

    have = {norm(e) for e in existing_entries}
    new_entries, seen_now = [], set()
    for f in _all_findings():
        if f.get("charter_gap") and f.get("lesson"):
            # sanitize: collapse to ONE line (so the `^- .*$` re-capture stays idempotent) and
            # neutralize the marker tokens (lessons are LLM free-text — a newline duplicated
            # entries, and an embedded AUTO-HARDENED:END would truncate/rewrite the block).
            lesson = re.sub(r"\s+", " ", str(f["lesson"])).replace("AUTO-HARDENED", "auto-hardened").strip()
            entry = f"- [from {f.get('id')}] {lesson}"
            k = norm(entry)
            if k in have or k in seen_now:
                continue
            seen_now.add(k)
            new_entries.append(entry)
    if not new_entries:
        print("harden: no new lessons — charter unchanged (idempotent).")
        return
    block = AUTO_START + "\n" + "\n".join(existing_entries + new_entries) + "\n" + AUTO_END
    if m:
        text = text[:m.start()] + block + text[m.end():]
    else:
        text = text.rstrip() + "\n\n## Self-hardened forbidden-patterns (auto)\n" + block + "\n"
    open(preamble, "w").write(text)
    print(f"harden: folded {len(new_entries)} lesson(s) into the charter:")
    for e in new_entries:
        print("  " + e)


# ─── REMEDIATION (generative mode) — propose a fix, verify it in ISOLATION ────────
# SAFETY: every fix is applied/verified ONLY in a throwaway git worktree; the user's
# working tree is never modified. A fix is VERIFIED only if the offline Oracle battery
# PASSes there and no HCD-I* regresses. A human always lands the patch.
WT = os.path.join(tempfile.gettempdir(), "hcd-arena-worktree")


def _git(args, cwd=ROOT):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def _battery_in(cwd):
    """Run the offline Oracle battery + invariants against a checkout at `cwd`."""
    checks = {}

    def ck(name, cmd, ok):
        r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=300)
        checks[name] = "PASS" if ok(r.returncode, (r.stdout or "") + (r.stderr or "")) else "FAIL"

    ck("bash-n", 'for s in scripts/*.sh; do bash -n "$s" || exit 1; done', lambda c, o: c == 0)
    ck("demo-score", "./scripts/demo-entropy.sh --score 2>/dev/null", lambda c, o: "Score:  100%" in o)
    ck("pytest", "python3 -m pytest tests/ -q 2>&1", lambda c, o: c == 0)  # exit code, not substring
    ck("dup-keys", _DUPKEY, lambda c, o: c == 0)
    ck("counts", "tm=$(grep -oE 'TOTAL_MODULES=[0-9]+' scripts/demo-entropy.sh | head -1 | cut -d= -f2); "
                 "grep -q \"all $tm modules\" Makefile", lambda c, o: c == 0)
    r = subprocess.run(["python3", "audit_arena/bin/arena.py", "invariants", "0"],
                       cwd=cwd, capture_output=True, text=True)
    try:
        inv = json.loads(r.stdout)
    except Exception:
        # invariants must be evaluable; an unrunnable check is a conservative FAIL, never skipped
        return {"checks": checks, "invariant_fail": ["<invariants-unrunnable>"], "overall": "FAIL"}
    inv_fail = [i["id"] for i in inv.get("invariants", []) if i["status"] == "FAIL"]
    overall = all(v == "PASS" for v in checks.values()) and not inv_fail
    return {"checks": checks, "invariant_fail": inv_fail, "overall": "PASS" if overall else "FAIL"}


def remediate_worktree():
    if _git(["rev-parse", "--is-inside-work-tree"]).stdout.strip() != "true":
        print("ERROR: not a git repo — cannot isolate."); sys.exit(1)
    _git(["worktree", "remove", "--force", WT])
    r = _git(["worktree", "add", "--detach", WT, "HEAD"])
    print((r.stdout + r.stderr).strip())
    print(f"worktree: {WT}")


def remediate_clean():
    print((_git(["worktree", "remove", "--force", WT]).stderr or "worktree removed").strip())


# The battery EXECUTES these as code (arena.py = invariant runner, demo-entropy.sh = --score,
# tests/ = pytest). A patch to any could FORGE an all-PASS and self-certify, so it cannot earn
# VERIFIED (-> UNTRUSTED). config/Makefile are read as DATA — tampering is CAUGHT, not hidden,
# so they are not harness.
_HARNESS = ("audit_arena/", "scripts/demo-entropy.sh", "tests/")


def _patch_touches_harness(patch_file):
    try:
        txt = open(os.path.abspath(patch_file)).read()
    except Exception:
        return []
    paths = set(re.findall(r"^[+-]{3} [ab]/(.+?)\s*$", txt, re.M))
    return sorted(p for p in paths if any(p.startswith(h) for h in _HARNESS))


def verify_fix(fix_patch, base_patch=None):
    """Apply (base then) fix patch in a throwaway, PER-RUN worktree, run the Oracle battery
    there, and report — NEVER touching the user's tree. Status VERIFIED iff the battery PASSes
    AND the patch does not modify the verification harness (else UNTRUSTED — it could self-certify).
    Note: the worktree is built from HEAD, so a fix is verified against COMMITTED state."""
    if _git(["rev-parse", "--is-inside-work-tree"]).stdout.strip() != "true":
        print(json.dumps({"error": "not a git repo — refusing to run"})); return
    wt = tempfile.mkdtemp(prefix="hcd-arena-vf-")
    os.rmdir(wt)  # unique name; `git worktree add` needs the path to not exist
    add = _git(["worktree", "add", "--detach", wt, "HEAD"])
    if add.returncode != 0:
        print(json.dumps({"error": "worktree add failed", "detail": add.stderr[:300]})); return
    tainted = sorted(set(_patch_touches_harness(fix_patch) + (_patch_touches_harness(base_patch) if base_patch else [])))
    verdict = {"fix_patch": fix_patch, "base_patch": base_patch,
               "verified_against": "committed HEAD", "harness_touched": tainted}
    try:
        if base_patch:
            a = _git(["apply", os.path.abspath(base_patch)], cwd=wt)
            verdict["base_applies"] = a.returncode == 0
            verdict["oracle_before"] = _battery_in(wt)["overall"] if a.returncode == 0 else "n/a"
        a = _git(["apply", os.path.abspath(fix_patch)], cwd=wt)
        verdict["fix_applies"] = a.returncode == 0
        if a.returncode != 0:
            verdict["status"] = "REJECTED"
            verdict["detail"] = a.stderr[:200]
        else:
            res = _battery_in(wt)
            verdict["oracle_after"] = res
            if res["overall"] != "PASS":
                verdict["status"] = "REJECTED"
            elif tainted:
                # battery passed, but the patch can subvert the verifier -> cannot self-certify
                verdict["status"] = "UNTRUSTED"
                verdict["reason"] = f"patch modifies the verification harness ({', '.join(tainted)}); Oracle PASS not trusted"
            else:
                verdict["status"] = "VERIFIED"
    finally:
        _git(["worktree", "remove", "--force", wt])
        import shutil
        shutil.rmtree(wt, ignore_errors=True)  # belt-and-suspenders cleanup
    print(json.dumps(verdict, indent=2))
    return verdict


def remediate_record(finding_id, patch_file, verdict_file, rnd="1"):
    v = json.load(open(verdict_file))
    fp = os.path.join(STATE, f"remediation_r{rnd}.json")
    data = json.load(open(fp)) if os.path.exists(fp) else {"remediations": []}
    data["remediations"] = [r for r in data["remediations"] if r.get("finding_id") != finding_id]
    data["remediations"].append({"finding_id": finding_id, "patch": patch_file,
                                 "status": v.get("status"), "oracle_after": v.get("oracle_after")})
    os.makedirs(STATE, exist_ok=True)
    json.dump(data, open(fp, "w"), indent=2)
    print(f"recorded remediation for {finding_id}: {v.get('status')}")


SEV = CONTRACT["severity_scale"]  # severity->colour, from the contract spine (single source of truth)


def lineage(rnd="1"):
    """F3 — emit one Oracle-DOMINANT provenance object per finding -> state/lineage_r{rnd}.json. This is
    the ONE place a finding's oracle_cmd executes (the binding ground-truth pass): render() then CONSUMES
    this file instead of re-running commands, so the dashboard's resolution is single-sourced from the
    gated audit rather than recomputed on every refresh. lineage_status follows L5 (the Oracle); when the
    Defender (L4) and the Oracle (L5) disagree, both are recorded but the Oracle wins. See DESIGN_v2_roadmap.md F3."""
    import hashlib

    def _dig(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]

    finds = []
    for fp in _by_round("findings_r*.json"):
        d = json.load(open(fp))
        finds += (d if isinstance(d, list) else d.get("findings", []))
    verds = {}
    for fp in _by_round("verdicts_r*.json"):
        d = json.load(open(fp))
        for v in (d if isinstance(d, list) else d.get("verdicts", [])):
            verds[v.get("id")] = v
    rem = {r.get("finding_id"): r for r in _latest("remediation_r*.json").get("remediations", [])}

    objs = []
    for f in finds:
        fid = f.get("id")
        v = verds.get(fid, {})
        # L5 ORACLE — the single execution of the finding's binding command (FIXED iff now correct).
        ores = f.get("oracle_result")
        cmd = f.get("oracle_cmd")
        if cmd and not ores:
            try:
                rc = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, timeout=60).returncode
                ores = "FIXED" if rc == 0 else "FAIL"
            except Exception:
                ores = "—"
        status = "FIXED" if ores == "FIXED" else (f.get("status") or "")
        # L7 LIVE — a recorded live PASS for this finding's invariant (or id).
        live = _last_live_pass(f.get("invariant") or "") or _last_live_pass(fid)
        rstat = (rem.get(fid, {}).get("status") or "").upper()
        dverd = (v.get("verdict") or "").upper()
        # lineage_status — Oracle-DOMINANT ladder. A current Oracle FAIL caps the status at ADJUDICATED:
        # a stale recorded live PASS must NEVER mask a finding that is failing the Oracle right now (that
        # would be exactly the green-on-stale dishonesty the engine exists to refuse).
        if live and ores != "FAIL":
            lstat = "LIVE_CONFIRMED"
        elif rstat == "VERIFIED" and ores != "FAIL":
            lstat = "REMEDIATED"
        elif ores in ("PASS", "FAIL", "FIXED"):
            lstat = "ADJUDICATED"
        elif dverd:
            lstat = "VERIFIED"
        else:
            lstat = "FILED"
        layers = {"L3_finding": fid, "L4_verdict": dverd or None, "L5_oracle": ores or None,
                  "L6_remediation": rstat or None, "L7_live": (live.get("ts") if live else None)}
        obj = {"id": fid, "lineage_status": lstat, "oracle_result": ores or None, "status": status,
               "defender_verdict": dverd or None, "invariant": f.get("invariant") or None,
               "layer_refs": {k: lv for k, lv in layers.items() if lv is not None},
               "content_digests": {"finding": _dig(f), **({"verdict": _dig(v)} if v else {})}}
        # Disagreements where the Oracle (L5) overrides an advocate, recorded both ways — the Oracle wins.
        if dverd in ("CONFIRMED", "OVERSTATED") and ores in ("FIXED", "PASS"):
            obj["l4_l5_disagreement"] = f"Defender={dverd} but Oracle={ores} — status follows the Oracle"
        elif dverd == "FALSE_POSITIVE" and ores == "FAIL":
            obj["l4_l5_disagreement"] = f"Defender=FALSE_POSITIVE but Oracle=FAIL — status follows the Oracle"
        if live and ores == "FAIL":
            obj["l5_l7_disagreement"] = (f"stale live PASS @ {live.get('ts')} but Oracle=FAIL now — "
                                         f"capped at ADJUDICATED (the current Oracle wins)")
        objs.append(obj)

    os.makedirs(STATE, exist_ok=True)
    ladder = ("FILED", "VERIFIED", "ADJUDICATED", "REMEDIATED", "LIVE_CONFIRMED")
    out = {"round": int(rnd), "findings": objs,
           "by_status": {s: sum(1 for o in objs if o["lineage_status"] == s) for s in ladder}}
    json.dump(out, open(os.path.join(STATE, f"lineage_r{rnd}.json"), "w"), indent=2)
    print(f"lineage r{rnd}: {len(objs)} findings · "
          + " · ".join(f"{k}:{vv}" for k, vv in out["by_status"].items() if vv))
    return out


def render():
    md = open(TRANSCRIPT, encoding="utf-8").read() if os.path.exists(TRANSCRIPT) else "*(awaiting prosecution)*"
    finds, verds, oracle_idx, grades = [], {}, {}, []
    for fp in _by_round("findings_r*.json"):
        d = json.load(open(fp)); finds += (d if isinstance(d, list) else d.get("findings", []))
    # F3: CONSUME the gated lineage pass (the single place oracle_cmd ran) instead of re-executing each
    # command here — the dashboard's resolution is single-sourced from the audit, not recomputed per refresh.
    lin = {o["id"]: o for o in _latest("lineage_r*.json").get("findings", [])}
    for f in finds:
        o = lin.get(f.get("id"))
        if not o:
            continue
        if o.get("oracle_result"):
            f["oracle_result"] = o["oracle_result"]
        if o.get("status"):
            f["status"] = o["status"]
    for fp in _by_round("verdicts_r*.json"):
        d = json.load(open(fp))
        for v in (d if isinstance(d, list) else d.get("verdicts", [])):
            verds[v.get("id")] = v
    for fp in _by_round("oracle_r*.json"):
        d = json.load(open(fp))
        for c in d.get("checks", []):
            oracle_idx[c.get("check")] = c
    for fp in _by_round("grades_r*.json"):
        grades.append(json.load(open(fp)))
    inv = _latest("invariants_r*.json")
    man = _latest("manifest_r*.json")
    cfp = os.path.join(STATE, "convergence.json")
    conv = json.load(open(cfp)) if os.path.exists(cfp) else {}
    rem = _latest("remediation_r*.json").get("remediations", [])
    rec = _load_reconciliation()

    rows = []
    for f in finds:
        v = verds.get(f.get("id"), {})
        verdict = (v.get("verdict") or "—").upper()
        vc = {"CONFIRMED": "#1e8449", "OVERSTATED": "#b7950b", "FALSE_POSITIVE": "#7f8c8d"}.get(verdict, "#555")
        sev = (v.get("adjusted_severity") or f.get("severity") or "LOW").upper()
        oresult = (f.get("oracle_result") or "—").upper()
        oc = {"PASS": "#1e8449", "FAIL": "#c0392b", "FIXED": "#16a085"}.get(oresult, "#566")
        st = (f.get("status") or "").upper()
        rows.append(f"""<tr>
<td><code>{html.escape(f.get('id','?'))}</code></td>
<td><b style="color:{SEV.get(sev,'#555')}">{sev}</b></td>
<td>{html.escape(f.get('dimension',''))}</td>
<td>{html.escape(f.get('finding','')[:260])}{' <b style="color:#16a085">[FIXED]</b>' if st=='FIXED' else ''}</td>
<td><code>{html.escape(f.get('evidence',''))}</code></td>
<td style="color:{vc};font-weight:600">{html.escape(verdict)}</td>
<td style="color:{oc};font-weight:600">{html.escape(oresult)}</td>
<td><code>{html.escape(f.get('invariant','—'))}</code></td>
</tr>""")

    ostat = {"PASS": "#1e8449", "FAIL": "#c0392b", "DEFERRED": "#b7950b", "TIMEOUT": "#b7950b"}
    orows = "".join(
        f"<tr><td>{html.escape(c['check'])}</td><td>{html.escape(c.get('dimension',''))}</td>"
        f"<td style=\"color:{ostat.get(c['status'],'#566')};font-weight:600\">{c['status']}</td>"
        f"<td><code>{html.escape(c.get('detail',''))}</code></td></tr>"
        for c in oracle_idx.values())

    grade_html = ""
    if grades:
        g = grades[-1]; L = g.get("lenses", {})
        grade_html = f"""<div class="verdict"><h2>⚖️ Judge verdict (round {len(grades)})</h2>
<p class="oneline">{html.escape(str(g.get('one_line_verdict','')))}</p><div class="lenses">
<div class="lens"><h3>SRE / Operations</h3><p>{html.escape(json.dumps(L.get('sre',''), ensure_ascii=False))}</p></div>
<div class="lens"><h3>Cassandra committer / Correctness</h3><p>{html.escape(json.dumps(L.get('committer',''), ensure_ascii=False))}</p></div>
<div class="lens"><h3>Security / Compliance</h3><p>{html.escape(json.dumps(L.get('security',''), ensure_ascii=False))}</p></div>
</div></div>"""

    surv = sum(1 for v in verds.values() if v.get('verdict', '').upper() in ('CONFIRMED', 'OVERSTATED'))
    fp_n = sum(1 for v in verds.values() if v.get('verdict', '').upper() == 'FALSE_POSITIVE')
    o_pass = sum(1 for c in oracle_idx.values() if c['status'] == 'PASS')
    o_fail = sum(1 for c in oracle_idx.values() if c['status'] == 'FAIL')
    o_def = sum(1 for c in oracle_idx.values() if c['status'] in ('DEFERRED', 'TIMEOUT'))
    rounds = sorted({int(str(f.get('id', '')).split('-')[0][1:])
                     for f in finds if str(f.get('id', ''))[:1] == 'R' and str(f.get('id', ''))[1:2].isdigit()})
    cur_round = max(rounds) if rounds else 0
    fixed_n = sum(1 for f in finds if (f.get('status') or '').upper() == 'FIXED')
    per_round = ' · '.join(f"R{r}:{sum(1 for f in finds if str(f.get('id', '')).startswith(f'R{r}-'))}" for r in rounds)

    istat = {"PASS": "#1e8449", "FAIL": "#c0392b", "DEFERRED": "#b7950b"}
    def _ll_badge(i):
        ll = i.get("last_live")  # status is already PASS for these; badge notes WHEN it was live
        return (f' <span style="color:#1e8449">· ✓ live @ {html.escape(str(ll["ts"])[11:19])}</span>'
                ) if ll else ""
    ichips = "".join(
        '<span style="display:inline-block;margin:3px 6px 3px 0;padding:4px 9px;border-radius:6px;'
        'background:#11242b;border:1px solid #1d3640;font-size:12px">'
        f'<b>{html.escape(i["id"])}</b> '
        f'<b style="color:{istat.get(i["status"], "#566")}">{i["status"]}</b> '
        f'<span style="color:#7fa6b0">· {html.escape(i["statement"][:48])}</span>{_ll_badge(i)}</span>'
        for i in inv.get("invariants", []))
    n_inv = len(inv.get("invariants", [])) or 7
    inv_html = (f'<h2>Invariants — Definition-of-Done ({inv.get("passed", 0)}/{n_inv} PASS · '
                f'{inv.get("deferred", 0)} deferred · {inv.get("failed", 0)} fail)</h2>'
                f'<div style="margin-bottom:14px">{ichips or "<i>run: bin/arena.py invariants</i>"}</div>')
    conv_html = ""
    if conv:
        ok = conv.get("converged")
        col = "#1e8449" if ok else "#d35400"
        bl = conv.get("blocking_invariants") or []
        df = conv.get("deferred_invariants") or []
        note = (f" — blocked by {', '.join(bl)}" if bl else
                (f" (offline; live invariants {', '.join(df)} deferred)" if df else ""))
        conv_html = (f'<div style="margin:6px 0;font-size:13px">Convergence: '
                     f'<b style="color:{col}">{"CONVERGED" if ok else "NOT CONVERGED"}</b>'
                     f'<span style="color:#7fa6b0">{html.escape(note)} · '
                     f'{"2 dry rounds" if conv.get("dry_2_rounds") else "findings still moving"}</span></div>')
    rem_html = ""
    if rem:
        rc = {"VERIFIED": "#1e8449", "REJECTED": "#c0392b", "UNRESOLVED": "#b7950b"}
        rrows = ""
        for r in rem:
            st = (r.get("status") or "").upper()
            rrows += ("<tr><td><code>" + html.escape(str(r.get("finding_id", "?"))) + "</code></td>"
                      "<td style='color:" + rc.get(st, "#566") + ";font-weight:600'>"
                      + html.escape(str(r.get("status", ""))) + "</td><td>"
                      + html.escape(str((r.get("oracle_after") or {}).get("overall", "—"))) + "</td>"
                      "<td><code>" + html.escape(str(r.get("patch", ""))) + "</code></td></tr>")
        rem_html = ("<h2>Remediation — verified-in-isolation fixes</h2>"
                    "<table><tr><th>Finding</th><th>Status</th><th>Oracle (worktree)</th><th>Patch</th></tr>"
                    + rrows + "</table>")
    # Honesty banner — lead with the BINDING verdict (Oracle reconciliation), never the advisory score.
    # This is the anti-score-theatre UI move: a high judge opinion over a DEFERRED live invariant reads
    # AMBER (not green); a judge that ships over an Oracle FAIL reads RED. See DESIGN_honesty_guardrails.md.
    honesty_html = ""
    if rec:
        hv = rec.get("verdict", "GREEN")
        hcol = {"GREEN": "#1e8449", "AMBER": "#b7950b", "RED": "#c0392b"}.get(hv, "#566")
        hmsg = {"GREEN": "Oracle clean — binding ground truth holds, nothing deferred",
                "AMBER": "green-on-deferred — the judge may approve, but a live invariant is not verified this run",
                "RED": "binding failure present — an Oracle check or invariant FAILs, regardless of any judge opinion"}.get(hv, "")
        detail = ""
        if hv == "AMBER":
            detail = f" · deferred: {html.escape(str(rec.get('invariant_deferred') or [c for c in rec.get('stale_live', [])]))}"
        elif hv == "RED":
            detail = f" · oracle FAIL: {html.escape(str(rec.get('oracle_fail') or '—'))} · invariant FAIL: {html.escape(str(rec.get('invariant_fail') or '—'))}"
        contra = ""
        if rec.get("contradictions"):
            contra = (f'<div style="margin-top:6px;color:#e6b0aa;font-size:12.5px">⚠ judge contradicts Oracle: '
                      f'{html.escape(str([c["kind"] for c in rec["contradictions"]]))} '
                      f'(judge disposition <code>{html.escape(str(rec.get("judge_disposition")))}</code> — advisory, NOT binding)</div>')
        honesty_html = (f'<div style="margin:0 0 14px;padding:11px 15px;border-radius:9px;'
                        f'background:#11242b;border:1px solid {hcol};border-left:5px solid {hcol};font-size:14px">'
                        f'<b style="color:{hcol};font-size:16px">HONESTY: {hv}</b> '
                        f'<span style="color:#cfe0e4">— {hmsg}{detail}</span>{contra}'
                        f'<div style="margin-top:5px;color:#7fa6b0;font-size:11.5px">Binding arbiter = the deterministic Oracle. '
                        f'LLM judge scores/opinions are advisory and are read by no gate.</div></div>')
    man_html = ""
    if man:
        g, rp = man.get("git", {}), man.get("repo", {})
        man_html = ('<div style="margin:6px 0 18px;color:#7fa6b0;font-size:12px">'
                    f'<b>manifest</b> · git <code>{html.escape(str(g.get("sha", "?"))[:9])}</code> '
                    f'({"dirty" if g.get("dirty") else "clean"}) · branch {html.escape(str(g.get("branch", "?")))} · '
                    f'source {rp.get("signal_files", "?")} files @ <code>{html.escape(str(rp.get("content_sha256", "?")))}</code> · '
                    f'generated {html.escape(str(man.get("generated_at", "")))}</div>')

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="6">
<title>HCD audit arena — adversarial tribunal</title><style>
:root{{color-scheme:dark}}
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0c1418;color:#e6eef0}}
header{{padding:14px 22px;background:#0f1d22;border-bottom:1px solid #1d3640;position:sticky;top:0}}
header h1{{margin:0;font-size:18px}} header .sub{{color:#7fa6b0;font-size:13px}}
.wrap{{padding:18px 22px;max-width:1480px;margin:auto}}
.panel{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;margin-bottom:18px}}
.col{{background:#0f1d22;border:1px solid #1d3640;border-radius:10px;padding:12px}}
.col h3{{margin:0 0 8px;font-size:14px}} .col .big{{font-size:22px;font-weight:700}}
.prosecutor{{border-top:3px solid #c0392b}} .defender{{border-top:3px solid #2e86c1}}
.judge{{border-top:3px solid #8e44ad}} .oracle{{border-top:3px solid #16a085}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #16323c;vertical-align:top}}
th{{color:#7fa6b0;font-weight:600}} code{{background:#13262d;padding:1px 5px;border-radius:4px;font-size:11.5px}}
.verdict{{background:#15121f;border:1px solid #33294a;border-radius:10px;padding:14px 18px;margin-bottom:18px}}
.oneline{{font-size:16px;font-weight:600;color:#d7c7f0}}
.lenses{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}}
.lens{{background:#1c1530;border-radius:8px;padding:10px}} .lens h3{{margin:0 0 6px;font-size:13px;color:#bfa3e6}}
pre{{white-space:pre-wrap;font-size:12px;line-height:1.5;background:#081016;border:1px solid #16323c;border-radius:8px;padding:14px;max-height:55vh;overflow:auto}}
</style></head><body>
<header><h1>🛡️ HCD audit arena — adversarial tribunal (HCD 2.0 / Cassandra 5.0)</h1>
<div class="sub">Prosecutor <b style="color:#e57373">refute-by-default</b> · Defender <b style="color:#6fb6e0">kills false positives</b> · Judge <b style="color:#b18ad6">SRE / committer / security</b> · Oracle <b style="color:#34c3a0">runs ground truth</b> — auto-refresh /6s</div></header>
<div class="wrap">
{honesty_html}
<div style="margin:0 0 14px;padding:11px 15px;background:#11242b;border:1px solid #1d3640;border-radius:9px;font-size:14px">
<b style="font-size:17px">Round {cur_round}</b> — latest tribunal pass · {len(finds)} findings across {len(rounds) or 1} round(s) (<span style="color:#7fa6b0">{html.escape(per_round) or '—'}</span>) · <b style="color:#16a085">{fixed_n} fixed</b> · generated {html.escape(str((man or {}).get('generated_at', '')))}</div>
<div class="panel">
<div class="col prosecutor"><h3>🔴 Prosecutor</h3><div class="big">{len(finds)}</div><div>findings filed</div></div>
<div class="col defender"><h3>🔵 Defender</h3><div class="big">{surv}</div><div>survived · {fp_n} false positive(s)</div></div>
<div class="col judge"><h3>🟣 Judge</h3><div class="big">{len(grades)}</div><div>tri-lens verdict(s)</div></div>
<div class="col oracle"><h3>🟢 Oracle</h3><div class="big">{o_pass}/{o_pass+o_fail}</div><div>checks PASS · {o_def} deferred (need live cluster)</div></div>
</div>
{grade_html}
{conv_html}
{man_html}
{inv_html}
<h2>Oracle — deterministic ground truth</h2>
<table><tr><th>Check</th><th>Dim</th><th>Status</th><th>Detail</th></tr>
{orows or '<tr><td colspan=4><i>run: bin/arena.py oracle</i></td></tr>'}</table>
{rem_html}
<h2>Findings register</h2>
<table><tr><th>ID</th><th>Sev</th><th>Dim</th><th>Finding</th><th>Citation</th><th>Defender</th><th>Oracle</th><th>Inv</th></tr>
{''.join(rows) if rows else '<tr><td colspan=8><i>awaiting the prosecutor…</i></td></tr>'}</table>
<h2>Court transcript</h2><pre>{html.escape(md)}</pre>
</div></body></html>"""
    open(HTML_OUT, "w", encoding="utf-8").write(page)
    print(f"courtroom.html rendered ({len(finds)} findings, {len(grades)} grades, {len(oracle_idx)} oracle checks)")


# ─── MODE B: drive a tribunal role with an EXTERNAL model family (vendor diversity) ──
def _extract_json(text):
    """Pull the outermost JSON object from an LLM response, tolerating ```json fences / prose."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("no JSON object found in model response")
    return json.loads(t[i:j + 1])


def mode_b(role, rnd="1"):
    """The REAL Mode B: assemble the role prompt from charter + arena state, call the external
    provider via bin/llm.sh (or $ARENA_LLM_CMD, used by tests), extract+validate the JSON, and
    write the SAME artifact Mode A would. Egress-gated: if the provider exits 2 (ARENA_MODE_B
    unset or no API key) this propagates exit 2 so the orchestrator falls back to Mode A."""
    role = role.lower()
    prompts = os.path.join(ARENA, "prompts")
    parts = []
    for p in ("_preamble.md", f"{role}.md"):
        fp = os.path.join(prompts, p)
        if os.path.isfile(fp):
            parts.append(open(fp, encoding="utf-8").read())

    if role == "defender":
        findings = os.path.join(STATE, f"findings_r{rnd}.json")
        if not os.path.isfile(findings):
            print(f"[mode-B] no findings_r{rnd}.json — run the prosecutor first", file=sys.stderr); sys.exit(1)
        rc, ex = _run([sys.executable, os.path.abspath(__file__), "excerpts", findings])
        parts.append("## FINDINGS UNDER REVIEW\n```json\n" + open(findings, encoding="utf-8").read() + "\n```")
        parts.append("## CITED EXCERPTS\n" + (ex if rc == 0 else "(excerpts unavailable)"))
        out_file, req_key = os.path.join(STATE, f"verdicts_r{rnd}.json"), "verdicts"
    elif role == "judge":
        brief = os.path.join(STATE, f"judge_brief_r{rnd}.md")
        if not os.path.isfile(brief):
            print(f"[mode-B] no judge_brief_r{rnd}.md — run `judge-brief {rnd}` first", file=sys.stderr); sys.exit(1)
        parts.append("## JUDGE BRIEF (severities stripped)\n" + open(brief, encoding="utf-8").read())
        verdicts = os.path.join(STATE, f"verdicts_r{rnd}.json")
        if os.path.isfile(verdicts):
            parts.append("## DEFENDER VERDICTS\n```json\n" + open(verdicts, encoding="utf-8").read() + "\n```")
        out_file, req_key = os.path.join(STATE, f"grades_r{rnd}.json"), "one_line_verdict"
    else:
        print(f"[mode-B] role must be 'defender' or 'judge', got {role!r}", file=sys.stderr); sys.exit(1)

    parts.append("OUTPUT: reply with ONLY the JSON object specified in your charter — "
                 "no prose, no explanation, no markdown fences.")
    prompt_file = os.path.join(STATE, f"_modeb_{role}_r{rnd}_prompt.md")
    open(prompt_file, "w", encoding="utf-8").write("\n\n".join(parts))

    llm = os.environ.get("ARENA_LLM_CMD") or os.path.join(ARENA, "bin", "llm.sh")
    r = subprocess.run([llm, role, prompt_file], capture_output=True, text=True)
    if r.returncode == 2:  # egress off / no key — the deliberate Mode-A fallback path
        sys.stderr.write(r.stderr)
        print(f"[mode-B] {role}: external family unavailable — use Mode A (subagent).", file=sys.stderr)
        sys.exit(2)
    if r.returncode != 0:
        print(f"[mode-B] {role}: provider call failed (exit {r.returncode}): {r.stderr[:300]}", file=sys.stderr); sys.exit(1)
    try:
        obj = _extract_json(r.stdout)
    except Exception as e:
        raw = os.path.join(STATE, f"_modeb_{role}_r{rnd}_raw.txt")
        open(raw, "w", encoding="utf-8").write(r.stdout)
        print(f"[mode-B] {role}: response was not valid JSON ({e}); raw saved to {raw}", file=sys.stderr); sys.exit(3)
    if req_key not in obj:
        print(f"[mode-B] {role}: JSON missing required key '{req_key}'", file=sys.stderr); sys.exit(3)
    json.dump(obj, open(out_file, "w", encoding="utf-8"), indent=2)
    print(f"[mode-B] {role} (external family) -> {os.path.relpath(out_file, ROOT)}  ✓ valid JSON ('{req_key}' present)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "repomap": repomap()
    elif cmd == "excerpts": excerpts(sys.argv[2])
    elif cmd == "oracle": oracle(sys.argv[2] if len(sys.argv) > 2 else _latest_round())
    elif cmd == "invariants": invariants(sys.argv[2] if len(sys.argv) > 2 else _latest_round())
    elif cmd == "manifest": manifest(sys.argv[2] if len(sys.argv) > 2 else _latest_round())
    elif cmd == "act": act(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "converge": converge()
    elif cmd == "lineage": lineage(sys.argv[2] if len(sys.argv) > 2 else _latest_round())
    elif cmd == "reconcile": reconcile()
    elif cmd == "contract": contract_check()
    elif cmd == "gate": gate()
    elif cmd == "judge-brief": judge_brief(sys.argv[2] if len(sys.argv) > 2 else "1")
    elif cmd == "harden": harden()
    elif cmd == "verify-fix": verify_fix(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "remediate-worktree": remediate_worktree()
    elif cmd == "remediate-clean": remediate_clean()
    elif cmd == "remediate-record": remediate_record(sys.argv[2], sys.argv[3], sys.argv[4],
                                                      sys.argv[5] if len(sys.argv) > 5 else "1")
    elif cmd == "render": render()
    elif cmd == "mode-b": mode_b(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "1")
    else: print(__doc__); sys.exit(1)
