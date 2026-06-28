# Audit Arena v4 — Design: generative remediation mode (Propose ⇄ Red-Team ⇄ Oracle)

**Status:** Implemented (approved with OQ1=verify-in-isolation/human-lands, OQ2=Mode A default, OQ3=single-finding prototype on an injected defect). Validated end-to-end: on an injected `mask_outer(card,0,4)` defect, `verify-fix` reported `oracle_before=FAIL` (Oracle/HCD-I1 caught it) → `oracle_after=PASS` → **VERIFIED**, with the **main tree byte-identical** (isolation proof asserted in `tests/`). A debug-found bug (`int("vf")` silently skipped invariants) was fixed: `_battery_in` now uses an int-safe round and treats an unrunnable invariants check as a conservative FAIL. Suite 262 passed.
**Scope:** add a *generative* mode — given a confirmed finding, **propose a fix, adversarially harden it, and executably verify it** — the `adl-aqt2` BATAILLE-1 (génération adversariale) paradigm, but with the arena's executable Oracle as the decisive verifier (which `adl-aqt2` lacked).
**Paradigm shift:** the arena becomes *audit + remediate*. The audit loop finds & verifies **defects**; this loop proposes & verifies **fixes**. Oracle and invariants are shared (a fix must pass the Oracle and violate no `HCD-I*`).

---

## 1. SAFETY MODEL (leads, because this mutates code)

This is the only arena feature that writes to source. Five hard rails:

1. **Never touch the user's working tree.** All fix application happens in a **throwaway git worktree** (`git worktree add` on a temp branch), auto-removed after. The user's checkout is never modified by the arena.
2. **Verified-patch output, human applies.** The arena emits a **unified diff + the Oracle before/after delta**; a human reviews and applies it (`git apply`). The arena *applies in isolation only to verify*, never to merge.
3. **A fix is "VERIFIED" only if the Oracle PASSes in the worktree** and **no `HCD-I*` regresses**. Otherwise it's `UNRESOLVED` (kept for a human) — never silently shipped.
4. **Egress-gated.** If external model families drive Propose/Red-Team, the existing `ARENA_MODE_B=1` opt-in applies; default is local subagents (Mode A).
5. **Bounded.** Hard caps: ≤ N red-team rounds per finding, a max patch size, and a per-run finding cap. No autonomous multi-file rewrites without these bounds.

> Net: the arena can *propose and prove* a fix, but **a human is always the one who lands it.** The value-add over "ask an LLM to fix it" is the adversarial loop + the executable proof, not autonomy.

---

## 2. The remediation loop (per confirmed finding)

```
finding (Defender CONFIRMED + Oracle FAIL/not-fixed)
  └─ R1 PROPOSE   (Proposer): minimal patch + rationale + which HCD-I* it restores
  └─ R2 RED-TEAM  (different family): attack the patch across 4 lenses —
        (a) incomplete / wrong fix   (b) breaks tests/scorecard (regression)
        (c) violates another HCD-I*  (d) introduces a new forbidden-pattern
        → DEFECTS {severity, evidence, invariant}
  └─ R3 ARBITER   : any BLOCKER/HIGH defect → back to R1 with the critique
  └─ R4 ORACLE    : apply the patch in a throwaway worktree, run the offline battery —
        the contract's invariants HCD-I1..I7 (HCD-I6 = bash-n/shellcheck/scorecard,
        HCD-I3 = dup-keys, HCD-I4 = module-counts) + pytest, single-sourced through the
        contract → PASS/FAIL is DECISIVE (overrides Proposer & Red-Team)
  └─ CONVERGE K=2 : two consecutive rounds with no BLOCKER/HIGH AND Oracle PASS AND
        no HCD-I* regression → status VERIFIED; else (cap reached) → UNRESOLVED
```

Mirrors `adl-aqt2`'s K=2 + invariants, **plus** the executable Oracle gate `adl-aqt2` never ran.

---

## 3. Roles, orchestration & the arena/LLM split

Same division as the audit loop: **arena.py is deterministic plumbing; the LLM steps are driven by Claude (Mode A subagents) or `llm.sh` (Mode B).**

| Step | Driver | Deterministic? |
|---|---|---|
| Propose patch | Proposer subagent / Mode-B family | no (LLM) |
| Red-Team patch | different family | no (LLM) |
| **Apply-in-worktree + Oracle-verify** | **`arena.py`** | **yes (the differentiator)** |
| Converge bookkeeping | `arena.py` | yes |

`arena.py` gains the worktree/verify plumbing; Claude orchestrates the propose→red-team→revise rounds, calling `arena.py verify-fix` to adjudicate each candidate patch.

---

## 4. `arena.py` API additions
- `remediate-worktree` → create a throwaway worktree + temp branch; print its path. (auto-clean on `remediate-clean`.)
- `verify-fix <patch_file>` → in the worktree: `git apply` the patch, run the **offline Oracle battery + invariants**, capture before/after, **revert**, and emit `{applies:bool, oracle_before, oracle_after, invariants_after, regressions:[], status:PASS|FAIL}`. Never touches the main tree.
- `remediate-record <finding_id> <patch_file> <verdict.json>` → append to `state/remediation_r{N}.json`.
- `render` → a **Remediation panel**: per finding {status VERIFIED/UNRESOLVED, rounds, Oracle Δ, patch link}.

State (gitignored generated): `state/remediation_r*.json`, `state/worktree/` (or a temp dir). The patches themselves are written to `state/patches/<finding_id>.diff` (kept as the human-appliable artifact).

---

## 5. Convergence & stop
- **VERIFIED**: K=2 clean red-team rounds + Oracle PASS in worktree + no `HCD-I*` regression.
- **UNRESOLVED**: round cap hit without convergence → flagged for a human, with the best candidate patch + the residual red-team defects.
- **REJECTED**: Oracle FAILs on every candidate → the fix approach is wrong; surface it.

---

## 6. Implementation plan (PR-sized; prototype-first)
1. **Worktree plumbing** — `remediate-worktree` / `remediate-clean` (git worktree add/remove, temp branch, safety asserts that we're never on the user's branch).
2. **`verify-fix`** — apply-in-worktree → Oracle battery + invariants → before/after → revert. The deterministic core.
3. **Record + render** — `remediation_r*.json` + the Remediation panel; gitignore generated.
4. **Orchestration recipe** — `prompts/proposer.md` + `prompts/redteam_fix.md`; a documented Claude-driven loop (Mode A) + `make remediate FINDING=R-NN`.
5. **Demonstrate end-to-end on a CONTROLLED injected defect** (see §7) — all seed findings are already fixed, so remediation is shown on a deliberately re-broken copy, in isolation.
6. **Tests + docs**, design status → Implemented.

First version = **single-finding, propose-only output + worktree-verify**, demonstrated on an injected defect. Multi-finding batching is a later extension.

## 7. Validation plan (deterministic; no user-tree mutation)
- **Isolation proof**: `verify-fix` on any patch leaves `git status` of the **main tree byte-identical** (asserted in `tests/`); all work confined to the worktree.
- **Controlled demo**: inject a known defect (e.g., revert the `mask_inner(card,0,4)` fix → `mask_outer`), run the loop; expect Oracle/invariant `HCD-I1` proxy to FAIL on the broken tree, a proposed patch that restores it, and `verify-fix` → PASS → status VERIFIED, with the main tree untouched.
- **Negative**: a deliberately-bad patch (breaks pytest) → `verify-fix` → FAIL → status not VERIFIED (the Oracle catches it).
- **Idempotency/cleanup**: `remediate-clean` removes the worktree + temp branch; re-runnable.
- Regression: full suite green; pre-push gate 6/6; `make audit` unchanged.

## 8. Risks / open questions
- **OQ1 — apply policy:** **verify-in-isolation, propose-to-human** (recommended — the arena applies+verifies in a throwaway worktree, outputs a verified patch, the human lands it) vs propose-only-no-verify (weaker — loses the executable proof) vs auto-apply (rejected — unsafe). *Proposed: verify-in-isolation, human lands.*
- **OQ2 — drivers:** Mode A subagents (recommended default) vs Mode B external families (egress-gated, optional). *Proposed: Mode A default.*
- **OQ3 — first-version scope:** single-finding prototype on an injected defect (recommended) vs full multi-finding batch now. *Proposed: prototype-first.*
- **R1 — git worktree availability/cleanliness:** requires a clean-ish repo and `git worktree`; the plumbing must refuse to run if it can't isolate, rather than fall back to the main tree.
- **R2 — Oracle cost per candidate:** each `verify-fix` runs pytest+scorecard (~45s). Bound rounds; cache where safe.
