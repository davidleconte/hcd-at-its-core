# Prosecutor — Round 3 (CONVERGENCE)

Near-dry round. Three passes have hardened the obvious surfaces; round 3 swept the
least-audited remainder (Python helpers, entrypoint edge cases, CI/Makefile, conda env,
Data API / compose) and surfaced exactly one real, executably-checkable defect.

## D4 — Tests / CI (1)

- **[MED][D4] CI `test` job scorecard step is a check that always passes** —
  `scripts/demo-entropy.sh:10537`. The `--score` block ends with an unconditional
  `exit 0`; `SCORE_PCT<100` only flips a printed message, never the exit status. The CI
  `test` job runs the scorecard as a bare step (`ci.yml:41`), which fails the job only on
  a non-zero exit — so a module regression to FAIL leaves that named step green. The arena
  gate compensates by grepping the literal `Score:  100%` text (`pre-merge-hook.sh:33-34`,
  `arena.py:296,551`) *because* the exit code is uninformative; the `test` job does not.
  Invariant HCD-I6. Mitigated (not eliminated) by the redundant `arena` job which does block
  on <100% — hence MED, not HIGH. Oracle: exit code must agree with the `Score:  100%` text.

## Refuted (searched, no defect — recorded so the next round doesn't re-walk them)

- `driver-demo.py` retry policy `AggressiveRetryPolicy`: `RETRY_NEXT_HOST` is a valid return
  for `on_read_timeout`/`on_write_timeout`/`on_unavailable`, and `retry_num` starts at 0, so
  `retry_num < 3` yields exactly 3 retries then RETHROW — semantically correct (verified vs
  DataStax python-driver policies API).
- `--local-dc` argument: defined on the top-level parser, consumed by all four subcommands
  via `args.local_dc` — not silently ignored.
- `generate-topology.py` seed math: single-DC second seed `int(nodes/2)+2` and multi-DC
  `dcs[0][1]+2` both land on a real node IP (node IPs are `i+1`); clamp prevents overshoot.
  No off-by-one produces an invalid/duplicate seed IP. `ip_to_dc` (`<=4 → dc1`) is correct
  for the shipped default 3+3 topology it is scoped to.
- `environment.yml` / `requirements-*.txt`: `pytest~=9.1` (exists; needs Py≥3.10), `ruff~=0.15`,
  `pyyaml~=6.0`, `cassandra-driver==3.29.2` — none contradict the container's Python 3.11.
- Data API healthcheck (`docker-compose.yml:285`): `/stargate/health` is the correct Quarkus
  endpoint; the `stargateio/data-api` UBI9-openjdk base ships `curl` via `curl-minimal` (could
  not establish curl-absence with confidence → not filed, burden-on-artefact).
- Entrypoint no-credential `cqlsh` seed-wait/healthcheck under PasswordAuthenticator is already
  resolved by the baked `cqlshrc` (Dockerfile:104-112) — a prior-round fix, not re-filed.

## Verdict

**ROUND 3 ≈ DRY (converged).** One MED finding (a decorative CI check), and it is already
backstopped by the redundant arena gate — no BLOCKER/HIGH defect survived. Surfaces searched:
`generate-topology.py`, `driver-demo.py`, `docker-entrypoint.sh`, `ci.yml`, `Makefile`,
`environment.yml`/`requirements-*.txt`, `docker-compose.yml` (Data API/MinIO/Stargate +
healthchecks/limits), and the test suite (`test_topology*`, `test_driver_demo`, `test_scripts`,
`test_secure_profile`) for non-discriminating assertions. The thrice-hardened code holds.
