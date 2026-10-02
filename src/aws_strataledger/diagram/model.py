"""
Diagram model builder.

Transforms scan inventory data into a structured diagram model:
  - Containers: AWS Cloud → Region → VPC → AZ → Subnet
  - Nodes: individual resources placed in their containers
  - Groups: multi-AZ constructs (ALB, ASG, ECS, EKS, Aurora, etc.)
  - Edges: derived from real inventory data (targets, SGs, peering, etc.)
  - Tiles: aggregated regional service panels (S3 ×12, DynamoDB ×3, etc.)

The model is layout-agnostic — geometry is computed separately by layout.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Tier classification ─────────────────────────────────────────────

TIER_TAG = "strataledger:tier"
VALID_TIERS = {"public", "app", "data", "firewall"}
DATA_NAME_TOKENS = {"db", "data", "database", "rds", "cache", "isolated", "redis", "mongo", "elastic"}
NAME_SPLIT = re.compile(r"[-_.\s]+")


def classify_subnet_tier(
    subnet: dict,
    route_tables: list[dict],
    nfw_subnet_ids: set[str],
) -> str:
    """
    Classify a subnet's tier from its effective route table.

    Priority:
      1. Tag strataledger:tier if valid
      2. Network Firewall subnet mapping → firewall
      3. Default route destination: igw-* → public; nat-*/tgw-*/vpce-*/eni-*/pcx-*/i-* → app
      4. No default route → data (isolated)
      5. Tie-break: app subnet whose name has a data-store token → data
    """
    # 1. Explicit tag override
    tags = subnet.get("tags", {})
    tier_tag = tags.get(TIER_TAG, "").lower().strip()
    if tier_tag in VALID_TIERS:
        return tier_tag

    subnet_id = subnet.get("resource_id", subnet.get("subnet_id", ""))

    # 2. NFW subnet
    if subnet_id in nfw_subnet_ids:
        return "firewall"

    # 3. Route-table based classification
    effective_rt = _find_effective_route_table(subnet_id, subnet.get("vpc_id", ""), route_tables)
    tier = _tier_from_routes(effective_rt)

    # 5. Tie-break: app → data if name contains data-store tokens
    if tier == "app":
        name = (subnet.get("name", "") or "").lower()
        tokens = set(NAME_SPLIT.split(name)) if name else set()
        if tokens & DATA_NAME_TOKENS:
            return "data"

    return tier


def _find_effective_route_table(
    subnet_id: str, vpc_id: str, route_tables: list[dict],
) -> dict | None:
    """Find the route table explicitly associated with this subnet, or the VPC main table."""
    explicit = None
    main_rt = None
    for rt in route_tables:
        if rt.get("vpc_id") != vpc_id:
            continue
        associations = rt.get("associations", [])
        for assoc in associations:
            if assoc.get("subnet_id") == subnet_id:
                return rt
            if assoc.get("main", False):
                main_rt = rt
    return main_rt


def _tier_from_routes(rt: dict | None) -> str:
    """Classify tier from the default route (0.0.0.0/0 or ::/0) destination."""
    if rt is None:
        return "data"
    for route in rt.get("routes", []):
        dest = route.get("destination_cidr", "") or route.get("destination_ipv6_cidr", "")
        if dest not in ("0.0.0.0/0", "::/0"):
            continue
        if route.get("state") == "blackhole":
            continue
        # Check gateway/target
        target = (
            route.get("gateway_id", "")
            or route.get("nat_gateway_id", "")
            or route.get("transit_gateway_id", "")
            or route.get("vpc_endpoint_id", "")
            or route.get("network_interface_id", "")
            or route.get("instance_id", "")
            or route.get("vpc_peering_connection_id", "")
            or ""
        )
        if target.startswith("igw-"):
            return "public"
        if target:
            return "app"
    return "data"


# ── Data classes ────────────────────────────────────────────────────

@dataclass
class DiagramNode:
    """A resource icon in the diagram."""
    id: str
    resource_type: str
    label: str
    container_id: str  # subnet_id, or "global", or "regional_<region>"
    sublabel: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class DiagramGroup:
    """A multi-AZ construct spanning multiple subnets."""
    id: str
    label: str
    category: str  # compute, database, networking, storage, security
    subnet_ids: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)  # node IDs
    sublabel: str = ""


@dataclass
class DiagramEdge:
    """A connection between two nodes/tiles."""
    source: str
    target: str
    kind: str  # traffic, data, network, endpoint, egress, replication, security
    label: str = ""


@dataclass
class ServiceTile:
    """An aggregated tile for a regional managed service."""
    service: str
    icon: str  # resource_type for icon lookup
    count: int
    names: list[str] = field(default_factory=list)  # top 5 names


@dataclass
class SubnetModel:
    """A subnet with its tier and resources."""
    id: str
    name: str
    cidr: str
    az: str
    tier: str
    vpc_id: str
    nodes: list[str] = field(default_factory=list)  # node IDs


@dataclass
class AZModel:
    """An availability zone row."""
    name: str
    subnets: dict[str, SubnetModel] = field(default_factory=dict)  # tier → subnet


@dataclass
class VPCModel:
    """A VPC container."""
    id: str
    name: str
    cidr: str
    is_default: bool
    has_workloads: bool = False
    azs: dict[str, AZModel] = field(default_factory=dict)  # az_name → AZModel
    igw_id: str | None = None
    vgw_id: str | None = None
    endpoints: list[DiagramNode] = field(default_factory=list)
    groups: list[DiagramGroup] = field(default_factory=list)


@dataclass
class RegionModel:
    """A region container."""
    name: str
    vpcs: dict[str, VPCModel] = field(default_factory=dict)
    tiles: list[ServiceTile] = field(default_factory=list)
    gutter_nodes: list[DiagramNode] = field(default_factory=list)  # TGW, VPN, DX, etc.


@dataclass
class DiagramModel:
    """The complete diagram model for one account."""
    account_id: str
    account_alias: str
    regions: dict[str, RegionModel] = field(default_factory=dict)
    global_nodes: list[DiagramNode] = field(default_factory=list)
    edges: list[DiagramEdge] = field(default_factory=list)
    all_nodes: dict[str, DiagramNode] = field(default_factory=dict)
    hidden_default_vpcs: list[str] = field(default_factory=list)
    skipped_regions: list[str] = field(default_factory=list)


# ── Regional service tiles ──────────────────────────────────────────

TILE_SERVICES = {
    "s3_bucket": ("S3", "s3_bucket"),
    "dynamodb_table": ("DynamoDB", "dynamodb_table"),
    "kms_key": ("KMS", "kms_key"),
    "secret": ("Secrets Mgr", "secret"),
    "ecr_repository": ("ECR", "ecr_repository"),
    "sqs_queue": ("SQS", "sqs_queue"),
    "sns_topic": ("SNS", "sns_topic"),
    "cloudwatch_alarm": ("CloudWatch", "cloudwatch"),
    "cloudwatch_log_group": ("CloudWatch", "cloudwatch"),
    "eventbridge_rule": ("EventBridge", "eventbridge"),
    "ssm_parameter": ("SSM Params", "generic"),
}

# Resources that go in VPCs (placed in subnets/groups)
VPC_RESOURCE_TYPES = {
    "ec2_instance", "nat_gateway", "rds_instance", "rds_cluster",
    "ecs_service", "eks_cluster", "elasticache_replication_group",
    "elasticache_cluster", "opensearch_domain", "redshift_cluster",
    "efs_filesystem", "lambda_function", "network_firewall",
}


def _node_id(resource_type: str, resource_id: str) -> str:
    """Create a unique, type-prefixed node ID."""
    # Shorten ARNs to the meaningful part
    if ":" in resource_id:
        parts = resource_id.rsplit(":", 1)
        short = parts[-1].rsplit("/", 1)[-1]
    else:
        short = resource_id
    return f"{resource_type}:{short}"


def _safe_label(name: str, max_len: int = 30) -> str:
    """Truncate long names for display."""
    if len(name) <= max_len:
        return name
    return name[:max_len - 1] + "…"


# ── Builder ─────────────────────────────────────────────────────────

def build_diagram_model(
    account_id: str,
    account_alias: str,
    account_data: dict,
) -> DiagramModel:
    """
    Build a DiagramModel from one account's scan data.

    Args:
        account_id: AWS account ID
        account_alias: Account alias or ID
        account_data: The account dict from scan results
            (has keys "global", "regions")
    """
    model = DiagramModel(account_id=account_id, account_alias=account_alias)

    global_data = account_data.get("global", {})
    regions_data = account_data.get("regions", {})

    # ── Build global nodes ──────────────────────────────────────────
    _build_global_nodes(model, global_data)

    # ── Build each region ───────────────────────────────────────────
    for region_name, region_data in regions_data.items():
        region_model = _build_region(model, region_name, region_data, global_data)
        if region_model.vpcs or region_model.tiles or region_model.gutter_nodes:
            model.regions[region_name] = region_model
        else:
            model.skipped_regions.append(region_name)

    # ── Build edges ─────────────────────────────────────────────────
    _build_edges(model, account_data)

    return model


def _build_global_nodes(model: DiagramModel, global_data: dict) -> None:
    """Create global-column nodes: CloudFront, Route 53, IAM, Organizations."""
    # Route 53 hosted zones
    r53 = global_data.get("route53", {})
    zones = r53.get("route53_hosted_zones", [])
    if zones:
        node = DiagramNode(
            id="global:route53",
            resource_type="route53",
            label="Route 53",
            container_id="global",
            sublabel=f"{len(zones)} zones",
        )
        model.global_nodes.append(node)
        model.all_nodes[node.id] = node

    # IAM summary
    iam = global_data.get("iam", {})
    users = iam.get("iam_users", [])
    roles = iam.get("iam_roles", [])
    if users or roles:
        node = DiagramNode(
            id="global:iam",
            resource_type="iam_user",
            label="IAM",
            container_id="global",
            sublabel=f"{len(users)} users, {len(roles)} roles",
        )
        model.global_nodes.append(node)
        model.all_nodes[node.id] = node

    # Users/Internet node
    node = DiagramNode(
        id="global:users",
        resource_type="users",
        label="Users / Internet",
        container_id="global",
    )
    model.global_nodes.append(node)
    model.all_nodes[node.id] = node


def _build_region(
    model: DiagramModel,
    region_name: str,
    region_data: dict,
    global_data: dict,
) -> RegionModel:
    """Build a RegionModel from one region's inventory."""
    region = RegionModel(name=region_name)

    net = region_data.get("networking", {})
    compute = region_data.get("compute", {})
    storage = region_data.get("storage", {})
    identity = region_data.get("identity", {})
    security = region_data.get("security", {})
    monitoring = region_data.get("monitoring", {})

    # ── Lookups ─────────────────────────────────────────────────────
    subnets = net.get("subnets", [])
    route_tables = net.get("route_tables", [])
    igws = net.get("internet_gateways", [])
    vgws = net.get("vpn_gateways", [])
    nfws = security.get("network_firewalls", []) if "network_firewalls" in security else net.get("network_firewalls", [])

    # NFW subnet IDs
    nfw_subnet_ids: set[str] = set()
    for fw in nfws:
        for sid in fw.get("subnet_mappings", []):
            nfw_subnet_ids.add(sid)

    # Subnet lookup
    subnet_map: dict[str, dict] = {}
    for s in subnets:
        sid = s.get("resource_id", s.get("subnet_id", ""))
        subnet_map[sid] = s

    # VPC lookup
    vpcs_raw = net.get("vpcs", [])
    vpc_map: dict[str, dict] = {v.get("resource_id", v.get("vpc_id", "")): v for v in vpcs_raw}

    # IGW/VGW → VPC mapping
    igw_vpc: dict[str, str] = {}
    for gw in igws:
        for att in gw.get("attachments", []):
            vpc_id = att.get("vpc_id", att.get("VpcId", ""))
            if vpc_id:
                igw_vpc[gw.get("resource_id", "")] = vpc_id

    vgw_vpc: dict[str, str] = {}
    for gw in vgws:
        for att in gw.get("vpc_attachments", gw.get("attachments", [])):
            vpc_id = att.get("vpc_id", att.get("VpcId", ""))
            if vpc_id:
                vgw_vpc[gw.get("resource_id", "")] = vpc_id

    # ── Build VPCs ──────────────────────────────────────────────────
    for vpc_id, vpc_raw in vpc_map.items():
        vpc_name = vpc_raw.get("name", "") or vpc_id
        vpc_model = VPCModel(
            id=vpc_id,
            name=_safe_label(vpc_name),
            cidr=vpc_raw.get("cidr_block", ""),
            is_default=vpc_raw.get("is_default", False),
        )

        # Attach IGW/VGW
        for gw_id, gw_vpc in igw_vpc.items():
            if gw_vpc == vpc_id:
                vpc_model.igw_id = gw_id
        for gw_id, gw_vpc in vgw_vpc.items():
            if gw_vpc == vpc_id:
                vpc_model.vgw_id = gw_id

        # Build subnets into AZ rows
        for subnet_raw in subnets:
            s_vpc = subnet_raw.get("vpc_id", "")
            if s_vpc != vpc_id:
                continue
            sid = subnet_raw.get("resource_id", subnet_raw.get("subnet_id", ""))
            az = subnet_raw.get("availability_zone", "")
            tier = classify_subnet_tier(subnet_raw, route_tables, nfw_subnet_ids)
            s_name = subnet_raw.get("name", "") or sid
            s_cidr = subnet_raw.get("cidr_block", "")

            sm = SubnetModel(
                id=sid, name=_safe_label(s_name), cidr=s_cidr,
                az=az, tier=tier, vpc_id=vpc_id,
            )

            if az not in vpc_model.azs:
                vpc_model.azs[az] = AZModel(name=az)
            vpc_model.azs[az].subnets[tier] = sm

        # VPC endpoints
        for ep in net.get("vpc_endpoints", []):
            if ep.get("vpc_id") != vpc_id:
                continue
            svc_name = ep.get("service_name", "")
            short_svc = svc_name.rsplit(".", 1)[-1] if "." in svc_name else svc_name
            ep_node = DiagramNode(
                id=_node_id("vpc_endpoint", ep.get("resource_id", "")),
                resource_type="vpc_endpoint",
                label=short_svc,
                container_id=vpc_id,
                sublabel=ep.get("vpc_endpoint_type", ""),
            )
            vpc_model.endpoints.append(ep_node)
            model.all_nodes[ep_node.id] = ep_node

        region.vpcs[vpc_id] = vpc_model

    # ── Place resources in subnets ──────────────────────────────────
    _place_ec2(model, region, compute, subnet_map)
    _place_rds(model, region, storage, subnet_map)
    _place_nat_gateways(model, region, net, subnet_map)
    _place_ecs_services(model, region, compute, subnet_map)
    _place_eks_clusters(model, region, compute, subnet_map)
    _place_asgs(model, region, compute, subnet_map)
    _place_lambda_vpc(model, region, compute, subnet_map)
    _place_elasticache(model, region, storage, subnet_map)
    _place_nfw(model, region, nfws, subnet_map)

    # Mark VPCs with workloads
    for vpc_id, vpc_model in region.vpcs.items():
        for az in vpc_model.azs.values():
            for sm in az.subnets.values():
                if sm.nodes:
                    vpc_model.has_workloads = True
                    break
        if vpc_model.groups:
            vpc_model.has_workloads = True

    # Hide empty default VPCs
    to_remove = []
    for vpc_id, vpc_model in region.vpcs.items():
        if vpc_model.is_default and not vpc_model.has_workloads:
            to_remove.append(vpc_id)
            model.hidden_default_vpcs.append(f"{vpc_id} ({region_name})")
    for vpc_id in to_remove:
        del region.vpcs[vpc_id]

    # ── Gutter nodes (region-level, outside VPCs) ───────────────────
    for tgw in net.get("transit_gateways", []):
        node = DiagramNode(
            id=_node_id("transit_gateway", tgw.get("resource_id", "")),
            resource_type="transit_gateway",
            label=_safe_label(tgw.get("name", "") or tgw.get("resource_id", "")),
            container_id=f"gutter:{region_name}",
        )
        region.gutter_nodes.append(node)
        model.all_nodes[node.id] = node

    for vpn in net.get("vpn_connections", []):
        node = DiagramNode(
            id=_node_id("vpn_gateway", vpn.get("resource_id", "")),
            resource_type="vpn_gateway",
            label=_safe_label(vpn.get("name", "") or "VPN"),
            container_id=f"gutter:{region_name}",
        )
        region.gutter_nodes.append(node)
        model.all_nodes[node.id] = node

    for apigw in compute.get("api_gateway_rest", []) + net.get("api_gateway_rest", []):
        node = DiagramNode(
            id=_node_id("api_gateway_rest", apigw.get("resource_id", "")),
            resource_type="api_gateway_rest",
            label=_safe_label(apigw.get("name", "")),
            container_id=f"gutter:{region_name}",
        )
        region.gutter_nodes.append(node)
        model.all_nodes[node.id] = node

    # ── Service tiles (right panel) ─────────────────────────────────
    _build_tiles(region, region_data, global_data, region_name)

    return region


def _place_ec2(model: DiagramModel, region: RegionModel, compute: dict, subnet_map: dict) -> None:
    """Place EC2 instances in their subnets."""
    for inst in compute.get("ec2_instances", []):
        state = inst.get("state", "")
        if state == "terminated":
            continue
        subnet_id = inst.get("subnet_id", "")
        if not subnet_id:
            continue
        lifecycle = inst.get("lifecycle", "on-demand")
        rt = "ec2_spot" if lifecycle == "spot" else "ec2_instance"
        node = DiagramNode(
            id=_node_id("ec2_instance", inst.get("resource_id", "")),
            resource_type=rt,
            label=_safe_label(inst.get("name", "") or inst.get("resource_id", "")),
            container_id=subnet_id,
            sublabel=inst.get("instance_type", ""),
        )
        model.all_nodes[node.id] = node
        _add_to_subnet(region, subnet_id, node.id)


def _place_rds(model: DiagramModel, region: RegionModel, storage: dict, subnet_map: dict) -> None:
    """Place RDS instances in their subnets."""
    for db in storage.get("rds_instances", []):
        subnet_id = db.get("subnet_id", "")
        if not subnet_id:
            continue
        node = DiagramNode(
            id=_node_id("rds_instance", db.get("resource_id", "")),
            resource_type="rds_instance",
            label=_safe_label(db.get("name", "") or db.get("resource_id", "")),
            container_id=subnet_id,
            sublabel=db.get("engine", ""),
        )
        model.all_nodes[node.id] = node
        _add_to_subnet(region, subnet_id, node.id)

    # RDS clusters → groups spanning subnets
    for cluster in storage.get("rds_clusters", []):
        subnet_ids = cluster.get("subnet_ids", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id("rds_cluster", cluster.get("resource_id", "")),
            label=_safe_label(cluster.get("name", "") or "Aurora"),
            category="database",
            subnet_ids=subnet_ids,
            sublabel=cluster.get("engine", ""),
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _place_nat_gateways(model: DiagramModel, region: RegionModel, net: dict, subnet_map: dict) -> None:
    """Place NAT gateways in their subnets."""
    for nat in net.get("nat_gateways", []):
        subnet_id = nat.get("subnet_id", "")
        if not subnet_id:
            continue
        node = DiagramNode(
            id=_node_id("nat_gateway", nat.get("resource_id", "")),
            resource_type="nat_gateway",
            label="NAT",
            container_id=subnet_id,
        )
        model.all_nodes[node.id] = node
        _add_to_subnet(region, subnet_id, node.id)


def _place_ecs_services(model: DiagramModel, region: RegionModel, compute: dict, subnet_map: dict) -> None:
    """Place ECS services as groups spanning their subnets."""
    for svc in compute.get("ecs_services", []):
        subnet_ids = svc.get("subnet_ids", [])
        if not subnet_ids:
            continue  # non-awsvpc → goes to regional tile
        group = DiagramGroup(
            id=_node_id("ecs_service", svc.get("resource_id", "")),
            label=_safe_label(svc.get("name", "")),
            category="compute",
            subnet_ids=subnet_ids,
            sublabel=f"{svc.get('launch_type', '')} ×{svc.get('desired_count', 0)}",
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _place_eks_clusters(model: DiagramModel, region: RegionModel, compute: dict, subnet_map: dict) -> None:
    """Place EKS clusters as groups spanning their node group subnets."""
    for cluster in compute.get("eks_clusters", []):
        # Prefer node group subnets over cluster subnets
        all_subnets: set[str] = set()
        for ng in cluster.get("node_groups", []):
            all_subnets.update(ng.get("subnet_ids", []))
        if not all_subnets:
            all_subnets = set(cluster.get("subnet_ids", []))
        if not all_subnets:
            continue
        group = DiagramGroup(
            id=_node_id("eks_cluster", cluster.get("resource_id", "")),
            label=_safe_label(cluster.get("name", "")),
            category="compute",
            subnet_ids=list(all_subnets),
            sublabel=f"EKS {cluster.get('version', '')}",
        )
        _add_group_to_vpc(region, list(all_subnets), group)


def _place_asgs(model: DiagramModel, region: RegionModel, compute: dict, subnet_map: dict) -> None:
    """Place ASGs as groups spanning their subnets."""
    for asg in compute.get("auto_scaling_groups", []):
        subnet_ids = asg.get("subnet_ids", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id("auto_scaling_group", asg.get("resource_id", asg.get("name", ""))),
            label=_safe_label(asg.get("name", "")),
            category="compute",
            subnet_ids=subnet_ids,
            sublabel=f"min={asg.get('min_size', 0)} max={asg.get('max_size', 0)}",
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _place_lambda_vpc(model: DiagramModel, region: RegionModel, compute: dict, subnet_map: dict) -> None:
    """Place VPC-attached Lambda functions. Non-VPC Lambdas go to tiles."""
    vpc_lambdas: dict[tuple, list[dict]] = {}  # (frozenset(subnets),) → functions
    for fn in compute.get("lambda_functions", []):
        vpc_config = fn.get("vpc_config", {})
        subnet_ids = vpc_config.get("SubnetIds", [])
        if not subnet_ids:
            continue  # non-VPC → tile
        key = tuple(sorted(subnet_ids))
        vpc_lambdas.setdefault(key, []).append(fn)

    for subnet_tuple, fns in vpc_lambdas.items():
        subnet_ids = list(subnet_tuple)
        count = len(fns)
        label = fns[0].get("name", "Lambda") if count == 1 else f"Lambda ×{count}"
        group = DiagramGroup(
            id=f"lambda_group:{'_'.join(subnet_ids[:3])}",
            label=label,
            category="compute",
            subnet_ids=subnet_ids,
            sublabel="VPC Lambda",
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _place_elasticache(model: DiagramModel, region: RegionModel, storage: dict, subnet_map: dict) -> None:
    """Place ElastiCache replication groups as groups."""
    for rg in storage.get("elasticache_replication_groups", []):
        subnet_ids = rg.get("subnet_ids", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id("elasticache_replication_group", rg.get("resource_id", "")),
            label=_safe_label(rg.get("name", "") or "ElastiCache"),
            category="database",
            subnet_ids=subnet_ids,
            sublabel=rg.get("engine", ""),
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _place_nfw(model: DiagramModel, region: RegionModel, nfws: list[dict], subnet_map: dict) -> None:
    """Place Network Firewalls as groups in their subnets."""
    for fw in nfws:
        subnet_ids = fw.get("subnet_mappings", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id("network_firewall", fw.get("resource_id", "")),
            label=_safe_label(fw.get("name", "") or "NFW"),
            category="security",
            subnet_ids=subnet_ids,
        )
        _add_group_to_vpc(region, subnet_ids, group)


def _add_to_subnet(region: RegionModel, subnet_id: str, node_id: str) -> None:
    """Add a node ID to the right subnet in the region model."""
    for vpc in region.vpcs.values():
        for az in vpc.azs.values():
            for sm in az.subnets.values():
                if sm.id == subnet_id:
                    sm.nodes.append(node_id)
                    return


def _add_group_to_vpc(region: RegionModel, subnet_ids: list[str], group: DiagramGroup) -> None:
    """Attach a group to the VPC that contains its subnets."""
    for vpc in region.vpcs.values():
        for az in vpc.azs.values():
            for sm in az.subnets.values():
                if sm.id in subnet_ids:
                    vpc.groups.append(group)
                    return


def _build_tiles(
    region: RegionModel,
    region_data: dict,
    global_data: dict,
    region_name: str,
) -> None:
    """Build aggregated service tiles for the region's right panel."""
    tile_counts: dict[str, tuple[str, str, int, list[str]]] = {}

    def _count(resources: list[dict], resource_type: str) -> None:
        if resource_type not in TILE_SERVICES:
            return
        display_name, icon = TILE_SERVICES[resource_type]
        key = display_name
        if key not in tile_counts:
            tile_counts[key] = (display_name, icon, 0, [])
        name, icon_key, count, names = tile_counts[key]
        tile_counts[key] = (name, icon_key, count + len(resources), names + [
            r.get("name", "") for r in resources[:5]
        ])

    # Regional resources
    for category_data in region_data.values():
        if not isinstance(category_data, dict):
            continue
        for rtype, rlist in category_data.items():
            if isinstance(rtype, str) and rtype.startswith("_"):
                continue
            if isinstance(rlist, list):
                _count(rlist, rtype)

    # S3 (global but shown per-account)
    s3_data = global_data.get("s3", {})
    s3_buckets = s3_data.get("s3_buckets", [])
    if s3_buckets and region_name == next(iter(region_data), ""):
        _count(s3_buckets, "s3_bucket")

    # Non-VPC Lambdas
    lambdas = region_data.get("compute", {}).get("lambda_functions", [])
    non_vpc = [f for f in lambdas if not (f.get("vpc_config") or {}).get("SubnetIds")]
    if non_vpc:
        key = "Lambda"
        tile_counts[key] = ("Lambda", "lambda_function", len(non_vpc), [
            f.get("name", "") for f in non_vpc[:5]
        ])

    for name, (display_name, icon, count, names) in sorted(tile_counts.items()):
        if count > 0:
            region.tiles.append(ServiceTile(
                service=display_name,
                icon=icon,
                count=count,
                names=names[:5],
            ))


def _build_edges(model: DiagramModel, account_data: dict) -> None:
    """Build all edges from inventory data."""
    global_data = account_data.get("global", {})
    regions_data = account_data.get("regions", {})

    # ── Route 53 alias → resource edges ─────────────────────────────
    r53 = global_data.get("route53", {})
    for zone in r53.get("route53_hosted_zones", []):
        for alias in zone.get("alias_targets", []):
            dns = alias.get("dns_name", "")
            if not dns:
                continue
            target_id = _find_node_by_dns(model, dns)
            if target_id:
                model.edges.append(DiagramEdge(
                    source="global:route53",
                    target=target_id,
                    kind="traffic",
                    label=alias.get("name", ""),
                ))

    for region_name, region_data in regions_data.items():
        net = region_data.get("networking", {})
        compute = region_data.get("compute", {})
        storage = region_data.get("storage", {})

        # ── LB → target edges ──────────────────────────────────────
        for tg in net.get("target_groups", []):
            tg_arn = tg.get("resource_id", "")
            tg_node_id = _node_id("target_group", tg_arn)
            for lb_arn in tg.get("load_balancer_arns", []):
                lb_id = _node_id("load_balancer_v2", lb_arn)
                if lb_id in model.all_nodes:
                    model.edges.append(DiagramEdge(
                        source=lb_id, target=tg_node_id,
                        kind="traffic",
                    ))
            for t in tg.get("targets", []):
                tid = t.get("id", "")
                if tid.startswith("i-"):
                    target_node = _node_id("ec2_instance", tid)
                    if target_node in model.all_nodes:
                        model.edges.append(DiagramEdge(
                            source=tg_node_id, target=target_node,
                            kind="traffic",
                        ))

        # ── NAT → IGW (same VPC) ───────────────────────────────────
        for nat in net.get("nat_gateways", []):
            nat_id = _node_id("nat_gateway", nat.get("resource_id", ""))
            nat_vpc = nat.get("vpc_id", "")
            if nat_vpc in model.regions.get(region_name, RegionModel(name="")).vpcs:
                vpc_model = model.regions[region_name].vpcs[nat_vpc]
                if vpc_model.igw_id:
                    model.edges.append(DiagramEdge(
                        source=nat_id,
                        target=_node_id("igw", vpc_model.igw_id),
                        kind="egress",
                    ))

        # ── TGW attachments ────────────────────────────────────────
        for att in net.get("transit_gateway_attachments", []):
            tgw_id = att.get("transit_gateway_id", "")
            vpc_id = att.get("resource_id", "")  # attached VPC
            tgw_node = _node_id("transit_gateway", tgw_id)
            if tgw_node in model.all_nodes:
                model.edges.append(DiagramEdge(
                    source=tgw_node,
                    target=f"vpc:{vpc_id}",
                    kind="network",
                ))

        # ── VPC peering ────────────────────────────────────────────
        for peer in net.get("vpc_peering_connections", []):
            req = peer.get("requester_vpc_id", "")
            acc = peer.get("accepter_vpc_id", "")
            if req and acc:
                model.edges.append(DiagramEdge(
                    source=f"vpc:{req}",
                    target=f"vpc:{acc}",
                    kind="network",
                    label="Peering",
                ))

    # ── Cross-region replication edges ──────────────────────────────
    _build_replication_edges(model, account_data)


def _build_replication_edges(model: DiagramModel, account_data: dict) -> None:
    """Build cross-region replication arrows."""
    global_data = account_data.get("global", {})
    regions_data = account_data.get("regions", {})

    # S3 CRR
    s3_data = global_data.get("s3", {})
    for bucket in s3_data.get("s3_buckets", []):
        for rule in bucket.get("replication_rules", []):
            dest = rule.get("destination_bucket", "")
            if dest:
                model.edges.append(DiagramEdge(
                    source=_node_id("s3_bucket", bucket.get("resource_id", "")),
                    target=_node_id("s3_bucket", dest),
                    kind="replication",
                    label="S3 CRR",
                ))

    # DynamoDB global tables
    for region_name, region_data in regions_data.items():
        for table in region_data.get("storage", {}).get("dynamodb_tables", []):
            for replica_region in table.get("replica_regions", []):
                if replica_region != region_name:
                    model.edges.append(DiagramEdge(
                        source=f"tile:{region_name}:DynamoDB",
                        target=f"tile:{replica_region}:DynamoDB",
                        kind="replication",
                        label="Global Table",
                    ))

    # KMS multi-region keys
    for region_name, region_data in regions_data.items():
        for key in region_data.get("identity", {}).get("kms_keys", []):
            if key.get("multi_region") and key.get("multi_region_type") == "PRIMARY":
                for replica_region in key.get("replica_regions", []):
                    model.edges.append(DiagramEdge(
                        source=f"tile:{region_name}:KMS",
                        target=f"tile:{replica_region}:KMS",
                        kind="replication",
                        label="Multi-Region Key",
                    ))

    # ECR replication
    for region_name, region_data in regions_data.items():
        ecr_repl = region_data.get("compute", {}).get("_ecr_replication", [])
        for dest in ecr_repl:
            dest_region = dest.get("region", "")
            if dest_region and dest_region != region_name:
                model.edges.append(DiagramEdge(
                    source=f"tile:{region_name}:ECR",
                    target=f"tile:{dest_region}:ECR",
                    kind="replication",
                    label="ECR Replication",
                ))


def _find_node_by_dns(model: DiagramModel, dns: str) -> str | None:
    """Find a node by matching its DNS name."""
    dns_lower = dns.lower().rstrip(".")
    for node in model.all_nodes.values():
        node_dns = node.data.get("dns_name", "")
        if node_dns and dns_lower == node_dns.lower().rstrip("."):
            return node.id
    return None
