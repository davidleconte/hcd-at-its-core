# HCD 2.0 Upgrade — Technical Design, Implementation & Validation Plan

**Status:** Implemented (all 5 PRs; see §7)
**Target release:** IBM HCD **2.0.6** (first public release, 2026-06-17, IBM Passport part `M1442EN`)
**Current demo baseline:** HCD **1.2.3** (`hcd-1.2.3-bin.tar.gz`, base image `eclipse-temurin:11-jre`)
**Scope:** Make the 85-module entropy/consistency demo (`hcd-at-its-core`) faithfully build on and showcase HCD 2.0, including the net-new innovations 2.0 brings over 1.2.

---

## 1. What HCD 2.0 actually changes (sourced from the release notes)

HCD 2.0.6 is **built on Apache Cassandra 5.0** plus DataStax/IBM enterprise enhancements. The headline deltas **versus HCD 1.2** fall into four buckets:

| Bucket | Feature | Release-note wording |
|---|---|---|
| **Runtime** | Java 17 support | "Added Java 17 support" |
| **Consensus** | Paxos v2 | `paxos_variant: v2`, `paxos_state_purging: repaired` |
| **Security — data** | Dynamic Data Masking (DDM) | "Added Dynamic Data Masking (DDM) support" |
| **Security — identity** | mTLS + external RBAC | "Added mTLS authentication integration support with externally managed RBAC systems" |
| **Security — access** | CIDR/IP allowlist authorizer; DC-level role restrictions; bulk permission grants; pre-hashed passwords; cert-based internode auth; auth rate limiting; PEM SSL; pluggable SSL context; audit-log hardening; auth-cache mgmt; startup resilience | Cassandra 5.0 security integration |
| **Supply chain** | Netty → 4.1.133.Final (7 CVEs), Apache Mina → 2.2.7 (4 CVEs), Apache Directory 2.0.0.M27 | dependency updates |
| **Fixes** | `nodetool --ssl` hostname-verification on JDK 17+ | requires cert **SAN**, not IP |

**Cassandra-5.0 storage/query features** (UCS, Trie memtables/SSTables, SAI, Vector/ANN, math CQL functions) were already present in the HCD-1.x line and are **partially** covered by the demo — but the GA framing should be elevated and one genuine gap (math functions) closed.

### 1.1 Gap analysis against the current demo

Term-frequency scan of `DEMO_ENTROPY.md` (current state):

| Feature | Hits | Verdict |
|---|---|---|
| SAI / Storage Attached | 29 / 3 | ✅ covered (M18) |
| Vector | 14 | ✅ covered (M21) |
| Trie | 17 | ✅ covered |
| UCS / Unified Compaction | 5 / 1 | ◑ mentioned, not made a default-story |
| Reaper | 7 | ✅ covered (M62) |
| **math function** | **0** | ❌ gap — Cassandra 5.0 `abs/exp/log/log10/round` |
| **Dynamic Data Masking / DDM / MASKED** | **0 / 0 / 0** | ❌ **net-new 2.0 — no coverage** |
| **Paxos v2 / paxos_variant** | **0 / 0** | ❌ **net-new 2.0 — no coverage** |
| **CIDR / allowlist** | **0 / 0** | ❌ **net-new 2.0 — no coverage** |
| **mTLS** | **0** | ❌ **net-new 2.0 — no coverage** |
| **Java 17** | **0** | ❌ build still on Java 11 |
| **pre-hashed / PEM** | **0 / 0** | ❌ net-new 2.0 — no coverage |

**Conclusion:** the demo is structurally sound but (a) **builds the wrong binary on the wrong JVM**, and (b) **shows none of the six innovations that justify the 2.0 release.** Two workstreams follow: **W1 — version/build correction** (mandatory), **W2 — new feature coverage** (Part 11 + targeted enhancements).

---

## 2. Workstream W1 — Version & build correction (mandatory)

These make "the last release" actually *be* the last release. Pure mechanics, no new pedagogy.

| # | File | Change | Note |
|---|---|---|---|
| W1.1 | `Dockerfile` | `FROM eclipse-temurin:11-jre` → **`eclipse-temurin:17-jre`** | HCD 2.0 adds Java 17; M82 (JVM/GC) needs 17 to show ZGC |
| W1.2 | `Dockerfile` | `COPY hcd-1.2.3-bin.tar.gz` → **`hcd-2.0.6-bin.tar.gz`**; `version="1.2.3"` label → **`2.0.6`** | |
| W1.3 | `Makefile` | tarball guard at L16, L20, L100: `hcd-1.2.3-bin.tar.gz` → **`hcd-2.0.6-bin.tar.gz`** | 3 occurrences |
| W1.4 | `README.md` / `CLAUDE.md` | Prereq + "IBM HCD" version strings → **2.0.6**; module count `85` → **94** (see W2) | |
| W1.5 | `config/cassandra.yaml.template` | add 2.0 knobs (Paxos v2 default, DDM enable, authorizers) — see §3 | gated for back-compat |
| W1.6 | `docker-compose.yml` healthcheck | unchanged (`SELECT release_version` still valid) — but add an **assertion** in CI that `release_version` starts with `5.0` | proves 2.0/C*5.0 base |
| W1.7 | `Dockerfile` wrapper scripts | unchanged, but **`nodetool --ssl`** examples must use cert **SAN** hostnames not IPs (2.0 JDK17 fix) | affects M88/M91 |
| W1.8 | `make pin-digests` | re-pin temurin:17 + uv digests | reproducibility |

**Back-compat risk (critical):** turning on `PasswordAuthenticator`/CIDR/mTLS *by default* would break the 84 existing no-auth modules (every `cqlsh` call assumes `AllowAllAuthenticator`). **Design rule:** all new identity/access features are **runtime-toggled inside their own module and reverted in cleanup**, following the existing **Module 27 audit-log pattern** (`nodetool enableauditlog`/`disableauditlog`). Settings that *require* a restart (authenticator class, `cidr_authorizer`, `paxos_variant`) are delivered through an **opt-in security profile** (see §4.2), not the default `make up`.

**Exception — Paxos v2 as default:** `paxos_variant: v2` is wire-compatible and strictly an improvement; we make it the **default** in `cassandra.yaml.template` so M12/M51/M61 transparently benefit, and M89 measures the delta.

---

## 3. Workstream W2 — New feature coverage

### 3.1 New "Part 11 — HCD 2.0 Innovations" (Modules 85–93)

Nine new modules, same `run_module()` `case` + `DEMO_ENTROPY.md` chapter structure as the existing 85. Each module: *concept → live CQL/nodetool → "what to look for" → revert*.

| Mod | Title | HCD 2.0 feature | Core demonstration (CQL/ops) | Revert |
|---|---|---|---|---|
| **85** | Dynamic Data Masking — Column-level redaction | DDM | `ALTER TABLE customers ALTER ssn MASKED WITH mask_inner(0,4)`; `SELECT ssn` as analyst (masked) vs `GRANT UNMASK` role (clear); `mask_default/mask_hash/mask_null/mask_replace/mask_outer` tour; show stored bytes are unchanged | `ALTER … DROP MASKED`, `DROP ROLE` |
| **86** | CIDR / IP Allowlist Authorizer | CIDR authorizer | `cidr_authorizer` MONITOR→ENFORCE; `CREATE CIDRGROUP … '172.28.0.0/24'`; `ALTER ROLE app WITH ACCESS FROM CIDRS {'office'}`; connect from in-range (OK) vs simulated out-of-range (rejected) | drop group/role |
| **87** | Datacenter-Level Role Restrictions | DC-restricted RBAC | `CassandraNetworkAuthorizer`; `CREATE ROLE dc1only WITH ACCESS TO DATACENTERS {'dc1'}`; prove query routed to dc2 is denied; `ALTER … ACCESS TO ALL DATACENTERS` | drop role |
| **88** | mTLS Authentication & External RBAC | mTLS + external RBAC | `MutualTlsWithPasswordFallbackAuthenticator`; generate client cert; `ADD IDENTITY 'spiffe://…' TO ROLE svc`; cert-only login OK, password-only rejected under enforce; SAN→role mapping | fallback to password auth |
| **89** | Paxos v2 Consensus | Paxos v2 | Confirm `paxos_variant: v2` active; re-run M51 lost-update LWT + M61 contention **side-by-side v1 vs v2**, chart latency/throughput delta; `paxos_state_purging: repaired` housekeeping | n/a (default) |
| **90** | Authentication Hardening | pre-hashed pw, auth rate-limit, auth cache, bulk grants | `CREATE ROLE x WITH HASHED PASSWORD '…'`; auth rate-limit rejects brute force; `nodetool invalidatecredentialscache`; **bulk** `GRANT SELECT ON ALL TABLES IN KEYSPACE` | drop roles |
| **91** | PEM SSL & Cert-Based Internode Auth | PEM material, pluggable SSL, cert internode | PEM keystore/truststore (no JKS); `server_encryption_options` cert-based internode; verify encrypted gossip; `nodetool --ssl` with **SAN host** (2.0 JDK17 fix) | disable encryption profile |
| **92** | Audit Logging 2.0 Hardening | audit hardening | Extends M27: structured audit categories, included/excluded keyspaces, roles, filtered DML/DDL/AUTH events; tamper-evident sink (ties to DORA Part 9) | `disableauditlog` |
| **93** | Java 17 Runtime & Supply-Chain Posture | Java 17, Netty/Mina CVE bumps | `java -version` = 17 in-container; enable **ZGC** and compare GC pauses vs M82 CMS/G1; print Netty 4.1.133 / Mina 2.2.7 / Apache Directory 2.0.0.M27 versions; CVE-remediation scorecard | n/a |

### 3.2 Enhancements to existing modules (no renumber)

| Module | Enhancement |
|---|---|
| **M12 / M51 / M61** (LWT) | Add a one-line callout that LWT now runs on **Paxos v2** by default; forward-ref M89 |
| **M27** (Audit) | Cross-ref M92 hardening; note tamper-evident sink overlaps DORA WORM (Part 9) |
| **M32 / M33** (Compaction/Compression) | Promote **UCS** from "mentioned" to "the default 2.0 strategy"; show `unified_compaction` scaling params |
| **M42 / M63** (Security/RBAC) | Forward-ref the new authorizers (M86/M87/M88) so the security arc is contiguous |
| **M82** (JVM/GC) | Re-baseline on **Java 17**; add **ZGC** sub-graph (feeds M93) |
| **M83** (CQL Aggregation/Analytics) | **Close the math-function gap** — add `abs/exp/log/log10/round` worked examples (Cassandra 5.0) |

---

## 4. Implementation plan

### 4.1 File-by-file change map

```
Dockerfile                         W1.1 W1.2 W1.7  (base 17, tarball 2.0.6, SAN note)
Makefile                           W1.3            (tarball guards ×3); demo-score "85"→"94"
README.md, CLAUDE.md, AGENTS.md    W1.4            (version + module count)
config/cassandra.yaml.template     W1.5 §3         (paxos_variant v2; DDM; authorizers — gated)
docker-compose.yml                 W1.6            (CI assertion release_version ~ ^5.0)
docker-compose.secure.yml  (NEW)   §4.2            (overlay: auth/CIDR/mTLS profile)
scripts/demo-entropy.sh            §3.1            (add case 85..93; menu Part 11; cleanup hooks)
scripts/execute-full-demo.sh       L66            (add `11) for m in $(seq 85 93)`)
scripts/gen-certs.sh       (NEW)   §3.1 M88/M91    (PEM CA + node/client certs w/ SAN)
scripts/driver-demo.py             M88            (mTLS connection example)
config/cidr_groups.example  (NEW)  M86
DEMO_ENTROPY.md                    §3             (Part 11 chapters + overview + Appendix C objectives)
config/grafana/dashboards/         §5             (Paxos v2 + auth-rate-limit panels)
tests/                             §5             (pytest acceptance per new module)
```

### 4.2 Security profile (the back-compat mechanism)

A new overlay `docker-compose.secure.yml` + an env switch `HCD_SECURITY_PROFILE={open|secure}` consumed by `docker-entrypoint.sh`'s `envsubst` over `cassandra.yaml.template`:

- **`open`** (default, `make up`): `AllowAllAuthenticator`, no CIDR, no mTLS, `paxos_variant: v2`. **Modules 0–84 unchanged.**
- **`secure`** (`make up-secure`): `PasswordAuthenticator` + `CassandraAuthorizer` + `CassandraNetworkAuthorizer` + `cidr_authorizer: CassandraCIDRAuthorizer (MONITOR)` + `MutualTlsWithPasswordFallbackAuthenticator`. **Part 11 modules 85–92 require this profile** and assert it on entry (skip-with-reason if `open`, mirroring how M26 CDC checks prerequisites).

New Make targets: `make up-secure`, `make demo-2.0` (runs 85–93), `make gen-certs`.

### 4.3 Sequencing (PR-sized increments)

1. **PR-1 (W1, mechanical):** ✅ *done* — version/JVM bump (Java 17), tarball rename → `hcd-2.0.6`, `pin-digests`→17, `make verify-release` (asserts Cassandra 5.0 + Java 17), colima preflight. *Green build on 2.0.6 with all 0–84 passing = exit criteria.*
2. **PR-2:** ✅ *done* — Paxos v2 as the default (`cassandra.yaml.template`) + LWT cross-refs in M12/M51/M61. **Refinement:** the standalone M89 *benchmark* module is folded into the contiguous Part 11 batch (PR-4/PR-5) rather than landing alone here — a lone module 89 while 85–88 don't exist would hole the sequential scorecard and force a v1↔v2 restart harness before the security-profile infra exists. The config flip is what makes every existing LWT module run on v2 today.
3. **PR-3:** ✅ *done* — DDM (new **Module 85**, Part 11) + Cassandra-5.0 scalar math functions into M83; `dynamic_data_masking_enabled: true`. Data-plane only, no profile. **Module count rolled 85 → 86.**
4. **PR-4:** ✅ *done* — secure profile (`docker-compose.secure.yml` overlay + `HCD_SECURITY_PROFILE` gating in the entrypoint + `config/cassandra-secure.yaml.fragment`), `scripts/gen-certs.sh` (PEM CA + SAN node/client certs), and **modules 86–92** (CIDR, DC-RBAC, mTLS, Paxos v2 benchmark, auth hardening, PEM SSL, audit 2.0). New `make` targets: `gen-certs`, `up-secure`, `down-secure`, `demo-2.0`. **Count rolled 86 → 93.** Modules 86–92 gate on `require_secure_profile`; live enforcement needs `make up-secure`. *Residual:* `docker compose config` merge of the overlay not yet run (no Docker in dev shell) — verify on a Docker host.
5. **PR-5:** ✅ *done* — Module 82 re-baselined on Java 17 (ZGC promoted to production-ready); new **Module 93** (Java 17 runtime + ZGC + Netty/Mina/ApacheDS CVE posture + JDK-17 nodetool --ssl SAN fix); two Grafana panels (LWT/CAS p99 for Paxos v2 + CAS-ops load). **Count rolled 93 → 94.**

---

## 7. Completion status

**All five PRs are implemented in the working tree.** The 85-module HCD 1.2.3 demo is now a **94-module HCD 2.0.6 demo** (`eclipse-temurin:17-jre`, Cassandra 5.0) with a full **Part 11 — HCD 2.0 Innovations (85–93)**: DDM, CIDR authorizer, DC-level RBAC, mTLS, Paxos v2 (default + benchmark), auth hardening, PEM SSL, audit 2.0, and Java 17 / supply-chain. Validated offline: `bash -n` + `shellcheck -S error` clean, **scorecard 94/94**, **246 pytest pass** (only the pre-existing local `cassandra-driver` gap fails), `gen-certs.sh` verified end-to-end, combined config has no duplicate keys, all dashboards/overlays YAML-valid.

**Residuals requiring infrastructure** (cannot close in a Docker-less dev shell, all logged): (a) stage `hcd-2.0.6-bin.tar.gz` and run a live `make up` / `make up-secure`; (b) live smoke-test of the newest 2.0 CQL/`nodetool` surfaces (CIDR group inserts, `ADD IDENTITY`, audit flags, ZGC pause numbers, Grafana panel data). *(The overlay-merge check from the original list was since verified with compose v1 — env merges, volumes concatenate.)*

## 8. Post-implementation MECE audit & corrections

A six-dimension adversarial audit (technical accuracy, build/runtime, shell, tests, docs, security/back-compat) was run after PR-5. It found and **fixed**:

- **CRITICAL — secure cluster could not form.** The Docker healthcheck and the entrypoint seed-wait call `cqlsh` anonymously; under the secure profile's `PasswordAuthenticator` they would fail, so node 1 never goes healthy and `depends_on` blocks nodes 2-6. **Fix:** baked `cqlshrc` (`cassandra/cassandra`) + `ENV HOME` in the Dockerfile (harmless on the open profile). Added `make secure-bootstrap` to raise `system_auth` RF from 1 → `{dc1:3,dc2:3}`.
- **CRITICAL — three wrong CQL surfaces** (would error live): `system_schema.column_masks` columns (`mask_keyspace`/`mask_function` → `function_keyspace`/`function_name`); `mask_outer(card,0,4)` inverted (→ `mask_inner(card,0,4)`); `GRANT … ON ALL TABLES IN KEYSPACE` invalid (→ `ON KEYSPACE`). All fixed in script + book.
- **HIGH:** sstable* wrapper exec'd a non-existent path (now resolves real dir); Module 92 `CREATE ROLE` failed on the open profile (now gated with `require_secure_profile`); `LIST IDENTITIES` unverified (→ `system_auth.identity_to_role`); `ADD IDENTITY … TO ROLE 'analyst'` quoted; DDM "always redact" wording corrected to mention `UNMASK`/`SELECT_MASKED`; stale `hcd-1.2.3` prerequisite in the book bumped to 2.0.6.
- **MEDIUM/LOW:** template duration-key units note; CIDR ENFORCE + system_auth production caveats; AGENTS.md duplicate-step/`{0..N}` checklist fix; design-doc status header; banner "(72-79)"→"(73-79)" + dynamic scorecard count; gen-certs unencrypted-CA warning; `.dockerignore` adds `certs/`; README secure-profile scope clarified.
- **Tests:** suite made fully green (driver-demo skips cleanly instead of erroring); **6 new tests** in `tests/test_secure_profile.py` cover gen-certs (CA+SAN), the fragment (no dup keys + unit durations), the compose overlay, the entrypoint gating, and the 2 Grafana panels.

**Confirmed-correct under audit** (no change needed): all version facts (Netty/Mina/ApacheDS/Java 17/dates) verbatim against the release notes; paxos/CIDR/DDM/mTLS/audit/math-function config & grammar; compose overlay merge semantics; fragment no-dup-keys; gen-certs on OpenSSL+LibreSSL.

**Rollover decision (revised):** `TOTAL_MODULES` in `demo-entropy.sh` drives the run loop and the scorecard ticker (`seq 0 $((TOTAL_MODULES - 1))`) — so a runnable module *cannot* be added to a full run without bumping it. (The input-validation regex is a separate hardcoded bound that must be edited in tandem; a future cleanup could derive it from `TOTAL_MODULES`.) We therefore do **incremental rollover** (each feature PR bumps the count + the few "0-8x" strings in Makefile/README/CLAUDE/book) rather than a big-bang count change in PR-5. This keeps the scorecard count truthful at every step; the cost is touching ~6 string sites per PR, which a CI grep-guard can police.

---

## 5. Validation plan

### 5.1 Build & regression gates (must pass before any feature PR merges)
- `make build` on `eclipse-temurin:17-jre` succeeds; `docker exec hcd-node1 java -version` → `17.x`.
- `docker exec hcd-node1 cqlsh -e "SELECT release_version FROM system.local"` → **`5.0.x`** (asserted in CI).
- `make wait` → all 6 nodes `UN`; `nodetool describecluster` → single schema version.
- **`make demo-dry`** (dry-run all 94) → 0 failures.
- **`make demo-score`** scorecard → **94/94 green** (was 85).
- `make test` (pytest) + `make lint` (shellcheck + ruff) clean.
- **Regression:** full `make demo-full` of modules 0–84 on the 2.0.6 base, **`HCD_SECURITY_PROFILE=open`**, byte-identical pass/fail to the 1.2.3 baseline (captured as a golden scorecard before W1).

### 5.2 Per-feature acceptance tests (one pytest per new module)

| Module | Acceptance assertion (objective, scriptable) |
|---|---|
| 85 DDM | analyst-role `SELECT ssn` returns masked pattern; UNMASK-role returns cleartext; on-disk `sstabledump` shows **original** value (masking is presentation-only) |
| 86 CIDR | role bound to `office` CIDR connects from `172.28.0.0/24`; connection asserted-out-of-range is **rejected** in ENFORCE, **logged** in MONITOR |
| 87 DC-restrict | `dc1only` role query coordinated by dc2 node → `Unauthorized`; `ACCESS TO ALL DATACENTERS` → allowed |
| 88 mTLS | client cert whose SAN maps to `ADD IDENTITY` authenticates with **no password**; password-only under enforce → rejected |
| 89 Paxos v2 | `paxos_variant=v2` confirmed; M61 contention p99 **≤** v1 baseline over ≥1000 LWT ops (report count + p50/p99, not a single number) |
| 90 Auth-harden | `HASHED PASSWORD` role logs in; >N rapid bad logins → rate-limited; bulk `GRANT` covers all tables in keyspace in one statement |
| 91 PEM SSL | node boots with **PEM** keystore/truststore (no JKS); internode gossip encrypted (`nodetool gossipinfo` over TLS); `nodetool --ssl <SAN-host>` succeeds, `<IP>` fails (documents the 2.0 fix) |
| 92 Audit 2.0 | filtered audit captures AUTH+DDL, **excludes** configured keyspace; sink file present and append-only |
| 93 Java 17/ZGC | `java -version`=17; ZGC active (`-XX:+UseZGC` in `nodetool sjk` / GC log); max GC pause reported vs M82 baseline; dependency versions match release notes (Netty 4.1.133, Mina 2.2.7, ApacheDS 2.0.0.M27) |

### 5.3 Non-functional / safety
- **Cleanup idempotency:** the `trap cleanup INT TERM EXIT` must restore `open` profile, drop all Part-11 roles/CIDR groups/identities, and remove generated certs — verified by re-running `make demo-score` twice back-to-back (second run identical).
- **Reproducibility manifest:** record image digests (`make pin-digests`), `hcd-2.0.6-bin.tar.gz` SHA-256, C* `release_version`, Java version, and the dependency versions from M93 into `docs/RELEASE_MANIFEST_2.0.6.md`.
- **Docs parity:** assert `DEMO_ENTROPY.md` module count, `Makefile` `demo-score` label, README, and the scorecard all agree on **94** (a tiny CI grep guard prevents the classic "85" drift).

### 5.4 Exit criteria
A reviewer can run `make up && make demo-full` (open) **and** `make up-secure && make demo-2.0` (secure) on a clean machine, both reach 100% green, and every one of the six HCD 2.0 innovations (DDM, CIDR, DC-RBAC, mTLS, Paxos v2, Java 17/supply-chain) is demonstrated with an observable before/after.

---

## 6. Open questions for sign-off
1. **Tarball availability** — `hcd-2.0.6-bin.tar.gz` must be obtained from IBM Passport Advantage (part `M1442EN`); confirm it's staged before PR-1.
2. **mTLS depth** — full external-RBAC (e.g. SPIFFE/cert-manager) vs. self-signed CA for the demo? Recommend **self-signed CA via `gen-certs.sh`** for portability; flag external-RBAC as an "in production" note.
3. **Module numbering** — append as **85–93** (recommended, preserves existing references) vs. interleaving by topic (breaks every existing cross-ref). Recommend append.
4. **Default Paxos v2** — confirm OK to flip the default (recommended) vs. keep v1 default and only show v2 in M89.
