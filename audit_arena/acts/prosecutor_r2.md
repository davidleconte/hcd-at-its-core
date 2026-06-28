# Prosecutor — Round 2 plaidoirie

**Round verdict: mostly DRY, one real HIGH.** The twice-audited surfaces (Part 11 CQL, compose
merge, secure-profile wiring, module 83 math functions, version facts, cert/secret handling)
held under deeper attack — I confirmed module 83's `abs/exp/log/log10/round` are valid C5.0
functions, the legacy `_in_ms` template keys still boot on 5.0 (deprecated, not removed), and
no key material is tracked (I5 holds). The one genuinely new defect is in the **monitoring
config**, which neither prior pass examined: a casing mismatch silently kills 4 of 8 Prometheus
alerts. The repo's own Grafana dashboard is the oracle that proves it.

Worst-first, grouped by dimension.

## D2 — Build & runtime wiring
- **[HIGH][D2][HCD-I4]** 4 of 8 Prometheus alerts never fire: `jmx-exporter.yml` sets
  `lowercaseOutputName: true`, but `alerts.yml` references CamelCase metric names
  (`cassandra_dropped_Dropped`, `cassandra_compaction_PendingTasks`,
  `cassandra_client_request_Latency_99thPercentile`) the exporter never emits. The Grafana
  dashboard queries the correctly-lowercased twins, proving the names are wrong only in alerts.
  — config/alerts.yml:29 (also :39, :69, :79; vs config/jmx-exporter.yml:4 and
  config/grafana/dashboards/hcd-cluster.json:24,168,185)
- **[LOW][D2][HCD-I5]** `.gitignore` line `[hcd-node*]` is a bracket glob matching a single
  char, not the `hcd-node*` data dirs; `git check-ignore hcd-node1` → not ignored. Dead rule.
  — .gitignore:40

## D4 — Tests
- **[MED][D4][HCD-I6]** `test_prometheus_alerts_valid_yaml` asserts only YAML shape (groups,
  >=5 rules, required keys) and never checks that `expr` metric names match the exporter output
  — a weak assertion that stays green while the 4 alerts above are dead. The consistency check
  is a pure offline string comparison, so the weak assertion isn't forced by the no-cluster
  constraint. — tests/test_scripts.py:104

## D5 — Documentation / single-source consistency
- **[LOW][D5][HCD-I4]** Hints alert (`cassandra_hints_TotalHintsInProgress`, alerts.yml:59)
  and hints dashboard panel (`cassandra_hints_hints_created`, hcd-cluster.json:219) name two
  different (and, for the alert, non-existent/mis-cased) series. — config/alerts.yml:59
- **[LOW][D5][HCD-I4]** MinIO defined twice with different IP + image tag: demo uses
  172.28.0.40 / RELEASE.2024-11-07, compose uses 172.28.0.10 / RELEASE.2024-03-30. Mutually
  exclusive paths, so no collision, but unsourced drift. — scripts/demo-entropy.sh:436 vs
  docker-compose.yml:183,188

## Charter gap
- R2-01 adds a defect class not in the tier-1 list: **PromQL/dashboard metric names that don't
  match the jmx-exporter's lowercased output**. Lesson folded for `arena.py harden`.
