"""
Topology graph builder.

Builds a node/edge graph from inventory data for visualization
in the interactive topology diagram (Cytoscape.js).
"""


def build_topology(inventory: dict) -> dict:
    """
    Build a topology graph from a single account-region inventory.

    Args:
        inventory: Dict with keys like 'compute', 'networking', 'storage', etc.

    Returns:
        {"nodes": [...], "edges": [...]}
    """
    nodes = []
    edges = []
    node_ids = set()

    def add_node(node_id: str, node_type: str, label: str, parent: str = None, data: dict = None):
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        node = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "parent": parent,
            "data": data or {},
        }
        nodes.append(node)

    def add_edge(source: str, target: str, label: str = "", edge_type: str = "default"):
        if source not in node_ids or target not in node_ids:
            return
        edges.append({
            "source": source,
            "target": target,
            "label": label,
            "type": edge_type,
        })

    networking = inventory.get("networking", {})
    compute = inventory.get("compute", {})
    storage = inventory.get("storage", {})

    # ── VPCs ─────────────────────────────────────────────────────────
    vpcs = networking.get("vpcs", [])
    for vpc in vpcs:
        vpc_id = vpc["resource_id"]
        vpc_label = f"{vpc_id}"
        if vpc.get("cidr_block"):
            vpc_label += f"\n{vpc['cidr_block']}"
        if vpc.get("name"):
            vpc_label = f"{vpc['name']}\n{vpc_label}"
        add_node(vpc_id, "vpc", vpc_label, data=vpc)

    # ── Subnets ──────────────────────────────────────────────────────
    subnets = networking.get("subnets", [])
    for subnet in subnets:
        subnet_id = subnet["resource_id"]
        vpc_id = subnet.get("vpc_id")
        is_public = subnet.get("map_public_ip_on_launch", False)
        subnet_type = "subnet_public" if is_public else "subnet_private"
        label = subnet_id
        if subnet.get("name"):
            label = subnet["name"]
        if subnet.get("cidr_block"):
            label += f"\n{subnet['cidr_block']}"
        if subnet.get("availability_zone"):
            label += f"\n{subnet['availability_zone']}"
        add_node(subnet_id, subnet_type, label, parent=vpc_id, data=subnet)

    # ── Internet Gateways ────────────────────────────────────────────
    igws = networking.get("internet_gateways", [])
    for igw in igws:
        igw_id = igw["resource_id"]
        label = igw.get("name") or igw_id
        add_node(igw_id, "internet_gateway", label, data=igw)
        for att in igw.get("attachments", []):
            vpc_id = att.get("vpc_id")
            if vpc_id:
                add_edge(igw_id, vpc_id, "attached", "gateway")

    # ── NAT Gateways ─────────────────────────────────────────────────
    nats = networking.get("nat_gateways", [])
    for nat in nats:
        nat_id = nat["resource_id"]
        label = nat.get("name") or nat_id
        subnet_id = nat.get("subnet_id")
        add_node(nat_id, "nat_gateway", label, parent=subnet_id, data=nat)

    # ── VPN Gateways ─────────────────────────────────────────────────
    vgws = networking.get("vpn_gateways", [])
    for vgw in vgws:
        vgw_id = vgw["resource_id"]
        label = vgw.get("name") or vgw_id
        add_node(vgw_id, "vpn_gateway", label, data=vgw)
        for att in vgw.get("vpc_attachments", []):
            vpc_id = att.get("vpc_id")
            if vpc_id:
                add_edge(vgw_id, vpc_id, "attached", "gateway")

    # ── Transit Gateways ─────────────────────────────────────────────
    tgws = networking.get("transit_gateways", [])
    for tgw in tgws:
        tgw_id = tgw["resource_id"]
        label = tgw.get("name") or tgw_id
        add_node(tgw_id, "transit_gateway", label, data=tgw)

    tgw_attachments = networking.get("transit_gateway_attachments", [])
    for att in tgw_attachments:
        tgw_id = att.get("transit_gateway_id")
        resource_id = att.get("resource_id_attached")
        if tgw_id and resource_id:
            add_edge(resource_id, tgw_id, att.get("resource_type_attached", ""), "tgw_attachment")

    # ── VPC Peering ──────────────────────────────────────────────────
    peerings = networking.get("vpc_peering_connections", [])
    for pcx in peerings:
        req_vpc = pcx.get("requester_vpc")
        acc_vpc = pcx.get("accepter_vpc")
        pcx_id = pcx["resource_id"]
        if req_vpc and acc_vpc:
            # Add peering as a node between the two VPCs
            add_node(pcx_id, "peering", pcx_id, data=pcx)
            add_edge(req_vpc, pcx_id, "requester", "peering")
            add_edge(pcx_id, acc_vpc, "accepter", "peering")

    # ── VPC Endpoints ────────────────────────────────────────────────
    endpoints = networking.get("vpc_endpoints", [])
    for ep in endpoints:
        ep_id = ep["resource_id"]
        vpc_id = ep.get("vpc_id")
        service = ep.get("service_name", "").split(".")[-1]
        add_node(ep_id, "vpc_endpoint", service, parent=vpc_id, data=ep)

    # ── Route Tables → Gateway edges ────────────────────────────────
    route_tables = networking.get("route_tables", [])
    for rt in route_tables:
        rt_id = rt["resource_id"]
        vpc_id = rt.get("vpc_id")
        add_node(rt_id, "route_table", rt.get("name") or rt_id, parent=vpc_id, data=rt)

        # Connect route table to associated subnets
        for assoc in rt.get("associations", []):
            subnet_id = assoc.get("subnet_id")
            if subnet_id:
                add_edge(subnet_id, rt_id, "routes via", "routing")

        # Connect route table to targets
        for route in rt.get("routes", []):
            target = route.get("target", "")
            dest = route.get("destination", "")
            if target == "local" or not target:
                continue
            if target in node_ids:
                add_edge(rt_id, target, dest, "routing")

    # ── EC2 Instances ────────────────────────────────────────────────
    instances = compute.get("ec2_instances", [])
    for inst in instances:
        inst_id = inst["resource_id"]
        subnet_id = inst.get("subnet_id")
        label = inst.get("name") or inst_id
        label += f"\n{inst.get('instance_type', '')}"
        add_node(inst_id, "ec2", label, parent=subnet_id, data=inst)

    # ── EKS Clusters ─────────────────────────────────────────────────
    eks_clusters = compute.get("eks_clusters", [])
    for cluster in eks_clusters:
        cluster_id = cluster.get("name", cluster["resource_id"])
        vpc_id = cluster.get("vpc_id")
        label = f"EKS: {cluster_id}\nv{cluster.get('version', '')}"
        add_node(cluster_id, "eks_cluster", label, parent=vpc_id, data=cluster)

    # ── Load Balancers ───────────────────────────────────────────────
    lbs = networking.get("load_balancers_v2", [])
    for lb in lbs:
        lb_id = lb.get("name", lb["resource_id"])
        vpc_id = lb.get("vpc_id")
        lb_type = (lb.get("type") or "application").upper()[:3]
        label = f"{lb_type}: {lb_id}"
        add_node(lb_id, "load_balancer", label, parent=vpc_id, data=lb)

        # Connect to subnets
        for az in lb.get("availability_zones", []):
            subnet_id = az.get("subnet_id")
            if subnet_id and subnet_id in node_ids:
                add_edge(lb_id, subnet_id, "in subnet", "lb_subnet")

    # Connect target groups to load balancers and instances
    target_groups = networking.get("target_groups", [])
    # Build instance-to-subnet map for reference
    instance_ids = {i["resource_id"] for i in instances}

    for tg in target_groups:
        for lb_arn in tg.get("load_balancer_arns", []):
            # Find LB by ARN
            lb_name = None
            for lb in lbs:
                if lb["resource_id"] == lb_arn:
                    lb_name = lb.get("name", lb["resource_id"])
                    break
            if lb_name and lb_name in node_ids:
                # We don't add target group as a separate node, but we could
                pass

    # ── RDS Instances ────────────────────────────────────────────────
    rds_instances = storage.get("rds_instances", [])
    for db in rds_instances:
        db_id = db.get("name", db["resource_id"])
        vpc_id = db.get("vpc_id")
        engine = db.get("engine", "")
        label = f"RDS: {db_id}\n{engine}"
        add_node(db_id, "rds", label, parent=vpc_id, data=db)

    # ── RDS Clusters ─────────────────────────────────────────────────
    rds_clusters = storage.get("rds_clusters", [])
    for cluster in rds_clusters:
        cluster_id = cluster.get("name", cluster["resource_id"])
        engine = cluster.get("engine", "")
        label = f"Aurora: {cluster_id}\n{engine}"
        # Don't set parent to avoid conflict with member instances
        add_node(cluster_id, "rds_cluster", label, data=cluster)

        # Connect members
        for member in cluster.get("members", []):
            member_id = member.get("instance_id")
            if member_id and member_id in node_ids:
                role = "writer" if member.get("is_writer") else "reader"
                add_edge(cluster_id, member_id, role, "cluster_member")

    # ── Lambda Functions (VPC-connected) ─────────────────────────────
    functions = compute.get("lambda_functions", [])
    for fn in functions:
        vpc_config = fn.get("vpc_config", {})
        vpc_id = vpc_config.get("VpcId")
        fn_name = fn.get("name", fn["resource_id"])
        label = f"λ: {fn_name}"
        if vpc_id:
            add_node(fn_name, "lambda", label, parent=vpc_id, data=fn)
        # Non-VPC lambdas are shown but floating
        else:
            add_node(fn_name, "lambda", label, data=fn)

    # ── S3 Buckets (peripheral) ──────────────────────────────────────
    s3_buckets = inventory.get("s3", {}).get("s3_buckets", [])
    for bucket in s3_buckets:
        bucket_name = bucket["resource_id"]
        label = f"S3: {bucket_name}"
        add_node(bucket_name, "s3_bucket", label, data=bucket)

    # ── Security Groups (as metadata, not separate nodes to avoid clutter) ──

    # ── Network Firewalls ────────────────────────────────────────────
    firewalls = networking.get("network_firewalls", [])
    for fw in firewalls:
        fw_id = fw.get("name", fw["resource_id"])
        vpc_id = fw.get("vpc_id")
        add_node(fw_id, "network_firewall", f"NFW: {fw_id}", parent=vpc_id, data=fw)

    return {"nodes": nodes, "edges": edges}
