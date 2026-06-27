ROLE: ORACLE / EXECUTIONER (deterministic, not an LLM). The HCD-specific upgrade over a pure
debate tribunal: HCD claims have a runnable ground truth, so findings are EXECUTABLY adjudicated.

`bin/arena.py oracle [ROUND]` runs the standing check battery and writes
`state/oracle_r{ROUND}.json`. Each check has a dimension and a PASS/FAIL with detail:

  D2  combined cassandra.yaml (template + secure fragment) parses with NO duplicate top-level keys
  D2  `docker compose -f docker-compose.yml -f docker-compose.secure.yml config` merges (if docker)
  D3  `bash -n` on every scripts/*.sh
  D3  `shellcheck -S error scripts/*.sh`
  D4  `./scripts/demo-entropy.sh --score` == 100% (94/94)
  D4  `python3 -m pytest tests/ -q` with no failures
  D5  count single-source-of-truth: TOTAL_MODULES matches the Makefile "all N modules" string

Per-finding adjudication: when a Prosecutor finding carries an `oracle_cmd` (a shell that returns 0
iff the artefact is CORRECT), the Oracle runs it and stamps the finding PASS (artefact correct →
finding is a false positive) or FAIL (artefact wrong → finding confirmed). For findings that need a
LIVE cluster (e.g. "this CQL errors on Cassandra 5.0", "the secure cluster won't form"), the Oracle
runs them only when a cluster is up (`make up` / `make up-secure` + `make wait`); otherwise it marks
them ORACLE-DEFERRED and they stay weighed against the artefact per the rules of evidence.

The Oracle is decisive: it overrides both Prosecutor and Defender for any finding it can run.
Live-cluster checks to add when the HCD 2.0 tarball is staged:
  - each Part 11 CQL statement executed via `cqlsh -e` → expect success (DDM, CIDR, ADD IDENTITY, …)
  - `make up-secure && make wait` → all 6 nodes UN (proves the secure cluster forms)
  - `make verify-release` → Cassandra 5.0.x + Java 17
