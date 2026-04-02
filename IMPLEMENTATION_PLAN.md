Good. So the Docker network name at runtime will be `brokk_hcd-cluster`. Now I have all the context needed. Let me produce the complete implementation plan.

---

# Implementation Plan: HCD Demo Script Enhancement (Modules 0-27)

## Summary of Changes

This plan covers 10 categories of work across 4 files, expanding the demo from 23 modules (0-22) to 28 modules (0-27). The changes break down into:
- 5 new modules (23-27)
- 8 enhanced existing modules (2, 4, 5, 7, 11, 12, 17, 18, 20, 22)
- 1 fixed module (17 - replacing dead iptables code)
- Infrastructure changes (validation regex, loop range, cleanup trap)
- Test and documentation updates

## Phase 0: Infrastructure Changes (Do First)

These changes affect the script skeleton and must land before any module work.

### 0.1 Update Validation Regex (line 51)

Change:
```
^([0-1]?[0-9]|2[0-2])$
```
To:
```
^([0-1]?[0-9]|2[0-7])$
```

And update the error message from `(Valid: 0-22)` to `(Valid: 0-27)`.

### 0.2 Update Main Loop (line 498)

Change `{0..22}` to `{0..27}`.

### 0.3 Update Cleanup Trap (line 9-13)

The current cleanup only restarts nodes 1-4. With modules 23-24 stopping dc1 entirely and module 17 disconnecting networks, the cleanup must be comprehensive:

```bash
cleanup() {
    log_info "Emergency cleanup: ensuring all nodes are started and connected..."
    docker-compose start hcd-node1 hcd-node2 hcd-node3 hcd-node4 hcd-node5 hcd-node6 >/dev/null 2>&1 || true
    docker network connect brokk_hcd-cluster hcd-node2 >/dev/null 2>&1 || true
}
```

Note: `hcd-node5` and `hcd-node6` are added because module 23/24 could leave them in an intermediate state if interrupted. The `docker network connect` line ensures module 17 cleanup. All commands use `|| true` since some will no-op.

### 0.4 Add Helper Function: `wait_for_node_un`

Add below the existing `pause()` function. Many modules need retry loops waiting for nodes to reach UN status. Factor this into a reusable function:

```bash
wait_for_node_un() {
    local target_ip=$1
    local node_label=$2
    local max_retries=${3:-30}
    local sleep_interval=${4:-3}
    if [ "$DRY_RUN" = false ]; then
        local count=0
        until docker exec hcd-node1 nodetool status 2>/dev/null | grep -E "UN\s+${target_ip}" >/dev/null 2>&1; do
            echo -n "."
            sleep "$sleep_interval"
            count=$((count + 1))
            if [ $count -ge $max_retries ]; then
                log_info "Timeout waiting for ${node_label} to reach UN. Continuing..."
                return 1
            fi
        done
        echo ""
    fi
    return 0
}

wait_for_all_un() {
    if [ "$DRY_RUN" = false ]; then
        local max_retries=${1:-40}
        local count=0
        until [ "$(docker exec hcd-node1 nodetool status 2>/dev/null | grep -c '^UN')" -eq 6 ]; do
            echo -n "."
            sleep 5
            count=$((count + 1))
            if [ $count -ge $max_retries ]; then
                log_info "Timeout waiting for all 6 nodes to reach UN. Continuing..."
                return 1
            fi
        done
        echo ""
    fi
    return 0
}
```

This eliminates duplicated retry logic across modules 4, 10, 14, 23, 24. Existing modules 4, 10, 14 should be refactored to use it (optional but recommended).

## Phase 1: Enhance Existing Modules

### 1.1 Enhance Module 2 (Consistency Levels) - Line 85-89

**Append** after the existing two `log_cmd` lines. Do not replace existing content.

```bash
        2)
            header 2 "Consistency Levels"
            log_info "Testing CL=QUORUM behavior..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"TRACING ON; USE rf_prod; CREATE TABLE IF NOT EXISTS logs (id uuid PRIMARY KEY, msg text);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY QUORUM; TRACING ON; INSERT INTO rf_prod.logs (id, msg) VALUES (uuid(), 'test');\""

            # --- NEW: CL Spectrum Demonstration ---
            echo ""
            echo "┌──────────────────────────────────────────────────────────────┐"
            echo "│          Consistency Level Spectrum                          │"
            echo "│                                                              │"
            echo "│  ONE ◄────── LOCAL_QUORUM ────── EACH_QUORUM ──────► ALL    │"
            echo "│  Fast         Balanced           Strict           Slowest    │"
            echo "│  Risky        Recommended        Safe             Fragile    │"
            echo "└──────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Writing at LOCAL_QUORUM with tracing..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; TRACING ON; INSERT INTO rf_prod.logs (id, msg) VALUES (uuid(), 'local_quorum_write');\""
            
            log_info "Writing at EACH_QUORUM with tracing (requires quorum in EVERY DC)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY EACH_QUORUM; TRACING ON; INSERT INTO rf_prod.logs (id, msg) VALUES (uuid(), 'each_quorum_write');\""
            
            log_info "Now let's break EACH_QUORUM: stopping 2 of 3 nodes in dc1..."
            log_cmd "docker-compose stop hcd-node2 hcd-node3"
            
            if [ "$DRY_RUN" = false ]; then
                sleep 10
            fi
            
            log_info "Attempting EACH_QUORUM write (EXPECTED TO FAIL - dc1 has only 1 of 3 nodes)..."
            log_cmd "docker exec hcd-node4 cqlsh -e \"CONSISTENCY EACH_QUORUM; INSERT INTO rf_prod.logs (id, msg) VALUES (uuid(), 'should_fail');\" || echo 'EXPECTED: EACH_QUORUM write failed - cannot achieve quorum in dc1'"
            
            log_info "But LOCAL_QUORUM from dc2 STILL WORKS (dc2 has all 3 nodes)..."
            log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.logs LIMIT 3;\""
            
            log_info "Restarting dc1 nodes..."
            log_cmd "docker-compose start hcd-node2 hcd-node3"
            if [ "$DRY_RUN" = false ]; then
                wait_for_node_un "172.28.0.3" "Node 2"
                wait_for_node_un "172.28.0.4" "Node 3"
            fi
            
            echo "Takeaway: LOCAL_QUORUM is the sweet spot for multi-DC deployments."
            echo "It avoids WAN latency while maintaining strong consistency within a DC."
            echo "EACH_QUORUM adds cross-DC guarantee but becomes unavailable if any DC loses quorum."
            ;;
```

**Dry-run considerations**: The EACH_QUORUM failure command uses `|| echo` so it won't break `set -e`. The `docker-compose stop/start` calls go through `log_cmd` so they print but don't execute in dry-run. The `wait_for_node_un` checks `DRY_RUN` internally. The `sleep 10` is gated behind `DRY_RUN` check.

**Wait/retry logic**: 10-second sleep after stopping nodes (gossip detection). Then `wait_for_node_un` for restart.

### 1.2 Enhance Module 4 (Hinted Handoff) - Line 99-135

**Insert additional commands** around the existing content. The FIXED_ID variable and core flow remain, but add count-before, count-after, and hints directory checks.

Add **before** `docker-compose stop hcd-node2` (before line 105):
```bash
            log_info "Counting current rows on node2 BEFORE it goes down..."
            log_cmd "docker exec hcd-node2 cqlsh -e \"CONSISTENCY ONE; SELECT count(*) FROM rf_prod.logs;\""
            
            log_info "Checking hints directory on node1 BEFORE (should be empty or minimal)..."
            log_cmd "docker exec hcd-node1 ls -la /var/lib/cassandra/hints/ || echo '(hints directory check)'"
```

Add **after** the hint replay sleep (after line 132), before the final query:
```bash
            log_info "Checking hints directory on node1 AFTER delivery (should be empty now)..."
            log_cmd "docker exec hcd-node1 ls -la /var/lib/cassandra/hints/ || echo '(hints directory check)'"
            
            log_info "Counting rows on node2 AFTER hint replay (should show +1 delta)..."
            log_cmd "docker exec hcd-node2 cqlsh -e \"CONSISTENCY ONE; SELECT count(*) FROM rf_prod.logs;\""
            
            echo "The delta between the two counts proves the hint was delivered."
            echo "Hinted Handoff is the first line of defense against short-term entropy."
```

**Dry-run**: All new commands go through `log_cmd`. The `ls` and `SELECT count(*)` are read-only and safe.

### 1.3 Enhance Module 5 (Read Repair) - Line 136-140

**Replace** the current minimal content with a more complete demonstration:

```bash
        5)
            header 5 "Read Repair"
            log_info "Read Repair automatically fixes stale replicas during normal reads."
            echo ""
            echo "┌─────────────────────────────────────────────────────────────────────┐"
            echo "│  Read Repair Flow:                                                    │"
            echo "│  Client ──► Coordinator ──► [Full Read: Node A] + [Digest: Node B,C]  │"
            echo "│                                 │ Mismatch detected!                   │"
            echo "│                                 ▼                                      │"
            echo "│                          Coordinator sends repair mutation to stale node│"
            echo "└─────────────────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Step 1: Reading from a single node (CL=ONE) - may return stale data..."
            log_cmd "docker exec hcd-node2 cqlsh -e \"CONSISTENCY ONE; SELECT * FROM rf_prod.logs LIMIT 5;\""
            
            log_info "Step 2: Triggering Read Repair via QUORUM read (coordinator compares digests)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY QUORUM; TRACING ON; SELECT * FROM rf_prod.logs LIMIT 5;\""
            echo "Look at the trace output above. If you see 'Sending READ_REPAIR' messages,"
            echo "that means stale replicas were detected and fixed during this read."
            
            log_info "Step 3: Reading from the same node again at CL=ONE - now it should be consistent..."
            log_cmd "docker exec hcd-node2 cqlsh -e \"CONSISTENCY ONE; SELECT * FROM rf_prod.logs LIMIT 5;\""
            
            log_info "Checking Read Repair metrics..."
            log_cmd "docker exec hcd-node1 nodetool tablestats rf_prod.logs | grep -i repair || echo '(No read repair stats yet - this is normal if replicas were already in sync)'"
            
            echo ""
            echo "Takeaway: Read Repair is passive entropy resolution. It piggybacks on normal reads"
            echo "to fix inconsistencies. It is NOT a substitute for regular anti-entropy repair."
            ;;
```

### 1.4 Enhance Module 7 (Token Ring) - Line 146-152

**Replace** the raw `nodetool ring` dump:

```bash
        7)
            header 7 "Token Ring & Consistent Hashing"
            echo ""
            echo "┌───────────────────────────────────────────────────────────────┐"
            echo "│                    Consistent Hashing Ring                     │"
            echo "│                                                               │"
            echo "│                        -2^63                                  │"
            echo "│                          │                                    │"
            echo "│                    N1 ◄──┤                                    │"
            echo "│                  ╱        │         ╲                          │"
            echo "│               N6           │           N2                      │"
            echo "│              │              │              │                   │"
            echo "│   -2^63 ────┤              0              ├──── +2^63         │"
            echo "│              │              │              │                   │"
            echo "│               N5           │           N3                      │"
            echo "│                  ╲        │         ╱                          │"
            echo "│                    N4 ◄──┤                                    │"
            echo "│                          │                                    │"
            echo "│                        +2^63                                  │"
            echo "│                                                               │"
            echo "│  Each node owns 256 vnodes (token ranges) on this ring.       │"
            echo "│  Data is placed on the ring by hashing the partition key.      │"
            echo "│  The next N nodes clockwise (where N=RF) store replicas.       │"
            echo "└───────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Describing token-to-node mapping for rf_prod keyspace..."
            log_cmd "docker exec hcd-node1 nodetool describering rf_prod | head -n 20"
            
            log_info "How many token ranges does each node own?"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.2' || echo '0'"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.3' || echo '0'"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.4' || echo '0'"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.5' || echo '0'"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.6' || echo '0'"
            log_cmd "docker exec hcd-node1 nodetool ring | grep -c '172.28.0.7' || echo '0'"
            
            echo ""
            echo "With 256 vnodes per node, each node owns ~256 small token ranges"
            echo "distributed evenly around the ring. This ensures balanced data distribution"
            echo "even as nodes join or leave the cluster."
            ;;
```

### 1.5 Enhance Module 11 (Tombstones) - Line 186-200

**Append** after existing content (before the `;;`):

```bash
            # --- NEW: gc_grace_seconds explanation ---
            echo ""
            log_info "Checking gc_grace_seconds for this table..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name = 'rf_prod' AND table_name = 'logs';\""
            
            echo ""
            echo "┌──────────────────────────────────────────────────────────────────┐"
            echo "│  gc_grace_seconds (default: 864000 = 10 days)                     │"
            echo "│                                                                    │"
            echo "│  WHY tombstones persist:                                           │"
            echo "│  • A deleted row might still exist on a stale replica              │"
            echo "│  • If the tombstone is removed before repair runs,                 │"
            echo "│    the stale replica's data would 'resurrect' during read repair   │"
            echo "│  • gc_grace_seconds is the safety window for repair to run          │"
            echo "│                                                                    │"
            echo "│  Timeline:                                                         │"
            echo "│  DELETE ──► Tombstone created ──► gc_grace expires ──► Compaction   │"
            echo "│                                    removes tombstone                │"
            echo "└──────────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Compacting to see tombstone resolution..."
            log_cmd "docker exec hcd-node1 nodetool compact rf_prod logs"
            
            log_info "Tombstone stats after compaction..."
            log_cmd "docker exec hcd-node1 nodetool tablestats rf_prod.logs | grep -E 'Tombstone|SSTable count' || echo '(Stats unavailable)'"
            
            echo "Tombstones are the price of distributed deletes. Without them,"
            echo "deleted data could reappear like a ghost from a stale replica."
```

### 1.6 Enhance Module 12 (LWT) - Line 201-212

**Replace** the entire case block with a story-driven demo:

```bash
        12)
            header 12 "Lightweight Transactions (LWT) - The Race Condition Story"
            echo ""
            echo "┌──────────────────────────────────────────────────────────────┐"
            echo "│  Scenario: Concert Ticket Sales                               │"
            echo "│                                                               │"
            echo "│  User A (New York)  ──┐                                       │"
            echo "│                        ├──► Same seat, same millisecond        │"
            echo "│  User B (London)    ──┘                                       │"
            echo "│                                                               │"
            echo "│  Without LWT: Both succeed. Double-booking!                   │"
            echo "│  With LWT: Exactly one succeeds. Paxos guarantees it.         │"
            echo "└──────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Creating the ticket inventory..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.tickets (event text, seat text, booked_by text, PRIMARY KEY (event, seat));\""
            
            log_info "Initializing available seats..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.tickets (event, seat, booked_by) VALUES ('concert-2025', 'A1', null);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.tickets (event, seat, booked_by) VALUES ('concert-2025', 'A2', null);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.tickets (event, seat, booked_by) VALUES ('concert-2025', 'A3', null);\""
            
            echo ""
            log_info "User A (New York) tries to book seat A1..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"TRACING ON; UPDATE rf_prod.tickets SET booked_by = 'Alice (NYC)' WHERE event = 'concert-2025' AND seat = 'A1' IF booked_by = null;\""
            echo "Expected: [applied]: True - Alice got the seat!"
            
            pause
            
            log_info "User B (London) tries to book the SAME seat A1 at the same time..."
            log_cmd "docker exec hcd-node5 cqlsh -e \"TRACING ON; UPDATE rf_prod.tickets SET booked_by = 'Bob (London)' WHERE event = 'concert-2025' AND seat = 'A1' IF booked_by = null;\""
            echo "Expected: [applied]: False - Bob sees Alice already booked it."
            echo "The response includes the current value so the app can show 'Seat taken'."
            
            pause
            
            log_info "Bob picks another seat instead..."
            log_cmd "docker exec hcd-node5 cqlsh -e \"TRACING ON; UPDATE rf_prod.tickets SET booked_by = 'Bob (London)' WHERE event = 'concert-2025' AND seat = 'A2' IF booked_by = null;\""
            echo "Expected: [applied]: True - Bob gets seat A2."
            
            log_info "Final state of all seats..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT * FROM rf_prod.tickets WHERE event = 'concert-2025';\""
            
            echo ""
            echo "Under the hood, each LWT goes through a 4-phase Paxos round:"
            echo "  1. Prepare - Leader proposes a ballot"
            echo "  2. Promise - Replicas promise to accept this ballot"
            echo "  3. Accept  - Leader sends the mutation"
            echo "  4. Commit  - Replicas apply the mutation"
            echo "This is ~4x slower than a normal write, so use LWT only when you need it."
            ;;
```

**Dry-run**: All CQL goes through `log_cmd`. The intermediate `pause` calls are fine since `--no-pause` will skip them, and dry-run tests always use `--no-pause`.

### 1.7 Fix + Enhance Module 17 (Zombie Node) - Line 260-280

**Replace** the entire case block:

```bash
        17)
            header 17 "The Zombie Node (Network Partition)"
            echo "A network partition makes a node unreachable to its peers, but the node"
            echo "itself thinks it is still alive. This creates a 'zombie' - it can accept"
            echo "local writes but cannot replicate them."
            echo ""
            echo "┌──────────────────────────────────────────────────────────────┐"
            echo "│  Before:   N1 ◄──► N2 ◄──► N3    (fully connected)          │"
            echo "│  During:   N1 ◄──►     X    N2    (N2 isolated)              │"
            echo "│  Gossip:   N1 sees N2 as DN after ~15-30 seconds              │"
            echo "│  After:    N1 ◄──► N2 ◄──► N3    (reconnected, healed)       │"
            echo "└──────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Disconnecting hcd-node2 from the cluster network..."
            log_cmd "docker network disconnect brokk_hcd-cluster hcd-node2"
            
            log_info "Waiting for Gossip to detect the partition (~15-30 seconds)..."
            if [ "$DRY_RUN" = false ]; then
                MAX_ZOMBIE_RETRIES=20
                ZOMBIE_COUNT=0
                until docker exec hcd-node1 nodetool status 2>/dev/null | grep -E "DN\s+172.28.0.3" >/dev/null 2>&1; do
                    echo -n "."
                    sleep 3
                    ZOMBIE_COUNT=$((ZOMBIE_COUNT + 1))
                    if [ $ZOMBIE_COUNT -ge $MAX_ZOMBIE_RETRIES ]; then
                        log_info "Timeout waiting for gossip to mark node as DN. Continuing..."
                        break
                    fi
                done
                echo ""
            fi
            
            log_info "Node 2 status (should show DN - Down/Normal)..."
            log_cmd "docker exec hcd-node1 nodetool status | grep '172.28.0.3' || echo 'Node 2 not visible'"
            
            log_info "Cluster can still serve reads/writes without Node 2 (RF=3, QUORUM=2)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.logs LIMIT 1;\""
            
            pause
            
            log_info "Reconnecting hcd-node2 to the cluster network..."
            log_cmd "docker network connect brokk_hcd-cluster hcd-node2"
            
            log_info "Waiting for Node 2 to rejoin the ring..."
            if [ "$DRY_RUN" = false ]; then
                wait_for_node_un "172.28.0.3" "Node 2" 30 5
            fi
            
            log_info "Node 2 status (should show UN - Up/Normal again)..."
            log_cmd "docker exec hcd-node1 nodetool status | grep '172.28.0.3' || echo 'Node 2 status unknown'"
            
            echo ""
            echo "The zombie is back in the land of the living. Gossip protocol detected"
            echo "the partition, the cluster continued serving traffic, and the node"
            echo "seamlessly rejoined when connectivity was restored."
            ;;
```

**Key design decision**: Using `docker network disconnect/connect brokk_hcd-cluster hcd-node2` instead of iptables. This works without NET_ADMIN and is more reliable. The network name `brokk_hcd-cluster` is derived from the project directory `brokk` + the compose network name `hcd-cluster`.

**Important caveat**: The `docker network disconnect/connect` commands are NOT CQL commands - they are host-level Docker commands. They should NOT go through `log_cmd` with `eval` if we want them to actually work. But looking at the existing code, `docker-compose stop/start` commands DO go through `log_cmd` (e.g., line 93, 97), so this pattern is consistent. In dry-run, they will only print.

**Wait/retry**: 20 retries at 3s intervals (60s max) for gossip detection. Then `wait_for_node_un` for reconnection.

### 1.8 Enhance Module 18 (SAI - Add Virtual Tables) - Line 281-335

**Append** before the final `;;` of module 18:

```bash
            # --- NEW: Virtual Table Introspection ---
            echo ""
            log_info "SAI Virtual Tables: Introspecting index internals..."
            echo "Unlike black-box indexes, SAI lets you introspect everything via system_views."
            
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT index_name, table_name, kind FROM system_schema.indexes WHERE keyspace_name = 'rf_prod';\""
            
            log_info "Checking per-SSTable index metadata (if available)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT * FROM system_views.sstable_tasks LIMIT 5;\" || echo '(system_views.sstable_tasks may not exist in this HCD version)'"
            
            echo "SAI transparency means you can monitor index health, size, and performance"
            echo "without relying on external tooling."
```

**Note**: The exact system_views tables available depend on the HCD/Cassandra version. `system_schema.indexes` is standard Cassandra 4.0. The `system_views.sstable_tasks` may not exist, hence the `|| echo` fallback.

### 1.9 Enhance Module 20 (Vector Search) - Line 386-437

**Replace** the data loading section (lines 396-401) with meaningful 5-dimensional vectors. This requires changing the table DDL from `vector<float, 3>` to `vector<float, 5>`.

Actually, wait - the requirement says "5-dimensional vectors" but the existing table uses `vector<float, 3>`. Since other tables (vectors_dot, vectors_euclidean, knowledge_base) also use 3 dimensions, and the vector index is already created, I recommend creating a NEW table for the enhanced demo rather than modifying the existing flow. This avoids breaking the similarity function tables.

**Replace** the entire module 20 case block. Key changes:
- New `rf_prod.documents` table with `vector<float, 5>`
- 15-20 meaningful rows with pre-computed vectors
- Semantic clustering (tech, science, business)
- Keep the existing knowledge_base RAG pattern
- Remove vectors_dot/vectors_euclidean (simplify)

```bash
        20)
            header 20 "Vector Search & AI Readiness"
            echo "HCD SAI supports Vector Search for AI-driven applications."
            echo "This is the technology behind semantic search in ChatGPT, Copilot, and RAG systems."
            echo ""
            echo "┌──────────────────────────────────────────────────────────────────┐"
            echo "│  How Vector Search Works:                                         │"
            echo "│                                                                   │"
            echo "│  1. Text is converted to a numeric vector (embedding)              │"
            echo "│     'database replication' -> [0.9, 0.1, 0.8, 0.2, 0.7]           │"
            echo "│                                                                   │"
            echo "│  2. Similar concepts have similar vectors (cosine similarity)       │"
            echo "│     'data consistency'     -> [0.85, 0.15, 0.75, 0.25, 0.65]       │"
            echo "│     'cooking recipes'      -> [0.1, 0.9, 0.05, 0.8, 0.1]          │"
            echo "│                                                                   │"
            echo "│  3. ANN search finds the closest vectors efficiently               │"
            echo "└──────────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Creating document store with 5-dimensional embeddings..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.documents (id uuid PRIMARY KEY, title text, content text, category text, embedding vector<float, 5>);\""
            
            log_info "Creating Vector Index (SAI with cosine similarity)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE CUSTOM INDEX IF NOT EXISTS ON rf_prod.documents (embedding) USING 'StorageAttachedIndex' WITH OPTIONS = {'similarity_function': 'cosine'};\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE CUSTOM INDEX IF NOT EXISTS ON rf_prod.documents (category) USING 'StorageAttachedIndex';\""
            
            log_info "Loading 15 documents across 3 semantic clusters..."
            echo ""
            echo "--- Technology Cluster ---"
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Database Replication', 'How distributed databases replicate data across nodes', 'tech', [0.9, 0.1, 0.8, 0.2, 0.7]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Consensus Algorithms', 'Paxos and Raft for distributed agreement', 'tech', [0.85, 0.15, 0.75, 0.25, 0.65]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Cloud Architecture', 'Designing fault-tolerant cloud systems', 'tech', [0.8, 0.2, 0.7, 0.3, 0.6]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Microservices', 'Event-driven microservice communication patterns', 'tech', [0.75, 0.25, 0.65, 0.35, 0.55]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Container Orchestration', 'Kubernetes and Docker Swarm deployment', 'tech', [0.7, 0.3, 0.6, 0.4, 0.5]);\""
            
            echo "--- Science Cluster ---"
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Quantum Computing', 'Quantum bits and superposition in computing', 'science', [0.3, 0.8, 0.2, 0.9, 0.4]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Gene Editing', 'CRISPR technology for genome modification', 'science', [0.25, 0.85, 0.15, 0.88, 0.35]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Climate Modeling', 'Simulating climate change with supercomputers', 'science', [0.2, 0.9, 0.1, 0.85, 0.3]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Neuroscience', 'Brain-computer interfaces and neural mapping', 'science', [0.35, 0.75, 0.25, 0.82, 0.45]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Space Exploration', 'Mars colonization and deep space travel', 'science', [0.28, 0.82, 0.18, 0.87, 0.38]);\""
            
            echo "--- Business Cluster ---"
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Market Analysis', 'Stock market prediction using ML models', 'business', [0.5, 0.5, 0.4, 0.6, 0.9]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Supply Chain', 'Global logistics optimization strategies', 'business', [0.45, 0.55, 0.35, 0.65, 0.85]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Digital Marketing', 'SEO and content marketing automation', 'business', [0.4, 0.6, 0.3, 0.7, 0.8]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Risk Management', 'Enterprise risk assessment frameworks', 'business', [0.48, 0.52, 0.38, 0.62, 0.88]);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.documents (id, title, content, category, embedding) VALUES (uuid(), 'Fintech Innovation', 'Blockchain and DeFi payment systems', 'business', [0.55, 0.45, 0.45, 0.55, 0.92]);\""
            
            pause
            
            log_info "Semantic Search: 'Find documents about distributed systems'..."
            echo "Query vector [0.88, 0.12, 0.78, 0.22, 0.68] represents the concept of distributed systems."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT title, content, similarity_cosine(embedding, [0.88, 0.12, 0.78, 0.22, 0.68]) as score FROM rf_prod.documents ORDER BY embedding ANN OF [0.88, 0.12, 0.78, 0.22, 0.68] LIMIT 5;\""
            echo "Notice: Tech documents cluster at the top with high similarity scores."
            
            pause
            
            log_info "Hybrid Search: Tech documents about distributed systems..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT title, similarity_cosine(embedding, [0.88, 0.12, 0.78, 0.22, 0.68]) as score FROM rf_prod.documents WHERE category = 'tech' ORDER BY embedding ANN OF [0.88, 0.12, 0.78, 0.22, 0.68] LIMIT 3;\""
            echo "Hybrid search combines metadata filtering (category='tech') with vector similarity."
            echo "This is how ChatGPT finds YOUR company's documents - filter by source, rank by relevance."
            
            log_info "Cross-cluster search: 'What about finance and technology?'..."
            echo "Query vector [0.6, 0.4, 0.5, 0.5, 0.8] sits between tech and business clusters."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT title, category, similarity_cosine(embedding, [0.6, 0.4, 0.5, 0.5, 0.8]) as score FROM rf_prod.documents ORDER BY embedding ANN OF [0.6, 0.4, 0.5, 0.5, 0.8] LIMIT 5;\""
            echo "The results show a mix of tech and business documents - the query is in between both clusters."
            
            echo ""
            echo "Similarity Functions available in HCD:"
            echo "  COSINE     - Normalized direction similarity (most common for LLM embeddings)"
            echo "  DOT_PRODUCT - Magnitude-aware similarity"
            echo "  EUCLIDEAN  - Absolute distance measurement"
            ;;
```

### 1.10 Enhance Module 22 (Compaction) - Line 476-489

**Replace** the case block with before/after proof:

```bash
        22)
            header 22 "Compaction: The Entropy Cleaner"
            echo "Compaction merges SSTables, resolves overwrites (LWW), and removes"
            echo "expired tombstones. It is the physical resolution of logical entropy."
            echo ""
            
            log_info "Step 1: Creating multiple SSTables via repeated writes + flushes..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.stream (id, val) VALUES (301, 'flush1');\""
            log_cmd "docker exec hcd-node1 nodetool flush rf_prod stream"
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.stream (id, val) VALUES (302, 'flush2');\""
            log_cmd "docker exec hcd-node1 nodetool flush rf_prod stream"
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.stream (id, val) VALUES (303, 'flush3');\""
            log_cmd "docker exec hcd-node1 nodetool flush rf_prod stream"
            
            log_info "Step 2: SSTable count BEFORE compaction..."
            log_cmd "docker exec hcd-node1 nodetool tablestats rf_prod.stream | grep -E 'SSTable count|Space used' || echo '(Stats unavailable)'"
            
            log_info "Step 3: Running compaction stats to see current state..."
            log_cmd "docker exec hcd-node1 nodetool compactionstats"
            
            pause
            
            log_info "Step 4: Triggering manual compaction..."
            log_cmd "docker exec hcd-node1 nodetool compact rf_prod stream"
            
            log_info "Step 5: SSTable count AFTER compaction (should be reduced)..."
            log_cmd "docker exec hcd-node1 nodetool tablestats rf_prod.stream | grep -E 'SSTable count|Space used' || echo '(Stats unavailable)'"
            
            echo ""
            echo "┌──────────────────────────────────────────────────────────────┐"
            echo "│  Before Compaction:                                           │"
            echo "│  [SSTable-1] [SSTable-2] [SSTable-3]  (3 files, overlap)      │"
            echo "│                                                               │"
            echo "│  After Compaction:                                             │"
            echo "│  [SSTable-merged]  (1 file, no overlap, tombstones purged)    │"
            echo "└──────────────────────────────────────────────────────────────┘"
            echo ""
            echo "HCD uses UnifiedCompactionStrategy (UCS) by default."
            echo "UCS adapts to workload patterns automatically, unlike STCS/LCS/TWCS"
            echo "which required manual tuning. This is a key HCD differentiator."
            ;;
```

## Phase 2: New Modules (23-27)

### 2.1 Module 23: Kill an Entire Datacenter

```bash
        23)
            header 23 "Kill an Entire Datacenter (Multi-DC Failover)"
            echo ""
            echo "┌──────────────────────────────────────────────────────────────────┐"
            echo "│  THE SCENARIO:                                                    │"
            echo "│                                                                   │"
            echo "│  Your US-East datacenter (dc1) just lost power.                   │"
            echo "│  Three nodes. Gone. All at once.                                  │"
            echo "│                                                                   │"
            echo "│  Can your users in US-West (dc2) still work?                      │"
            echo "│  Can they write NEW data while US-East is down?                   │"
            echo "│  When US-East comes back, does it catch up automatically?          │"
            echo "│                                                                   │"
            echo "│  Let's find out.                                                  │"
            echo "└──────────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Creating a dedicated table for this test..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.dc_failover (id int PRIMARY KEY, msg text, written_from text);\""
            
            log_info "Inserting 20 rows from dc1 (hcd-node1)..."
            for i in $(seq 1 20); do
                log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.dc_failover (id, msg, written_from) VALUES ($i, 'row-$i-before-outage', 'dc1');\""
            done
            
            log_info "Verifying all 20 rows readable from dc1..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.dc_failover;\""
            
            pause
            
            echo ""
            echo "============================================"
            echo "     KILLING ENTIRE DATACENTER 1 (dc1)      "
            echo "============================================"
            echo ""
            log_cmd "docker-compose stop hcd-node1 hcd-node2 hcd-node3"
            
            if [ "$DRY_RUN" = false ]; then
                sleep 10
            fi
            
            log_info "dc1 is DEAD. Let's see what dc2 thinks..."
            log_cmd "docker exec hcd-node5 nodetool status"
            
            pause
            
            log_info "Can dc2 still read the data? (LOCAL_QUORUM from dc2)..."
            log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.dc_failover;\""
            log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.dc_failover WHERE id IN (1, 10, 20);\""
            echo "All 20 rows are there. dc2 has full copies because RF=3 per DC."
            
            pause
            
            log_info "Writing NEW data from dc2 while dc1 is completely down..."
            for i in $(seq 21 30); do
                log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; INSERT INTO rf_prod.dc_failover (id, msg, written_from) VALUES ($i, 'row-$i-during-outage', 'dc2');\""
            done
            log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.dc_failover;\""
            echo "30 rows total. 10 new rows written while dc1 was dead."
            
            pause
            
            echo ""
            echo "============================================"
            echo "     RESTORING DATACENTER 1 (dc1)           "
            echo "============================================"
            echo ""
            log_cmd "docker-compose start hcd-node1 hcd-node2 hcd-node3"
            
            log_info "Waiting for dc1 nodes to rejoin the cluster..."
            if [ "$DRY_RUN" = false ]; then
                wait_for_all_un 60
            fi
            
            log_cmd "docker exec hcd-node1 nodetool status"
            
            pause
            
            log_info "The moment of truth: querying dc1 for data written DURING the outage..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.dc_failover;\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT * FROM rf_prod.dc_failover WHERE id IN (21, 25, 30);\""
            
            echo ""
            echo "All 30 rows are visible from dc1, including the 10 written while it was dead."
            echo ""
            echo "Your entire US-East region just went down."
            echo "Users in US-West didn't notice."
            echo "When US-East came back, it caught up automatically."
            echo "That is the power of multi-DC replication with NetworkTopologyStrategy."
            ;;
```

**Dry-run**: The `for` loops will print each INSERT via `log_cmd`. The `docker-compose stop/start` are in `log_cmd`. The `sleep 10` and `wait_for_all_un` are gated by `DRY_RUN`.

**Wait/retry**: `wait_for_all_un 60` = 60 retries at 5s = 5 minutes max for dc1 to come back.

### 2.2 Module 24: Grand Finale - Self-Healing Database

```bash
        24)
            header 24 "Grand Finale - The Self-Healing Database"
            echo ""
            echo "We are going to throw everything at this database and watch it heal."
            echo "Three escalating failures. One conclusion."
            echo ""
            
            # --- Act 1: Single Node Failure + Hinted Handoff ---
            echo "================================================================"
            echo " ACT 1: Single Node Failure (Hinted Handoff)"
            echo "================================================================"
            echo ""
            
            log_info "Creating our test table..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.resilience (id int PRIMARY KEY, msg text, act text);\""
            
            log_info "Counting rows before Act 1..."
            log_cmd "docker exec hcd-node3 cqlsh -e \"CONSISTENCY ONE; SELECT count(*) FROM rf_prod.resilience;\""
            
            log_info "Killing node3..."
            log_cmd "docker-compose stop hcd-node3"
            if [ "$DRY_RUN" = false ]; then sleep 5; fi
            
            log_info "Writing 10 rows while node3 is dead (hints will be stored)..."
            for i in $(seq 1 10); do
                log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY ONE; INSERT INTO rf_prod.resilience (id, msg, act) VALUES ($i, 'written-while-node3-down', 'act1');\""
            done
            
            log_info "Bringing node3 back..."
            log_cmd "docker-compose start hcd-node3"
            if [ "$DRY_RUN" = false ]; then
                wait_for_node_un "172.28.0.4" "Node 3" 30 3
                sleep 15  # Wait for hint replay
            fi
            
            log_info "Row count on node3 after hint replay (should include the 10 new rows)..."
            log_cmd "docker exec hcd-node3 cqlsh -e \"CONSISTENCY ONE; SELECT count(*) FROM rf_prod.resilience;\""
            echo "Hinted Handoff healed node3 automatically. No manual intervention."
            
            pause
            
            # --- Act 2: Entire DC Failure + Cross-DC Availability ---
            echo ""
            echo "================================================================"
            echo " ACT 2: Entire Datacenter Failure (Cross-DC Availability)"
            echo "================================================================"
            echo ""
            
            log_info "Killing ALL of dc1 (nodes 1, 2, 3)..."
            log_cmd "docker-compose stop hcd-node1 hcd-node2 hcd-node3"
            if [ "$DRY_RUN" = false ]; then sleep 10; fi
            
            log_info "Reading from dc2 - all data must be present..."
            log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.resilience;\""
            echo "dc2 serves all data. Zero downtime for the other region."
            
            log_info "Writing more data from dc2 during the outage..."
            for i in $(seq 11 15); do
                log_cmd "docker exec hcd-node5 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; INSERT INTO rf_prod.resilience (id, msg, act) VALUES ($i, 'written-during-dc1-outage', 'act2');\""
            done
            
            pause
            
            # --- Act 3: Full Recovery + Repair ---
            echo ""
            echo "================================================================"
            echo " ACT 3: Full Recovery & Anti-Entropy Repair"
            echo "================================================================"
            echo ""
            
            log_info "Restoring dc1..."
            log_cmd "docker-compose start hcd-node1 hcd-node2 hcd-node3"
            if [ "$DRY_RUN" = false ]; then
                wait_for_all_un 60
            fi
            
            log_info "Running anti-entropy repair to guarantee full consistency..."
            log_cmd "docker exec hcd-node1 nodetool repair -pr rf_prod"
            
            log_info "Final cluster status - all 6 nodes should be UN..."
            log_cmd "docker exec hcd-node1 nodetool status"
            
            log_info "Final row count from dc1 (should include act2 data written during outage)..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.resilience;\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT act, count(*) FROM rf_prod.resilience GROUP BY act; \" || echo '(GROUP BY may not be supported on this table structure)'"
            
            echo ""
            echo "================================================================"
            echo ""
            echo "  We threw everything at this database:"
            echo "    1. Killed a single node -> Hinted Handoff healed it"
            echo "    2. Killed an entire datacenter -> Other DC kept serving"
            echo "    3. Brought it all back -> Anti-Entropy Repair ensured consistency"
            echo ""
            echo "  Final status: All 6 nodes UP. All data intact. Zero data loss."
            echo ""
            echo "  This is what self-healing means at planetary scale."
            echo ""
            echo "================================================================"
            ;;
```

**Note on Act 3**: The `nodetool repair -pr rf_prod` may take a few minutes. This is expected and part of the demo narrative. The `-pr` flag (primary range only) limits scope.

### 2.3 Module 25: CDC (Change Data Capture)

```bash
        25)
            header 25 "Change Data Capture (CDC)"
            echo "CDC captures every mutation as an event, enabling event-driven architectures."
            echo "Every INSERT, UPDATE, and DELETE on a CDC-enabled table is recorded in"
            echo "commitlog segments that downstream systems can consume."
            echo ""
            echo "┌──────────────────────────────────────────────────────────────────┐"
            echo "│  App ──► HCD Write ──► CDC Commitlog ──► Stream Processor        │"
            echo "│                                          (Kafka, Pulsar, etc.)    │"
            echo "└──────────────────────────────────────────────────────────────────┘"
            echo ""
            
            log_info "Creating a CDC-enabled table..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.events (id uuid PRIMARY KEY, event_type text, payload text) WITH cdc = true;\""
            
            log_info "Inserting events..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.events (id, event_type, payload) VALUES (uuid(), 'user_signup', 'user=alice');\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.events (id, event_type, payload) VALUES (uuid(), 'purchase', 'item=widget,qty=3');\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.events (id, event_type, payload) VALUES (uuid(), 'page_view', 'url=/dashboard');\""
            
            log_info "Flushing to ensure CDC segments are written to disk..."
            log_cmd "docker exec hcd-node1 nodetool flush rf_prod events"
            
            log_info "Checking CDC commitlog segments..."
            log_cmd "docker exec hcd-node1 ls -la /var/lib/cassandra/cdc_raw/ || echo '(CDC directory not found or empty)'"
            
            log_info "Verifying CDC is enabled on the table..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT table_name, cdc FROM system_schema.tables WHERE keyspace_name = 'rf_prod' AND table_name = 'events';\""
            
            echo ""
            echo "Use cases for CDC:"
            echo "  - Real-time data pipelines to Kafka/Pulsar"
            echo "  - Audit trails for compliance"
            echo "  - Cache invalidation"
            echo "  - Cross-system synchronization"
            echo ""
            echo "Every mutation is captured as an event for downstream systems."
            echo "This is the foundation of event-driven architecture with HCD."
            ;;
```

**Note on CDC**: In Cassandra 4.0, `cdc = true` is a valid table property. The CDC segments are stored in `/var/lib/cassandra/cdc_raw/`. If CDC is not enabled at the cluster level (`cdc_enabled: true` in cassandra.yaml), the table creation will succeed but no segments will be written. The `|| echo` fallback handles this gracefully.

### 2.4 Module 26: Audit Logging

```bash
        26)
            header 26 "Audit Logging"
            echo "Enterprise compliance requires knowing who did what, when."
            echo "HCD audit logging captures all CQL operations with timestamps and client details."
            echo ""
            
            log_info "Enabling audit logging..."
            log_cmd "docker exec hcd-node1 nodetool enableauditlog || echo '(Audit logging may not be available in this configuration)'"
            
            log_info "Performing some tracked operations..."
            log_cmd "docker exec hcd-node1 cqlsh -e \"CREATE TABLE IF NOT EXISTS rf_prod.audit_test (id int PRIMARY KEY, data text);\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"INSERT INTO rf_prod.audit_test (id, data) VALUES (1, 'sensitive_data');\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT * FROM rf_prod.audit_test WHERE id = 1;\""
            log_cmd "docker exec hcd-node1 cqlsh -e \"DELETE FROM rf_prod.audit_test WHERE id = 1;\""
            
            log_info "Checking audit log output..."
            log_cmd "docker exec hcd-node1 ls -la /var/lib/cassandra/audit/ || echo '(Audit log directory not found)'"
            log_cmd "docker exec hcd-node1 cat /var/lib/cassandra/audit/audit.log 2>/dev/null | tail -n 20 || echo '(Audit log empty or not in expected location - check /var/log/cassandra/)'"
            log_cmd "docker exec hcd-node1 cat /var/log/cassandra/audit/audit.log 2>/dev/null | tail -n 20 || echo '(Checking alternate audit log location...)'"
            
            log_info "Disabling audit logging..."
            log_cmd "docker exec hcd-node1 nodetool disableauditlog || echo '(Audit logging disable not available)'"
            
            echo ""
            echo "Audit logging records:"
            echo "  - Timestamp of every operation"
            echo "  - Client IP address"
            echo "  - CQL statement executed"
            echo "  - Keyspace and table affected"
            echo "  - Whether the operation succeeded or failed"
            echo ""
            echo "In production, audit logs feed into SIEM systems (Splunk, ELK)"
            echo "for real-time compliance monitoring and threat detection."
            ;;
```

**Note**: The audit log location varies between Cassandra distributions. The script tries both `/var/lib/cassandra/audit/` and `/var/log/cassandra/audit/` with `|| echo` fallbacks. The `enableauditlog` nodetool command is available in Cassandra 4.0+.

### 2.5 Module 27: Guardrails

```bash
        27)
            header 27 "Guardrails - Protecting the Database from Misuse"
            echo "HCD includes guardrails that prevent common mistakes from causing"
            echo "production incidents. These are configurable limits that warn or reject"
            echo "operations that could harm cluster health."
            echo ""
            
            log_info "Checking current guardrail configuration..."
            log_cmd "docker exec hcd-node1 nodetool getconfig tables_warn_threshold 2>/dev/null || echo '(getconfig not available for guardrails)'"
            log_cmd "docker exec hcd-node1 cqlsh -e \"SELECT * FROM system_views.settings WHERE name LIKE '%guard%';\" || echo '(Guardrail settings not available in system_views)'"
            
            log_info "Alternative: checking cassandra.yaml for guardrail settings..."
            log_cmd "docker exec hcd-node1 grep -i 'guardrail\|warn_threshold\|fail_threshold\|batch_size' /opt/hcd/resources/cassandra/conf/cassandra.yaml 2>/dev/null | head -n 20 || echo '(Guardrail config not found in cassandra.yaml)'"
            
            log_info "Demonstrating a batch size warning..."
            echo "Creating a large batch that may trigger a warning..."
            BATCH_CQL="BEGIN UNLOGGED BATCH "
            for i in $(seq 1 50); do
                BATCH_CQL="${BATCH_CQL} INSERT INTO rf_prod.stream (id, val) VALUES ($((1000 + i)), 'batch-guardrail-test');"
            done
            BATCH_CQL="${BATCH_CQL} APPLY BATCH;"
            log_cmd "docker exec hcd-node1 cqlsh -e \"${BATCH_CQL}\" || echo '(Batch may have been rejected by guardrail)'"
            
            log_info "Checking for guardrail warnings in logs..."
            log_cmd "docker exec hcd-node1 grep -i 'guardrail\|batch size\|warn' /var/log/cassandra/system.log 2>/dev/null | tail -n 10 || echo '(No guardrail warnings found in logs - batch may be within limits)'"
            
            echo ""
            echo "Common HCD Guardrails:"
            echo "  - Batch size warnings (default: 5KB warn, 50KB fail)"
            echo "  - Collection size limits"  
            echo "  - Partition size warnings"
            echo "  - Number of tables per keyspace"
            echo "  - Query page size limits"
            echo "  - Tombstone warnings per read"
            echo ""
            echo "HCD protects itself from misuse. These guardrails catch common"
            echo "anti-patterns before they become production incidents."
            ;;
```

**Dry-run considerations**: The large batch is built in a shell variable then passed to `log_cmd`. In dry-run, the full command string will be printed (it's long but functional). The `for` loop building `BATCH_CQL` runs regardless of dry-run (it's just string construction), which is correct behavior.

## Phase 3: Test Updates

### 3.1 Update `tests/test_demo_entropy.py`

File: `/Users/david.leconte/Documents/Work/Labs/brokk/tests/test_demo_entropy.py`

**Change 1**: Line 28 - Update range from `range(23)` to `range(28)`:
```python
@pytest.mark.parametrize("module_id", [str(i) for i in range(28)])
```

**Change 2**: Lines 14-15 - Add assertions for new modules in `test_dry_run_execution`:
```python
def test_dry_run_execution():
    """Verify the script runs through all modules in dry-run mode without errors."""
    result = subprocess.run(
        ["bash", "scripts/demo-entropy.sh", "--dry-run", "--no-pause"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "[DRY-RUN]" in result.stdout
    assert "Module 21: Mixed" in result.stdout
    assert "Module 22: Compaction" in result.stdout
    assert "Module 23: Kill an Entire Datacenter" in result.stdout
    assert "Module 24: Grand Finale" in result.stdout
    assert "Module 25: Change Data Capture" in result.stdout
    assert "Module 26: Audit Logging" in result.stdout
    assert "Module 27: Guardrails" in result.stdout
```

**Change 3**: Update `test_invalid_module` - the test passes `99` which is still invalid, so no change needed. But add a boundary test:
```python
def test_boundary_module_valid():
    """Verify module 27 is accepted."""
    result = subprocess.run(
        ["bash", "scripts/demo-entropy.sh", "--dry-run", "--no-pause", "27"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Module 27:" in result.stdout

def test_boundary_module_invalid():
    """Verify module 28 is rejected."""
    result = subprocess.run(
        ["bash", "scripts/demo-entropy.sh", "--dry-run", "28"],
        capture_output=True,
        text=True,
    )
    assert "Invalid module number" in result.stdout
```

## Phase 4: Documentation Updates

### 4.1 Update `DEMO_ENTROPY.md`

Add to the "Demo Modules Overview" section (after line 82):

```markdown
- **Module 23**: Kill an Entire Datacenter - Multi-DC failover proving zero-downtime
- **Module 24**: Grand Finale - Self-Healing Database (chained failure scenarios)
- **Module 25**: CDC (Change Data Capture) - Event-driven architecture
- **Module 26**: Audit Logging - Enterprise compliance tracking
- **Module 27**: Guardrails - Protecting the database from misuse
```

Add a new section after Module 22 content:

```markdown
---

## Module 23: Kill an Entire Datacenter (Multi-DC Failover)

This is the "wow moment" of the demo. We prove zero-downtime cross-DC failover by:
1. Inserting 20 rows from dc1
2. Killing ALL of dc1 (nodes 1, 2, 3)
3. Proving dc2 can read all data at LOCAL_QUORUM
4. Writing 10 NEW rows from dc2 while dc1 is down
5. Restarting dc1 and proving it has all 30 rows

```sql
-- Create test table
CREATE TABLE rf_prod.dc_failover (id int PRIMARY KEY, msg text, written_from text);

-- Insert from dc1
INSERT INTO rf_prod.dc_failover (id, msg, written_from) VALUES (1, 'row-1', 'dc1');

-- Kill dc1: docker-compose stop hcd-node1 hcd-node2 hcd-node3

-- Read from dc2 (all data present)
CONSISTENCY LOCAL_QUORUM; SELECT count(*) FROM rf_prod.dc_failover;

-- Write from dc2 during outage
INSERT INTO rf_prod.dc_failover (id, msg, written_from) VALUES (21, 'during-outage', 'dc2');

-- Restore dc1: docker-compose start hcd-node1 hcd-node2 hcd-node3
-- dc1 sees all data including rows written during outage
```

---

## Module 24: Grand Finale - The Self-Healing Database

Three escalating failure scenarios demonstrating HCD's resilience:

| Act | Failure | Resolution | Proof |
|-----|---------|------------|-------|
| 1 | Kill node3 | Hinted Handoff | Row count match after restart |
| 2 | Kill entire dc1 | Cross-DC reads | LOCAL_QUORUM from dc2 |
| 3 | Restore dc1 + repair | Anti-Entropy Repair | All nodes UN, full row count |

---

## Module 25: CDC (Change Data Capture)

CDC captures every mutation as an event for downstream systems.

```sql
CREATE TABLE rf_prod.events (
    id uuid PRIMARY KEY,
    event_type text,
    payload text
) WITH cdc = true;
```

CDC commitlog segments are stored in `/var/lib/cassandra/cdc_raw/`.

---

## Module 26: Audit Logging

Enterprise audit logging tracks all CQL operations.

```bash
# Enable
nodetool enableauditlog
# Run operations...
# Check logs
cat /var/lib/cassandra/audit/audit.log
# Disable
nodetool disableauditlog
```

---

## Module 27: Guardrails

HCD guardrails prevent common anti-patterns:
- Batch size warnings (5KB warn, 50KB fail)
- Collection and partition size limits
- Tombstone warnings per read

---

## Wow Moments

The most impressive demonstrations for stakeholder presentations:

1. **Module 23 - Datacenter Kill**: Stop 3 nodes simultaneously. Query from the other DC. Zero data loss. (5 min)
2. **Module 24 - Grand Finale**: Chain 3 failures, prove self-healing after each one. (10 min)
3. **Module 17 - Network Partition**: Watch gossip detect a zombie node in real-time. (3 min)
4. **Module 2 - CL Spectrum**: Show EACH_QUORUM failing while LOCAL_QUORUM survives. (3 min)
5. **Module 12 - Ticket Race**: Two users, two continents, one seat. LWT prevents double-booking. (2 min)
```

### 4.2 Update `AGENTS.md`

Update the "Running the Demo" section (line 68):
```markdown
# Run specific module (0-27)
./scripts/demo-entropy.sh 3
```

Add to project structure if desired:
```
├── tests/
│   ├── test_demo_entropy.py
│   └── test_topology.py
```

### 4.3 Documentation note on `vector<float, 3>` vs `vector<float32, 3>`

**DONE:** The `DEMO_ENTROPY.md` references have been fixed. HCD 1.2.3 (Cassandra 4.0) uses `vector<float, n>`. Both the script and documentation now use `vector<float, n>` consistently.

## Implementation Sequencing

The work can be parallelized as follows:

**Can be done simultaneously (no dependencies between them):**
- Phase 0 (infrastructure) - MUST be done first, but all 4 items in Phase 0 are independent
- Phase 1 items 1.1-1.10 are all independent of each other
- Phase 2 items 2.1-2.5 are independent of each other (but depend on Phase 0)
- Phase 3 depends on Phase 0 (validation regex) and all module numbers being finalized
- Phase 4 depends on all module content being finalized

**Recommended order:**
1. Phase 0 (infrastructure skeleton)
2. Phase 1 + Phase 2 (all module work, in parallel)
3. Phase 3 (tests)
4. Phase 4 (documentation)

## Risk Assessment

1. **`docker network disconnect` network name**: The network name `brokk_hcd-cluster` depends on the project directory being `brokk`. If the user runs from a different directory or uses `COMPOSE_PROJECT_NAME`, this will break Module 17. Mitigation: use `$(docker inspect hcd-node2 --format '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}}{{end}}')` to dynamically get the network name, or hardcode based on the known project setup.

2. **CDC may not be enabled**: If `cdc_enabled: false` in cassandra.yaml (which is the default), Module 25's CDC directory check will show nothing. The `|| echo` fallback handles this, but it's worth verifying the cassandra.yaml template has `cdc_enabled: true`.

3. **Audit log location**: Varies by distribution. Multiple fallback paths are checked.

4. **Module 24 repair duration**: `nodetool repair -pr rf_prod` may take several minutes on a 6-node cluster. This is acceptable for a grand finale demo but should be noted in the documentation.

5. **The `for` loop in modules 23/24/27**: Shell `for` loops with `log_cmd` inside work in dry-run mode because `log_cmd` will print each command. However, the loop itself always runs (it's not gated by dry-run), which is correct - you want to see all 20 INSERT commands printed in dry-run.

6. **Module 2 restart timing**: After stopping nodes 2 and 3, the script attempts EACH_QUORUM from node4 (dc2). There's a 10-second sleep to let gossip propagate the DN status, but in some cases this may not be enough. The `|| echo` on the expected failure handles this gracefully.

### Critical Files for Implementation
- `/Users/david.leconte/Documents/Work/Labs/brokk/scripts/demo-entropy.sh` - Primary script to modify: all 5 new modules, 8 enhanced modules, infrastructure changes (validation, loop range, cleanup trap, helper functions)
- `/Users/david.leconte/Documents/Work/Labs/brokk/tests/test_demo_entropy.py` - Test file: update parametrize range to 28, add assertions for new module names, add boundary tests
- `/Users/david.leconte/Documents/Work/Labs/brokk/DEMO_ENTROPY.md` - Documentation: add module 23-27 sections, add "Wow Moments" section (DONE: vector<float> references fixed)
- `/Users/david.leconte/Documents/Work/Labs/brokk/AGENTS.md` - Update module range from 0-22 to 0-27 in running instructions
- `/Users/david.leconte/Documents/Work/Labs/brokk/docker-compose.yml` - Reference file (read-only): verify network name `hcd-cluster`, confirm node IPs, check if `cdc_enabled` needs adding to cassandra.yaml template
