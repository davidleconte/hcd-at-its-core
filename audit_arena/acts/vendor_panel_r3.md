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

---

## Update (2026-06-29, later run) — third vendor: Anthropic Opus 4.8 (high effort)

A new `anthropic` provider was added to `bin/llm.sh` (Claude Messages API, model `claude-opus-4-8`,
**"high" reasoning effort** via `output_config.effort:"high"` — `budget_tokens` is removed on Opus 4.8;
adaptive thinking keeps the chain-of-thought in thinking blocks so the visible text stays clean JSON) and
the same round-3 judge brief was re-run across **three** families.

| Vendor | Disposition | Read the `oracle=FIXED` adjudication? |
|---|---|---|
| **Anthropic Opus 4.8** (high) | **CONDITIONAL-SHIP** | **Yes — for the R1 deal-breakers** |
| **Gemini 2.5 Pro** (Google) | **BLOCK** | No — re-litigated fixed R1 in present tense |
| **GLM-4.6** (z.ai) | *abstained* (`invalid_json`, transient — as before) | — |

**Inter-vendor variance: DISAGREE** (`block` vs `conditional-ship`). Adding the most-capable model **broke
the false consensus** of the two-vendor run.

### What changed — Opus 4.8 tracked the adjudication where Gemini didn't
Opus 4.8 (high) explicitly honored the Oracle's resolution of the **R1 deal-breakers**: its committer lens
reports `cql_that_would_error_live: 0`, grade **A-**, and its one-line verdict states *"All R1 deal-breakers
(live CQL errors, secure-cluster non-formation, system_auth RF) are **Oracle-verified FIXED**, so the cluster
now forms and the Part-11 CQL runs."* It **dropped every R1 CRITICAL** that Gemini re-raised. Gemini, by
contrast, repeated the two-vendor failure mode verbatim — present-tense re-litigation of R1-01/03/04/08
(*"cannot form," "would fail live"*) — reaching **BLOCK** in defiance of the `oracle=FIXED` markers.

### The honest caveat — even the best model still diverged at the margin
Opus 4.8 said **conditional-ship, not ship**. It surfaced six **R2/R3** findings (observability +
test/CI hygiene) as *surviving* — every one of which the brief also annotates `oracle=FIXED` and the Oracle
reconciles GREEN. Its lead concern (**R2-01**) is a specific, line-cited, falsifiable claim: four Prometheus
alerts (`HCDDroppedMessages`, `HCDCompactionBacklog`, `HCDHigh{Read,Write}Latency`) reference CamelCase
metric names while `jmx-exporter.yml` sets `lowercaseOutputName: true`, so — it argues — those alerts never
fire, with the Grafana dashboard already querying the lowercased names as the in-repo "smoking gun." That is
**either** a real surviving observability gap the Oracle's R2 check does not *discriminate* (a candidate
non-discriminating-check finding worth a follow-up), **or** Opus being over-cautious on an already-fixed
item. It is not resolved here — and that ambiguity is precisely why it is recorded as advisory, not promoted.

### The sharpened lesson
The two-vendor run showed *consensus ≠ truth*. The three-vendor run shows the complement: **vendor
disagreement is itself the signal, and the deterministic Oracle is what resolves it.** The strongest model
read the adjudication best — and *still* diverged from ground truth at the margin (conditional-ship vs the
Oracle's GREEN/converged). Had any vendor verdict gated merges, the panel would have been **split** (1 block,
1 conditional, 1 abstain) on a tree the Oracle proves is fixed. The binding verdict stays the **Oracle's**;
the panel is advisory and read by no gate. No LLM verdict — not even Opus 4.8 at high effort — can be the gate.

*Provenance: `vendor_panel_r3_judge.json` regenerated 2026-06-29T08:55:44 over the same brief
`state/judge_brief_r3.md`; roster `glm,gemini,anthropic`, 2/3 participated; code at HEAD `833473c`
(adds the `anthropic` provider). Per-vendor outputs `state/grades_r3__{anthropic,gemini,glm}.json`
(gitignored). reconcile = GREEN.*
