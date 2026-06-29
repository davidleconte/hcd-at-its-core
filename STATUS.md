# STATUS — hcd-at-its-core

_Handoff snapshot. Last updated 2026-06-28._

A Dockerized IBM HCD 2.0.6 (Cassandra 5.0 / Java 17) multi-node demo — a 94-module didactic
walkthrough — plus a self-contained **adversarial audit engine** (`audit_arena/`) that has been
dogfooded against this repo. Everything below is **green, CI-gated, and committed** on `master`.

## TL;DR

- **PROVEN LIVE (2026-06-28).** The tarball was staged and the stack booted on colima (aarch64,
  12 GiB). Both the open and **secure** profiles form a **6-node multi-DC cluster (6× UN)**;
  `make verify-release` confirms **Cassandra 5.0.7 + Java 17.0.19**; and **all 7 invariants
  `HCD-I1..I7` PASS live** (`passed=7 failed=0 deferred=0`) — `HCD-I1` (Part-11 DDM/RBAC CQL on a
  live, authenticated cluster) and `HCD-I2` (secure cluster forms) are no longer deferred.
- The live boot found **four real bugs** the entire offline suite + 3 audit rounds + cross-vendor
  tribunal missed (3 runtime config + 1 secure-profile) — all fixed (see git log around the live
  bring-up). Offline-green was necessary but not sufficient; this is why I1/I2 stayed honest.
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

## Proven live (2026-06-28) — what the bring-up established

The stack booted on colima (aarch64, 12 GiB), tarball sha256 `a41ffe25…`:

- **Open profile:** 6× UN multi-DC; `make verify-release` → Cassandra **5.0.7** + Java **17.0.19**.
- **Secure profile:** 6× UN with **PasswordAuthenticator + CassandraAuthorizer + NetworkAuthorizer
  + mTLS certs**, authenticated cqlsh, `secure-bootstrap` replicating `system_auth` across DCs.
- **`HCD-I1` PASS live** — the Part-11 DDM/RBAC CQL battery runs clean: `mask_inner`, the
  `function_keyspace`/`function_name` `column_masks` query, and `GRANT ... ON KEYSPACE` under auth.
- **`HCD-I2` PASS live** — secure cluster forms 6× UN. **All 7 invariants PASS, zero deferred.**

### Four bugs the live boot found (all fixed)
1. `cassandra.yaml.template` — C* 5.0 rejects the old `*_in_kb` size guardrails (typed sizes now).
2. `docker-entrypoint.sh` — JMX agent double-loaded (cassandra-env already appends it) → premain abort.
3. `docker-entrypoint.sh` + `docker-compose.yml` — entrypoint rewrote `jvm-server.options` with a
   conflicting `-Xmn` under G1 → JVM abort; removed (cassandra-env owns the heap; dropped HEAP_NEWSIZE).
4. `cassandra-secure.yaml.fragment` — `CassandraCIDRAuthorizer` NPEs at first-boot cache-init;
   disabled in the base profile (advisory MONITOR-only; Module 86 enables it post-boot).

### Live exploration of the two optional items (2026-06-28)

**`demo-full` autonomously — partially, then accepted as interactive-by-design.** Running
`demo-entropy.sh --no-pause` against the live 6-node secure cluster surfaced **3 real, general
robustness bugs, all fixed** (commit `2ae4a0a`): (1) `system_traces`/`system_distributed` were
SimpleStrategy → `LOCAL_QUORUM` tracing failed on multi-DC (now NTS in `secure-bootstrap`); (2)
`wait_for_node_un` waited for UN but not CQL-readiness → restart-then-query race; (3) `log_cmd` had
no retry → a transient cqlsh connection error aborted the whole run (now retries connection-level
errors only). It then hit a 4th issue that is **design, not a bug**: the destructive modules
(DC-failover/decommission/chaos, e.g. Module 3) `docker exec` a **hardcoded coordinator** that may
be the node they just stopped. Making all 94 modules run autonomously end-to-end would need
per-module coordinator-failover + MinIO/Data-API orchestration — i.e. turning an interactive
teaching tool into a CI runner. Decision: keep the 3 fixes; the demo stays interactive; the bulk
(pure-CQL) modules run fine live.

**Module 86 CIDR enforce — BLOCKED by a confirmed HCD 2.0.6 limitation.** `CassandraCIDRAuthorizer`
throws `NullPointerException` in `AuthCacheService.register` ← `initCaches` at **first boot**, before
any node serves CQL, so the cluster never forms. **Refuted the missing-param hypothesis**: it
reproduces with the full stock param set (`cidr_authorizer_mode` + `cidr_groups_cache_refresh_interval`
+ `ip_cache_max_size` all parsed). It is a bootstrap catch-22 — `initCaches` reads
`system_auth.cidr_groups`, a table the authorizer itself is supposed to create. Disabling it in the
base profile (default `AllowAllCIDRAuthorizer`) is correct; enabling CIDR enforce would need a
post-boot table-seed step IBM/DataStax does not document for this build. The rest of the secure
profile (Password/Authorizer/NetworkAuthorizer/mTLS) is unaffected and proven live.

- **Secure bootstrap requires fresh volumes** if a prior boot half-initialized `system_auth`
  (`docker compose ... down -v`) — the QUORUM-auth gotcha.

### Re-boot recipe (now that it works)
```bash
colima start --cpu 4 --memory 12         # 6 nodes + headroom (host has 36 GiB)
make up && make verify-release           # open profile, 6× UN, C* 5.0 + Java 17
make gen-certs && make up-secure && make secure-bootstrap   # secure profile, 6× UN + auth
python3 audit_arena/bin/arena.py invariants 1   # -> 7/7 PASS live
```

## Open options (pick up here)

1. **Live bring-up** — _highest value_, gated on the tarball (above).
2. **Another tribunal round** — `make audit-tribunal` prints the recipe; round 3 was near-dry, so a
   round 4 mostly tests for true mechanical convergence (two consecutive empty rounds).
3. **More cross-vendor Mode B** — `ARENA_MODE_B=1 make audit-mode-b ROLE=defender ROUND=N`
   (egress-gated; sends repo excerpts to z.ai/Google/Anthropic — deliberate opt-in).
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
