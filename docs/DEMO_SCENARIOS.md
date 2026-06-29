# HCD Demo — Scenario Catalog, Validation Roadmap & Direct-Jump Guide

> Companion to `scripts/demo-entropy.sh` (94 modules, 0–93, in 11 parts). This document answers three
> questions: **(1)** how do we *validate* that the full demo works live; **(2)** what scenarios are
> covered — described, with what's at stake, in a MECE taxonomy; **(3)** how do we *jump straight to a
> specific scenario* once the environment is up. Section 7 audits what could have been **missed**.
>
> Source of truth for the per-module metadata is the classification in §4 (each row cites the executed
> command behind a `⚠ destructive` flag). Last compiled 2026-06-29 against `master`.

---

## 1. How to use this document

- **Operators running a live demo** → §2 (jump-to-scenario) + §3 (what to bring up first).
- **Validating a build / handoff** → §3 validation roadmap (staged, with acceptance criteria).
- **Choosing what to show an audience** → §6 audience cross-reference, then §4 catalog.
- **Extending the demo** → §7 gap audit (what's thin or missing) + §8 (direct-jump design to implement).

Two environment **profiles** gate what enforces:
- **open** (`make up`) — no auth; modules 0–85, 89, 93 run as-is.
- **secure** (`make gen-certs && make up-secure && make secure-bootstrap`) — `PasswordAuthenticator` +
  authorizers + mTLS; required for modules **86, 87, 88, 90, 91, 92** to *enforce*.

Three **external services** are opt-in: **Monitoring** (`make monitoring`), **Data API** (`make api`),
**MinIO/WORM** (`make minio`).

---

## 2. Jump straight to a scenario (env already up)

Once the cluster is `6× UN`, you do **not** have to replay from module 0:

```bash
./scripts/demo-entropy.sh <N>          # run a single module N (0–93)
./scripts/demo-entropy.sh <N> --no-pause   # …without the interactive pauses
make demo-part P=<1-11>                 # run a whole Part
make demo-2.0                           # Part 11 innovations (85–93)
make demo-ransomware                    # DORA series (73–79)
```

**Discover and jump safely (implemented — see §8):**

```bash
./scripts/demo-entropy.sh --list                  # full catalog: mod · dim · profile · deps · ⚠ · title
./scripts/demo-entropy.sh --list --tag security   # filter the listing by tag
./scripts/demo-entropy.sh --tag dora              # RUN every module carrying a tag (preflighted)
./scripts/demo-entropy.sh 86                       # a preflight guard runs first
./scripts/demo-entropy.sh 86 --no-preflight        # bypass the guard
```

A **preflight guard** runs before any single-module or `--tag` jump: it asserts the cluster is UN, the
required **profile** is active, and any external **service** is up — and **fails fast with the exact
`make` command** if not (e.g. a `secure`-only module on the open profile → *"run: make up-secure …"*).
`--list` needs no cluster. Tags: the 12 dimension names (orientation, consistency, topology, modeling,
storage, transactions, ops, observability, security, resilience, driver, enterprise) plus `dora`,
`secure`, `destructive`. Source of truth: [`scripts/scenario_catalog.json`](../scripts/scenario_catalog.json).

> ⚠ **Destructive modules** stop/pause/kill nodes or `TRUNCATE` data (26 of 94 — flagged in §4). Run
> them **one at a time** and wait for recovery (`make wait`) before the next. They are *not* safe to
> chain via a single `--no-pause` sweep (a stopped coordinator breaks the next module). See §9.

---

## 3. Validation roadmap — "is the full demo working?"

The demo is **interactive-by-design**; it cannot all run in one autonomous pass (destructive modules
target hardcoded coordinators; some need external services). Validate in **stages**, each with a clear
exit criterion. Stages 0–1 are mandatory; 2–5 are scoped to what you intend to show.

| # | Stage | Commands | Acceptance criterion | ~Time |
|---|---|---|---|---|
| **0** | Offline gate | `make test-env` · `make demo-score` · `make audit` | suite green · 94/94 dry-run · offline gate PASS | 5 min |
| **1** | Open bring-up | `make up && make wait && make verify-release` | 6× UN both DCs · C* 5.0.7 + Java 17 | 10–15 min |
| **2** | Open non-destructive sweep | run §4 dims A–K rows tagged `open`, non-`⚠`, via `--no-pause` | each module `rc=0` | ~20 min |
| **3** | Secure profile | `make gen-certs && make up-secure && make secure-bootstrap && make demo-2.0` | 7/7 invariants · modules 86–92 enforce | ~25 min |
| **4** | External services | `make monitoring` (39, 41) · `make api` (55) · `make minio` (73–79) | each service-bound module `rc=0` | ~15 min |
| **5** | Destructive / chaos | each `⚠` module individually, `make wait` between | cluster returns to 6× UN after each | ~30 min |

**Acceptance for "full demo works"** = Stage 0 + Stage 1 green, **and** a representative module from each
MECE dimension (§4) passes `rc=0` live, **and** every destructive module recovers to 6× UN.

### Known caveats to bake into Stage 2/5

- **`system_traces` on the open profile (modules 2, 30):** `TRACING ON` + `LOCAL_QUORUM` fails the
  trace-fetch on the multi-DC cluster because `system_traces` ships as `SimpleStrategy` RF=1. The secure
  profile fixes this in `secure-bootstrap`; the **open profile has no equivalent** → either add an
  "open-bootstrap" (ALTER `system_traces`/`system_distributed` to NTS) or document the caveat. *(Verified
  live 2026-06-29.)*
- **Destructive autonomy:** modules that stop the coordinator they then `docker exec` against cannot run
  back-to-back unattended (STATUS.md, 2026-06-28). Run individually with recovery between.

---

## 4. MECE scenario catalog

Every module is assigned to **exactly one** capability dimension by its *primary* concern (a few span
two — e.g. TDE is storage+security; assigned by the value it teaches). Legend: **Prof** = open/secure ·
**Deps** = MinIO / API / Mon · **⚠** = destructive (stops nodes or wipes data). Run any row with
`./scripts/demo-entropy.sh <mod>`.

### M — Orientation & checkpoints
*Navigational, not capabilities.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 0 | Introduction & Cluster Status | open | — | | Confirms 6-node/2-DC topology is UN before anything runs |
| 13 | Summary & Health Check | open | — | | Recaps Part 1; final integrity check |
| 48 | Parts 1–5 Checkpoint | open | — | | Consolidates the distributed-systems mental model |

### A — Data distribution & consistency
*How data is replicated and reconciled — the heart of the "entropy" story.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 1 | Replication Factors | open | — | | RF per keyspace = how many node losses data survives |
| 2 | Consistency Levels | open | — | ⚠ | EACH_QUORUM fails on DC quorum loss while LOCAL_QUORUM serves — the availability tradeoff |
| 4 | Hinted Handoff & Entropy Viz | open | — | ⚠ | A down node accumulates hints and catches up on recovery — no data loss |
| 5 | Read Repair | open | — | ⚠ | Reads silently reconcile stale replicas, healing divergence on the fly |
| 6 | Anti-Entropy Repair | open | — | | Scheduled `nodetool repair` is the backstop guaranteeing eventual consistency |
| 10 | Node Recovery — Full Picture | open | — | | Hints + read repair + anti-entropy = the complete self-healing story |
| 30 | Latency vs Consistency | open | — | | Quantifies the latency price of stronger CLs so teams pick per workload |
| 35 | Multi-DC Write Conflict | open | — | | Last-write-wins timestamp resolution across DCs and its pitfalls |
| 54 | Consistency Decision Framework | open | — | | Decision tree for CL/RF/LWT/saga per use case |
| 71 | Cross-DC Consistency Window | open | — | ⚠ | Measures cross-DC replication lag so apps understand staleness |

### B — Topology & failure
*The ring, node/DC failure, gossip, partition.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 3 | Node Failures | open | — | ⚠ | RF=3 survives one node down; reads/writes continue under QUORUM |
| 7 | Token Ring & Consistent Hashing | open | — | | vnodes/token ranges distribute data — ownership & balance |
| 14 | The Ghost Rack (Double Rack Failure) | open | — | ⚠ | Both seed nodes (one/DC) dropping — rack-aware placement limits |
| 16 | Gossip Protocol & Failure Detection | open | — | | phi-accrual detector governs failover timing |
| 17 | The Zombie Node (Network Partition) | open | — | | Split-brain risk when a partitioned node still thinks it's alive |
| 24 | Kill an Entire Datacenter | open | — | ⚠ | Surviving DC serves traffic when a whole DC goes dark — DR cornerstone |
| 25 | Grand Finale — Self-Healing DB | open | — | ⚠ | Failure + automatic recovery in one narrative — heals without intervention |
| 34 | Live Failover Under Load | open | — | ⚠ | A node fails mid-traffic with the app seeing no errors |
| 43 | Geographic Viz & Token Ownership | open | — | | Maps token ranges to DCs/racks — data locality reasoning |

### C — Data modeling & query
*Schema, indexing, document/vector, modeling correctness.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 11 | Tombstones & Shadowed Data | open | — | | Deletes leave tombstones that hurt reads and can resurrect data |
| 15 | Schema Disagreement | open | — | | Detecting/resolving schema-version mismatch that silently breaks a cluster |
| 18 | Storage Attached Indexing (SAI) | open | — | | Flexible secondary-index queries without legacy-2i anti-patterns |
| 19 | JSON Fundamentals | open | — | | Native CQL JSON insert/select for document-shaped data |
| 20 | JSON Enterprise Patterns | open | — | | Production JSON modeling (nested types, collections) |
| 21 | Vector Search & AI Readiness | open | — | | Store embeddings + ANN search — the RAG/AI value proposition |
| 22 | Mixed Real-time Ops (CRUD + Upsert) | open | — | | Upsert semantics + mixed CRUD under live load |
| 29 | Data Modeling Anti-Patterns | open | — | | Why wide/unbounded partitions kill performance — the #1 mistake |
| 31 | Time-Series Use Case | open | — | | Bucketing/TTL modeling — a top real-world HCD workload |
| 69 | Materialized Views | open | — | | MVs maintain alternate query tables automatically (with caveats) |
| 80 | Counter Columns | open | — | | Distributed counters and their non-idempotent caveats |
| 83 | CQL Aggregation & Analytics | open | — | | Server-side aggregation + C* 5.0 scalar math functions |
| 84 | Collection Types (Frozen vs Non-Frozen) | open | — | | Frozen/non-frozen tradeoffs (tombstones, update granularity) |

### D — Storage internals
*Write/read path, compaction, compression, commitlog, bloom/cache.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 8 | Write Path Trace | open | — | | commitlog + memtable + coordinator fan-out — durability & latency |
| 9 | Read Path Trace | open | — | | bloom filter, cache, SSTable merge — read latency & tuning levers |
| 23 | Compaction: The Entropy Cleaner | open | — | | Merging SSTables + purging tombstones reclaims space, speeds reads |
| 32 | Compaction Strategies Deep Dive | open | — | | STCS/LCS/TWCS choice matching read/write/TTL pattern |
| 33 | Compression Strategies | open | — | | LZ4/Zstd tradeoffs — disk savings vs CPU |
| 59 | Silent Data Corruption Detection | open | — | | Checksums/scrub catch bit-rot before it propagates |
| 65 | Commitlog Durability & Crash Recovery | open | — | ⚠ | Un-flushed write survives a hard crash via commitlog replay |
| 72 | Bloom Filter & Cache Tuning | open | — | | Tuning FP rate + caches cuts disk reads, improves latency |

### E — Transactions & coordination
*LWT, batches, sagas, ACID expectations, Paxos.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 12 | Lightweight Transactions (LWT) | open | — | | Paxos compare-and-set prevents duplicate inserts under concurrency |
| 49 | ACID vs HCD | open | — | | Corrects the dangerous assumption that HCD offers RDBMS ACID |
| 50 | LOGGED vs UNLOGGED BATCH | open | — | | Atomicity ≠ isolation; warns against batch misuse |
| 51 | The Lost Update Problem | open | — | ⚠ | Concurrent read-modify-write loses updates without LWT |
| 52 | Banking: Instant Payment | open | — | ⚠ | Cross-account transfer needs LWT/saga for correctness |
| 53 | The Saga Pattern | open | — | ⚠ | Compensating actions coordinate multi-step flows w/o distributed txns |
| 60 | Cross-Service Saga | open | — | ⚠ | Transactional-outbox + saga coordinating HCD with external services |
| 61 | LWT Contention Under Load | open | — | ⚠ | LWT throughput collapses under hot-key contention — capacity warning |
| 89 | Paxos v2 Consensus (Benchmark) | open | — | | Paxos v2 fewer round-trips → faster LWT in HCD 2.0 |

### F — Operations & maintenance
*Routine cluster lifecycle: repair, restart, scale, backup, troubleshooting.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 36 | Adding a New Datacenter Live | open | — | ⚠ | Online DC expansion + chaos test (survives node failure during rebuild) |
| 37 | Backup & Restore | open | — | ⚠ | Wipe a table and recover it — RPO/RTO proof |
| 38 | Rolling Restart (Zero-Downtime) | open | — | ⚠ | Patch/upgrade nodes one at a time with no interruption |
| 40 | Repair Strategies | open | — | | Full/incremental/subrange — least-disruptive anti-entropy |
| 57 | Node Decommission (Controlled Shrink) | open | — | ⚠ | Drain + remove a node without data loss |
| 62 | Repair Deep-Dive | open | — | ⚠ | Anti-entropy reconciles a node that missed writes while down |
| 66 | Hint Expiration & Data Gaps | open | — | ⚠ | Hints expire after the window → a long-down node needs repair |
| 67 | Dynamic Replication Factor Change | open | — | | Altering RF live + mandatory repair after |
| 68 | Streaming & Bootstrap Monitoring | open | — | | `nodetool netstats` during bootstrap — when a node is truly ready |
| 70 | Nodetool Ops Deep-Dive | open | — | | Field guide to `nodetool` diagnostics for triaging a cluster |

### G — Observability & performance
*Metrics, back-pressure, stress, runtime tuning.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 39 | Rate Limiting & Back-Pressure | open | Mon | ⚠ | Back-pressure protects the cluster from overload; watch it in Grafana |
| 41 | Stress Testing & Capacity Planning | open | Mon | | `cassandra-stress` sizes the cluster, finds the throughput ceiling |
| 82 | JVM & GC Tuning | open | — | | Heap/GC tuning (G1/ZGC) avoids stop-the-world latency spikes |

### H — Security & governance
*AuthN/Z, encryption, masking, audit, supply-chain.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 27 | Audit Logging | open | — | | Who-did-what for compliance and forensics |
| 28 | Guardrails | open | — | | Block dangerous queries (large batches, unbounded reads) before harm |
| 42 | Security Fundamentals | open | — | | Intro to auth/RBAC/TLS concepts production must enable |
| 63 | Live RBAC Demo | open | — | | Roles + grants live — least-privilege enforced by the DB |
| 64 | Encryption at Rest (TDE) | open | — | | Data on disk unreadable if drives are stolen — compliance |
| 85 | Dynamic Data Masking (DDM) | open | — | | Column masking redacts PII for unprivileged roles, no app changes |
| 86 | CIDR / IP Allowlist Authorizer | **secure** | — | | Restrict which source IPs a role may connect from |
| 87 | Datacenter-Level Role Restrictions | **secure** | — | | Confine a role to DCs — data-residency / blast-radius |
| 88 | mTLS Authentication & External RBAC | **secure** | — | | Cert (SPIFFE) identity instead of passwords — zero-trust client auth |
| 90 | Authentication Hardening | **secure** | — | | Pre-hashed passwords, login rate-limit, bulk grants — anti-brute-force |
| 91 | PEM SSL & Cert-Based Internode Auth | **secure** | — | | Encrypt+authenticate internode traffic; block rogue nodes |
| 92 | Audit Logging 2.0 Hardening | **secure** | — | | Tamper-resistant audit logging for regulated environments |
| 93 | Java 17 Runtime & Supply-Chain | open | — | | Confirms Java 17 base + reviews CVE/supply-chain posture |

### I — Cyber-resilience & compliance (DORA)
*Disaster recovery and ransomware resilience.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 58 | Disaster Recovery Runbook | open | — | ⚠ | End-to-end: simulate disaster, then restore — documented recovery works |
| 73 | DORA — Kill Chain & Setup | open | MinIO | | Frame the kill chain; provision WORM buckets (Object Lock) |
| 74 | DORA — Backup to WORM | open | MinIO | | Immutable snapshots + checksums attackers cannot delete |
| 75 | DORA — Commitlog Archiving to WORM | open | MinIO | | Point-in-time recovery beyond last snapshot — tighter RPO |
| 76 | DORA — The Attack Simulation | open | MinIO | ⚠ | Attacker truncates every replica — in-cluster replication is no defense |
| 77 | DORA — Recovery from WORM | open | MinIO | | Restore wiped data from immutable backups — recoverable after attack |
| 78 | DORA — DC Failover Under Attack | open | — | | Keep serving from a clean DC while an attack is contained |
| 79 | DORA — Compliance Scorecard & K8s | open | — | | Score vs DORA requirements; K8ssandra auto-healing wrap-up |

### J — Client / driver
*Client-side resilience and best practices.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 44 | Driver Policies | open | — | | Token-aware + DC-aware LB cuts latency, avoids cross-DC hops |
| 45 | Speculative Execution | open | — | | Redundant requests hide a slow replica's tail latency |
| 46 | Live DC Failover with Driver | open | — | ⚠ | Driver auto-routes to the remote DC when local dies — client-side DR |
| 47 | Retry Policies Under Partition | open | — | ⚠ | Retry policies recover from a hung node without surfacing errors |
| 81 | Prepared Statements & Best Practices | open | — | | Cut parse overhead + prevent CQL injection |

### K — Enterprise integration & multi-tenancy
*App-facing access, change streaming, tenant isolation.*

| Mod | Title | Prof | Deps | ⚠ | What's at stake |
|---|---|---|---|---|---|
| 26 | Change Data Capture (CDC) | open | — | | CDC emits mutation logs for downstream (Kafka/ETL) streaming |
| 55 | HCD Data API (REST/JSON) | open | API | | JSON/REST Document API (:8181) — use HCD like a document DB |
| 56 | Multi-Tenant Isolation | open | — | | Keyspace/RBAC isolation so one customer can't read another's data |

---

## 5. Prerequisite matrix (what to bring up first)

| If you want to run… | First bring up | Then |
|---|---|---|
| Any open module (A–K, non-secure) | `make up && make wait` | `./scripts/demo-entropy.sh <N>` |
| Secure modules 86–92 | `make gen-certs && make up-secure && make secure-bootstrap` | `make demo-2.0` or `… <N>` |
| 39, 41 (back-pressure / stress) | `make up && make monitoring` | open Grafana at :3000 |
| 55 (Data API) | `make up && make api` | curl :8181 |
| 73–77 (DORA WORM) | `make up && make minio` | `make demo-ransomware` |
| 2, 30 (tracing at LOCAL_QUORUM) | open profile **+ system_traces→NTS** (see §3 caveat) | `… 2` |

---

## 6. Audience cross-reference

| Audience | Lead with dimensions | Signature modules |
|---|---|---|
| **SRE / Platform** | B, F, G, A | 3, 24, 25, 38, 57, 62, 70, 39 |
| **App developer** | C, E, J, K | 18, 21, 12, 50, 53, 44, 55 |
| **Security / Compliance** | H, I | 63, 64, 85, 86–92, 27, 73–79 |
| **Architect / Decision-maker** | A, E, I, K | 1, 2, 54, 49, 79, 56 |

---

## 7. Gap audit — scenarios that could have been missed (MECE)

Coverage is **strong** in A, B, C, E, F, H, I. The thin/absent areas, by dimension:

**G — Observability & performance (thinnest, 3 modules).**
- No **SLO / latency-budget** scenario (define a p99 target, breach it, observe).
- No **distributed tracing as observability** (OTel/Zipkin) — only per-query `TRACING ON`.
- No **alerting** path scenario (Prometheus alert → fire → ack); `config/alerts.yml` exists but isn't demoed.

**F/I — Operations & resilience gaps.**
- **Upgrade / rollback** is documented (HCD 1.2.3→2.0) but is **not a runnable module**. A mixed-version
  rolling-upgrade scenario would be high-value.
- **Cross-region restore** and **backup *verification* at scale** beyond the single-table 37/58.
- **Key/secret rotation** is absent: TDE keys (64) and certs (91) are created but never *rotated*.

**C/D — Data-lifecycle & failure-injection gaps.**
- **TTL → tombstone → TWCS** end-to-end lifecycle (31 touches time-series; not tied together with GC grace).
- **Hot/large-partition live failure** — 29 *explains* the anti-pattern but never *triggers* a
  `TombstoneOverwhelmingException` / wide-partition timeout live.
- **Online schema migration** at scale — 15 is *disagreement*, not a managed migration/DDL rollout.

**A/B — Distributed-failure realism.**
- **Clock skew / time drift** — LWW (35) depends on clocks, but no clock-skew demo.
- **Network degradation** (latency injection, packet loss) — 17 *simulates* a partition via narrative
  rather than injecting one (e.g. via `tc`/iptables).

**H — Security gaps.**
- **GDPR right-to-erasure** end-to-end (crypto-shredding) — residency is touched by 56/87, erasure is not.
- **Secret/credential scanning** and **connection-storm / auth brute-force at the socket** beyond 90.

**Process / validation gaps (not scenarios, but block "full demo works"):**
- **No post-destructive recovery *assertion*** — destructive modules stop nodes but don't all gate on
  return-to-UN; recovery is operator-judged. Add an explicit `assert 6× UN` tail per `⚠` module.
- **Open-profile `system_traces`** has no NTS bootstrap (modules 2/30) — see §3.
- **No autonomous destructive run** — needs per-module coordinator-failover (STATUS.md). Acceptable as a
  design decision, but should be stated, not implicit.

---

## 8. Direct-jump design (the "very important" requirement)

**Goal:** with the env up and configured, jump straight to any scenario *safely* — never half-run a
module whose prerequisite is missing.

**Today:** `./scripts/demo-entropy.sh N`, `make demo-part`, `make demo-2.0`, `make demo-ransomware`.
**Missing:** a prerequisite guard, discoverability, and named/tagged groups.

**Proposed (single source of truth = a sidecar catalog):**

1. **`scripts/scenario_catalog.json`** — the §4 table as data: per module `{part, dim, profile, deps,
   destructive, tags[]}`. Both the runner and these docs generate from it (no drift).

2. **Preflight guard** — before running module `N`, assert its declared requirements and fail fast with
   the exact fix (or auto-start with `--auto-prereq`):
   ```
   need cluster UN?      → nodetool status | grep -c '^UN' == 6   else: "run: make up && make wait"
   need secure profile?  → HCD_SECURITY_PROFILE=secure present     else: "run: make up-secure"
   need MinIO/API/Mon?   → service reachable                       else: "run: make minio | api | monitoring"
   ```

3. **Discoverability & tags:**
   ```bash
   ./scripts/demo-entropy.sh --list                 # print the catalog (mod · dim · profile · deps · ⚠)
   ./scripts/demo-entropy.sh --tag security         # run all H-dimension modules
   make scenario TAG=dora                           # run a named group
   ```

**Status: implemented (2026-06-29).** `scripts/scenario_catalog.json` ships as the single source of truth;
`demo-entropy.sh` gained `--list`, `--tag <name>`, `--no-preflight`, and a `preflight()` guard wired
before every single-module and tag jump. Guarded by `tests/test_scripts.py`
(`test_scenario_catalog_consistent_with_script` keeps the catalog and the script's `header N` modules in
lockstep, so a new module without a catalog row fails CI).

---

## 9. Appendix — destructive modules & recovery

**26 destructive modules** (stop/pause/kill a node, or `TRUNCATE` data):
`2, 3, 4, 5, 14, 24, 25, 34, 36, 37, 38, 39, 46, 47, 51, 52, 53, 57, 58, 60, 61, 62, 65, 66, 71, 76`.

Recovery discipline:
- Run **one at a time**; after each, `make wait` until 6× UN before the next.
- Node-down modules rely on the cluster's restart policy + the script's cleanup trap to bring nodes back;
  the most aggressive (24, 25, 46 — whole-DC stop) take the longest to recover on a CPU-constrained host.
- Data-wipe modules (`TRUNCATE`) operate on demo keyspaces (`rf_prod.*`, `dora_bank.*`); they self-seed.
- If a run is interrupted mid-destruction, `make up && make wait` (or `make restart`) restores the cluster.
