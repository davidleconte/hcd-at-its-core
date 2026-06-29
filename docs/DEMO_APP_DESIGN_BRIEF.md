# IBM HCD Live Demo Experience — Design Brief & Product Prospectus

> **Purpose of this document.** A McKinsey-structured, MECE design brief to hand to **Claude Design** as
> the basis for a mock-up / interactive prototype. It describes the project, its goals, the content it
> must present, the experience it must create, and the technical substrate it builds on — so a designer
> can produce a beautiful, professional, *wow-effect* application that **tells, shows, and proves** IBM
> HCD 2.0 to prospects and customers, encapsulating `cqlsh` and the other client tools behind a
> cinematic, explanatory interface.
>
> **Audience of this document:** the design/prototyping team. **End-users of the product:** David
> (presenter) + the prospects/customers he is showcasing to.
> **Companion data/source-of-truth:** [`scripts/scenario_catalog.json`](../scripts/scenario_catalog.json)
> (machine-readable catalog of all 94 scenarios) and [`docs/DEMO_SCENARIOS.md`](DEMO_SCENARIOS.md)
> (the full scenario reference). This brief is the *narrative*; those are the *data*.

---

## 0. Executive summary (answer-first)

**The opportunity.** IBM HCD 2.0 (Apache Cassandra 5.0 + Java 17) is a deep, enterprise-grade distributed
database. Today its capabilities are proven by a **94-module live demo** that runs as a terminal script
against a real 6-node, 2-datacenter cluster. The *substance* is world-class; the *surface* is a black
terminal. In a sales setting, a terminal under-sells the product and puts the burden of "wow" on the
presenter, not the platform.

**The answer.** Build a **single-screen, story-driven demo console** — *"HCD Live"* — that wraps the
existing live cluster and its client tools (`cqlsh`, `nodetool`, the DataStax driver, `cassandra-stress`,
the Data API, MinIO/WORM, Grafana) and renders every scenario as a **Tell → Show → Prove** narrative:
*tell* the concept with a clear visual explanation, *show* it executing live against the real cluster,
*prove* it with rendered output (topology maps, token rings, latency curves, replica state) instead of
raw text. The presenter drives it like a deck; the audience watches a real distributed database survive a
datacenter outage, repel a ransomware attack, auto-mask PII, and serve AI vector search — **cinematically**.

**Why it wins (the three differentiators).**
1. **Real, not simulated** — every visual is backed by a live command against a real 6-node cluster; the
   "show" is genuine, which is rare and credible.
2. **Tell + Show + Prove** — concept, live execution, and rendered evidence in one frame; the audience
   *understands* what they're seeing, not just watches a terminal scroll.
3. **Safe to drive live** — a built-in prerequisite/safety model (already implemented) means the presenter
   can jump to any of 94 scenarios without breaking the cluster mid-pitch.

---

## 1. Situation · Complication · Question · Answer

**Situation.** A production-grade artifact exists and works:
- A Dockerized **6-node, 2-datacenter** IBM HCD 2.0.6 cluster (Cassandra 5.0.7 / Java 17), reproducible on
  a laptop.
- A **94-module curriculum** (modules 0–93, 11 parts) covering the full distributed-database story —
  entropy/consistency, failure & self-healing, data modeling, AI vector search, transactions, operations,
  security & governance, and cyber-resilience (DORA/ransomware).
- A **navigator + safety layer** (catalog-driven jump-to-scenario, prerequisite guard) and a **self-audit
  engine** that continuously verifies the demo's own claims.

**Complication.** The experience is a terminal. For an engineer, that's fine. For a **prospect or
executive buyer**, it (a) hides the product's sophistication behind monospaced text, (b) makes the
presenter the single point of "wow," (c) gives no visual mental model of *what just happened*, and (d) is
fragile to drive live (one wrong destructive command degrades the cluster mid-demo).

**Question.** How do we turn a technically-excellent terminal demo into a **showcase-grade application**
that creates a wow effect, explains as it demonstrates, and is safe and effortless to present?

**Answer.** *HCD Live* — a beautiful "tell-show-prove" console (this brief). It does not replace the
engine; it **encapsulates and dramatizes** it.

---

## 2. Product vision & first principles (MECE)

A governing idea — *"Make the invisible visible, and make the powerful obvious"* — supported by six
mutually-exclusive design principles:

| # | Principle | What it means for the design |
|---|---|---|
| **P1** | **Tell before you Show** | Every scenario opens with a one-breath concept + a visual model, *then* runs. No cold CQL. |
| **P2** | **Show it live, render it rich** | The command runs against the real cluster; the *output* is a visualization, never raw terminal text. |
| **P3** | **Prove the claim** | Each scenario ends with an explicit "what this proved" — the buyer takeaway, tied to a business stake. |
| **P4** | **Presenter-grade control** | Drive like a deck: jump anywhere, no fragility, graceful recovery, speaker notes, pacing controls. |
| **P5** | **Truthful theatre** | Drama from *real* behavior (a real DC dies), never faked. Credibility is the product's moat. |
| **P6** | **Progressive depth** | A 90-second headline for execs; a "show me the CQL / the node-tool output" reveal for engineers. |

---

## 3. Audiences & moments (MECE)

**Who watches** (mutually exclusive personas, each needs a different altitude):

| Persona | Cares about | Demo altitude |
|---|---|---|
| **Economic buyer / exec** | resilience, compliance, risk, "won't lose my data / fail an audit" | headline visuals, business stakes, no CQL |
| **Architect / platform lead** | topology, consistency model, scale, integration | topology + data-flow visuals, the "why it works" |
| **SRE / DBA** | failure modes, ops procedures, recovery | live node-tool output, repair/restore mechanics |
| **App developer** | data modeling, drivers, APIs, AI/vector | query interfaces, code snippets, the Data API |

**Where it runs** (mutually exclusive contexts the design must serve):

| Context | Constraint | Design implication |
|---|---|---|
| **In-person / on-stage** | big screen, far audience | bold typography, high-contrast, motion, minimal text density |
| **Screen-share / remote** | smaller viewport, latency | crisp at 100%, no reliance on tiny detail, captioned actions |
| **Self-guided / leave-behind** | no presenter | auto-narration mode, tooltips, "play" sequencing |

---

## 4. What we are showcasing — the content architecture (MECE)

The 94 scenarios are **already** organized into a mutually-exclusive, collectively-exhaustive taxonomy of
**12 capability dimensions** (see [`DEMO_SCENARIOS.md §4`](DEMO_SCENARIOS.md) and the machine-readable
[`scenario_catalog.json`](../scripts/scenario_catalog.json)). Every module carries: **profile** (open/secure),
**external dependencies** (Monitoring / Data API / MinIO), a **destructive** flag, and a one-line
**"what's at stake."** The app's content model maps 1:1 to this catalog.

| Dim | Capability theme | # | The buyer story it tells |
|---|---|---|---|
| **A** | Distribution & consistency | 10 | "Your data is in many places, always reconciled — tune the consistency/latency dial per workload." |
| **B** | Topology & failure | 9 | "Nodes and whole datacenters can die; the cluster keeps serving." |
| **C** | Data modeling & query | 13 | "Model documents, JSON, **vector/AI**, time-series — query flexibly with SAI." |
| **D** | Storage internals | 8 | "Durability, compaction, compression, crash recovery — the engine room." |
| **E** | Transactions & coordination | 9 | "LWT, sagas, **Paxos v2** — correctness without a single point of failure." |
| **F** | Operations & maintenance | 10 | "Repair, rolling upgrades, scale in/out, backup/restore — zero-downtime ops." |
| **G** | Observability & performance | 3 | "See it, size it, protect it under load." |
| **H** | Security & governance | 13 | "RBAC, **mTLS**, encryption-at-rest, **Dynamic Data Masking**, audit — compliance-ready." |
| **I** | Cyber-resilience (DORA) | 8 | "Survive **ransomware**: immutable WORM backups, recovery, DORA scorecard." |
| **J** | Client / driver | 5 | "Smart clients: token-aware routing, speculative execution, automatic failover." |
| **K** | Enterprise integration | 3 | "JSON/REST **Data API**, multi-tenant isolation, CDC streaming." |
| **M** | Orientation & checkpoints | 3 | Navigation/recap (not a sell theme). |

**The "hero" set-pieces** (the highest-wow scenarios to lead with — see §8):
*Kill a Datacenter* (B/24), *Ransomware vs WORM* (I/73–79), *Self-Healing Database* (B/25), *Vector Search
for AI* (C/21), *Dynamic Data Masking* (H/85), *mTLS zero-trust* (H/88), *Paxos v2 benchmark* (E/89).

---

## 5. The experience model — "Tell · Show · Prove" (the core triad)

Every scenario screen is the same three-act frame. **This is the heart of the design.**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ① TELL  — concept in one breath + a live-updating visual mental model      │
│            (e.g. the 6-node ring across 2 DCs, replicas highlighted)        │
├──────────────────────────────────────────────────────────────────────────┤
│  ② SHOW  — the real action runs (a node goes dark / a write fans out);      │
│            the underlying command is available on a "reveal" (cqlsh /        │
│            nodetool / driver), but the DEFAULT view is the visualization     │
├──────────────────────────────────────────────────────────────────────────┤
│  ③ PROVE — the rendered result + an explicit "what this proves" + the        │
│            business stake (the buyer takeaway), and the data to back it      │
└──────────────────────────────────────────────────────────────────────────┘
```

The raw terminal output (`cqlsh`/`nodetool`) is **never the primary surface** — it is a deliberate
"under the hood" reveal for technical audiences (P6). The default is always the rendered story.

---

## 6. Functional requirements — capability pillars (MECE)

What the application must *do*, in six non-overlapping pillars:

**F1 — Navigate.** Browse/search all 94 scenarios by dimension, persona, profile, or "hero" status; build
and save a **playlist** (a curated demo flow for a specific prospect); jump to any scenario instantly.

**F2 — Orchestrate the environment.** One-click bring-up/teardown of the cluster and its profiles
(open / secure) and optional services (Monitoring, Data API, MinIO); a persistent **environment status
bar** (6× node health, profile, services) always visible so the presenter knows the stage is set.

**F3 — Run, safely.** Execute a scenario against the live cluster via the existing **preflight guard**
(asserts cluster-UN + required profile + services before running) and the **destructive-safety model**
(destructive scenarios are flagged, run individually, and the cluster auto-recovers between them). No
action can silently break the demo.

**F4 — Encapsulate the client tools.** Drive `cqlsh`, `nodetool`, the DataStax Python driver,
`cassandra-stress`, `mc` (MinIO), `curl` (Data API), and Grafana **behind the UI** and **render their
output as visuals** (§7). The user never touches a terminal.

**F5 — Explain (Tell + Prove).** For every scenario: a concept card, a live visual model, speaker notes,
a "what this proves" takeaway, and a progressive "show me the command/output" reveal.

**F6 — Present.** Deck-like controls: pacing (manual / auto-play), full-screen, a remote-friendly layout,
"reset to clean state," and an **auto-narrated** self-guided mode for leave-behinds.

---

## 7. Encapsulating the client tools — the "Show" rendering map

The product's signature move: **client-tool output → live visualization.** Each tool maps to a visual
idiom the designer should mock:

| Tool (encapsulated) | Used by | Render it as… |
|---|---|---|
| **`nodetool status` / `ring`** | topology, failure, ops | a live **2-DC cluster map** + **token ring** — nodes pulse UN/DN, ranges colour by ownership |
| **`cqlsh` writes/reads at CL** | consistency, RF | an animated **write fan-out / read path**: coordinator → replicas, ack counts, CL satisfied/not |
| **`cqlsh` TRACING** | write/read path | a **latency waterfall** (commitlog → memtable → replica RTT) |
| **DataStax driver** | client/driver | a **client→cluster routing diagram** (token-aware hops, speculative retries, DC failover) |
| **`cassandra-stress`** | performance | a **live throughput/latency gauge** + percentile curves |
| **SAI / vector search** | data modeling, AI | a **query → matched rows / nearest-neighbour** panel (the RAG moment) |
| **Dynamic Data Masking** | security | a **before/after PII reveal** (same row, masked vs unmasked by role) |
| **`mc` + Object Lock (WORM)** | DORA | an **immutable-vault** motif: backup locked, attacker's delete *bounces off* |
| **Data API (`curl` :8181)** | enterprise | a **REST/JSON request→document** view (HCD as a document DB) |
| **Grafana / Prometheus** | observability | embedded **live dashboards** (p99, thread pools, compaction, hints) |

Principle: the command is the *engine*; the visualization is the *product*. Show the command on demand
(P6), never as the default.

---

## 8. Signature "wow" set-pieces (the cinematic moments)

These are the demo's tentpoles — design them as **mini-films** (10–60s each), real behavior dramatized:

1. **"Kill a Datacenter, keep serving"** (B/24). On screen: the 2-DC map. The presenter "pulls the plug"
   on dc1 — three nodes go dark with a visible jolt — yet a live write/read stream **never stops** on dc2.
   *Proves:* multi-DC survivability. *Stake:* zero downtime through a regional outage.
2. **"Ransomware vs the immutable vault"** (I/73–79). An attacker `TRUNCATE`s every table across all
   replicas (the in-cluster copies vanish — a gut-punch visual) — then recovery streams the data **back
   from WORM** that the attacker *could not delete*. *Proves:* DORA-grade cyber-resilience.
3. **"The self-healing database"** (B/25). Induce divergence; watch hints + read-repair + anti-entropy
   **reconcile the cluster automatically**, rendered as the ring re-synchronizing to green.
4. **"AI-ready in one query"** (C/21). Store embeddings, run a vector similarity search — the
   nearest-neighbour result lands instantly. *Stake:* HCD is your RAG/AI data layer.
5. **"PII that protects itself"** (H/85). The same row, queried by two roles — one sees `4111…1111`, the
   other sees `****…****`. *Stake:* privacy compliance with no app changes.
6. **"Zero-trust by certificate"** (H/88) and **"Paxos v2 is faster"** (E/89) — for the technical room.

---

## 9. Information architecture & screen inventory (for the designer)

A proposed MECE screen set — mock these:

1. **Stage / Home** — the "command center": environment status bar, the hero-scenario carousel, "start a
   demo / load a playlist."
2. **Scenario Library** — the 94 scenarios as a filterable gallery (by dimension, persona, profile, hero,
   destructive). Card = title, dimension, "what's at stake," prereqs, a thumbnail of its visual.
3. **Scenario Stage (the core screen)** — the Tell·Show·Prove triad (§5) with the live visualization
   center-stage, a concept rail, speaker notes, the "reveal command/output" drawer, and Next/Prev/Reset.
4. **Cluster Live View** — the always-available 2-DC map + token ring + health (the persistent "set").
5. **Playlist Builder** — drag scenarios into a flow tailored to a prospect; reorder; save/share.
6. **Environment Control** — bring up/down, switch profile (open/secure), toggle services; shows
   readiness + the exact prerequisite state the preflight guard checks.
7. **"Under the hood" panel** — the encapsulated terminal/output (cqlsh/nodetool), styled, for the
   technical reveal.
8. **Trust / Provenance badge** *(optional, high-credibility)* — surfaces that the demo is self-audited
   (the audit_arena: every claim verified; versions pinned). A subtle "verified live" mark.

---

### 9.A Wireframe sketch — the Scenario Stage (hero: "Kill a Datacenter")

Low-fidelity layout to anchor the first mock. It shows the **Tell·Show·Prove** triad (§5) with the
**Cluster Live View** center-stage, the persistent environment status bar, deck controls, the
"under the hood" reveal, and the trust badge. Everything here is driven by *real* cluster state.

```
┌─ HCD LIVE ───────────────────────────  ⬤dc1 ✓  ⬤dc2 ✓  ·  open profile  ·  MinIO▫ Grafana▫ DataAPI▫ ─┐
│  ◀ Prev    ⟳ Reset stage     ▌ 24/94 · B · Topology & Failure ▐     Next ▶    ⤢ Full-screen    ☰ Library │
├───────────────────────────────────────────────┬───────────────────────────────────────────────────────┤
│  ①  TELL                                        │  ②③  SHOW · PROVE   (center stage)                      │
│  ┌────────────────────────────────────────────┐│  ┌──────────────── Cluster Live View ─────────────────┐│
│  │  KILL AN ENTIRE DATACENTER                   ││  │      dc1                          dc2               ││
│  │  Multi-DC failover                           ││  │   ⬤n1 ⬤n2 ⬤n3   ───►   ◍n1 ◍n2 ◍n3   ⬤n4 ⬤n5 ⬤n6   ││
│  │                                              ││  │   (going dark ⚡)              (serving ✓)           ││
│  │  When a whole datacenter goes dark, the      ││  │   ┌── token ring ──┐     live write stream ▸▸▸▸▸   ││
│  │  surviving DC keeps serving reads + writes   ││  │   │   ◴ ◵ ◶ ◷ ◸ ◹  │     ✓ 1,204 ok · 0 errors    ││
│  │  at LOCAL_QUORUM — no client error.          ││  │   └────────────────┘     p99 12ms ▁▂▃▂▁            ││
│  │                                              ││  └─────────────────────────────────────────────────────┘│
│  │  ◇ STAKE  zero downtime through a regional   ││   ▸ WHAT THIS PROVES ─────────────────────────────────  │
│  │    outage — your application never notices.  ││     dc1 is DOWN; the client stream never stalled.       │
│  │                                              ││     LOCAL_QUORUM on dc2 ⇒ continuous availability.      │
│  │  ⓘ Speaker notes ▾   👤 Architect · SRE      ││   ◷ BUSINESS STAKE  survive an AZ/region loss, no RTO.  │
│  └────────────────────────────────────────────┘│                                                          │
│                                                 │   ⌄ Under the hood (reveal) ── nodetool · cqlsh ───────  │
│   ▷  Run scenario        ◼ Recover cluster      │     $ COMPOSE stop dc1 ;  cqlsh -e "CONSISTENCY          │
│   ⚠ destructive · auto-recovers after           │       LOCAL_QUORUM; SELECT ..."   (styled, on demand)    │
├─────────────────────────────────────────────────┴───────────────────────────────────────────────────────┤
│  ⓥ verified live · HCD 2.0.6 / Cassandra 5.0.7 / Java 17 · audit_arena ✓        ▮▮▮▮▯▯▯▯ playlist 4/9      │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Reading the regions: **top bar** = environment status (F2) + deck controls (F6) + scenario locator
(dim · part). **Left = ① Tell** (concept, stake, persona badge, speaker notes). **Right = ②③ Show·Prove**
(the live cluster visualization is the hero; the "what this proves" + business stake sit beneath it).
**Reveal drawer** = the encapsulated command/output for the technical room (P6). **Run / Recover** make
the destructive-safety model visible. **Footer** = the trust badge (§9.8) + playlist progress.

## 10. Component & visual-system guidance

- **Tone:** confident, modern-enterprise, "IBM-grade" but not stuffy; cinematic dark canvas with one or
  two vivid accent colours for *live* action (writes, repairs, attacks). High contrast for stage use.
- **Signature components to design:** the **2-DC node map**, the **token ring**, the **write/read
  fan-out animation**, the **latency waterfall**, the **throughput gauge**, the **WORM vault**, the
  **PII before/after**, the **concept card**, the **"what this proves" takeaway chip**, the **environment
  status bar**, the **command-reveal drawer**.
- **Motion is meaning:** animation conveys real state changes (a node dying, a write replicating, data
  recovering) — not decoration. Every motion maps to a real event.
- **Typography:** large, legible headlines (stage-readable); monospace reserved for the reveal drawer.
- **Accessibility & remote:** legible at 100% on a shared screen; captions for each live action.

---

## 11. Technical substrate the app builds on (what already exists)

The prototype is **not** starting from zero — it sits on a real, scriptable substrate. The app is a
**presentation/orchestration layer** over these existing primitives:

- **The cluster.** 6 nodes (`hcd-node1..6`), dc1 (1–3) / dc2 (4–6), Docker Compose, static IPs
  `172.28.0.0/24`. Lifecycle via `make up` / `up-secure` / `wait` / `down`.
- **The scenario engine.** `scripts/demo-entropy.sh` runs any module by number; it already supports
  `--list`, `--tag`, `--dry-run`, `--no-pause`, and a **preflight guard** that checks cluster-UN, profile,
  and services before running and **refuses to chain destructive scenarios**. Each module emits narrative
  + the live command + a teaching diagram.
- **The data contract.** [`scenario_catalog.json`](../scripts/scenario_catalog.json) — the single source
  of truth the app should consume directly: per scenario `{mod, title, part, dim, profile, external_deps,
  destructive, tags, at_stake}`. *This is the app's content API.*
- **Profiles & services.** open vs secure (`make gen-certs && up-secure && secure-bootstrap`); optional
  Monitoring (`make monitoring`), Data API (`make api`), MinIO/WORM (`make minio`).
- **The client tools** to wrap: `cqlsh`, `nodetool`, DataStax Python driver (`scripts/driver-demo.py`),
  `cassandra-stress`, `mc`, `curl` (Data API), Grafana.
- **Trust layer.** `audit_arena/` continuously verifies the demo's claims (versions, CQL, no-secrets,
  module counts) — a credibility asset the UI can surface.

**Integration note for engineering (not design):** the cleanest contract is for the app to (a) read
`scenario_catalog.json` for content, (b) call the cluster lifecycle `make` targets for F2, (c) invoke
`demo-entropy.sh <N>` (or, better, structured per-tool calls) for F3, and (d) parse `nodetool`/`cqlsh`
output (or JMX/Prometheus + the Data API) into the visual models of §7. A thin "demo API" wrapping these
is the recommended seam between the beautiful front-end and the live engine.

---

## 12. Scope & phasing (MECE — ship value early)

| Phase | Goal | Contents |
|---|---|---|
| **MVP — "The Pitch"** | one flawless live narrative | Stage + Cluster Live View + ~6 hero scenarios (§8) fully rendered; environment status bar; manual pacing. |
| **V1 — "The Library"** | self-serve breadth | all 94 scenarios from the catalog; filter by dimension/persona; command-reveal drawer; profiles & services control. |
| **V2 — "The Tailored Demo"** | sell to a specific account | playlist builder; auto-narrated leave-behind mode; trust/provenance badge; export/share. |

Design the MVP first; it is the artifact that creates the wow in front of the first prospect.

---

## 13. Risks, constraints & guardrails (own them up front)

- **Live-cluster fragility.** Destructive scenarios degrade the cluster; chaining is unsafe. *Mitigation
  (already built):* the preflight guard + destructive flag + per-scenario recovery; the UI must respect
  this (no "run all," explicit recovery between destructive set-pieces).
- **Resource footprint.** 6 nodes (+ services) need a sized host (≈12 GiB). The app should detect/queue,
  not assume infinite headroom.
- **Profile-gated scenarios.** Security set-pieces (mTLS, CIDR, DC-RBAC) need the **secure profile**; the
  UI must guide the switch, not fail cryptically.
- **Latency of "real."** Real commands take seconds; design *anticipatory* states (the "tell" fills the
  wait) so dead air never happens on stage.
- **Truthfulness.** Never fake a result for effect (P5) — the credibility is the moat.

---

## 14. Success criteria

- **Wow:** a non-technical buyer can articulate *what they saw and why it matters* after a hero scenario.
- **Clarity:** each scenario lands one concept + one business stake, unmistakably.
- **Confidence:** the presenter can jump anywhere and never breaks the demo live.
- **Credibility:** every visual is backed by a real command on a real cluster (and the app can prove it).
- **Reusability:** a tailored playlist can be assembled for a specific prospect in minutes.

---

## 15. Appendix

**A. Data contract (the app's content API)** — `scenario_catalog.json`, one object per scenario:
`mod` (0–93), `title`, `part` (1–11), `dim` (A–K, M), `profile` (`open`|`secure`), `external_deps`
(`MinIO`|`DataAPI`|`Monitoring`), `destructive` (bool), `tags` (dimension name + `dora`/`secure`/
`destructive`), `at_stake` (one-line buyer takeaway). 94 entries; the destructive flag is CI-verified
against the script.

**B. Full scenario reference** — [`docs/DEMO_SCENARIOS.md`](DEMO_SCENARIOS.md): every module with profile,
deps, destructive status, "what's at stake," and the validation roadmap.

**C. Glossary (for the designer):** *HCD* = IBM Hyper-Converged Database (Cassandra 5.0 core); *node* =
one DB server (6 total); *DC* = datacenter (dc1, dc2); *RF* = replication factor (copies of data);
*CL* = consistency level (how many copies must ack); *cqlsh* = the CQL shell; *nodetool* = the cluster
admin CLI; *SAI* = Storage-Attached Indexing; *LWT* = lightweight transaction; *DDM* = Dynamic Data
Masking; *WORM* = write-once-read-many immutable storage; *DORA* = EU Digital Operational Resilience Act.

---

*Hand-off note to Claude Design: the strongest first mock is the **Scenario Stage** (§5/§9.3) for a single
hero scenario — "Kill a Datacenter" (§8.1) — with the persistent **Cluster Live View** (§9.4). Nailing
that one screen establishes the entire visual language; the rest of the app composes from it.*
