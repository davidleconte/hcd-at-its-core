# audit_arena v2 — improvement roadmap

**Status:** design of record (not yet built, except where noted). **Derived from:** a 14-agent design
panel (7 architects + 7 adversarial critics) that compared `audit_arena` against the `adl-aqt2` /
*pupitre* "battle of prompts" demo (demo.alphadebunker.cc) and stress-tested every proposal against the
engine's core ethos. See [DESIGN.md](DESIGN.md) for the as-built v1.

---

## 1. What `adl-aqt2` / pupitre taught us

`adl-aqt2` is the more-evolved sibling of the same lineage `audit_arena` descends from (the
bb-debunking courtroom). The comparison is **two-sided** — it shows us the next moves *and* the
anti-pattern to refuse.

| Capability | adl-aqt2 / pupitre | audit_arena v1 | Delta |
|---|---|---|---|
| **Two battles** | BATAILLE 1 *generates* an artefact (Proposer⇄Red-team→converge); BATAILLE 2 *validates* it | only the destructive audit loop + per-finding `verify-fix` (repair, not design) | we lack the generative battle |
| **Numeric multi-vendor judge panel** | N vendors *score* (10/10, 9.5/10), extract weaknesses, re-inject into §8 | single tri-lens judge + charter self-hardening | we lack scored panel + formal reinjection |
| **Governed contract / meta-prompt** | one versioned CONTRACT (registry·gates·L2) drives everything; the team is *generated* from it | invariants + forbidden-patterns + reference_facts hardcoded, scattered in `arena.py` | our contract is implicit |
| **Interactive Pupitre console** | 3 modes: guided / click-to-understand / execute-in-page | read-only auto-refresh dashboard | ours is static |
| **Multi-vendor as routine** | GLM/Gemini/Z.ai first-class | Mode B opt-in, run cross-vendor once | ours is a one-off |
| **Layered artefacts L1–L7 + lineage** | every conclusion traces to its layer | flat findings/verdicts/grades + per-round manifest | our lineage is loose |

### The load-bearing lesson — what NOT to adopt
adl-aqt2 makes a **numeric LLM score the headline result** ("9.5/10 → ship"). That is precisely the
*score-theatre* `audit_arena` exists to refuse. Our differentiator is the **deterministic Oracle
(executable exit codes), not an LLM's opinion** — proven live when GLM and Gemini disagreed cross-vendor
and the Oracle settled it. The whole panel converged on one rule:

> **Adopt adl-aqt2's structure (generative battle, scored panel, multi-vendor, interactivity) — but
> every anti-theatre control must be RE-DERIVED in deterministic code, never prose. The Oracle stays
> binding *by construction*.**

Every refinement below pushed an anti-theatre control from prose into code. That is the same
*verify, don't trust* discipline the engine applies to the codebase — now applied to its own evolution.

---

## 2. Prioritized roadmap

All 7 themes returned **REFINE** from the adversarial critics (valid core, scoped down) — none rejected,
none rubber-stamped. Sequenced by erosion-risk and dependency.

### Tier 0 — Foundation (P1, build first; makes the rest safe to add)

| # | Theme | Core delta | Effort |
|---|---|---|---|
| F1 | **Honesty reconciler / determinism-guard** | The Oracle's primacy as a *code invariant*, not a charter promise | M |
| F2 | **Contract spine** | The Definition-of-Done as versioned data; `arena.py` loads it | M |
| F3 | **Artefact lineage core** | One Oracle-dominant provenance object per finding; render consumes it | M |

**F1 — Honesty reconciler.** A thin pass on the *deterministic side* of the boundary so it cannot be
argued away by any model/vendor:
- **G2 reconciler / contradiction gate** — `reconcile` cross-joins grades vs oracle+invariants and emits
  `reconciliation.json`: a ship-leaning judge disposition co-existing with **any** Oracle/invariant FAIL
  ⇒ **RED** (gate exits non-zero); judge-green over a **DEFERRED** invariant ⇒ **AMBER**
  "green-on-deferred — not live-verified," never promoted to green.
- **G3 Oracle-primacy self-test** — an executable assertion that for every finding with an
  `oracle_result`, the rendered disposition equals the Oracle's (FIXED/PASS ⇒ non-blocking, FAIL ⇒
  blocking). "Oracle beats advocates" as a test, mirroring the dogfooding that caught the false-VERIFIED
  bug ([DESIGN.md §8](DESIGN.md)).
- **G4 last-live freshness** — `ARENA_LAST_LIVE_MAX_AGE_DAYS` (default generous): a `last_live` PASS older
  than the threshold renders `PASS (stale: live @ ts, N days old)` in amber. **Surfacing only** — a stale
  live PASS still does not hard-FAIL (that would punish honest deferral).
- **Render honesty banner** — the dashboard leads with the binding verdict (GREEN / AMBER
  green-on-deferred / RED judge-contradicts-Oracle), not the advisory score.
- **`DESIGN_honesty_guardrails.md`** — the binding rule as a documented contract.
- *Critic refinement:* G1 (structured-grades schema + reject any score→disposition wiring) is a hard
  prerequisite for G2; until it lands, G2's only RED is the unambiguous case (ship-leaning judge +
  any Oracle/invariant FAIL), AMBER for ship-leaning-over-DEFERRED. Do **not** add a numeric score
  surface yet — that arrives with the scored panel (T1).

**F2 — Contract spine.** `contract/contract.v1.json` = the Definition-of-Done as data: `meta`
(semver + `effective_date` + self `content_sha256`), `dimensions` (D1–D6), `invariants` (`HCD-I1..I7`
records: id/dim/statement/mode + offline_cmd | live_cmd+proxy_cmd), `severity_scale`, `reference_facts`.
`arena.py` **loads** it, replacing the `INVARIANTS` literal, the `SEV` map, and the inline
`reference_facts` read. *Critic refinement:* ship the **spine** (M); expose a Python-importable parsed
view (`arena.CONTRACT` / `arena.invariant_records()`) so existing tests bind to records, not the raw
JSON; do **not** add role-schemas-as-JSON-Schema yet; defer the generative meta-prompt tail.

**F3 — Artefact lineage core.** `arena.py lineage [round]` → `lineage_rN.json`: one **Oracle-dominant**
provenance object per finding `{id, layer_refs, content_digests, lineage_status}` with status derivation
`FILED→VERIFIED→ADJUDICATED→REMEDIATED→LIVE_CONFIRMED` (status follows L5/Oracle; record both L4 Defender
and L5 Oracle when they disagree). `render()` then **consumes** `lineage_rN.json` and the render-time
oracle re-execution is **deleted** — single-sourcing the binding result from the gated run (the single
biggest integrity win). `manifest()` gains a Merkle `audit_root_sha256` over the content/oracle/lineage
digests.

### Tier 1 — Validation upgrades (P1; the adl-aqt2 BATAILLE-2 patterns, safe on the foundation)

| # | Theme | Core delta | Effort |
|---|---|---|---|
| T1 | **Scored judge panel** | Numeric score with the **ceiling re-derived in Python** | L |
| T2 | **Routine multi-vendor panel** | N-vendor adjudication per advisory role + deterministic variance artifact | M |

**T1 — Scored judge panel.** *Phase 1 (ship first — proves the anti-theatre control):* add numeric
`score`+`rubric` to the judge output, and **re-derive the ceiling deterministically in code** —
`panel-aggregate` reads oracle+invariants and caps the score (any `HCD-I*` FAIL → cap 5; Oracle FAIL on a
surviving finding → cap 7), overwriting the judge's self-reported number and recording
`{ceiling_applied, judge_claimed, capped_to}`. The Oracle ceiling becomes a *verified fact*, not a prompt
request. *Phase 2:* K-vendor fan-out (`panel-judge`), `panel_rN.json` with median/spread/dissent.

**T2 — Routine multi-vendor panel.** `panel <role> <round>` fans `mode_b` over N vendors via
`ARENA_PROVIDER` env per iteration (**no `llm.sh` signature change** — `llm.sh` already honors it),
writing per-vendor artifacts (`verdicts_rN__<vendor>.json`). A deterministic `aggregate` produces a
variance artifact (median/spread/dissent), tagging `oracle_absent` to prevent vendor-majority overriding
the Oracle. Egress discipline intact (`ARENA_MODE_B=1`); vendor disagreement is settled by the Oracle and
surfaced as a *variance signal* (turning "Gemini ignored `oracle=FIXED`" into a routine observation).
*Critic refinement:* extract `mode_b`'s body into a helper returning `(status, obj_or_reason)` without
`sys.exit`, so a per-vendor failure maps to `abstain`, never aborts the panel.

### Tier 2 — Generative & pedagogical (P2; higher-effort, high-value-later)

| # | Theme | Core delta | Effort |
|---|---|---|---|
| G1 | **Generative battle (`forge`)** | Proposer⇄Red-team *designs* an artefact against a contract | L |
| G2 | **Pupitre console** | 3-mode interactive teaching console over `courtroom.html` | L |

**G1 — Generative battle.** A first-class loop that *designs/hardens a new artefact* against an
acceptance contract (not just fixes a cited line). `forge-verify` is a thin generalization of `verify_fix`
— same throwaway worktree, same `_battery_in` Oracle, same `_patch_touches_harness` can't-self-certify
rail — plus the contract's **executable acceptance predicates** as the hard gate. `forge-converge` gets
its OWN predicate (every clause exits-0 AND no `must_not_regress` HCD-I* FAIL AND 2 rounds zero-open-defect)
— **not** the `new==0` heuristic, which would false-converge on a persistently-unmet clause. A
**human-freeze marker** keeps a machine-stubbed contract badged PROVISIONAL/contract-unreviewed until a
human signs the predicate (the judge-brief-severity-strip analog applied to the *grader*).

**G2 — Pupitre console.** Evolve `courtroom.html` into 3 modes (Comprendre / Exécuter / Naviguer) over an
embedded JSON state blob, no framework/network. Two non-negotiable critic guards: **(a)** findings without
an `oracle_cmd` (≈70% of R1) render an explicit "argued-only — no binding command" state, never a fake
copy-box; **(b)** `replay` executes only the **stored** `oracle_cmd` matched by id from committed state,
**never** a command string carried in the browser JSON (closes a shell-injection path into the
deterministic core).

---

## 3. Explicit DO-NOT-ADOPT list (from the determinism-guard)

Carried verbatim from the panel — the anti-patterns to refuse while importing adl-aqt2's machinery:
1. A single averaged numeric panel score as the **headline pass signal**.
2. Feeding LLM "faiblesses" into the charter loop **without** the `charter_gap` + `confirmed` gating that
   `harden()` already enforces — re-injection stays evidence-gated; never raw LLM free-text into the
   forbidden-patterns list.
3. **Any** path where vendor-panel agreement (both vendors 9.5+) is allowed to stand in for a live Oracle
   run.

---

## 4. Build order

Foundation first (F1→F2→F3), then validation (T1→T2), then generative/pedagogical (G1→G2). Each item is
its own commit: tests + `make audit` gate + CI green + tree clean, per the established cadence. The
foundation is sequenced first **on purpose** — it is the constraint layer that makes the LLM-scoring and
multi-vendor patterns safe to adopt without drifting into score-theatre.
