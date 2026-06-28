# HCD Docker Cluster — Developer Shortcuts
# Detects 'docker compose' (v2) vs 'docker-compose' (v1) automatically.

COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")
# Secure profile (HCD 2.0): base compose + secure overlay (auth, CIDR, mTLS certs).
COMPOSE_SECURE := $(COMPOSE) -f docker-compose.yml -f docker-compose.secure.yml
EXPECTED_NODES ?= 6
# Conda + uv hybrid dev env (host tooling). Override with: make env ENV_NAME=foo
ENV_NAME ?= hcd-at-its-core

# HCD 2.0 release artifacts. Single source of truth — bump these on a version change.
HCD_VERSION ?= 2.0.6
HCD_TARBALL ?= hcd-$(HCD_VERSION)-bin.tar.gz
# Apache Cassandra base version HCD 2.0 is built on (asserted by `make verify-release`).
EXPECTED_CASSANDRA_MAJOR ?= 5.0

.DEFAULT_GOAL := help

.PHONY: help build up down destroy restart status logs cqlsh demo demo-dry demo-full demo-score demo-ransomware demo-part demo-2.0 gen-certs up-secure down-secure secure-bootstrap minio minio-down check-prereqs verify-release env test-env test test-integration lint validate pin-digests wait clean monitoring monitoring-down api api-down audit audit-tribunal audit-mode-b audit-harden verify-fix audit-install-hook

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

build: ## Build container images
	@test -f $(HCD_TARBALL) || (echo "ERROR: $(HCD_TARBALL) not found in project root (IBM Passport Advantage part M1442EN). See README.md Prerequisites." >&2; exit 1)
	$(COMPOSE) build

up: ## Start the 6-node cluster (build if needed)
	@test -f $(HCD_TARBALL) || (echo "ERROR: $(HCD_TARBALL) not found in project root (IBM Passport Advantage part M1442EN). See README.md Prerequisites." >&2; exit 1)
	$(COMPOSE) up -d --build

gen-certs: ## Generate PEM CA + node/client certs for the secure profile (./certs)
	./scripts/gen-certs.sh

up-secure: ## Start the cluster with the HCD 2.0 secure profile (auth + CIDR + certs)
	@test -f $(HCD_TARBALL) || (echo "ERROR: $(HCD_TARBALL) not found in project root (IBM Passport Advantage part M1442EN). See README.md Prerequisites." >&2; exit 1)
	@test -d certs || (echo "ERROR: ./certs not found — run 'make gen-certs' first." >&2; exit 1)
	$(COMPOSE_SECURE) up -d --build

secure-bootstrap: ## Replicate system_auth/traces/distributed across DCs after up-secure (run once cluster is UN)
	@echo "Setting multi-DC system keyspaces to NetworkTopologyStrategy..."
	docker exec hcd-node1 cqlsh -e "ALTER KEYSPACE system_auth WITH replication = {'class':'NetworkTopologyStrategy','dc1':3,'dc2':3};"
	@# system_traces / system_distributed ship as SimpleStrategy, which has no DC awareness — so any
	@# LOCAL_QUORUM read against them (e.g. cqlsh TRACING ON, used by demo Module 2) fails on a
	@# multi-DC cluster with "Unable to complete the operation against any hosts". Make them NTS too.
	docker exec hcd-node1 cqlsh -e "ALTER KEYSPACE system_traces WITH replication = {'class':'NetworkTopologyStrategy','dc1':2,'dc2':2};"
	docker exec hcd-node1 cqlsh -e "ALTER KEYSPACE system_distributed WITH replication = {'class':'NetworkTopologyStrategy','dc1':2,'dc2':2};"
	@for n in 1 2 3 4 5 6; do docker exec hcd-node$$n nodetool repair -- system_auth system_traces system_distributed || true; done
	@echo "Done. system_auth/traces/distributed are DC-replicated; auth + LOCAL_QUORUM tracing resilient."

down-secure: ## Stop the secure-profile cluster (preserve volumes)
	$(COMPOSE_SECURE) down

down: ## Stop the cluster (preserve volumes)
	$(COMPOSE) down

restart: down up ## Restart the cluster

destroy: ## Stop the cluster and delete all data volumes
	$(COMPOSE) down -v

status: ## Show nodetool status
	@docker exec hcd-node1 nodetool status

logs: ## Tail cluster logs
	$(COMPOSE) logs -f

cqlsh: ## Open CQL shell on node1
	docker exec -it hcd-node1 cqlsh

demo: ## Run the interactive entropy demo
	./scripts/demo-entropy.sh

demo-dry: ## Run the demo in dry-run mode (no cluster needed)
	./scripts/demo-entropy.sh --dry-run --no-pause

demo-full: ## Build cluster + run full automated demo
	./scripts/execute-full-demo.sh

demo-score: ## Validate all 94 modules (dry-run scorecard)
	./scripts/demo-entropy.sh --score

demo-2.0: ## Run the HCD 2.0 innovation modules (Part 11: 85-93)
	@for m in $$(seq 85 93); do ./scripts/demo-entropy.sh $$m; done

demo-ransomware: ## Run DORA ransomware demo (modules 73-79)
	@for m in 73 74 75 76 77 78 79; do ./scripts/demo-entropy.sh $$m; done

demo-part: ## Run a demo part (1-11): make demo-part P=3
	@case "$(P)" in \
		1) for m in $$(seq 0 13);  do ./scripts/demo-entropy.sh $$m; done ;; \
		2) for m in $$(seq 14 25); do ./scripts/demo-entropy.sh $$m; done ;; \
		3) for m in $$(seq 26 38); do ./scripts/demo-entropy.sh $$m; done ;; \
		4) for m in $$(seq 39 43); do ./scripts/demo-entropy.sh $$m; done ;; \
		5) for m in $$(seq 44 48); do ./scripts/demo-entropy.sh $$m; done ;; \
		6) for m in $$(seq 49 54); do ./scripts/demo-entropy.sh $$m; done ;; \
		7) for m in $$(seq 55 62); do ./scripts/demo-entropy.sh $$m; done ;; \
		8) for m in $$(seq 63 72); do ./scripts/demo-entropy.sh $$m; done ;; \
		9) for m in $$(seq 73 79); do ./scripts/demo-entropy.sh $$m; done ;; \
		10) for m in $$(seq 80 84); do ./scripts/demo-entropy.sh $$m; done ;; \
		11) for m in $$(seq 85 93); do ./scripts/demo-entropy.sh $$m; done ;; \
		*) echo "Usage: make demo-part P=N (where N is 1-11)" >&2; \
		   echo "  1=Foundations   2=Failures    3=Operations  4=Performance  5=Drivers" >&2; \
		   echo "  6=Transactions  7=Enterprise  8=Deep-Dives  9=DORA        10=Production" >&2; \
		   echo "  11=HCD 2.0 Innovations (DDM, CIDR, DC-RBAC, mTLS, Paxos v2, auth, PEM SSL, audit)" >&2; exit 1 ;; \
	esac

minio: ## Start MinIO WORM storage (S3-compatible)
	$(COMPOSE) --profile ransomware up -d minio

minio-down: ## Stop MinIO
	$(COMPOSE) --profile ransomware down

api: ## Start Data API (http://localhost:8181)
	$(COMPOSE) --profile api up -d

api-down: ## Stop Data API
	$(COMPOSE) --profile api down

monitoring: ## Start Prometheus + Grafana (http://localhost:3000)
	$(COMPOSE) --profile monitoring up -d

monitoring-down: ## Stop Prometheus + Grafana
	$(COMPOSE) --profile monitoring down

check-prereqs: ## Verify all prerequisites are installed
	@echo "Checking prerequisites..."
	@command -v docker >/dev/null 2>&1 && echo "  [OK] docker $$(docker --version | cut -d' ' -f3 | tr -d ',')" || echo "  [MISSING] docker"
	@docker compose version >/dev/null 2>&1 && echo "  [OK] docker compose $$(docker compose version --short 2>/dev/null || echo 'v2')" || \
		(command -v docker-compose >/dev/null 2>&1 && echo "  [OK] docker-compose (v1)" || echo "  [MISSING] docker compose")
	@command -v python3 >/dev/null 2>&1 && echo "  [OK] python3 $$(python3 --version | cut -d' ' -f2)" || echo "  [MISSING] python3"
	@command -v conda >/dev/null 2>&1 && echo "  [OK] conda $$(conda --version | cut -d' ' -f2)" || echo "  [OPTIONAL] conda (for 'make env' hybrid dev env)"
	@conda env list 2>/dev/null | grep -qE "^$(ENV_NAME)\b" && echo "  [OK] conda env '$(ENV_NAME)' exists" || echo "  [INFO] conda env '$(ENV_NAME)' not created — run 'make env'"
	@python3 -c "import pytest" 2>/dev/null && echo "  [OK] pytest" || echo "  [MISSING] pytest (run 'make env' or pip install pytest)"
	@python3 -c "import yaml" 2>/dev/null && echo "  [OK] pyyaml" || echo "  [MISSING] pyyaml (run 'make env' or pip install pyyaml)"
	@command -v shellcheck >/dev/null 2>&1 && echo "  [OK] shellcheck" || echo "  [OPTIONAL] shellcheck (for linting)"
	@command -v ruff >/dev/null 2>&1 && echo "  [OK] ruff" || echo "  [OPTIONAL] ruff (for Python linting)"
	@test -f $(HCD_TARBALL) && echo "  [OK] $(HCD_TARBALL)" || echo "  [MISSING] $(HCD_TARBALL) (IBM Passport Advantage part M1442EN; place in project root)"
	@# Colima runtime check (MBP M3 Pro): a 6-node cluster needs the VM sized up.
	@# Compose limits sum to ~6 GB RAM + 3 CPU; default colima VM (2 CPU/2 GB) is too small.
	@if command -v colima >/dev/null 2>&1; then \
		if colima status >/dev/null 2>&1; then \
			cpu=$$(colima status 2>&1 | grep -iE 'cpu' | grep -oE '[0-9]+' | head -1); \
			mem=$$(colima status 2>&1 | grep -iE 'mem|memory' | grep -oE '[0-9]+' | head -1); \
			echo "  [OK] colima running (cpu=$${cpu:-?} mem=$${mem:-?}GiB) — recommend >=4 CPU / >=8 GiB for 6 nodes"; \
		else \
			echo "  [INFO] colima installed but not running — start with: colima start --cpu 4 --memory 8 --disk 60"; \
		fi; \
	else \
		echo "  [INFO] colima not found (using Docker Desktop?) — either runtime is fine"; \
	fi

verify-release: ## Assert the running cluster is HCD 2.0 (Cassandra 5.0 base)
	@echo "Verifying HCD release ($(HCD_VERSION), Cassandra base $(EXPECTED_CASSANDRA_MAJOR))..."
	@rv=$$(docker exec hcd-node1 cqlsh -e "SELECT release_version FROM system.local" 2>/dev/null | sed -n '4p' | tr -d ' '); \
	echo "  release_version reported: $${rv:-<none>}"; \
	case "$$rv" in \
		$(EXPECTED_CASSANDRA_MAJOR)*) echo "  [OK] Cassandra $(EXPECTED_CASSANDRA_MAJOR).x base confirmed (HCD 2.0)";; \
		"") echo "  [FAIL] No release_version — is the cluster up? (make up && make wait)" >&2; exit 1;; \
		*) echo "  [FAIL] Expected $(EXPECTED_CASSANDRA_MAJOR).x, got '$$rv' — wrong HCD binary?" >&2; exit 1;; \
	esac
	@jv=$$(docker exec hcd-node1 java -version 2>&1 | head -1); echo "  runtime: $$jv"; \
	echo "$$jv" | grep -qE '"17' && echo "  [OK] Java 17 runtime confirmed" || echo "  [WARN] Expected Java 17 — got: $$jv"

env: ## Create/update the conda env (Python 3.11 + uv) and uv-install dev tooling
	@command -v conda >/dev/null 2>&1 || { echo "ERROR: conda not on PATH. Activate your conda shell first." >&2; exit 1; }
	conda env update -n $(ENV_NAME) -f environment.yml --prune
	conda run --no-capture-output -n $(ENV_NAME) uv pip install -r requirements-dev.txt
	@conda run --no-capture-output -n $(ENV_NAME) uv pip install -r requirements-driver.txt \
		|| echo "  [note] cassandra-driver not installed (no wheel?) — driver tests will skip."
	@echo "Done. Activate with: conda activate $(ENV_NAME)   then: make test / make lint"

test-env: ## Run the test suite inside the conda env (no activation needed)
	conda run --no-capture-output -n $(ENV_NAME) pytest tests/ -q

test: ## Run all pytest tests (dry-run, no cluster needed)
	pytest tests/ -v

test-integration: ## Run integration tests against live cluster (requires make up && make wait)
	pytest tests/test_integration.py -v --run-integration

lint: ## Lint shell scripts (shellcheck) and Python (ruff)
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; else echo "shellcheck not installed, skipping"; fi
	@if command -v ruff >/dev/null 2>&1; then ruff check scripts/*.py tests/*.py; else echo "ruff not installed, skipping"; fi

validate: ## Validate docker-compose.yml syntax
	@$(COMPOSE) config >/dev/null && echo "docker-compose.yml is valid"

pin-digests: ## Pin Dockerfile base images by SHA256 digest for reproducibility
	@echo "Pulling images and extracting digests..."
	@BASE_DIGEST=$$(docker pull -q eclipse-temurin:17-jre >/dev/null && docker inspect --format='{{index .RepoDigests 0}}' eclipse-temurin:17-jre | sed 's/.*@//'); \
	UV_DIGEST=$$(docker pull -q ghcr.io/astral-sh/uv:0.5.14 >/dev/null && docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:0.5.14 | sed 's/.*@//'); \
	if [ -n "$$BASE_DIGEST" ]; then \
		sed -i.bak "s|FROM eclipse-temurin:17-jre.*|FROM eclipse-temurin:17-jre@$$BASE_DIGEST|" Dockerfile && rm -f Dockerfile.bak; \
		echo "  [OK] Base image pinned: $$BASE_DIGEST"; \
	else echo "  [SKIP] Could not resolve eclipse-temurin:17-jre digest"; fi; \
	if [ -n "$$UV_DIGEST" ]; then \
		sed -i.bak "s|COPY --from=ghcr.io/astral-sh/uv:0.5.14|COPY --from=ghcr.io/astral-sh/uv:0.5.14@$$UV_DIGEST|" Dockerfile && rm -f Dockerfile.bak; \
		echo "  [OK] uv image pinned: $$UV_DIGEST"; \
	else echo "  [SKIP] Could not resolve ghcr.io/astral-sh/uv:0.5.14 digest"; fi

wait: ## Wait until all nodes are UN (Up/Normal)
	@echo "Waiting for $(EXPECTED_NODES) nodes to reach UN status..."
	@count=0; \
	while [ "$$(docker exec hcd-node1 nodetool status 2>/dev/null | grep -c '^UN')" -ne "$(EXPECTED_NODES)" ]; do \
		printf "."; sleep 10; count=$$((count + 1)); \
		if [ $$count -ge 30 ]; then echo ""; echo "Timeout."; exit 1; fi; \
	done; echo ""; echo "All $(EXPECTED_NODES) nodes are Up/Normal."

clean: ## Remove dangling images and build cache
	docker image prune -f
	docker builder prune -f

# ─── Adversarial audit arena ────────────────────────────────────────────────────
audit: ## Run the deterministic audit (Oracle + invariants + manifest) and render courtroom.html
	python3 audit_arena/bin/arena.py repomap
	python3 audit_arena/bin/arena.py oracle 1
	python3 audit_arena/bin/arena.py invariants 1
	python3 audit_arena/bin/arena.py manifest 1
	python3 audit_arena/bin/arena.py render
	@echo "Open: audit_arena/courtroom.html"
	python3 audit_arena/bin/arena.py gate   # exit 1 on any FAILing oracle check / invariant (CI blocks)

audit-tribunal: ## Show how to run the LLM tribunal rounds (Mode A subagents / Mode B external)
	@echo "Tribunal (per round R):"
	@echo "  1. python3 audit_arena/bin/arena.py repomap"
	@echo "  2. Prosecutor (this Claude session / subagents) -> audit_arena/state/findings_rR.json"
	@echo "  3. python3 audit_arena/bin/arena.py excerpts audit_arena/state/findings_rR.json > /tmp/exc.md"
	@echo "  4. Defender:  make audit-mode-b ROLE=defender ROUND=R   (Mode B, needs ZAI_API_KEY)  OR subagent (Mode A)"
	@echo "  5. python3 audit_arena/bin/arena.py oracle R && judge-brief R"
	@echo "  6. Judge:     make audit-mode-b ROLE=judge ROUND=R      (Mode B, needs GEMINI_API_KEY) OR subagent (Mode A)"
	@echo "     (Mode B is opt-in: without ARENA_MODE_B=1 it refuses to call out and you use Mode A.)"
	@echo "  7. python3 audit_arena/bin/arena.py converge && render"

audit-mode-b: ## Drive a tribunal role with an EXTERNAL family (egress-gated): make audit-mode-b ROLE=defender ROUND=2
	ARENA_MODE_B=1 python3 audit_arena/bin/arena.py mode-b $(ROLE) $(ROUND)

verify-fix: ## Verify a fix patch in an ISOLATED worktree (never touches your tree): make verify-fix FIX=p.diff [BASE=b.diff]
	python3 audit_arena/bin/arena.py verify-fix $(FIX) $(BASE)

audit-harden: ## Self-harden the prosecutor charter from confirmed charter_gap lessons (deliberate)
	python3 audit_arena/bin/arena.py harden
	@echo "Review the AUTO-HARDENED block in audit_arena/prompts/_preamble.md (git diff) and commit it."

audit-install-hook: ## Install the deterministic pre-merge gate (git pre-push)
	@chmod +x audit_arena/bin/pre-merge-hook.sh
	@hookdir="$$(git rev-parse --git-path hooks)"; \
	printf '#!/usr/bin/env bash\nexec "$$(git rev-parse --show-toplevel)/audit_arena/bin/pre-merge-hook.sh" "$$@"\n' > "$$hookdir/pre-push"; \
	chmod +x "$$hookdir/pre-push"; \
	echo "Installed pre-push gate -> $$hookdir/pre-push (bypass once: git push --no-verify)"
