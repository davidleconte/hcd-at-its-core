# audit_arena — honesty guardrails (the binding contract)

**Status:** built (Tier 0 / F1 of [DESIGN_v2_roadmap.md](DESIGN_v2_roadmap.md)). This file is the
*documented contract* for the engine's honesty discipline — so the rule is enforceable code, not tribal
prose in a charter. It exists because `adl-aqt2`/pupitre makes a numeric LLM score the headline result,
and `audit_arena`'s entire reason to exist is to refuse that.

## The binding rule

> **A numeric LLM score is advisory and is read by NO gate. An Oracle exit code is binding. A
> judge-green over a DEFERRED or FAILing invariant is a flagged contradiction, never green.**

The deterministic **Oracle** (executable `cqlsh` / `nodetool` / `shellcheck` / `git` / score commands)
is the only arbiter that can move a finding's disposition. Prosecutor, Defender, and Judge — and any
external vendor in Mode B — are advocates. Advocates argue; the Oracle decides.

## How it is enforced in code

| Guardrail | Where | What it does |
|---|---|---|
| **G1 — no score surface** | `reconcile()` validator (`arena.py`) | REJECTS (exit 2) any `grades_rN.json` carrying a numeric `score`/`grade`/`rating`/`panel_score` field — there is no score→disposition wiring to launder. Numeric scores may live only in a future *advisory* `panel_scores` block. |
| **G2 — reconciler / contradiction** | `arena.py reconcile` → `state/reconciliation.json` | Cross-joins the latest grades (advisory) against oracle + invariants (binding). Emits one verdict: **RED** (any Oracle/invariant FAIL — if the judge also leans *ship*, recorded as `judge-ships-over-FAIL`), **AMBER** (no FAIL but a live invariant DEFERRED / stale — `green-on-deferred, not live-verified this run`; a ship-leaning judge here is recorded but **never blocks**), **GREEN** (all PASS, nothing deferred). |
| **G3 — Oracle-primacy self-test** | `tests/test_arena.py` | Asserts that for every finding with an `oracle_result`, the rendered disposition follows the Oracle (FIXED/PASS ⇒ non-blocking, FAIL ⇒ blocking) — "Oracle beats advocates" as an executable assertion. |
| **G4 — last-live freshness** | `reconcile()` (`ARENA_LAST_LIVE_MAX_AGE_DAYS`) | A `last_live` PASS older than the threshold reads `stale`, contributing AMBER. **Surfacing only** — default OFF (`0`), and a stale live PASS never hard-FAILs (that would punish honest deferral). Respects the green-PASS-with-timestamp decision. |
| **Honesty banner** | `render()` | The dashboard *leads* with the binding verdict (GREEN / AMBER / RED), visually above and dominant over any judge opinion. The advisory note is explicit: "LLM judge scores/opinions are advisory and are read by no gate." |

The reconciler reads only **structured** fields (`disposition`, oracle/invariant `status`) — never a regex
over the judges' free-text lenses, which would mis-flag. A judge may emit an optional `disposition`
(`ship`/`block`/`hold`); if absent, the reconciler simply reconciles on Oracle state alone.

## Explicit DO-NOT-ADOPT (from the v2 design panel)

1. A single averaged numeric panel score as the **headline pass signal**.
2. Feeding LLM "weaknesses" into the self-hardening charter loop **without** the `charter_gap` + `confirmed`
   gating that `harden()` already enforces — re-injection stays evidence-gated; never raw LLM free-text into
   the forbidden-patterns list.
3. **Any** path where vendor-panel agreement (e.g. both vendors 9.5+) is allowed to stand in for a live
   Oracle run.

## Relationship to the gate

`gate()` blocks on a fresh Oracle/invariant **FAIL** (authoritative, unchanged). A RED reconciliation
always coincides with such a FAIL, so it is already blocked; `gate()` additionally *surfaces* the
reconciliation verdict (and any judge-contradiction) so a green gate with an AMBER honesty state is never
silently read as fully green. AMBER never blocks — honest deferral is not a failure.
