# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dockerized multi-node IBM HCD (Hyper-Converged Database) cluster for development, testing, and demos. Runs a 6-node cluster across 2 datacenters (dc1: nodes 1-3, dc2: nodes 4-6) on a single machine using Docker Compose with static IPs on a `172.28.0.0/24` bridge network.

**Prerequisite:** `hcd-2.0.6-bin.tar.gz` (IBM HCD 2.0, Passport Advantage part `M1442EN`) must be placed in the project root before building. HCD 2.0 is built on Apache Cassandra 5.0 and requires the Java 17 runtime (the image base is `eclipse-temurin:17-jre`).

**Runtime:** Works against any Docker-compatible engine. On macOS (Apple Silicon, e.g. MBP M3 Pro) **colima** is supported — it exposes a Docker socket (note: this Docker CLI ships only the standalone `docker-compose` v2, not the `docker compose` plugin; the Makefile auto-detects). Size the VM for 6 nodes with `colima start --cpu 4 --memory 12 --disk 60` — 8 GiB is the bare floor (the 6 compose limits sum to ~6 GiB, leaving almost nothing for the VM/daemon and none for MinIO/Data-API/Grafana); 12 GiB is what booted cleanly live on 2026-06-28. Run `make verify-release` after `make up` to assert the Cassandra 5.0 base and Java 17 runtime.

## Common Commands

```bash
# Makefile shortcuts (auto-detects docker compose v1/v2)
make up              # build and start 6-node cluster
make down            # stop cluster (preserve volumes)
make destroy         # stop cluster and delete all data
make status          # nodetool status
make cqlsh           # open CQL shell on node1
make demo            # interactive entropy demo
make demo-dry        # dry-run (no cluster needed)
make demo-full       # build cluster + run full demo
make demo-score      # validate all 94 modules (scorecard)
make gen-certs       # generate PEM CA + node/client certs (secure profile)
make up-secure       # start cluster with HCD 2.0 secure profile (auth + CIDR + certs)
make demo-2.0        # run HCD 2.0 innovation modules (Part 11: 85-93)
make demo-ransomware # run DORA ransomware demo (modules 73-79)
make minio           # start MinIO WORM storage
make minio-down      # stop MinIO
make api             # start Data API (http://localhost:8181)
make api-down        # stop Data API
make monitoring      # start Prometheus + Grafana (http://localhost:3000)
make monitoring-down # stop Prometheus + Grafana
make env             # create/update conda env (Python 3.11 + uv) + uv-install dev tooling
make test            # run all pytest tests
make test-env        # run pytest inside the conda env (no activation needed)
make lint            # shellcheck + ruff
make validate        # validate docker-compose.yml syntax
make wait            # wait until all nodes are UN

# Direct commands (equivalent)
docker compose up -d --build
docker exec hcd-node1 nodetool status
./scripts/demo-entropy.sh 3              # run specific module (0-93)
./scripts/demo-entropy.sh --dry-run      # dry-run mode
./scripts/demo-entropy.sh --score        # automated 94-module scorecard

# Generate topology for different cluster sizes
python3 scripts/generate-topology.py -i                        # interactive
python3 scripts/generate-topology.py --nodes 5                 # single DC
python3 scripts/generate-topology.py --datacenters "dc1:3,dc2:2"  # multi-DC

# Run tests (requires pytest and pyyaml)
pytest tests/
pytest tests/test_demo_entropy.py        # demo script tests (dry-run)
pytest tests/test_topology.py            # topology generator tests
pytest tests/test_scripts.py             # script syntax + helper tests
pytest tests/test_topology_unit.py       # topology generator unit tests
```

## Architecture

- **Dockerfile** - Single image based on `eclipse-temurin:17-jre` (Java 17, required by HCD 2.0). Installs HCD 2.0.6 from local tarball, sets up Python 3.11 via `uv`, creates wrapper scripts for `nodetool`/`cqlsh`/etc. that set `HCD_CONF` paths. Runs as non-root `cassandra` user (UID/GID 999).
- **docker-compose.yml** - Defines 6 services using YAML anchors (`x-hcd-common`). Node 1 is the primary seed; nodes 2-6 depend on node 1's health. Seeds are nodes 1 and 4 (one per DC). Port 9042 bound to localhost on node 1. Hardened with `cap_drop: ALL`, `no-new-privileges`, ulimits (`nofile: 100000`, `memlock: unlimited`), and CPU/memory limits.
- **config/cassandra.yaml.template** - Cassandra config template using `${ENV_VAR}` substitution, processed by `envsubst` at container startup. Includes CDC, audit logging, and guardrails configuration for modules 26-28.
- **scripts/docker-entrypoint.sh** - Generates `cassandra.yaml` from template, writes rack/DC properties, waits for seed node with exponential backoff before starting HCD.
- **Makefile** - Developer shortcuts with auto-detection of `docker compose` (v2) vs `docker-compose` (v1).
- **scripts/generate-topology.py** - Generates `docker-compose.yml` for arbitrary cluster sizes and multi-DC configurations. Uses atomic file writes and validates DC node count consistency.
- **scripts/demo-entropy.sh** - Interactive 94-module demo (modules 0-93) in 11 parts. Parts 1-6 cover entropy, consistency, SAI, vector search, CDC, audit logging, guardrails, data modeling, compaction, compression, DC expansion (with chaos test), backup/restore, rolling restart, repair, stress testing, security (RBAC + TLS), GDPR data sovereignty, driver policies, ACID model, batches, LWT, sagas, and consistency decision framework. Part 7 (Enterprise, modules 55-62) adds: HCD Data API (REST/JSON via HTTP), multi-tenant isolation, node decommission, disaster recovery, silent data corruption, cross-service saga, LWT contention, and repair deep-dive. Part 8 (Ops Deep-Dives, modules 63-72) adds: live RBAC demo, encryption at rest (TDE), commitlog crash recovery, hint expiration & data gaps, dynamic RF change, streaming & bootstrap monitoring, materialized views, nodetool ops deep-dive, cross-DC consistency window, and bloom filter & cache tuning. Part 9 (DORA Ransomware, modules 73-79) adds: kill chain overview, WORM backup to MinIO Object Lock, commitlog archiving to WORM, ransomware attack simulation (TRUNCATE + snapshot wipe), recovery from WORM backups, DC failover under attack, and DORA compliance scorecard with K8ssandra auto-healing. Part 10 (Production Essentials, modules 80-84) adds: counter columns, prepared statements & driver best practices, JVM & GC tuning, CQL aggregation functions (now including HCD 2.0 / Cassandra 5.0 scalar math functions in module 83), and collection types deep-dive (frozen vs non-frozen). Part 11 (HCD 2.0 Innovations, modules 85-93) adds: Dynamic Data Masking (85), CIDR/IP allowlist authorizer (86), datacenter-level role restrictions (87), mTLS authentication & external RBAC (88), Paxos v2 consensus benchmark (89), authentication hardening — pre-hashed passwords/rate limiting/bulk grants (90), PEM SSL & cert-based internode auth (91), audit logging 2.0 hardening (92), and Java 17 runtime & supply-chain/CVE posture (93). Modules 86-92 require the **secure profile** (`make gen-certs && make up-secure`); on the default open profile they render the commands but do not enforce (modules 85 and 93 run on either profile). Supports `--dry-run`, `--no-pause`, and `--score` flags. Progress bar and counter `[mod/93]` in every module header (94 modules numbered 0-93).

- **docker-compose.secure.yml** - Overlay that sets `HCD_SECURITY_PROFILE=secure` on every node and mounts `./certs` read-only at `/opt/hcd/certs`. Merged via `docker compose -f docker-compose.yml -f docker-compose.secure.yml` (the `make up-secure` target).
- **config/cassandra-secure.yaml.fragment** - Appended to the generated `cassandra.yaml` by the entrypoint when `HCD_SECURITY_PROFILE=secure`. Enables `PasswordAuthenticator`, `CassandraAuthorizer`, and `CassandraNetworkAuthorizer`. The **CIDR authorizer stays DISABLED** (default `AllowAllCIDRAuthorizer`): on a live HCD 2.0.6 boot (2026-06-28) enabling `CassandraCIDRAuthorizer` NPEs every node at first-boot cache-init (`AuthCacheService.register`) — confirmed with the full param set, so it is a product bootstrap catch-22, not a config gap. Base auth keys stay commented in the template so there are no duplicate YAML keys. TLS stays off here (Modules 88/91 enable it) so the cluster boots without certs.
- **scripts/gen-certs.sh** - Generates a PEM CA, per-node server certs (SAN = hostname + container IP), and client identity certs (SAN = `spiffe://hcd/role/<name>`) into `./certs/` for Modules 88 and 91. Portable across OpenSSL/LibreSSL.
- **config/prometheus.yml** - Prometheus scrape config for JMX exporter metrics on all 6 nodes (port 9404).
- **config/jmx-exporter.yml** - JMX-to-Prometheus metric mapping for Cassandra thread pools, latencies, compaction, hints, and caches.
- **config/grafana/** - Grafana provisioning (datasource + dashboard). Pre-built dashboard shows write/read p99, thread pool activity, compaction pending, dropped messages, and hints.
- **scripts/driver-demo.py** - Python helper script using the DataStax cassandra-driver for modules 44-47. Subcommands: `token-aware`, `speculative`, `dc-failover`, `retry-policies`. Use `--local-dc` to override the default datacenter (default: `dc1`).
- **audit_arena/** - Adversarial audit engine for this repo: a 4-role tribunal (Prosecutor / Defender / Judge / **Oracle**) plus formal invariants `HCD-I1..I7`, a provenance manifest (git SHA / tool versions / content hash), a self-hardening charter (`make audit-harden`), and a generative remediation loop (`make verify-fix` — propose→red-team→verify a patch in a throwaway worktree, never touching your tree). `bin/arena.py` is the deterministic plumbing — the `make audit` pipeline is `contract` → `repomap` → `oracle` → `invariants` → `lineage` → `manifest` → `panel-aggregate` → `reconcile` → `render` → `gate`, plus remediation (`verify-fix`/`remediate-*`), self-hardening (`harden`), the generative forge (`forge-contract`/`-sign`/`-verify`/`-record`/`-converge`), external-vendor modes (`mode-b`/`vendor-panel`), and the pupitre's `replay`; see `audit_arena/README.md` + `DESIGN_v2_roadmap.md`. Run `make audit` to refresh the Oracle + `courtroom.html`.
- **CI** (`.github/workflows/ci.yml`) - four jobs on push/PR: lint (shellcheck `-S warning` + ruff), pytest (with cassandra-driver, demo scorecard), docker-validate (compose base + **secure overlay** + hadolint), and the **audit-arena gate** (runs the deterministic Oracle battery — blocks on failure — and uploads the manifest/courtroom artifacts). The same gate is installable locally as a git pre-push hook via `make audit-install-hook`.

## Code Style

- Shell scripts: `set -e`, quote variable expansions (`"${VAR}"`), lowercase for locals, UPPERCASE for env vars
- YAML: 2-space indentation, use anchors to reduce duplication
- Docker: specific base image tags, minimize layers, clean caches in same layer, non-root user
