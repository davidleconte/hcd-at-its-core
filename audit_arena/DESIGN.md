# audit_arena — Detailed Technical Design (retrospective)

_Status: as-built. Written 2026-06-28 after the engine was implemented, dogfooded across three
adversarial rounds, run cross-vendor once, and validated against a live HCD 2.0.6 cluster._
_Companion docs: [`README.md`](README.md) (usage), [`DESIGN_invariants_manifest.md`](DESIGN_invariants_manifest.md),
[`DESIGN_selfhardening_convergence.md`](DESIGN_selfhardening_convergence.md),
[`DESIGN_remediation_mode.md`](DESIGN_remediation_mode.md) (per-feature designs)._

This is a single, consolidated technical design for the whole engine — what it is, how it is built,
the decisions that shaped it, and what dogfooding + a live cluster taught us. It is **retrospective**:
every claim below describes code that exists and ran, and every "lesson" is a defect the engine
actually had and a fix that actually landed (with the commit, where it matters).

---

## 1. Purpose & origin

`audit_arena/` is a **self-contained adversarial audit engine** for the `hcd-at-its-core` repo — a
Dockerized IBM HCD 2.0.6 (Cassandra 5.0 / Java 17) demo. It exists to answer one question rigorously:
**"is a claim about this HCD demo actually true, or does it just look true?"**

It was adapted from a quant-debunking "courtroom" UI (`bb-debunking-phase-1/audit_arena/courtroom.html`)
and re-grounded for HCD/Cassandra. The decisive change from the original is the **Oracle**: in the
quant version the verdict was argued by LLMs; here, HCD claims are **executably adjudicated** —
`cqlsh`, `nodetool`, the demo scorecard, `shellcheck`, YAML dup-key checks, `git` — so the ground
truth is a process exit code, not a rhetorical win.

### Why it was worth building
The HCD demo is ~10k lines of shell + config + 94 didactic modules. Claims of correctness (CQL is
valid, the secure cluster forms, no secrets leak, module counts agree) are exactly the kind of thing
that passes review by inspection and fails in practice. The arena turns "trust me" into "run it."

---

## 2. Goals & non-goals

**Goals**
- **Deterministic adjudication.** Every finding that *can* be checked by running something, is.
- **Adversarial structure.** A prosecutor that refutes by default, a defender that kills false
  positives, a judge that decides — each ideally a *different* model, so no family grades its own work.
- **Honest deferral.** A check that needs a live cluster and has none is `DEFERRED` (amber), never
  silently passed and never a hard fail.
- **Reproducibility.** Every run emits a provenance manifest (git SHA, dirty flag, tool versions,
  content hash).
- **Enforceable.** The deterministic half is a git pre-push gate and a CI job — it blocks bad pushes.
- **Self-improving + self-auditing.** A charter that hardens from confirmed gaps; an engine willing
  to be turned on itself.

**Non-goals**
- Not a general-purpose linter or test runner (it *orchestrates* those as Oracle checks).
- Not a replacement for the test suite — it consumes `pytest` as one Oracle check.
- Not a live monitoring system — it is a point-in-time audit + a snapshot dashboard.
- The LLM roles are **not** the source of truth; the Oracle overrides them for anything it can run.

---

## 3. Architecture

```
                         ┌─────────────────────────────────────────────────────┐
                         │  bin/arena.py  — deterministic plumbing (≈1800 LOC)  │
                         │  stdlib only; runs on Python 3.11 (project) & 3.14   │
                         └─────────────────────────────────────────────────────┘
   LLM roles (judgement)                         │                 Deterministic core (ground truth)
   ───────────────────────                       │                 ──────────────────────────────────
   Prosecutor  refute-by-default  ─┐             │            ┌─►  Oracle      cqlsh/nodetool/score/shellcheck
   Defender    kill false-positive ├─ findings ──┤            ├─►  Invariants  HCD-I1..I7 (Definition-of-Done)
   Judge       SRE/committer/sec   ─┘  verdicts  │            ├─►  Manifest    git SHA + tool versions + hash
                                       grades     │            ├─►  Gate        blocks push on any FAIL
   Driver A: Claude subagents (this session)      │            └─►  Render      courtroom.html (live dashboard)
   Driver B: bin/llm.sh → glm/gemini/openai       │
                                                   ▼
                                   state/*.json  (per-round artefacts)  →  courtroom.html
```

**The determinism boundary is the whole point.** Left of it, models argue. Right of it, the Oracle
runs commands. A finding's *severity* and *survival* are argued; its *truth*, where executable, is
decided by an exit code. The Oracle's word beats both advocates.

### The four roles
| Role | Mandate | Driver | Output |
|---|---|---|---|
| **Prosecutor** | Refute by default; file only findings with a real `path:line` and a survived rebuttal | Claude subagent / Mode B | `findings_rN.json` + `acts/prosecutor_rN.md` |
| **Defender** | Kill false positives; cross-examine each finding (CONFIRMED / OVERSTATED / FALSE_POSITIVE) | *different* model | `verdicts_rN.json` |
| **Judge** | Decide via three lenses (SRE / committer / security); severity-stripped brief (blind judge) | *third* model | `grades_rN.json` |
| **Oracle** | Run the executable checks; **binding** where it can run | deterministic code | `oracle_rN.json` |

---

## 4. Component design

### 4.1 `bin/arena.py` — the deterministic plumbing
A single ~1800-line, **stdlib-only** Python file (no third-party imports → runs anywhere a Python
does). Subcommands:

| Command | Purpose |
|---|---|
| `repomap` | Inventory the signal files → `state/REPO_MAP.md` |
| `excerpts <findings>` | Pull verbatim cited `path:line` windows for the Defender |
| `oracle [round]` | Run the deterministic + live Oracle battery → `oracle_rN.json` |
| `invariants [round]` | Evaluate `HCD-I1..I7` → `invariants_rN.json` |
| `manifest [round]` | Provenance: git SHA/dirty/branch, tool versions, content hash → `manifest_rN.json` |
| `judge-brief <round>` | Severity-stripped findings for the blind judge → `judge_brief_rN.md` |
| `act <role> <round> <md>` | Append a role's plaidoirie to the court transcript |
| `converge` | Convergence verdict (2 dry rounds ∧ no blocking invariant) → `convergence.json` |
| `lineage` | Per-finding Oracle-dominant provenance → `lineage_rN.json` (runs each `oracle_cmd` **once**; `render` consumes it). Status ladder FILED→VERIFIED→ADJUDICATED→REMEDIATED→LIVE_CONFIRMED |
| `reconcile` | Honesty reconciler — cross-join advisory grades vs binding oracle+invariants → `reconciliation.json` (GREEN/AMBER/RED); REJECT (exit 2) any grades wiring a numeric score. See [DESIGN_honesty_guardrails.md](DESIGN_honesty_guardrails.md) |
| `panel-aggregate` | Advisory judge self-score with the **Oracle ceiling re-derived in code** (invariant FAIL → cap 5; Oracle FAIL → cap 7) → `panel_rN.json`; read by no gate (v2 Tier 1) |
| `vendor-panel <role> <round>` | Routine multi-vendor advisory panel — fans Mode B over N vendors (`ARENA_PANEL`), emits a deterministic variance artifact `vendor_panel_rN_<role>.json`; egress-gated, a bad/gated vendor *abstains* (never aborts). Advisory; the Oracle settles disagreements (v2 Tier 1) |
| `contract` | Validate the contract spine `contract/contract.v1.json` (semver + content_sha256 integrity + invariant well-formedness). The Definition-of-Done is loaded from it, not hardcoded |
| `gate` | Exit non-zero on any FAILing Oracle check / invariant (what makes the gate *gate*) |
| `harden` | Fold confirmed `charter_gap` lessons into the prosecutor charter (idempotent) |
| `verify-fix <fix.diff> [base.diff]` | Apply a patch in a throwaway worktree, run the battery, never touch the tree |
| `remediate-worktree` / `-clean` | Manual remediation-worktree plumbing (create / remove a throwaway worktree) |
| `remediate-record <id> <patch> <verdict> [round]` | Record a `verify-fix` verdict into `state/remediation_rN.json` |
| `forge-contract <id>` | Validate a forge contract (`forge/<id>.contract.json`) — non-degenerate, harness-free acceptance predicates — + report its human-freeze status (v2 Tier 2/G1) |
| `forge-sign <id>` | **Human-freeze**: a human vouches for the contract's acceptance predicates (pins a digest; only a human runs this) |
| `forge-verify <id> <cand.diff>` | Apply a candidate in a throwaway worktree, run the battery + the contract's acceptance predicates; ACCEPTED only on a **signed** contract, else PROVISIONAL/REJECTED/UNTRUSTED |
| `forge-record` / `forge-converge <id>` | Record a forge verdict / converge (2 ACCEPTED rounds, 0 open defects) |
| `mode-b <defender\|judge> <round>` | Drive a role with an external model family (egress-gated) |
| `render` | Build `courtroom.html` from all `state/` artefacts (incl. the interactive pupitre console) |
| `replay <id...>` | Re-run the **stored** `oracle_cmd` for the given finding ids (looked up server-side; never a passed command string) — the pupitre's safe execution path (v2 Tier 2/G2) |

`oracle`/`invariants`/`manifest` default to the **latest** tribunal round (§4.10 lesson).

### 4.2 The Oracle — deterministic ground truth
Two tiers, both in `oracle()`:

**Offline checks** (always runnable): `bash -n` on all scripts; `shellcheck -S error`;
`demo-entropy.sh --score` == 100%; full `pytest`; combined-`cassandra.yaml` no-duplicate-keys;
`docker compose config` secure-overlay merge; module-count-vs-docs consistency.

**Live checks** (need a cluster; `nodetool status` auto-detect): `D1 secure cluster forms (6×UN)`;
`D1 release == Cassandra 5.0 + Java 17` (`make verify-release`); `D1 Part 11 DDM CQL executes`
(the corrected `mask_inner` / `column_masks(function_keyspace,function_name)` battery via `cqlsh -e`).

Status model: **PASS** (green) · **FAIL** (red, blocks) · **DEFERRED** (amber, live check w/ no
cluster, never blocks) · **TIMEOUT** (amber, a check couldn't finish — see §4.9).

### 4.3 Invariants — the Definition-of-Done (`HCD-I1..I7`)
Formal, per-dimension invariants the demo must satisfy. Each has either an `offline_cmd`, or a
`live_cmd` + `proxy_cmd` pair (the proxy can *demote* to FAIL on broken wiring offline but can only
**confirm** PASS live — burden on the artefact). Since v2 (F2) these are **loaded from the contract
spine** `contract/contract.v1.json` — a versioned, content-hashed Definition-of-Done — rather than
hardcoded in `arena.py`; `arena.py contract` validates its integrity and `make audit` runs it first.

| Id | Dim | Statement | Mode |
|----|-----|-----------|------|
| **HCD-I1** | D1 | Every Part 11 CQL executes on Cassandra 5.0 | live (proxy: no forbidden CQL grammar) |
| **HCD-I2** | D6 | Secure cluster forms (6x UN) | live (proxy: cqlshrc + HCD_SECURITY_PROFILE wiring present) |
| **HCD-I3** | D2 | Generated `cassandra.yaml` has zero duplicate top-level keys | offline |
| **HCD-I4** | D5 | No module-COUNT claim disagrees with `TOTAL_MODULES` (all docs) | offline |
| **HCD-I5** | D6 | No key/cert material baked into the image or committed | offline |
| **HCD-I6** | D3 | Demo script is dry-run/score safe (syntax+lint+scorecard) | offline |
| **HCD-I7** | D1 | Pinned HCD-2.0/C5.0 version facts present in the docs (drift denylist) | offline |

Dimensions: D1 correctness/CQL · D2 config · D3 scripts · D5 docs/consistency · D6 security.
Detailed rationale in [`DESIGN_invariants_manifest.md`](DESIGN_invariants_manifest.md).

### 4.4 The manifest — reproducibility
`manifest_rN.json`: git SHA (full sha256, never truncated), `git_dirty` flag, branch, signal-file
count + content sha256 (generated artefacts excluded so the hash is stable), tool versions in an
`env` map (`python`, `pytest`, `ruff`, `shellcheck`, `docker`, `conda`), the Oracle summary
(+ `results_sha256`), and the seven invariant statuses. Cross-checked
against `invariants_rN.json` by a self-test (`test_manifest_matches_invariants_if_generated`).

### 4.5 Drivers — Mode A and Mode B
- **Mode A (default):** the LLM roles are Claude subagents dispatched in-session. The three rounds
  run this way used **opus / sonnet / fable** for Prosecutor / Defender / Judge → *model diversity*,
  the best anti-collusion available without external keys.
- **Mode B (opt-in):** `bin/llm.sh` routes a role to an **external** family (GLM / Gemini /
  OpenAI-compatible). `arena.py mode-b <role> <round>` assembles the prompt from the charter + that
  round's state, calls the provider, extracts + validates the JSON, writes the same artefact Mode A
  would. **Two safety gates:** an *egress opt-in* (`ARENA_MODE_B=1` per run) and *key-gating* (exits
  2 if no key) — either gate ⇒ fall back to Mode A. *Vendor diversity*, not just model diversity.

### 4.6 Self-hardening charter
`harden` folds each confirmed `charter_gap` lesson (a defect class not yet in the tier-1
forbidden-patterns list) into an `AUTO-HARDENED` block in `prompts/_preamble.md`, **idempotently** and
without touching hand-authored prose. The prosecutor reads the hardened charter next round, so the
engine learns from each round. Design: [`DESIGN_selfhardening_convergence.md`](DESIGN_selfhardening_convergence.md).

### 4.7 Generative remediation — `verify-fix`
Propose → red-team → **verify a patch in a throwaway `git worktree`**, run the Oracle battery there,
report `VERIFIED` / `REJECTED` / `UNTRUSTED` — *never* touching the user's working tree. Safety rails:
unique per-run worktree (concurrency-safe), verified against committed HEAD, and a patch that touches
the **verification harness itself** (`audit_arena/`, `demo-entropy.sh`, `tests/`) is `UNTRUSTED` even
on an Oracle PASS — you can't earn VERIFIED by patching the verifier. Design:
[`DESIGN_remediation_mode.md`](DESIGN_remediation_mode.md).

### 4.8 Convergence
`converge` declares the audit done iff **two consecutive dry rounds** (no new surviving findings) ∧
no FAILing `HCD-I*`. A `DEFERRED` live invariant does **not** block convergence (it is inconclusive,
not a failure). The judge also gives a *qualitative* convergence read (the 14→5→1 finding-count and
character collapse across rounds was the real signal).

### 4.9 The gate — enforceability
`gate` reads the latest oracle + invariants and `sys.exit(1)` on any `FAIL` (DEFERRED/TIMEOUT never
block). `gate` is run by `make audit` (and the CI `audit-arena` job, which runs `make audit`). The
push-blocking **pre-push hook** (`bin/pre-merge-hook.sh`, installable via `make audit-install-hook`)
does **not** call `gate` — it runs an *equivalent inline* docker-free battery (`bash -n`,
`shellcheck -S error`, demo-score, `pytest`, config dup-keys, module-count) and blocks the push on any
failure. The hook is read-only on *tracked* files but, on success, refreshes the courtroom snapshot
(§4.10).

### 4.10 The render — `courtroom.html` (live dashboard semantics)
`render` aggregates every `state/` artefact into a single auto-refreshing HTML dashboard: an
[honesty banner](DESIGN_honesty_guardrails.md) (the binding GREEN/AMBER/RED verdict, leading), the
four-role summary, the latest judge verdict (tri-lens), convergence, manifest provenance, the seven
invariants, the Oracle table, remediation, and the full findings register. Since v2 (F3) the per-finding
FIXED/FAIL resolution is **consumed from the gated `lineage_rN.json`** (single-sourced from the audit),
not re-executed at render time.

Since v2 (G2) it also embeds the **pupitre** — a 3-mode interactive teaching console (Comprendre /
Exécuter / Naviguer) over an embedded JSON blob, no framework or network. Two guards: a finding with no
`oracle_cmd` renders *"argued-only — no binding command"* (never a fake run); the only execution path is
`arena.py replay <ids>`, which passes **ids** (the trusted core looks up the stored command) — a browser
can never carry a command string into the deterministic core. Console state lives in `location.hash`, so
the 6s auto-refresh never wipes the user's exploration. Three dashboard rules earned the hard way:

- **Latest-round refresh.** `render`/`gate` read the *latest* round; `make audit` therefore defaults
  to the latest round so the dashboard's provenance can't silently lag once the tribunal advances.
- **Self-refreshing.** The pre-push hook re-renders to the *pushed* commit, so the git-provenance
  line never trails HEAD after a commit.
- **Live verdicts persist.** A live PASS is recorded to a tracked `state/last_live.json`; an offline
  render then shows a green **PASS · last LIVE: PASS @ \<ts\>** instead of discarding the proof. A
  check never run live stays `DEFERRED`; a live FAIL never promotes.

---

## 5. Data model (`state/`)

| Artefact | Tracked? | Written by | Notes |
|---|---|---|---|
| `findings_rN.json` | yes | Prosecutor | the round's filed findings (seed `r1` = manual MECE pass) |
| `verdicts_rN.json` | yes | Defender | per-finding CONFIRMED/OVERSTATED/FALSE_POSITIVE + missed strengths |
| `grades_rN.json` | yes | Judge | one-line verdict, surviving findings, tri-lens, convergence |
| `acts/*.md` | yes | roles | plaidoiries / cross-vendor record |
| `last_live.json` | yes | oracle/invariants (live) | durable live-verification record |
| `oracle_rN.json` · `invariants_rN.json` · `manifest_rN.json` | no (gitignored) | deterministic core | regenerated by `make audit` |
| `remediation_rN.json` | no (gitignored) | `verify-fix` / `remediate-record` | recorded remediation verdicts (patch + Oracle-after) |
| `reconciliation.json` | no (gitignored) | `reconcile` | honesty verdict (GREEN/AMBER/RED) + any judge-vs-Oracle contradictions |
| `panel_rN.json` | no (gitignored) | `panel-aggregate` | advisory judge score + the code-derived Oracle ceiling (`judge_claimed`/`ceiling`/`capped_to`/`ceiling_applied`) |
| `vendor_panel_rN_<role>.json` · `verdicts_rN__<vendor>.json` · `grades_rN__<vendor>.json` | no (gitignored) | `vendor-panel` | per-vendor outputs (the `__<vendor>` namespace, excluded from binding pipelines) + the inter-vendor variance/dissent artifact (advisory) |
| `lineage_rN.json` | no (gitignored) | `lineage` | one Oracle-dominant provenance object per finding (layer_refs L3–L7 + content digests + lineage_status) |
| `patches/*.diff` | no (gitignored) | `verify-fix` / red-team | candidate-fix + defect-injection diffs applied in the throwaway worktree |
| `REPO_MAP.md` · `convergence.json` · `judge_brief_rN.md` · `courtroom.html` | no | generated | local artefacts |
| `_modeb_*` | no | mode-b | transient prompt scratch |

Round numbering is parsed numerically (`_r10` sorts after `_r2`, a real bug that was fixed).

---

## 6. What actually ran (the retrospective evidence)

| Round | Driver | Findings | Outcome |
|---|---|---|---|
| **R1** | manual MECE seed (Claude) | 14 (**5 BLOCKER** incl. live-breaking CQL + secure-profile healthcheck/auth) | all FIXED |
| **R2** | opus → sonnet → fable | 5 (1 HIGH: dead Prometheus alerts; non-WORM compose) | all FIXED |
| **R3** | opus → sonnet → fable | 1 (LOW: decorative CI scorecard step) | FIXED; judge: *converged* |
| **R3 cross-vendor** | **GLM** (def) → **Gemini** (judge) | — | Mode B proven; exposed model-variance (see below) |

The **14 → 5 → 1** decline (and the *character* collapse — live-breaking CQL → observability → a
single backstopped CI-quality gap) is the convergence signal. The cross-vendor run is recorded in
[`acts/crossvendor_r3.md`](acts/crossvendor_r3.md).

**Live adjudication (2026-06-28).** Against a real 6-node secure HCD 2.0.6 cluster on colima, all
deferred topics executed and passed: `HCD-I1`/`I2` + the 3 D1 Oracle checks (cluster forms, release
5.0.7 + Java 17, Part-11 DDM CQL) → recorded in `last_live.json`. **7/7 invariants, 0 deferred, live.**

---

## 7. Key design decisions & rationale

1. **Deterministic Oracle as binding arbiter** — the single most important decision. When GLM and
   Gemini disagreed (cross-vendor R3), the Oracle / `gate PASS` settled it. Models advise; exit codes
   decide.
2. **DEFERRED, not pass-or-fail, for live checks** — honesty over a green checkmark. Inventing a PASS
   you can't run is the exact failure mode the arena exists to catch.
3. **Stdlib-only, single file** — `arena.py` runs on the project's Python 3.11 *and* the host's 3.14;
   no dependency to drift. (Cost: a dense terse style with E701/E702 lints, kept out of CI's lint
   scope deliberately.)
4. **Severity-stripped blind judge** — the judge re-derives severity from the finding + Oracle result
   so it doesn't anchor on the prosecutor/defender.
5. **Different model per role** — anti-collusion. Mode A gives model diversity; Mode B gives vendor
   diversity. Both are documented as *exactly* what they are, never overstated.
6. **Egress is a deliberate act** — Mode B never calls out without `ARENA_MODE_B=1`; an ambient key
   in the shell is not consent to ship repo excerpts to a third party.
7. **The verifier can't self-certify** — `verify-fix` marks any patch touching the harness `UNTRUSTED`.
8. **The gate is the contract** — without `gate`, `oracle`/`invariants` are reporters that exit 0 and
   the CI step is decorative. `gate` is what makes "audit" mean "block."

---

## 8. Retrospective: the engine's own defects (dogfooding)

The arena was built to find defects, so it was turned on itself. It had serious ones — and finding
them *is* the validation. Highlights, all fixed:

- **False VERIFIED / false gate-PASS.** The pytest checks grepped for `" failed"` and ignored the exit
  code — a collection error (exit 2) or zero-tests (5) reported PASS. Now gate on `c == 0`.
- **CI theatre.** `make audit` exited 0 even on FAIL; only the hook's checks gated. Added the `gate`
  subcommand → `make audit` actually blocks.
- **Self-certification hole.** `verify-fix` ran the harness *from the patched worktree* → a patch to
  the verifier could forge a PASS. Now `UNTRUSTED`.
- **Round-≥10 lexical sort, sha256 truncation, harden charter-injection, invariant false-PASS
  (I3/I5/I6), excerpts-on-empty-evidence crash** — all found by the self-audit, all fixed.
- **Stale-dashboard class** (three distinct causes): render read the latest round but `make audit`
  refreshed round 1 (provenance lag); a generated snapshot froze at the last `make audit` (offline
  pushes wiped the live PASS); a timed-out check read as a red FAIL. Fixes: latest-round default,
  pre-push auto-refresh, `TIMEOUT` status, and `last_live.json` persistence.

**Meta-lesson:** an audit tool that trusts its own green output is not auditing. Several of these
(false VERIFIED, CI theatre) were the very "passing-but-empty-check = false confidence" trap the
arena targets — caught only because the reviewers *ran the attacks* rather than trusting the code.

---

## 9. Honesty principles (anti-overstatement)

The arena is engineered to refuse to flatter itself, and the docs say exactly what is and isn't true:
- `FIXED` ≠ live-verified — it means the code fix landed and the *offline* Oracle passes; live status
  is tracked separately (`last_live.json`, the DEFERRED/PASS-last-LIVE distinction).
- The LLM tribunal HAS run (rounds 2–3, `acts/` populated) — but Mode A is *model* diversity, not the
  *vendor* diversity of Mode B; that distinction is stated everywhere it matters.
- `make audit` is the **offline** gate (a live cluster starves the CPU → `pytest` shows `TIMEOUT`,
  inconclusive); the live checks are confirmed separately.

---

## 10. Limitations & future work

- **`HCD-I1`/`I2` are live-or-nothing** — proven live once, persisted, but a code change that would
  break them live is only caught by a *live* re-run, not the offline gate (by design).
- **`last_live.json` can go stale** — it records the last live PASS with a timestamp; it does not
  re-verify. The timestamp is the honesty signal; a regression would show a green PASS with an old
  stamp until the next live run.
- **Mode B coverage** — wired + mock-tested + run once cross-vendor; not part of CI (egress + keys).
- **Invariant breadth** — I4/I7 are denylist/presence checks, not full grammatical proofs (a
  documented boundary, per `DESIGN_invariants_manifest.md`).
- **`make audit` under a live cluster** — the bundled `pytest` check is CPU-bound and not meant to run
  while 6 JVMs compete; the engine reports `TIMEOUT` rather than a false FAIL, but the right workflow
  is offline gate + separate live invariant run.
- **Future:** record live FAILs too (currently only PASS persists); a "last_live age" warning;
  optional Mode-B-in-CI behind a secret; widening I4/I7 toward grammatical checks.

---

## 11. File map

```
audit_arena/
├── bin/
│   ├── arena.py            # the deterministic plumbing (all subcommands)
│   ├── llm.sh              # Mode B provider adapter (glm/gemini/openai; egress+key gated)
│   └── pre-merge-hook.sh   # git pre-push gate + courtroom auto-refresh
├── prompts/                # role charters: _preamble, prosecutor, defender, judge, oracle, proposer,
│                           #   redteam_fix, forge_proposer, forge_redteam (hardened charter in _preamble.md)
├── contract/               # the Definition-of-Done as versioned data
│   └── contract.v1.json    #   dimensions + invariants (HCD-I1..I7) + severity scale, content-hashed
├── state/                  # per-round artefacts (see §5); courtroom.html renders from here
├── acts/                   # plaidoiries + crossvendor_r3.md
├── reference_facts.json    # pinned HCD-2.0/C5.0 version facts for HCD-I7
├── README.md               # usage + status legend
├── DESIGN.md               # ← this document
├── DESIGN_v2_roadmap.md    # v2 improvement roadmap (learnings from adl-aqt2/pupitre)
├── DESIGN_honesty_guardrails.md  # the binding honesty contract (G1-G4 + DO-NOT-ADOPT)
├── DESIGN_invariants_manifest.md
├── DESIGN_selfhardening_convergence.md
└── DESIGN_remediation_mode.md
```
