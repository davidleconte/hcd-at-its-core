# STATUS — hcd-at-its-core

_Handoff snapshot. Last updated 2026-06-28._

A Dockerized IBM HCD 2.0.6 (Cassandra 5.0 / Java 17) multi-node demo — a 94-module didactic
walkthrough — plus a self-contained **adversarial audit engine** (`audit_arena/`) that has been
dogfooded against this repo. Everything below is **green, CI-gated, and committed** on `master`.

## TL;DR

- The demo + secure profile + audit engine are **complete and verified _offline_**.
- The **one blocker** to proving it _live_ is the IBM binary: **`hcd-2.0.6-bin.tar.gz`** (Passport
  Advantage part **`M1442EN`**) must be placed in the repo root before anything boots a cluster.
- CI is 4 green jobs on every push. Local suite: **288 passed** under Python **3.11** (the project
  runtime — do not validate with the host's newer `python3`).

## What's done

| Area | State |
|---|---|
| HCD 1.2.3 → 2.0.6 upgrade | Complete (5 PRs). Java 17 base, Paxos v2, DDM, CIDR, mTLS, audit 2.0, secure profile. |
| 94-module demo (`scripts/demo-entropy.sh`) | Complete; `--score` self-gating (exit 1 on any module regression). |
| Secure profile | `make gen-certs && make up-secure`; overlay + auth fragment + baked cqlshrc. **Boot never verified (needs tarball).** |
| Conda+uv dev env | `make env` (Python 3.11). `environment.yml` + `requirements-*.txt`. |
| CI (`.github/workflows/ci.yml`) | 4 jobs: lint · pytest · docker-validate · **audit-arena gate**. |
| Audit arena | Oracle, `HCD-I1..I7` invariants, manifest, self-hardening, `verify-fix`, gate, Mode A + **Mode B**. |
| Adversarial rounds | **R1** (14 findings, upgrade), **R2** (5, monitoring), **R3** (1, CI-quality). All FIXED. Judge: **converged**. |
| Cross-vendor Mode B | **Ran for real** (GLM + Gemini) — see `audit_arena/acts/crossvendor_r3.md`. |

## What is NOT proven (the deferred edge)

The entire stack has only ever run **offline** (dry-run, static, scorecard). Nothing has booted a
real cluster, because that needs the tarball. Concretely deferred:

- **`HCD-I1`** (every Part-11 CQL executes on Cassandra 5.0) — `DEFERRED`.
- **`HCD-I2`** (secure cluster forms, 6× UN) — `DEFERRED`.
- The 3 live Oracle checks and the secure-profile boot — never executed.
- `make verify-release` (asserts C* 5.0 base + Java 17 at runtime) — never run.

Findings tagged `FIXED` mean _the code fix landed and the offline Oracle passes_ — not that the
live path was exercised.

## The one blocker → live bring-up

```bash
# 1. place the IBM binary in the repo root:
#    hcd-2.0.6-bin.tar.gz   (Passport Advantage part M1442EN)
# 2. colima is the supported macOS engine (MBP M3 Pro):
colima start --cpu 4 --memory 8 --disk 60
make up && make verify-release      # boots 6 nodes, asserts C* 5.0 + Java 17
make demo-full                      # full 94-module demo against the live cluster
make gen-certs && make up-secure && make secure-bootstrap   # secure profile
```
A successful bring-up flips `HCD-I1`/`HCD-I2` and the 3 live Oracle checks from `DEFERRED` to
executed — the only thing that turns "offline-green" into "proven."

## Open options (pick up here)

1. **Live bring-up** — _highest value_, gated on the tarball (above).
2. **Another tribunal round** — `make audit-tribunal` prints the recipe; round 3 was near-dry, so a
   round 4 mostly tests for true mechanical convergence (two consecutive empty rounds).
3. **More cross-vendor Mode B** — `ARENA_MODE_B=1 make audit-mode-b ROLE=defender ROUND=N`
   (egress-gated; sends repo excerpts to z.ai/Google — deliberate opt-in).
4. **Stop** — this is a legitimate finish line.

## Operating notes

- **Python:** validate with `/Users/david.leconte/miniforge3/envs/hcd-at-its-core/bin/python`
  (3.11). The host `python3` is newer and masks 3.11-only failures (this bit CI once).
- **Refresh the dashboard:** `make audit` → `audit_arena/courtroom.html` (auto-refreshes /6s; shows
  the latest round + per-finding FIXED state). Generated artifacts are gitignored.
- **Git / push:** the repo is `davidleconte/hcd-at-its-core`. `gh`'s active account is
  `valentinleconte` (read-only here); switch to `davidleconte` to push, then restore
  `valentinleconte`. A pre-push gate (`make audit-install-hook`) runs the deterministic Oracle.
- **Honest scope:** the multi-family tribunal has run as **Mode A** (Claude-family: model diversity)
  and once cross-vendor via **Mode B**; the round-1 seed was a manual MECE pass. Don't overstate it.

## Key commands

```bash
make help              # all targets
make demo-dry          # full demo, no cluster (works today)
make demo-score        # 94-module scorecard (self-gating exit code)
make test-env          # pytest inside the 3.11 conda env
make audit             # refresh Oracle + invariants + manifest + courtroom + gate
make audit-tribunal    # per-round tribunal recipe (Mode A / Mode B)
```
