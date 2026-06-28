# Development Guidelines

## Project Structure

```
├── config/                 # Configuration templates
│   ├── cassandra.yaml.template
│   ├── cassandra-secure.yaml.fragment  # appended in the secure profile (auth/CIDR)
│   ├── prometheus.yml      # Prometheus scrape config for JMX metrics
│   ├── alerts.yml          # Prometheus alerting rules
│   ├── jmx-exporter.yml   # JMX-to-Prometheus metric mapping
│   └── grafana/            # Grafana provisioning (datasource + dashboard)
├── scripts/               # Automation scripts
│   ├── docker-entrypoint.sh
│   ├── generate-topology.py
│   ├── demo-entropy.sh
│   ├── driver-demo.py
│   ├── gen-certs.sh        # PEM CA + node/client certs for the secure profile
│   └── execute-full-demo.sh
├── tests/                 # Pytest test suites
│   ├── test_demo_entropy.py · test_topology.py · test_topology_unit.py
│   ├── test_scripts.py · test_driver_demo.py · test_integration.py
│   ├── test_secure_profile.py  # gen-certs / fragment / overlay / entrypoint / grafana
│   └── test_arena.py           # audit-arena invariants / manifest / harden / isolation
├── audit_arena/           # Adversarial audit engine (Prosecutor/Defender/Judge/Oracle)
│   ├── bin/arena.py       # plumbing: oracle, invariants, manifest, harden, verify-fix, render
│   ├── prompts/           # role charters (_preamble, prosecutor, defender, judge, proposer, redteam_fix)
│   ├── state/             # seed findings/verdicts/grades (generated outputs gitignored)
│   └── DESIGN_*.md        # design docs for each pass
├── .github/workflows/ci.yml    # CI: lint · pytest · docker-validate · audit-arena gate
├── environment.yml             # conda + uv dev env (Python 3.11)
├── requirements-dev.txt        # uv-managed dev tooling; requirements-driver.txt (optional driver)
├── docker-compose.yml          # Multi-node cluster definition
├── docker-compose.secure.yml   # secure-profile overlay (HCD_SECURITY_PROFILE + certs mount)
├── Dockerfile                  # Container image (eclipse-temurin:17-jre, HCD 2.0)
├── Makefile                    # Developer shortcuts (up/down/demo/test/audit/env/secure)
├── DEMO_ENTROPY.md             # Didactic demo documentation (94 modules)
├── RANSOMWARE_DORA_DESIGN.md   # DORA ransomware resilience design doc
├── docs/HCD_2.0_UPGRADE_DESIGN.md  # the HCD 1.2.3 -> 2.0.6 upgrade design
├── CLAUDE.md · AGENTS.md · README.md   # guidance / dev guidelines / project docs
```

## Code Style

### Shell Scripts
- Use `#!/bin/bash` shebang
- Ensure scripts are executable (`chmod +x scripts/*.sh scripts/*.py`)
- Always use `set -e` for error handling
- Quote all variable expansions: `"${VAR}"`
- Use lowercase for local variables, UPPERCASE for environment variables

### Docker
- Use specific base image tags, not `latest`
- Minimize layers by combining RUN commands
- Clean up package manager caches in the same layer
- Run as non-root user when possible

### YAML
- 2-space indentation
- Quote strings containing special characters
- Use anchors to reduce duplication

## Testing

```bash
# Run all tests
pytest tests/

# Demo script tests (dry-run mode, no cluster needed)
pytest tests/test_demo_entropy.py -v

# Topology generator tests (integration — runs script as subprocess)
pytest tests/test_topology.py -v

# Topology unit tests (imports generate_topology() directly)
pytest tests/test_topology_unit.py -v

# Script syntax and helper tests
pytest tests/test_scripts.py -v

# Run a single test
pytest tests/test_demo_entropy.py::test_dry_run_execution -v
```

Tests use `--dry-run` mode so they don't require a running cluster.

## Demos & Use Cases

- **Entropy & Consistency**: See `DEMO_ENTROPY.md` for a walkthrough of multi-DC replication and repair scenarios.

## Running the Demo

The Entropy & Consistency demo is an interactive, didactic script (94 modules, 0-93) that explains HCD internals through hands-on scenarios, including a DORA ransomware resilience suite (modules 73-79), production essentials (modules 80-84) with MinIO WORM backups, and a Part 11 HCD 2.0 innovations suite (modules 85-93: DDM, CIDR, DC-RBAC, mTLS, Paxos v2, auth hardening, PEM SSL, audit 2.0, Java 17 — modules 86-92 need `make up-secure`).

*Focus areas: Entropy resolution, SAI composability, mutation-based write path, multi-DC failover (Module 23), CDC, audit logging, and guardrails.*

```bash
# Full interactive demo
./scripts/demo-entropy.sh

# Run specific module (0-93)
./scripts/demo-entropy.sh 3

# Non-interactive mode (no pauses)
./scripts/demo-entropy.sh --no-pause

# Dry-run mode (prints commands, no execution)
./scripts/demo-entropy.sh --dry-run
```

## Adding a New Module

To add Module N to `demo-entropy.sh`:

1. Add a new case in the `run_module()` function:
   ```bash
   N)
       header N "Module Title"
       echo "Introductory explanation..."
       # ASCII diagram if appropriate
       lookfor "What the user should observe"
       log_cmd "docker exec hcd-node1 cqlsh -e \"YOUR CQL HERE\""
       takeaway "Key learning point"
       ;;
   ```
2. Update `TOTAL_MODULES` and add a `PART_NAMES` entry in the script. The run loop and scorecard derive from `TOTAL_MODULES` (`seq 0 $((TOTAL_MODULES - 1))`) — there is no separate `{0..N}` loop to edit.
3. Update the input-validation regex in the script (it is hardcoded, not derived — adjust the upper bound to include N).
4. Add the module to `DEMO_ENTROPY.md` (Part 11 overview table + body chapter + Appendix C).
5. Update `tests/test_demo_entropy.py`: bump `range(N+1)` in the parametrize and full-run header checks, the boundary tests, the scorecard count, and add a `MODULE_CONTENT_EXPECTATIONS` row with a module-*specific* keyword.
6. Update the count strings (Makefile/README/CLAUDE/AGENTS/DEMO_ENTROPY) and run `pytest tests/test_demo_entropy.py -v` + `./scripts/demo-entropy.sh --score` to verify.
