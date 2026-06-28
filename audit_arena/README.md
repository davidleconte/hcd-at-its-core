# HCD audit arena — adversarial tribunal for the HCD demo

A dedicated, repeatable **adversarial audit engine** for `hcd-at-its-core`, inspired by the
`bb-debunking-phase-1` courtroom but adapted to **serious HCD 2.0 / Cassandra 5.0 requirements**.

Four roles. Diversity-of-judgement is the anti-collusion mechanism:

| Role | Job | Driven by |
|---|---|---|
| 🔴 **Prosecutor** | refute-by-default; every finding cites `path:line` + a Cassandra-5.0 source | Claude / subagent |
| 🔵 **Defender** | kills false positives (CONFIRMED / OVERSTATED / FALSE_POSITIVE) | a *different* model family |
| 🟣 **Judge** | HCD tri-lens verdict — **SRE · Cassandra-committer · Security** | a *third* family |
| 🟢 **Oracle** | **deterministic ground truth** — runs the verifiable checks | `bin/arena.py` (no LLM) |

The **Oracle is the HCD-specific upgrade**. A quant audit can only *argue* whether a result is
look-ahead-biased; an HCD audit can *run* the artefact — `cqlsh`, `make demo-score`, `shellcheck`,
`docker compose config`, the no-duplicate-key check, `openssl verify`, or WebFetch against
apache/cassandra. So HCD findings are **executably adjudicated**, not merely debated. The Oracle
overrides both Prosecutor and Defender for any finding it can run.

> **What actually runs vs what's a design (be precise):** the **deterministic half** — the
> Oracle, the `HCD-I*` invariants, the manifest, `verify-fix`, the gate — is real code that runs
> every time. The **LLM tribunal HAS now run**: rounds 2 and 3 are real Prosecutor→Defender→Judge
> passes (`acts/` is populated; `findings_r2/r3`, `verdicts_r2/r3`, `grades_r2/r3` are their
> output), each role a **different model** for anti-collusion, with the deterministic Oracle as
> binding arbiter. **But that was Mode A** — different *Claude-family* models (opus/sonnet/fable):
> **model diversity, not vendor diversity.** True cross-vendor adjudication is **Mode B**, which is
> now wired one-command (`arena.py mode-b`, mock-tested) but only *runs* against real third-party
> families when you supply keys + `ARENA_MODE_B=1`. The round-1 seed remains a manual MECE pass.
> Findings tagged `FIXED` mean the code fix landed and the *offline* Oracle passes. `HCD-I1`/`I2`
> (live CQL / cluster-forms) and the 3 D1 Oracle checks **HAVE now been executed live** (2026-06-28,
> secure profile) and PASS — recorded in `state/last_live.json`, so the dashboard shows them green
> with a `last LIVE: PASS @ <ts>` stamp even when the cluster is down. A check never run live shows
> `DEFERRED` until a cluster boots.

## MECE dimensions
D1 technical accuracy (CQL/config vs C5.0) · D2 build & runtime wiring · D3 shell robustness ·
D4 tests · D5 documentation consistency · D6 security & back-compat. See `prompts/_preamble.md`
for the dimension charter and the HCD tier-1 forbidden patterns.

## Run it

### Mode A — self-contained (default, no API keys)
The orchestrating Claude Code session dispatches subagents as the roles (exactly the 6-dimension
MECE pass that seeded this arena). Per round:

```bash
python3 audit_arena/bin/arena.py repomap          # 1. inventory signal artefacts
# 2. Prosecutor subagent(s) read REPO_MAP + artefacts, web-verify CQL,
#    write audit_arena/state/findings_r1.json + acts/prosecutor_r1.md
python3 audit_arena/bin/arena.py excerpts audit_arena/state/findings_r1.json > /tmp/exc.md
# 3. Defender subagent (different model via Agent `model:`) -> state/verdicts_r1.json
python3 audit_arena/bin/arena.py oracle 1          # 4. deterministic battery -> state/oracle_r1.json
# 5. Judge subagent (third model) -> state/grades_r1.json
python3 audit_arena/bin/arena.py converge          # 6. loop-until-2-dry-rounds check
python3 audit_arena/bin/arena.py render            # 7. build courtroom.html
open audit_arena/courtroom.html                    # auto-refreshes /6s
```

### Mode B — true cross-vendor tribunal (optional, needs keys)
**One command** routes a role to an **external model family** so no single family grades its own
work. `arena.py mode-b <defender|judge> <round>` does the whole loop: it assembles the role prompt
from the charter + that round's state (Defender: `findings_rN` + cited excerpts; Judge: the
severity-stripped `judge_brief_rN` + verdicts), calls the provider via `bin/llm.sh`, then
**extracts and validates the JSON** (tolerating ```json fences / prose) and writes the same
`verdicts_rN.json` / `grades_rN.json` artifact Mode A produces.

Two safety gates: (1) an **egress opt-in** — refuses to call out unless `ARENA_MODE_B=1` is set for
that run (an ambient key never triggers a silent off-machine call); (2) **key-gated** — with no
provider key it exits 2. Either gate → `mode-b` propagates exit 2 and you fall back to Mode A.

```bash
# defaults: Defender=glm (ZAI_API_KEY), Judge=gemini (GEMINI_API_KEY). Keys live in ~/.secrets.env.
ARENA_MODE_B=1 python3 audit_arena/bin/arena.py mode-b defender 2     # -> state/verdicts_r2.json
ARENA_MODE_B=1 ARENA_JUDGE_PROVIDER=gemini \
  python3 audit_arena/bin/arena.py mode-b judge 2                     # -> state/grades_r2.json
# any OpenAI-compatible endpoint:
ARENA_MODE_B=1 ARENA_DEFENDER_PROVIDER=openai OPENAI_BASE_URL=... OPENAI_MODEL=... \
  python3 audit_arena/bin/arena.py mode-b defender 2
```
Mode B sends repo excerpts (findings + cited source) to a third party — that is why it is opt-in.
The wiring is tested offline with a mock provider (`$ARENA_LLM_CMD`), so the prompt-build →
extract → validate → write pipeline is covered without real egress. The Prosecutor stays Claude.
`make audit-tribunal` prints the full per-round recipe.

### Live-cluster Oracle (decisive HCD adjudication)
`bin/arena.py oracle` auto-detects a running cluster (`nodetool status`). Once `hcd-2.0.6-bin.tar.gz`
is staged and `make up` / `make up-secure` runs, the Oracle executes the live checks — 6×UN
cluster-forms, `make verify-release` (C5.0 + Java 17), and the **Part 11 DDM CQL battery via
`cqlsh -e`** (plus `HCD-I1`/`I2`) — promoting "verified-against-docs" findings to "executed-live".
**Live verdicts persist:** a live PASS is recorded to `state/last_live.json` (tracked), so when the
cluster is later down the row renders as a green **PASS · last LIVE: PASS @ \<ts\>** (with a `✓ live`
badge on invariant chips) — *not* lost. A check **never** run live shows amber **DEFERRED**; a live
FAIL never promotes. This was populated live on 2026-06-28 (HCD-I1/I2 + the 3 D1 checks, all PASS).

**Status legend:** `PASS` (green, verified — `· last LIVE @ ts` if from the last live run) · `FAIL`
(red, blocks the gate) · `DEFERRED` (amber, live check, no cluster yet — never blocks) · `TIMEOUT`
(amber, a check couldn't finish — usually a live cluster starving the CPU; inconclusive, non-blocking,
so `make audit` is the **offline** gate). `make audit` always refreshes the **latest** tribunal round
(the one the courtroom renders), and the pre-push hook re-refreshes it to the pushed commit.

### Formal invariants (Definition-of-Done) + provenance manifest

`bin/arena.py invariants` evaluates the seven named **HCD invariants** — the formal DoD every
finding and Oracle check maps to (full spec + design in `DESIGN_invariants_manifest.md`):

| | | |
|---|---|---|
| **HCD-I1** Part 11 CQL executes on C5.0 | **HCD-I2** secure cluster forms | **HCD-I3** no duplicate yaml keys |
| **HCD-I4** counts == TOTAL_MODULES | **HCD-I5** no secrets in image/git | **HCD-I6** demo dry-run/score safe |
| **HCD-I7** version & CQL claims source-verified | | |

Offline they evaluate to `PASS`/`FAIL`; the two live invariants (I1/I2) fall back to a proxy that
can **fail fast on broken wiring but only `DEFERRED` until a live cluster confirms** (burden on the
artefact). `I7` checks the pinned `reference_facts.json` — a drift to a wrong version/date fails it.

`bin/arena.py manifest` emits a **provenance manifest** (`state/manifest_r{N}.json`) — it *records* (does not bundle/pin): git SHA +
`git_dirty`, tool versions, a **content hash of the audited HCD source** (the arena's own outputs are
excluded, so the hash is stable across runs), the Oracle summary, and the seven invariant statuses.
Both surface in `courtroom.html` (an invariant scorecard + a manifest strip).

> Generated arena outputs (`courtroom.html`, `REPO_MAP.md`, `oracle_r*/invariants_r*/manifest_r*.json`)
> are git-ignored and regenerated by `make audit`; only the seed `findings/verdicts/grades_r1` and the
> engine code are tracked.

### Convergence, blind-judge & self-hardening charter

- **Convergence** (`bin/arena.py converge`) is a verdict, not just a count: `CONVERGED` requires
  *both* two dry rounds (no new surviving findings) **and** no `HCD-I*` FAILing. A `DEFERRED` live
  invariant doesn't block but is reported, so "converged-offline" ≠ "converged-live".
- **Blind-judge** (`bin/arena.py judge-brief`): the Judge's input has the Prosecutor's **severity
  stripped** — it re-derives severity from the finding + Oracle (anti-anchoring, the `adl-aqt2`
  truncate-before-judge discipline).
- **Self-hardening charter** (`make audit-harden` → `bin/arena.py harden`, the `adl-aqt2` §8 analog):
  when a finding is tagged `charter_gap:true` + a `lesson`, `harden` folds it into a delimited,
  append-only, **idempotent** `AUTO-HARDENED` block in `prompts/_preamble.md` — never touching
  hand-authored prose. It is **not** in `make audit` (a separate, deliberate target; you commit the
  diff). See `DESIGN_selfhardening_convergence.md`.

### Generative remediation (propose → red-team → verify-in-isolation)

The arena can also *fix*, not just *find* — the `adl-aqt2` generation-adversariale paradigm with the
Oracle as the decisive verifier. Per confirmed finding: **Propose** a minimal patch → **Red-Team** it
(4 lenses: incomplete / regression / violates another I* / new forbidden-pattern) → **`verify-fix`**.

`bin/arena.py verify-fix <fix.diff> [base.diff]` applies the patch(es) in a **per-run throwaway
`git worktree`** (concurrency-safe), runs the offline Oracle battery + invariants there, and reports:
- **`VERIFIED`** — Oracle PASS, no `HCD-I*` regression, and the patch does **not** touch the
  verification harness;
- **`UNTRUSTED`** — Oracle PASS *but* the patch modifies the harness the battery executes
  (`audit_arena/`, `scripts/demo-entropy.sh`, `tests/`), so it could self-certify — a human must
  review (you cannot earn VERIFIED by patching the verifier);
- **`REJECTED`** — the patch doesn't apply or the Oracle FAILs.

It **never touches your working tree** (a human always lands the patch), and it verifies against
**committed HEAD** (`verified_against` is recorded). Example — the demo fix patches `demo-entropy.sh`
(harness), so it is honestly `UNTRUSTED`, not `VERIFIED`:

```bash
make verify-fix FIX=audit_arena/state/patches/fix.diff BASE=audit_arena/state/patches/defect.diff
# -> { oracle_before: FAIL, oracle_after: PASS, harness_touched: ["scripts/demo-entropy.sh"], status: UNTRUSTED }
```

Safety rails: isolation (unique worktree, auto-removed), verified-patch output (human merges),
VERIFIED requires an executable Oracle PASS **and** an untouched harness, egress-gated drivers
(Mode B), and round/patch caps. Charters: `prompts/proposer.md`, `prompts/redteam_fix.md`.
Design: `DESIGN_remediation_mode.md`.

### `make audit` + deterministic pre-merge gate
```bash
make audit               # repomap + oracle + render -> audit_arena/courtroom.html
make audit-install-hook  # install the docker-free gate as git pre-push
```
The gate (`bin/pre-merge-hook.sh`) **blocks the push** if any deterministic check fails — `bash -n`,
`shellcheck -S error`, `make demo-score` (100%), `pytest` (no fail), no-duplicate-keys, count
consistency — and refreshes `courtroom.html`. Bypass once with `git push --no-verify`. The LLM
tribunal stays advisory (run on demand); only the deterministic Oracle gates merges.

## What's in `state/`
Seeded with the **real findings from the post-PR-5 MECE audit**: 14 findings (4 BLOCKER), the
Defender verdicts (12 confirmed, 2 false positives killed), the live Oracle battery, and the Judge's
tri-lens verdict (CONDITIONAL-SHIP). `courtroom.html` renders all of it.

## Live-cluster checks (when the 2.0.6 tarball is staged)
The Oracle's `oracle()` battery gains the decisive HCD checks once a cluster can boot:
`make up-secure && make wait` (proves the secure cluster forms), `make verify-release`
(Cassandra 5.0.x + Java 17), and per-statement `cqlsh -e` for every Part 11 CQL — turning the
"verified against docs" findings into "executed live".
