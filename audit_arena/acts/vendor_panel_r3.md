# Vendor panel — round 3 (Mode B, `vendor-panel`, two real external families)

**2026-06-29.** The first run of the v2 **`vendor-panel`** (T2) against real vendors. Egress was explicit
and operator-authorized (`ARENA_MODE_B=1`, keys from `~/.secrets.env`); the round-3 **judge brief**
(severity-stripped, every finding annotated `oracle=FIXED`) was sent to **z.ai** and **Google**. Both
providers were called, returned parseable JSON, and the deterministic aggregator wrote the variance
artefact `state/vendor_panel_r3_judge.json` (gitignored). 2/2 participated, 0 abstained.

## Result: the two vendors AGREE — on the wrong answer

| Vendor | SRE | Committer | Security | Integrated |
|---|---|---|---|---|
| **GLM-4.6** (z.ai) | BLOCK | **D** (4 CQL "errors") | reject | **BLOCK** |
| **Gemini 2.5 Pro** (Google) | BLOCK | **F** (4 CQL "errors") | reject | **BLOCK** |

**Inter-vendor variance: AGREE.** Two frontier models from different vendors, given the same brief,
independently reached **BLOCK** — no dissent between them.

- GLM: *"multiple confirmed defects that would prevent a secure cluster forming (R1-08), break core demo
  modules (R1-06, R1-01…), render monitoring ineffective (R2-01…). Not ready for production."*
- Gemini: *"Blocked: the secure cluster fails to form, critical alerts are dead, multiple demo modules
  contain invalid CQL."*

## Why both are wrong — and why that is the point

Every one of the **11 findings** in the judge brief is annotated `oracle=FIXED`, and the deterministic
Oracle reconciles **GREEN** for round 3 (all PASS, converged — `gate PASS`). Yet both vendors judged in
the **present tense** ("the cluster *fails* to form," "alerts *are* dead," "modules *contain* invalid
CQL"), re-litigating the already-fixed R1/R2 backlog as live CRITICAL/HIGH defects. Both **ignored the
`oracle=FIXED` resolution** — despite the brief's explicit instruction to "re-derive severity from the
finding **+ Oracle result**." They anchored on the alarming finding *descriptions* and not on the
adjudication.

This is a stronger demonstration than the [original cross-vendor run](crossvendor_r3.md). There, the two
families *disagreed* with each other (GLM-defender said FALSE_POSITIVE; Gemini-judge said BLOCK). Here, the
two vendors **agree with each other and disagree with ground truth**:

> **LLM consensus is not truth.** Two independent frontier models *converged* on BLOCK for a codebase the
> Oracle proves is fixed and converged. Had vendor scores gated merges, a correct release would have been
> blocked **2–0** by model agreement.

## Disposition

The canonical round-3 record stays the **Oracle's** verdict: all findings `oracle=FIXED`, `gate PASS`,
converged. The Mode B panel outputs are preserved here as **evidence, not promoted** — both vendors'
BLOCK is demonstrably wrong for the current (fixed) tree. The vendor verdicts are **advisory and read by
no gate** (the v2 reconciler/gate read only the deterministic oracle + invariants); the Oracle — which
actually ran the commands — is the binding arbiter. That override, when even two agreeing frontier models
get it wrong, is the entire reason the arena exists.

*Provenance: `vendor_panel_r3_judge.json` generated 2026-06-29T00:41:54 over judge brief
`state/judge_brief_r3.md` (HEAD `d4458b1`); 11 `oracle=FIXED` markers; reconcile = GREEN.*
