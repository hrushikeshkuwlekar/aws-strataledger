"""
AWS Architecture Landscape & Topology Builder.

Transforms multi-account cloud inventory into an authentic, structured
AWS Architecture Diagram graph with proper tiered flow (Ingress -> Public -> App -> Data)
and eliminates noisy route table spiderwebs.
"""

from typing import Dict, Any, List, Set


def build_topology(inventory: dict) -> dict:
    """
    Build an AWS Architecture Landscape graph from an account-region inventory.

    Args:
        inventory: Dict with keys 'networking', 'compute', 'storage', 'identity', 'security', 'monitoring', 's3'

    Returns:
        {"nodes": [...], "edges": [...]}
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()
    edge_pairs: Set[tuple] = set()

    def add_node(node_id: str, node_type: str, label: str, parent: str = None, data: dict = None, tier: str = "app"):
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "parent": parent,
            "tier": tier,
            "data": data or {},
        })

    def add_edge(source: str, target: str, label: str = "", edge_type: str = "default"):
        if source not in node_ids or target not in node_ids or source == target:
            return
        pair = (source, target, edge_type)
        if pair in edge_pairs:
            return
        edge_pairs.add(pair)
        edges.append({
            "source": source,
            "target": target,
            "label": label,
            "type": edge_type,
            "edgeType": edge_type,
        })

    networking = inventory.get("networking", {})
    compute = inventory.get("compute", {})
    storage = inventory.get("storage", {})
    identity = inventory.get("identity", {})
    security = inventory.get("security", {})
    monitoring = inventory.get("monitoring", {})
    s3_data = inventory.get("s3", {})

    # ── 1. Route Table Analysis: Classify Subnet Tiers ────────────────
    # Instead of creating messy route table nodes with 50+ diagonal lines,
    # we inspect route tables to classify subnets into architectural tiers:
    # - "public": Has default route to an Internet Gateway
    # - "app": Has default route to a NAT Gateway or VPC peering/TGW/NFW
    # - "db": Isolated subnet with only local routes
    public_subnets = set()
    nat_subnets = set()
    subnet_to_nat = {}

    firewalls = networking.get("network_firewalls", [])
    nfw_endpoints = set()
    nfw_subnets = set()
    for fw in firewalls:
        for ep in fw.get("endpoint_ids", []):
            nfw_endpoints.add(ep)
        for s in fw.get("subnet_mappings", []):
            nfw_subnets.add(s)

    route_tables = networking.get("route_tables", [])
    for rt in route_tables:
        routes = rt.get("routes", [])
        has_igw = any(r.get("target", "").startswith("igw-") for r in routes)
        nat_target = next((r.get("target") for r in routes if r.get("target", "").startswith("nat-")), None)
        nfw_target = next((r.get("target") for r in routes if r.get("target") in nfw_endpoints), None)

        for assoc in rt.get("associations", []):
            sub_id = assoc.get("subnet_id")
            if sub_id:
                if has_igw:
                    public_subnets.add(sub_id)
                elif nat_target:
                    nat_subnets.add(sub_id)
                    subnet_to_nat[sub_id] = nat_target
                elif nfw_target:
                    nat_subnets.add(sub_id)

    # ── 2. VPC Network Enclosures ─────────────────────────────────────
    vpcs = networking.get("vpcs", [])
    for vpc in vpcs:
        vpc_id = vpc.get("resource_id") or vpc.get("vpc_id") or vpc.get("id")
        if not vpc_id:
            continue
        name = vpc.get("name") or vpc_id
        cidr = vpc.get("cidr_block", "")
        label = f"{name}\n{cidr}" if cidr and cidr != name else name
        add_node(vpc_id, "vpc", label, data=vpc, tier="vpc")

    # ── 3. Subnets with Architecture Tiers ────────────────────────────
    subnets = networking.get("subnets", [])
    for subnet in subnets:
        subnet_id = subnet.get("resource_id") or subnet.get("subnet_id") or subnet.get("id")
        if not subnet_id:
            continue
        vpc_id = subnet.get("vpc_id")
        name = subnet.get("name") or subnet_id
        cidr = subnet.get("cidr_block", "")
        az = subnet.get("availability_zone", "")

        name_lower = (name or "").lower()
        if subnet_id in nfw_subnets or "firewall" in name_lower or "nfw" in name_lower:
            tier = "public"
            subnet_type = "subnet_public"
            tier_title = "Firewall Subnet"
        elif "pub" in name_lower or subnet_id in public_subnets or subnet.get("map_public_ip_on_launch", False):
            tier = "public"
            subnet_type = "subnet_public"
            tier_title = "Public Subnet"
        elif "db" in name_lower or "data" in name_lower or "rds" in name_lower or "sql" in name_lower:
            tier = "db"
            subnet_type = "subnet_private"
            tier_title = "Private DB Subnet"
        elif subnet_id in nat_subnets or "app" in name_lower or "priv" in name_lower or "compute" in name_lower:
            tier = "app"
            subnet_type = "subnet_private"
            tier_title = "Private App Subnet"
        else:
            tier = "app"
            subnet_type = "subnet_private"
            tier_title = "Private Subnet"

        label = f"[{tier_title}] {name}\n{cidr} • {az}" if cidr else f"[{tier_title}] {name}"
        add_node(subnet_id, subnet_type, label, parent=vpc_id, data=subnet, tier=tier)

    # ── 4. Edge, Perimeter & Ingress Gateways ────────────────────────
    # Internet Gateways (IGW)
    igws = networking.get("internet_gateways", [])
    for igw in igws:
        igw_id = igw.get("resource_id") or igw.get("igw_id") or igw.get("id")
        if not igw_id:
            continue
        label = igw.get("name") or igw_id
        add_node(igw_id, "internet_gateway", label, data=igw, tier="ingress")
        for att in igw.get("attachments", []):
            vpc_id = att.get("vpc_id")
            if vpc_id:
                add_edge(igw_id, vpc_id, "Internet Ingress", "gateway")

    # AWS Transit Gateways (TGW) - Central Hub
    tgws = networking.get("transit_gateways", [])
    for tgw in tgws:
        tgw_id = tgw.get("resource_id") or tgw.get("tgw_id") or tgw.get("id")
        if not tgw_id:
            continue
        label = tgw.get("name") or tgw_id
        add_node(tgw_id, "transit_gateway", label, data=tgw, tier="ingress")

    tgw_attachments = networking.get("transit_gateway_attachments", [])
    for att in tgw_attachments:
        tgw_id = att.get("transit_gateway_id")
        resource_id = att.get("resource_id_attached")
        att_type = att.get("resource_type_attached", "vpc")
        if tgw_id and resource_id:
            add_edge(tgw_id, resource_id, f"TGW Attachment ({att_type})", "tgw_attachment")

    # VPC Peering Connections
    peerings = networking.get("vpc_peering_connections", [])
    for pcx in peerings:
        req_vpc = pcx.get("requester_vpc")
        acc_vpc = pcx.get("accepter_vpc")
        pcx_id = pcx.get("resource_id") or pcx.get("pcx_id") or pcx.get("id")
        name = pcx.get("name") or pcx_id
        if req_vpc and acc_vpc and req_vpc in node_ids and acc_vpc in node_ids:
            add_edge(req_vpc, acc_vpc, f"VPC Peering: {name}", "peering")

    # VPN Gateways
    vgws = networking.get("vpn_gateways", [])
    for vgw in vgws:
        vgw_id = vgw.get("resource_id") or vgw.get("vgw_id") or vgw.get("id")
        if not vgw_id:
            continue
        label = vgw.get("name") or vgw_id
        add_node(vgw_id, "vpn_gateway", label, data=vgw, tier="ingress")
        for att in vgw.get("vpc_attachments", []):
            vpc_id = att.get("vpc_id")
            if vpc_id:
                add_edge(vgw_id, vpc_id, "Site-to-Site VPN", "gateway")

    # AWS Network Firewalls
    for fw in firewalls:
        fw_id = fw.get("name") or fw.get("resource_id") or fw.get("id")
        if not fw_id:
            continue
        vpc_id = fw.get("vpc_id")
        status = fw.get("status", "ACTIVE")
        label = f"Network Firewall: {fw_id}\n({status})"

        fw_subnets = [s for s in fw.get("subnet_mappings", []) if s in node_ids]
        target_parent = fw_subnets[0] if fw_subnets else (vpc_id if vpc_id in node_ids else None)
        tier = "public" if fw_subnets else "ingress"

        add_node(fw_id, "network_firewall", label, parent=target_parent, data=fw, tier=tier)

        # Connect to VPC boundary
        if vpc_id and vpc_id in node_ids:
            add_edge(fw_id, vpc_id, "Inspects VPC", "gateway")

        # Connect from IGW if present
        if igws:
            first_igw = igws[0].get("resource_id") or igws[0].get("igw_id") or igws[0].get("id")
            if first_igw and first_igw in node_ids:
                add_edge(first_igw, fw_id, "Ingress Inspection", "traffic")

        # Connect to Transit Gateway if attached
        tgw_id = fw.get("transit_gateway_id")
        if tgw_id and tgw_id in node_ids:
            add_edge(tgw_id, fw_id, "TGW Inspection", "tgw_attachment")

    # AWS WAF Web ACLs
    waf_acls = networking.get("waf_web_acls", [])
    for acl in waf_acls:
        acl_id = acl.get("resource_id") or acl.get("name") or acl.get("id")
        if not acl_id:
            continue
        acl_name = acl.get("name", acl_id)
        add_node(acl_id, "waf_web_acl", f"WAF: {acl_name}", data=acl, tier="ingress")

    # ── 5. NAT Gateways (Public Tier Egress) ──────────────────────────
    nats = networking.get("nat_gateways", [])
    for nat in nats:
        nat_id = nat.get("resource_id") or nat.get("nat_id") or nat.get("id")
        if not nat_id:
            continue
        label = nat.get("name") or nat_id
        subnet_id = nat.get("subnet_id")
        add_node(nat_id, "nat_gateway", f"NAT: {label}", parent=subnet_id, data=nat, tier="public")
        # Connect NAT to IGW
        for igw in igws:
            igw_id = igw.get("resource_id") or igw.get("igw_id") or igw.get("id")
            if igw_id:
                add_edge(nat_id, igw_id, "Outbound", "egress")

    # Connect Private App subnets to their respective NAT Gateway
    for sub_id, nat_id in subnet_to_nat.items():
        if sub_id in node_ids and nat_id in node_ids:
            add_edge(sub_id, nat_id, "Outbound NAT", "egress")

    # ── 6. Load Balancers (ALB / NLB) ────────────────────────────────
    lbs = networking.get("load_balancers_v2", [])
    for lb in lbs:
        lb_id = lb.get("name") or lb.get("resource_id") or lb.get("id")
        if not lb_id:
            continue
        vpc_id = lb.get("vpc_id")
        scheme = lb.get("scheme", "internet-facing")
        lb_type = (lb.get("type") or "application").upper()[:3]
        label = f"{lb_type}: {lb_id}\n({scheme})"
        tier = "public" if "internet" in scheme else "app"

        # Place inside first associated subnet or VPC
        target_parent = vpc_id
        az_subnets = [az.get("subnet_id") for az in lb.get("availability_zones", []) if az.get("subnet_id")]
        if az_subnets and az_subnets[0] in node_ids:
            target_parent = az_subnets[0]

        add_node(lb_id, "load_balancer", label, parent=target_parent, data=lb, tier=tier)

        # If internet-facing, connect from IGW
        if "internet" in scheme and igws:
            first_igw = igws[0].get("resource_id") or igws[0].get("igw_id") or igws[0].get("id")
            if first_igw:
                add_edge(first_igw, lb_id, "HTTP/HTTPS", "traffic")

    # ── 7. Compute Tier (EC2, EKS, ASG, Lambda) ──────────────────────
    # EC2 Instances
    instances = compute.get("ec2_instances", [])
    inst_by_id = {}
    for inst in instances:
        inst_id = inst.get("resource_id") or inst.get("instance_id") or inst.get("id")
        if not inst_id:
            continue
        inst_by_id[inst_id] = inst
        subnet_id = inst.get("subnet_id")
        name = inst.get("name") or inst_id
        itype = inst.get("instance_type", "")
        state = inst.get("state", "running")
        label = f"{name}\n{itype} • {state}"

        is_sub_public = subnet_id in public_subnets
        tier = "public" if is_sub_public else "app"
        add_node(inst_id, "ec2", label, parent=subnet_id, data=inst, tier=tier)

    # Auto Scaling Groups
    asgs = compute.get("auto_scaling_groups", [])
    for asg in asgs:
        asg_name = asg.get("name") or asg.get("resource_id") or asg.get("id")
        if not asg_name:
            continue
        vpc_subnets = asg.get("vpc_zone_identifier", "").split(",")
        parent = vpc_subnets[0] if vpc_subnets and vpc_subnets[0] in node_ids else None
        asg_label = f"ASG: {asg_name}\n({asg.get('desired_capacity', 0)} instances)"
        add_node(asg_name, "auto_scaling_group", asg_label, parent=parent, data=asg, tier="app")

    # EKS Clusters
    eks_clusters = compute.get("eks_clusters", [])
    for cluster in eks_clusters:
        cluster_name = cluster.get("name") or cluster.get("resource_id") or cluster.get("id")
        if not cluster_name:
            continue
        vpc_id = cluster.get("vpc_id")
        version = cluster.get("version", "")
        status = cluster.get("status", "ACTIVE")
        label = f"EKS: {cluster_name}\nK8s v{version} • {status}"
        add_node(cluster_name, "eks_cluster", label, parent=vpc_id, data=cluster, tier="app")

        # Connect EKS to cluster subnets
        for sub_id in cluster.get("subnet_ids", []):
            if sub_id in node_ids:
                add_edge(cluster_name, sub_id, "Cluster Subnet", "traffic")

    # Connect Load Balancers to Target Instances
    target_groups = networking.get("target_groups", [])
    for tg in target_groups:
        for lb_arn in tg.get("load_balancer_arns", []):
            matching_lb = next((l.get("name") for l in lbs if (l.get("resource_id") == lb_arn or l.get("name") == lb_arn)), None)
            if matching_lb and matching_lb in node_ids:
                for inst_id in inst_by_id:
                    # Link ALB to compute instances in the same VPC
                    inst_vpc = inst_by_id[inst_id].get("vpc_id")
                    lb_vpc = next((l.get("vpc_id") for l in lbs if l.get("name") == matching_lb), None)
                    if inst_vpc and lb_vpc and inst_vpc == lb_vpc:
                        add_edge(matching_lb, inst_id, "Target", "traffic")
                        break

    # VPC Lambda Functions
    functions = compute.get("lambda_functions", [])
    for fn in functions:
        fn_name = fn.get("name") or fn.get("resource_id") or fn.get("id")
        if not fn_name:
            continue
        vpc_config = fn.get("vpc_config", {})
        vpc_id = vpc_config.get("VpcId")
        runtime = fn.get("runtime", "")
        label = f"λ: {fn_name}\n{runtime}"

        if vpc_id and vpc_id in node_ids:
            fn_subnets = vpc_config.get("SubnetIds", [])
            parent = fn_subnets[0] if fn_subnets and fn_subnets[0] in node_ids else vpc_id
            add_node(fn_name, "lambda", label, parent=parent, data=fn, tier="app")
        else:
            # Non-VPC Lambda in regional tier
            add_node(fn_name, "lambda", label, data=fn, tier="regional")

    # VPC Endpoints
    endpoints = networking.get("vpc_endpoints", [])
    for ep in endpoints:
        ep_id = ep.get("resource_id") or ep.get("vpc_endpoint_id") or ep.get("id")
        if not ep_id:
            continue
        vpc_id = ep.get("vpc_id")
        svc_name = ep.get("service_name", "").split(".")[-1]
        label = f"Endpoint: {svc_name}"
        add_node(ep_id, "vpc_endpoint", label, parent=vpc_id, data=ep, tier="app")

    # ── 8. Database & Storage Tier (RDS, Aurora, DynamoDB, EFS) ───────
    # Aurora DB Clusters
    rds_clusters = storage.get("rds_clusters", [])
    for cluster in rds_clusters:
        cluster_id = cluster.get("name") or cluster.get("resource_id") or cluster.get("id")
        if not cluster_id:
            continue
        engine = cluster.get("engine", "")
        status = cluster.get("status", "available")
        cluster_label = f"Aurora: {cluster_id}\n{engine} • {status}"
        cluster_vpc = cluster.get("vpc_id")
        target_parent = cluster_vpc
        if cluster_vpc:
            db_named_subnets = [s.get("resource_id") or s.get("subnet_id") for s in subnets if s.get("vpc_id") == cluster_vpc and (
                "db" in (s.get("name") or "").lower() or "data" in (s.get("name") or "").lower() or "rds" in (s.get("name") or "").lower()
            )]
            if db_named_subnets and db_named_subnets[0] in node_ids:
                target_parent = db_named_subnets[0]
        add_node(cluster_id, "rds_cluster", cluster_label, parent=target_parent, data=cluster, tier="db")

    # RDS Instances
    rds_instances = storage.get("rds_instances", [])
    for db in rds_instances:
        db_id = db.get("name") or db.get("resource_id") or db.get("id")
        if not db_id:
            continue
        vpc_id = db.get("vpc_id")
        engine = db.get("engine", "")
        status = db.get("status", "available")
        label = f"RDS: {db_id}\n{engine} • {status}"

        # Place inside DB subnet if available, otherwise fallback to private subnet or VPC
        target_parent = vpc_id
        if vpc_id:
            db_named_subnets = [s.get("resource_id") or s.get("subnet_id") for s in subnets if s.get("vpc_id") == vpc_id and (
                "db" in (s.get("name") or "").lower() or "data" in (s.get("name") or "").lower() or "rds" in (s.get("name") or "").lower()
            )]
            if db_named_subnets and db_named_subnets[0] in node_ids:
                target_parent = db_named_subnets[0]
            else:
                priv_subnets = [s.get("resource_id") or s.get("subnet_id") for s in subnets if s.get("vpc_id") == vpc_id and (s.get("resource_id") or s.get("subnet_id")) not in public_subnets]
                if priv_subnets and priv_subnets[0] in node_ids:
                    target_parent = priv_subnets[0]

        add_node(db_id, "rds_instance", label, parent=target_parent, data=db, tier="db")

        # Connect instances to Aurora cluster if member
        for cluster in rds_clusters:
            for member in cluster.get("members", []):
                if member.get("instance_id") == db_id:
                    role = "Writer" if member.get("is_writer") else "Reader"
                    c_name = cluster.get("name") or cluster.get("resource_id")
                    if c_name:
                        add_edge(c_name, db_id, role, "database")

        # Connect app instances to database in same VPC
        if vpc_id:
            for inst_id, inst in inst_by_id.items():
                if inst.get("vpc_id") == vpc_id:
                    add_edge(inst_id, db_id, "SQL Access", "database")
                    break

    # EFS File Systems
    efs_filesystems = storage.get("efs_file_systems", [])
    for efs in efs_filesystems:
        efs_id = efs.get("name") or efs.get("resource_id") or efs.get("id")
        if not efs_id:
            continue
        label = f"EFS: {efs_id}"
        add_node(efs_id, "efs_file_system", label, data=efs, tier="db")

    # ── 9. AWS Regional & Managed Services ────────────────────────────
    # Amazon S3 Buckets
    s3_buckets = s3_data.get("s3_buckets", []) or inventory.get("s3_buckets", [])
    for bucket in s3_buckets[:15]:  # show up to 15 key buckets
        b_name = bucket.get("name") or bucket.get("resource_id") or bucket.get("id")
        if not b_name:
            continue
        add_node(b_name, "s3_bucket", f"S3: {b_name}", data=bucket, tier="regional")

    # DynamoDB Tables
    dynamo_tables = storage.get("dynamodb_tables", [])
    for table in dynamo_tables[:10]:
        t_name = table.get("name") or table.get("resource_id") or table.get("id")
        if not t_name:
            continue
        add_node(t_name, "dynamodb_table", f"DynamoDB: {t_name}", data=table, tier="regional")

    # KMS Keys (Customer Managed)
    kms_keys = identity.get("kms_keys", [])
    for key in kms_keys[:6]:
        key_id = key.get("alias") or key.get("key_id") or key.get("resource_id") or key.get("id")
        if not key_id:
            continue
        add_node(key_id, "kms_key", f"KMS: {key_id}", data=key, tier="regional")

    # Secrets Manager
    secrets = identity.get("secrets", [])
    for sec in secrets[:6]:
        sec_name = sec.get("name") or sec.get("resource_id") or sec.get("id")
        if not sec_name:
            continue
        add_node(sec_name, "secrets_manager", f"Secret: {sec_name}", data=sec, tier="regional")

    # CloudWatch Alarms
    alarms = monitoring.get("cloudwatch_alarms", [])
    for alm in alarms[:6]:
        alm_name = alm.get("name") or alm.get("resource_id") or alm.get("id")
        if not alm_name:
            continue
        state = alm.get("state", "OK")
        add_node(alm_name, "cloudwatch_alarm", f"Alarm: {alm_name} ({state})", data=alm, tier="regional")

    return {"nodes": nodes, "edges": edges}
