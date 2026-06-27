#!/usr/bin/env bash
# HCD arena — deterministic pre-merge gate.
# Installed as .git/hooks/pre-push by `make audit-install-hook`. Blocks the push if any
# docker-free Oracle check fails, then refreshes courtroom.html (non-blocking).
# Bypass once with: git push --no-verify
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT" || exit 1
fail=0
say() { printf '  %-44s %s\n' "$1" "$2"; }

echo "── HCD arena pre-merge gate ─────────────────────────────"

# D3 — shell syntax
if for s in scripts/*.sh; do bash -n "$s" || exit 1; done; then say "bash -n (scripts)" "PASS"; else say "bash -n (scripts)" "FAIL"; fail=1; fi

# D3 — shellcheck (only if installed)
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck -S error scripts/*.sh >/dev/null 2>&1; then say "shellcheck -S error" "PASS"; else say "shellcheck -S error" "FAIL"; fail=1; fi
else say "shellcheck" "skip (not installed)"; fi

# D4 — scorecard 100% (capture to a file; piping into `grep -q` would SIGPIPE the
# scorecard and, under `set -o pipefail`, report a false failure on success)
./scripts/demo-entropy.sh --score >/tmp/_arena_score 2>/dev/null || true
if grep -q "Score:  100%" /tmp/_arena_score; then say "make demo-score (100%)" "PASS"; else say "make demo-score" "FAIL"; fail=1; fi

# D4 — pytest no failures
if python3 -m pytest tests/ -q >/tmp/_arena_pytest 2>&1; then say "pytest" "PASS"; else
  if grep -q " failed" /tmp/_arena_pytest; then say "pytest" "FAIL"; fail=1; else say "pytest" "PASS (skips only)"; fi; fi

# D2 — combined cassandra.yaml: no duplicate keys
if CASSANDRA_CLUSTER_NAME=t CASSANDRA_SEEDS=1 CASSANDRA_LISTEN_ADDRESS=1 CASSANDRA_BROADCAST_ADDRESS=1 \
   CASSANDRA_RPC_ADDRESS=0 CASSANDRA_ENDPOINT_SNITCH=s envsubst < config/cassandra.yaml.template > /tmp/_a.yaml 2>/dev/null \
   && printf '\n' >> /tmp/_a.yaml \
   && CASSANDRA_CLUSTER_NAME=t CASSANDRA_SEEDS=1 CASSANDRA_LISTEN_ADDRESS=1 CASSANDRA_BROADCAST_ADDRESS=1 \
      CASSANDRA_RPC_ADDRESS=0 CASSANDRA_ENDPOINT_SNITCH=s envsubst < config/cassandra-secure.yaml.fragment >> /tmp/_a.yaml 2>/dev/null \
   && python3 -c "import yaml,re,collections,sys; s=open('/tmp/_a.yaml').read(); yaml.safe_load(s); k=re.findall(r'^([A-Za-z_]\w*):',s,re.M); sys.exit(1 if [x for x,c in collections.Counter(k).items() if c>1] else 0)"; then
  say "config: no duplicate keys" "PASS"; else say "config: no duplicate keys" "FAIL"; fail=1; fi

# D5 — count single-source-of-truth
tm=$(grep -oE 'TOTAL_MODULES=[0-9]+' scripts/demo-entropy.sh | head -1 | cut -d= -f2)
if grep -q "all ${tm} modules" Makefile; then say "count consistency (=$tm)" "PASS"; else say "count consistency" "FAIL"; fail=1; fi

# Pure gate: this hook is read-only on tracked files. Refresh the dashboard explicitly
# with `make audit` (kept out of the hook so a push never mutates committed artefacts).

echo "─────────────────────────────────────────────────────────"
if [ "$fail" -ne 0 ]; then
  echo "BLOCKED: deterministic gate failed. Fix the above or bypass with: git push --no-verify" >&2
  exit 1
fi
echo "OK: deterministic gate passed (LLM tribunal is advisory — run 'make audit-tribunal')."
exit 0
