# Development Guidelines

## Project Structure

```
├── config/                 # Configuration templates
│   └── cassandra.yaml.template
├── scripts/               # Automation scripts
│   ├── docker-entrypoint.sh
│   ├── generate-topology.py
│   ├── demo-entropy.sh
│   ├── driver-demo.py
│   └── execute-full-demo.sh
├── tests/                 # Pytest test suites
│   ├── test_demo_entropy.py
│   ├── test_topology.py
│   └── test_scripts.py
├── .github/workflows/     # CI/CD
│   └── ci.yml
├── .env.example           # Environment variable template
├── docker-compose.yml     # Multi-node cluster definition (768M per node)
├── Dockerfile             # Container image definition
├── Makefile               # Developer shortcuts (make up/down/demo/test)
├── DEMO_ENTROPY.md        # Didactic demo documentation
├── CLAUDE.md              # Claude Code guidance
└── README.md              # Project documentation
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

# Topology generator tests
pytest tests/test_topology.py -v

# Run a single test
pytest tests/test_demo_entropy.py::test_dry_run_execution -v
```

Tests use `--dry-run` mode so they don't require a running cluster.

## Demos & Use Cases

- **Entropy & Consistency**: See `DEMO_ENTROPY.md` for a walkthrough of multi-DC replication and repair scenarios.

## Running the Demo

The Entropy & Consistency demo is an interactive, didactic script (54 modules, 0-53) that explains HCD internals through hands-on scenarios.

**Review Status:** Grade A (Jonathan Ellis).
*Focus areas: Entropy resolution, SAI composability, mutation-based write path, multi-DC failover (Module 23), CDC, audit logging, and guardrails.*

```bash
# Full interactive demo
./scripts/demo-entropy.sh

# Run specific module (0-53)
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
2. Update the validation regex: `^([0-9]|[1-4][0-9]|5[0-3])$` (adjust upper bound)
3. Update the main loop range: `for i in {0..N}`
4. Add the module to `DEMO_ENTROPY.md` (overview list + body section)
5. Update `tests/test_demo_entropy.py`: adjust `range(N+1)` in parametrize and full-run test
6. Run `pytest tests/test_demo_entropy.py -v` to verify
