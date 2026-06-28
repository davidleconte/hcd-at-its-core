# Audit Arena v3 — Design: self-hardening charter + convergence/blind-judge

**Status:** Implemented (approved with OQ1=explicit flag, OQ2=separate `make audit-harden`, OQ3=DEFERRED doesn't block). Validated: converge FAIL-blocks (HCD-I3=FAIL → not converged), judge-brief leaks no severity field, harden folds once + idempotent + hand-prose untouched; suite 260 passed. The self-hardening run already folded two real lessons (from R1-02, R1-06) into `_preamble.md`'s AUTO block — committed as the demonstrated outcome.
**Scope (pass 3, the deferred items):** (3) self-hardening charter loop (the adl-aqt2 §8 analog); (4) sharpen convergence + blind the Judge to prior severities.
**Motivation:** the architectural comparison vs `adl-aqt2`. Its distinctive idea is that the loop hardens *the generator* (weaknesses re-inject into the prompt §8), and its judges are blinded to prior scores. The arena currently hardens only the *code*, never its own charter, and its Judge sees the Prosecutor's severities (anchoring).

---

## 1. Goals & non-goals
**Goals**
- G1. When the arena confirms a defect *class* the charter didn't anticipate, **fold the lesson back into the charter** so future rounds catch it — the §8 move, applied to an audit engine.
- G2. **Convergence** means *both* "no new surviving findings for K rounds" **and** "no `HCD-I*` is FAILing" (an invariant FAIL must block convergence).
- G3. **Blind the Judge** to the Prosecutor's self-assigned severities (re-derive from surviving findings + Oracle).

**Non-goals**
- No generative/remediation mode (proposing fixes) — that's a separate paradigm shift, out of scope.
- No automatic editing of *code* or *hand-authored* charter prose. The self-hardening writes ONLY into a delimited, auto-managed block, append-only, human-prunable.

---

## 2. Item 4 — convergence + blind-judge (lower risk; do first)

### 2.1 Convergence (`converge()` change)
Today: prints `dry_2_rounds` (≥2 rounds with 0 new surviving findings). Change to a real verdict:
```
converged = dry_2_rounds AND (no HCD-I* status == "FAIL")   # PASS or DEFERRED both OK
```
- Reads the latest `invariants_r*.json`. A FAILing invariant **blocks** convergence even if findings went dry (you can't "converge" with a known-broken invariant).
- Output adds: `{"converged": bool, "blocking": ["HCD-I3", ...], "dry_2_rounds": bool}`.
- `render`: the convergence verdict shows in the header strip (CONVERGED / NOT — blocked by Ix).

### 2.2 Blind-judge (`judge_brief()` + charter)
- New `bin/arena.py judge-brief [R]` → writes `state/judge_brief_r{R}.md`: the surviving findings with the **`severity` field stripped**, plus each finding's evidence, dimension, invariant, Defender verdict, and **Oracle result** — but NOT the Prosecutor's severity.
- `prompts/judge.md`: instruct the Judge to **re-derive severity itself** from the finding + Oracle, explicitly "do not anchor on any prior severity."
- The Judge's tri-lens output is unchanged; only its *input* is de-anchored.

*Both 2.1 and 2.2 are pure additions (a function + a charter line + a render field). No file auto-mutation.*

---

## 3. Item 3 — self-hardening charter (higher risk; gated, explicit)

### 3.1 Trigger — what counts as "the charter missed it"
A finding carries a new optional flag **`charter_gap: true`** + a one-line **`lesson`**, set by the Prosecutor or Judge when *"this defect-class is not in the tier-1 forbidden-patterns."* (Explicit flag, not auto-derived — intentional, auditable. Auto-deriving "which forbidden-pattern would have caught this" is brittle; a human/LLM judgement is safer.)

Example: the `mask_outer` inversion (R1-02) was caught only via source, not by any forbidden-pattern → it would carry `charter_gap:true, lesson:"DDM mask-function arg semantics (inner vs outer) must be checked against the Apache DDM docs, not assumed."`

### 3.2 Mechanism (`harden()` subcommand)
- Scan all `findings_r*.json` for `charter_gap:true` with a `lesson`.
- Dedupe lessons (normalized text) against what's already in the auto block.
- Rewrite ONLY a delimited block in `prompts/_preamble.md`:
  ```
  <!-- AUTO-HARDENED:START — appended by `arena.py harden`; human-prunable -->
  - [from R1-02] DDM mask-function arg semantics must be checked against Apache DDM docs.
  <!-- AUTO-HARDENED:END -->
  ```
- **Append-only within the markers**, never touches hand-authored prose, **idempotent** (re-running adds nothing new), prints a diff of what it added.

### 3.3 Risk controls (this is the part that mutates files)
| Risk | Control |
|---|---|
| Charter corruption | writes only between `AUTO-HARDENED` markers; if markers absent, creates them at a fixed anchor; never edits outside |
| Charter bloat | dedupe by normalized lesson; each entry tagged with its source finding id for pruning |
| Wrong lesson | charters are *advisory prompts* to LLM roles — a bad lesson adds noise, not a hard break; and it's human-reviewable in git diff before the next run |
| Silent mutation | **NOT in `make audit`** — a separate explicit `make audit-harden` target; charter mutation is always deliberate; the diff is printed and committed by a human |
| Runaway loop | `harden()` only reads findings + writes the block; it never calls an LLM or re-runs the tribunal |

### 3.4 Charter changes
- `prompts/_preamble.md`: add the `AUTO-HARDENED` block markers (initially empty).
- `prompts/prosecutor.md` + `prompts/judge.md`: "if a confirmed defect-class is not covered by the tier-1 forbidden-patterns, set `charter_gap:true` + a one-line `lesson`."

---

## 4. Implementation plan (ordered)
1. `converge()` → invariant-aware `converged` verdict + render field. *(item 4.1)*
2. `judge-brief` subcommand + `judge.md` de-anchoring line. *(item 4.2)*
3. `harden()` subcommand (read `charter_gap`, dedupe, rewrite AUTO block, print diff). *(item 3)*
4. `_preamble.md` markers; `prosecutor.md`/`judge.md` charter-gap instruction.
5. `make audit-harden` target (separate, explicit); `make audit` unchanged.
6. Seed: tag 1–2 existing findings (e.g. R1-02) `charter_gap:true,lesson:...` to demonstrate; tests.

## 5. Validation plan (deterministic, offline)
- `converge` → `converged:false` when an invariant is FAIL (inject a temp FAIL to prove the block), `true` only when dry AND no FAIL. Asserted by `tests/test_arena.py`.
- `judge-brief` → output contains finding text + Oracle result but **no `severity:` token**.
- `harden` → on a seeded `charter_gap` finding, the AUTO block gains exactly one entry; **second run is a no-op** (idempotent); hand-authored prose byte-identical outside the markers (diff-checked).
- Regression: full suite green; gate 6/6; `make audit` output unchanged (harden not in it).
- Safety: `harden` on a charter with NO markers creates them at the anchor and is still idempotent.

## 6. Open questions (need a call)
- **OQ1 — trigger:** explicit `charter_gap` flag (recommended — auditable, intentional) vs auto-derive the missed pattern (brittle). *Proposed: explicit.*
- **OQ2 — harden cadence:** separate `make audit-harden` (recommended — deliberate mutation, human commits the diff) vs auto in `make audit`. *Proposed: separate.*
- **OQ3 — convergence on DEFERRED:** an invariant that is `DEFERRED` (live, no cluster) — does it block convergence? *Proposed: no (DEFERRED ≠ FAIL); only FAIL blocks, but the verdict lists deferred invariants so "converged-offline" is honestly distinguished from "converged-live".*
