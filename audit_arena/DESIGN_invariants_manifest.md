# Audit Arena v2 — Design: formal HCD invariants + reproducibility manifest

**Status:** Implemented (approved with OQ1 = advisory-first).

**Implementation deviation (honest):** §3.6 proposed the pre-push gate *print* an invariant
summary. Dropped — running `invariants` re-executes the scorecard (I6) the gate already runs,
so it would add ~15s to every push for redundant output. The gate stays lean and unchanged;
the invariant scorecard lives in `make audit` and `courtroom.html`. Everything else shipped as
designed. `git_dirty` uses plain `git status --porcelain` (the generated outputs are git-ignored,
so the pathspec exclusion from §3.3 proved unnecessary).

---

**Scope (b):** (1) formalize `HCD-I1..I7` invariants wired into the Oracle; (2) emit a reproducibility manifest. **Out of scope:** the self-hardening charter loop and convergence/blind-judge changes (a follow-up pass).
**Motivation:** the architectural comparison vs `bb-debunking-phase-1/adl-aqt2` — that system has a formal Definition-of-Done (I1–I7, PASS/FAIL-with-evidence) and a content-addressed manifest (L7); the arena has neither, and the manifest omission is inconsistent with the repo's own reproducibility discipline.

---

## 1. Design goals & non-goals

**Goals**
- G1. A **named, enumerable Definition-of-Done** for the HCD project — every Oracle check and every finding maps to one of `HCD-I1..I7`, each reported `PASS | FAIL | DEFERRED` **with evidence**.
- G2. A **reproducibility manifest** per audit run: what was audited (content-addressed), with what tooling, and the resulting invariant/oracle verdicts.
- G3. Both surfaced in `courtroom.html` and consumable as JSON.
- G4. Deterministic and offline-runnable (live-cluster invariants degrade to `DEFERRED`, never guessed).

**Non-goals (this pass)**
- No change to the LLM tribunal roles, the Mode-B adapter, or the pre-push gate's blocking set.
- No self-hardening of charters; no convergence/judge-blinding changes.

---

## 2. The seven invariants (the formal DoD)

| ID | Statement (holds ⇔ artefact correct) | Dim | Check kind | Evidence |
|----|--------------------------------------|-----|-----------|----------|
| **HCD-I1** | Every Part 11 (modules 85–93) CQL statement executes without error on Cassandra 5.0 | D1 | **live** (cqlsh battery); offline **proxy**: no known-invalid pattern present (`mask_outer(card`, `ON ALL TABLES IN KEYSPACE`, `mask_keyspace`/`mask_function` columns) | cqlsh exit 0 / grep-absent |
| **HCD-I2** | `make up-secure` forms a healthy 6-node / 2-DC cluster (6×UN) | D6 | **live** (`nodetool status`); offline **proxy**: cluster-formation wiring present (baked `cqlshrc` + entrypoint secure-gating) | UN count == 6 / grep-present |
| **HCD-I3** | The generated `cassandra.yaml` (template + secure fragment) has **zero duplicate top-level keys** | D2 | **offline** | yaml load + key-count == 1 each |
| **HCD-I4** | Every module-count string equals `TOTAL_MODULES` (single source of truth) | D5 | **offline** | grep all docs vs `TOTAL_MODULES` |
| **HCD-I5** | **No private key / cert material** is baked into the image or committed to git | D6 | **offline** | `git ls-files` ∌ `*.key/*.pem`; Dockerfile ∌ `COPY certs`; `.gitignore`/`.dockerignore` ∋ `certs/` |
| **HCD-I6** | The demo script is **dry-run / score safe** (bash-n + shellcheck clean, scorecard 100%, no real `docker`/`cqlsh` exec under `--dry-run`) | D3 | **offline** | bash -n + shellcheck + `Score: 100%` |
| **HCD-I7** | Every HCD-2.0 / C5.0 **version & CQL claim is source-verified** (release notes / apache-cassandra) | D1 | **offline proxy** (pinned version facts match a reference) + audit-discipline | version-fact grep vs `reference_facts.json` |

**Mapping to today's Oracle:** I3/I4/I6 already exist as checks; I5 is partly in the existing security audit; I1/I2 are the existing `DEFERRED` live checks; I7 is new (a pinned reference-facts comparison). So this is mostly **re-labelling existing checks under named invariants + 2 small additions (I5 grep, I7 reference-facts)**.

---

## 3. Detailed design

### 3.1 Invariant spec (declarative, in `bin/arena.py`)
A module-level list; the Oracle evaluates each and writes `state/invariants_r{N}.json`.

```python
INVARIANTS = [
  {"id": "HCD-I1", "dim": "D1", "statement": "...",
   "live_cmd": "<cqlsh battery>",                 # PASS iff exit 0 on a live cluster
   "proxy_cmd": "! grep -RqE 'mask_outer\\(card|ON ALL TABLES IN KEYSPACE|mask_keyspace' scripts config"},
  {"id": "HCD-I3", "dim": "D2", "statement": "...",
   "offline_cmd": "<dup-key check>"},             # PASS iff exit 0, offline
  ...
]
```
Evaluation rule per invariant:
- has `offline_cmd` → run it → `PASS|FAIL` (`via:"offline"`).
- has `live_cmd` → if cluster up, run → `PASS|FAIL` (`via:"live"`); else run `proxy_cmd` → `PASS|FAIL` but status capped at **`DEFERRED`** with `via:"proxy"` and the proxy verdict in `evidence` (proxy can *demote* to FAIL but cannot *confirm* PASS — burden-on-artefact).

`state/invariants_r{N}.json`:
```json
{"round":1,"invariants":[
  {"id":"HCD-I3","dim":"D2","status":"PASS","via":"offline","evidence":"no duplicate top-level keys"},
  {"id":"HCD-I1","dim":"D1","status":"DEFERRED","via":"proxy","evidence":"no known-invalid CQL patterns; live cqlsh deferred"}
], "passed":N,"failed":N,"deferred":N}
```

### 3.2 Finding ↔ invariant linkage
- Add an `"invariant": "HCD-I3"` field to the finding schema.
- `prompts/prosecutor.md`: require every finding to cite the invariant it violates (mirrors adl-aqt2's red-team `{… invariant: <I1..I7>}`).
- Seed `state/findings_r1.json`: backfill `invariant` on the 14 existing findings (R1-01→I1, R1-08→I2, R1-03→I1, R1-11→I4, …).
- `render`: add an **"Inv"** column to the findings table + an **invariant scorecard panel** (7 chips PASS/FAIL/DEFERRED).

### 3.3 Reproducibility manifest
New `manifest(round)` → `state/manifest_r{N}.json`. **Content hash is over the audited HCD source only** — `tracked_files()` already excludes `audit_arena/`, so the arena's own outputs never pollute the hash (and `git_dirty` is computed with a pathspec that excludes `audit_arena/state` + `courtroom.html`, so regenerating the dashboard never marks the source dirty).

```json
{
  "schema_version": 1,
  "generated_at": "<ISO8601>",
  "git": {"sha": "<HEAD>", "branch": "master", "dirty": false},
  "env": {"python":"3.11.15","pytest":"9.1.1","ruff":"0.15.20","shellcheck":"0.10.0","docker":"…|absent","conda_env":"hcd-at-its-core"},
  "repo": {"signal_files": 38, "content_sha256": "<hash of sorted path:filesha>"},
  "oracle": {"passed":7,"failed":0,"deferred":3,"results_sha256":"<hash of oracle_r{N}.json>"},
  "invariants": {"HCD-I1":"DEFERRED","HCD-I2":"DEFERRED","HCD-I3":"PASS","HCD-I4":"PASS","HCD-I5":"PASS","HCD-I6":"PASS","HCD-I7":"PASS"}
}
```
`render`: a **manifest strip** (git sha • dirty • content hash • invariants N/7 PASS).

### 3.4 Generated-vs-tracked separation (resolves churn + honest `git_dirty`)
Reclassify the arena's `state/`:
- **Tracked (the seed/example):** `findings_r1.json`, `verdicts_r1.json`, `grades_r1.json`, `REPO_MAP.md`.
- **Generated (gitignore):** `oracle_r*.json`, `invariants_r*.json`, `manifest_r*.json`, `courtroom.html`.
Add these globs to `.gitignore`. `make audit` regenerates them; they never dirty the tree.

### 3.5 `bin/arena.py` API additions
- `invariants [R]` → evaluate `INVARIANTS`, write `state/invariants_r{R}.json`.
- `manifest [R]` → write `state/manifest_r{R}.json`.
- `render` → also load latest invariants + manifest; new panels.
- `repomap/excerpts/oracle/converge` unchanged.

### 3.6 Make / docs
- `make audit` → `repomap → oracle → invariants → manifest → render`.
- README/arena-README: document the invariant DoD + manifest.
- Pre-push gate: **unchanged blocking set** (offline invariants are already covered by its checks); it additionally *prints* the invariant summary (advisory), not blocks on it — avoids double-gating.

---

## 4. Implementation plan (PR-sized, ordered)
1. **I-spec + evaluator** — add `INVARIANTS`, `invariants()` subcommand; write JSON. *(no behaviour change elsewhere)*
2. **Manifest** — `manifest()` subcommand; git/env/hash collection; pathspec-scoped `git_dirty`.
3. **Render** — invariant scorecard panel + manifest strip + "Inv" column.
4. **Linkage** — finding schema `+invariant`; backfill seed findings; update `prosecutor.md`.
5. **Wiring** — `make audit` chain; `.gitignore` generated outputs; gate prints invariant summary.
6. **Docs** — arena README + this doc's status → Implemented.

## 5. Validation plan (deterministic, offline)
- `arena.py invariants` → `invariants_r1.json` has exactly 7 ids; I3/I4/I5/I6 = PASS, I1/I2 = DEFERRED(proxy), I7 = PASS — asserted by a new `tests/test_arena.py` (subprocess the arena; pure-stdlib, no cluster).
- `arena.py manifest` → valid JSON with all required keys; `git.dirty == false` immediately after a clean commit; `repo.content_sha256` **stable across two runs** (proves arena outputs excluded); `repo.signal_files == tracked_files()` count.
- `arena.py render` → `courtroom.html` parses; contains the 7 invariant chips + manifest strip; existing 14 findings now show an Inv column.
- Idempotency: `make audit` run twice → identical `manifest.git.dirty`, identical `content_sha256`, no working-tree dirtying (generated files gitignored).
- Regression: full `pytest` still green (system + env); pre-push gate still 6/6.
- **Self-check (eat-own-dogfood):** the manifest's `invariants` block must agree with `invariants_r1.json`; a test asserts they match.

## 6. Risks / open questions
- **R1 — I7 automation is partial.** Version facts are grep-checkable against a pinned `reference_facts.json`; CQL-grammar correctness is not fully automatable offline (that's what live-I1 is for). I7 offline = "pinned facts match"; deeper grammar verification stays `DEFERRED`/live. *Accept; document the boundary.*
- **R2 — proxy can't confirm, only deny.** A live cluster is still required to turn I1/I2 from `DEFERRED` to `PASS`. The proxy only *fails fast* on obviously-broken wiring. *By design (burden-on-artefact).*
- **OQ1 — should any offline invariant FAIL *block* the pre-push gate?** Proposed: no new blocking this pass (offline invariants already overlap the gate's checks); revisit once invariants are proven stable.
- **OQ2 — manifest signing?** Out of scope; a `content_sha256` is enough for reproducibility now.
