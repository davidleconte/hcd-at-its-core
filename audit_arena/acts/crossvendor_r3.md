# Cross-vendor tribunal — round 3 (Mode B, real external families)

The first time the tribunal ran with **non-Claude vendors**. Egress was explicit (`ARENA_MODE_B=1`,
operator-authorized); findings + cited excerpts were sent to z.ai and Google. Mode B worked
end-to-end: both providers were called, returned parseable JSON, and the orchestrator validated and
wrote the role artifacts. This is the evidence that the cross-vendor path is real, not a design.

## Result vs Mode A (Claude-family)

| Role | Mode A (Claude) | Mode B (external) | Agree? |
|---|---|---|---|
| Defender | sonnet → R3-01 **CONFIRMED / MED** | **GLM-4.6** (z.ai) → R3-01 **FALSE_POSITIVE** | No |
| Judge | fable → **LOW · 1 surviving · converged=YES** | **Gemini 2.5 Pro** → **BLOCK · 16 surviving CRIT/HIGH** | No |

Both vendors *disagreed* with the Claude-family verdict — but for instructive, non-symmetric reasons.

## Two findings the cross-vendor run surfaced

1. **Defender reads the LIVE tree (GLM was right about *current* code).** Mode A's sonnet ran
   *during* round 3, against the pre-fix `scripts/demo-entropy.sh` (unconditional `exit 0`), and
   correctly CONFIRMED. By the time GLM ran, R3-01 was already fixed (the excerpts are regenerated
   from the working tree), so GLM read a comment at line 10537 + the new `exit 1` and correctly
   called it FALSE_POSITIVE. **Neither model is wrong — they judged different code.** Lesson: a
   Defender re-run after the fix lands refutes the finding; the tribunal record is point-in-time.

2. **Cross-vendor judgment variance (Gemini was wrong about *current* state).** The judge brief
   marked every historical finding `oracle=FIXED` (20 explicit markers). Claude-family fable read
   those and declared convergence (LOW). Gemini 2.5 Pro **ignored the FIXED resolution** and
   re-litigated the entire fixed R1/R2 backlog as CRITICAL/HIGH, producing an alarmist "BLOCK"
   verdict. This is the exact failure mode a multi-family tribunal exists to expose — and the
   concrete argument for **never trusting a single family's verdict** (and for the deterministic
   Oracle being the binding arbiter, not any LLM).

## Disposition

The canonical round-3 record stays **Mode A** (the correct point-in-time tribunal: R3-01 CONFIRMED
pre-fix → FIXED → converged). The Mode B outputs are preserved here as evidence, not promoted to
the record — Gemini's BLOCK is demonstrably wrong for the current (fixed) tree, and the Oracle
(`gate` PASS, all findings `oracle=FIXED`) overrides it. That override is the whole point.
