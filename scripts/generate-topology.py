#!/usr/bin/env python3
import argparse
import ipaddress
import os
import sys

def parse_datacenters(dc_str):
    """Parses 'dc1:2,dc2:3' into [('dc1', 2), ('dc2', 3)]"""
    try:
        dcs = []
        for part in dc_str.split(','):
            name, count = part.split(':')
            count = int(count.strip())
            if count <= 0:
                raise argparse.ArgumentTypeError(f'Node count must be positive, got {count} for {name.strip()}')
            dcs.append((name.strip(), count))
        return dcs
    except ValueError:
        raise argparse.ArgumentTypeError('Datacenters must be in format name:count,name:count')

def get_input(prompt, default):
    value = input(f"{prompt} [{default}]: ").strip()
    return value if value else default

def generate_topology(nodes_count, cluster_name="HCDCluster", dcs=None, subnet="172.28.0.0/24"):
    # Validate subnet
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        print(f"Error: Invalid subnet '{subnet}': {e}", file=sys.stderr)
        sys.exit(1)

    # Only /24 subnets are supported (simplifies IP assignment)
    if network.prefixlen != 24:
        print(f"Error: Only /24 subnets are supported, got /{network.prefixlen}", file=sys.stderr)
        sys.exit(1)

    # Validate node count fits in subnet (reserve .0 for network, .1 for gateway, .255 for broadcast)
    max_hosts = network.num_addresses - 3
    if nodes_count > max_hosts:
        print(f"Error: {nodes_count} nodes exceed subnet capacity ({max_hosts} usable addresses in {subnet})", file=sys.stderr)
        sys.exit(1)

    if nodes_count <= 0:
        print("Error: Node count must be positive", file=sys.stderr)
        sys.exit(1)

    # Extract base IP from network address (e.g., "172.28.0" from "172.28.0.0/24")
    base_ip = str(network.network_address).rsplit('.', 1)[0]

    # In multi-DC, we want a seed in each DC for reliability
    if dcs and len(dcs) > 1:
        seed_ips = [f"{base_ip}.2", f"{base_ip}.{dcs[0][1] + 2}"]
        seed_ip_str = ",".join(seed_ips)
    else:
        seed_ip_str = f"{base_ip}.2"
        
    snitch = "GossipingPropertyFileSnitch" if dcs else "SimpleSnitch"
    
    compose = [
        "x-hcd-common: &hcd-common",
        "  build: .",
        "  restart: on-failure:3",
        "  cap_add:",
        "    - NET_ADMIN",
        "  networks:",
        "    hcd-cluster:",
        "  environment:",
        f"    CASSANDRA_CLUSTER_NAME: ${{CASSANDRA_CLUSTER_NAME:-{cluster_name}}}",
        "    CASSANDRA_SEEDS: " + seed_ip_str,
        "    CASSANDRA_RPC_ADDRESS: 0.0.0.0",
        f"    CASSANDRA_ENDPOINT_SNITCH: {snitch}",
        "  healthcheck:",
        "    interval: 30s",
        "    timeout: 10s",
        "    retries: 5",
        "    start_period: 90s",
        "",
        "services:"
    ]

    node_configs = []
    if dcs:
        node_idx = 1
        for dc_name, count in dcs:
            for _ in range(count):
                node_configs.append((node_idx, dc_name))
                node_idx += 1
    else:
        for i in range(1, nodes_count + 1):
            node_configs.append((i, None))

    for i, dc_name in node_configs:
        ip = f"{base_ip}.{i+1}"
        node_name = f"hcd-node{i}"
        
        compose.extend([
            f"  {node_name}:",
            "    <<: *hcd-common",
            f"    container_name: {node_name}",
            f"    hostname: {node_name}",
            "    networks:",
            "      hcd-cluster:",
            f"        ipv4_address: {ip}",
            "    environment:",
            f"      CASSANDRA_LISTEN_ADDRESS: {ip}",
            f"      CASSANDRA_BROADCAST_ADDRESS: {ip}",
        ])

        if dc_name:
            # Distribute nodes across 3 racks (rack1, rack2, rack3)
            rack_idx = ((i - 1) % 3) + 1
            compose.append(f"      CASSANDRA_DC: {dc_name}")
            compose.append(f"      CASSANDRA_RACK: rack{rack_idx}")
        
        if i == 1:
            compose.append("      MAX_HEAP_SIZE: 512M")
            compose.append("    ports:")
            compose.append('      - "9042:9042"')
        
        if i > 1:
            compose.append("    depends_on:")
            # Multi-DC logic: depends on seed node primarily
            compose.append("      hcd-node1:")
            compose.append("        condition: service_healthy")
        
        compose.append("    volumes:")
        compose.append(f"      - {node_name}-data:/var/lib/cassandra")
        compose.append("    healthcheck:")
        compose.append(f'      test: ["CMD-SHELL", "cqlsh -e \'SELECT release_version FROM system.local\' || exit 1"]')
        compose.append("")

    compose.extend([
        "networks:",
        "  hcd-cluster:",
        "    driver: bridge",
        "    ipam:",
        "      config:",
        f"        - subnet: {subnet}",
        "",
        "volumes:"
    ])
    
    for i, _ in node_configs:
        compose.append(f"  hcd-node{i}-data:")

    return "\n".join(compose)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HCD Docker Topology")
    parser.add_argument("--nodes", type=int, default=3, help="Number of nodes to generate (ignored if --datacenters is used)")
    parser.add_argument("--datacenters", type=parse_datacenters, help="DC specification, e.g., 'dc1:2,dc2:2'")
    parser.add_argument("--cluster-name", default="HCDCluster", help="Cluster name")
    parser.add_argument("--subnet", default="172.28.0.0/24", help="Subnet for the cluster")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    args = parser.parse_args()

    if args.interactive:
        print("HCD Topology Generator (Interactive Mode)")
        print("==========================================")
        try:
            while True:
                try:
                    nodes = int(get_input("Enter number of nodes", "3"))
                    if nodes <= 0:
                        print("Node count must be positive. Try again.")
                        continue
                    break
                except ValueError:
                    print("Invalid number. Try again.")

            cluster_name = get_input("Enter cluster name", "HCDCluster")
            use_multi_dc = get_input("Use multi-datacenter topology? (y/n)", "n").lower().startswith('y')

            dcs = None
            if use_multi_dc:
                while True:
                    dc_spec = get_input("Enter datacenter configuration (e.g., 'dc1:2,dc2:3')", "dc1:2,dc2:1")
                    try:
                        dcs = parse_datacenters(dc_spec)
                        nodes = sum(count for _, count in dcs)
                        break
                    except (ValueError, argparse.ArgumentTypeError) as e:
                        print(f"Invalid format: {e}. Try again.")

            subnet = get_input("Enter subnet (/24 only)", "172.28.0.0/24")

            print("\nGenerating topology:")
            print(f"- Cluster: {cluster_name}")
            if dcs:
                dc_summary = ", ".join([f"{name} ({count} nodes)" for name, count in dcs])
                print(f"- Datacenters: {dc_summary}")
            print(f"- Total Nodes: {nodes}")
            print(f"- Network: {subnet}")

            args.nodes = nodes
            args.cluster_name = cluster_name
            args.datacenters = dcs
            args.subnet = subnet
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        except Exception as e:
            print(f"\nError during interactive input: {e}")
            sys.exit(1)
    else:
        if args.datacenters:
            args.nodes = sum(count for _, count in args.datacenters)

    output_file = "docker-compose.yml"
    if os.path.exists(output_file):
        backup_file = output_file + ".bak"
        os.rename(output_file, backup_file)
        print(f"Backed up existing {output_file} to {backup_file}")

    with open(output_file, "w") as f:
        f.write(generate_topology(args.nodes, args.cluster_name, args.datacenters, args.subnet))
    
    dc_info = f" across {len(args.datacenters)} datacenters" if args.datacenters else ""
    print(f"\nSuccessfully generated docker-compose.yml with {args.nodes} nodes{dc_info}.")
