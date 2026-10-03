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
    container_id: str  # subnet_id, "group", "global", or "gutter:<region>"
    sublabel: str = ""
    data: dict = field(default_factory=dict)
    # Child resources drawn as mini icons under the parent (EC2 → EBS, EIP)
    attachments: list[tuple[str, str]] = field(default_factory=list)
    tooltip: str = ""


@dataclass
class DiagramGroup:
    """A multi-AZ construct spanning multiple subnets."""
    id: str
    label: str
    category: str  # compute, database, networking, storage, security
    subnet_ids: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)  # node IDs drawn inside the group card
    sublabel: str = ""
    icon: str = ""  # parent resource type shown in the card header


@dataclass
class DiagramEdge:
    """A connection between two nodes/groups/tiles/containers."""
    source: str
    target: str
    kind: str  # traffic, data, network, endpoint, egress, replication, security
    label: str = ""


@dataclass
class ServiceTile:
    """An aggregated tile for a regional managed service."""
    service: str
    icon: str
    count: int
    names: list[str] = field(default_factory=list)


@dataclass
class SubnetModel:
    """A subnet with its tier and resources."""
    id: str
    name: str
    cidr: str
    az: str
    tier: str
    vpc_id: str
    nodes: list[str] = field(default_factory=list)


@dataclass
class AZModel:
    """An availability zone row."""
    name: str
    # Keyed by tier; extra subnets of the same tier get "tier#2", "tier#3"…
    subnets: dict[str, SubnetModel] = field(default_factory=dict)


@dataclass
class VPCModel:
    """A VPC container."""
    id: str
    name: str
    cidr: str
    is_default: bool
    has_workloads: bool = False
    azs: dict[str, AZModel] = field(default_factory=dict)
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
    gutter_nodes: list[DiagramNode] = field(default_factory=list)


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
    dns_index: dict[str, str] = field(default_factory=dict)  # dns name → node/group id


# ── Regional service tiles ──────────────────────────────────────────

# Keys are the inventory list keys produced by the collectors.
TILE_SERVICES = {
    "dynamodb_tables": ("DynamoDB", "dynamodb_table"),
    "kms_keys": ("KMS", "kms_key"),
    "secrets": ("Secrets Mgr", "secret"),
    "ecr_repositories": ("ECR", "ecr_repository"),
    "sqs_queues": ("SQS", "sqs_queue"),
    "sns_topics": ("SNS", "sns_topic"),
    "cloudwatch_alarms": ("CloudWatch", "cloudwatch"),
    "cloudwatch_log_groups": ("CloudWatch", "cloudwatch"),
    "eventbridge_rules": ("EventBridge", "eventbridge"),
    "ssm_parameters": ("SSM Params", "generic"),
    "ebs_snapshots": ("EBS Snaps", "ebs_volume"),
    "rds_snapshots": ("RDS Snaps", "rds_instance"),
    "backup_vaults": ("Backup", "backup"),
    "backup_plans": ("Backup", "backup"),
    "guardduty_detectors": ("GuardDuty", "guardduty"),
    "acm_certificates": ("ACM", "acm"),
    "cloudhsm_clusters": ("CloudHSM", "cloudhsm"),
    "ecs_clusters": ("ECS", "ecs_cluster"),
    "ec2_amis": ("AMIs", "ec2_instance"),
}

MAX_GROUP_MEMBERS = 8


def _node_id(resource_type: str, resource_id: str) -> str:
    """Create a unique, type-prefixed node ID."""
    if ":" in resource_id:
        short = resource_id.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    else:
        short = resource_id
    return f"{resource_type}:{short}"


def _safe_label(name: str, max_len: int = 30) -> str:
    """Truncate long names for display."""
    name = name or ""
    if len(name) <= max_len:
        return name
    return name[:max_len - 1] + "…"


def _register(model: DiagramModel, node: DiagramNode) -> DiagramNode:
    model.all_nodes[node.id] = node
    return node


def _members_with_overflow(model: DiagramModel, group_id: str, ids: list[str]) -> list[str]:
    """Cap members, replacing the tail with a '+N more' chip node."""
    if len(ids) <= MAX_GROUP_MEMBERS:
        return ids
    keep = ids[:MAX_GROUP_MEMBERS - 1]
    chip = _register(model, DiagramNode(
        id=f"overflow:{group_id}", resource_type="generic",
        label=f"+{len(ids) - len(keep)} more", container_id="group",
    ))
    return keep + [chip.id]


def _normalize_dns(dns: str) -> str:
    dns = (dns or "").lower().rstrip(".")
    return dns[len("dualstack."):] if dns.startswith("dualstack.") else dns


# ── Builder ─────────────────────────────────────────────────────────

def build_diagram_model(
    account_id: str,
    account_alias: str,
    account_data: dict,
) -> DiagramModel:
    """Build a DiagramModel from one account's scan data ({"global":…, "regions":…})."""
    model = DiagramModel(account_id=account_id, account_alias=account_alias)

    global_data = account_data.get("global", {})
    regions_data = account_data.get("regions", {})

    _build_global_nodes(model, global_data)

    first_region = next(iter(regions_data), "")
    for region_name, region_data in regions_data.items():
        region_model = _build_region(
            model, region_name, region_data, global_data, region_name == first_region,
        )
        if region_model.vpcs or region_model.tiles or region_model.gutter_nodes:
            model.regions[region_name] = region_model
        else:
            model.skipped_regions.append(region_name)

    _build_edges(model, account_data)
    return model


def _build_global_nodes(model: DiagramModel, global_data: dict) -> None:
    """Create global-column nodes: Route 53, IAM, CloudFront, Users."""
    zones = global_data.get("route53", {}).get("route53_hosted_zones", [])
    if zones:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:route53", resource_type="route53", label="Route 53",
            container_id="global", sublabel=f"{len(zones)} zones",
        )))

    iam = global_data.get("iam", {})
    users = iam.get("iam_users", [])
    roles = iam.get("iam_roles", [])
    if users or roles:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:iam", resource_type="iam_user", label="IAM",
            container_id="global", sublabel=f"{len(users)} users, {len(roles)} roles",
        )))

    distributions: list = []
    for cat_data in global_data.values():
        if isinstance(cat_data, dict) and cat_data.get("cloudfront_distributions"):
            distributions = cat_data["cloudfront_distributions"]
            break
    if distributions:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:cloudfront", resource_type="cloudfront", label="CloudFront",
            container_id="global", sublabel=f"{len(distributions)} distributions",
        )))
        for d in distributions:
            if d.get("domain_name"):
                model.dns_index[_normalize_dns(d["domain_name"])] = "global:cloudfront"

    model.global_nodes.append(_register(model, DiagramNode(
        id="global:users", resource_type="users", label="Users / Internet",
        container_id="global",
    )))


def _build_region(
    model: DiagramModel,
    region_name: str,
    region_data: dict,
    global_data: dict,
    is_first_region: bool,
) -> RegionModel:
    """Build a RegionModel from one region's inventory."""
    region = RegionModel(name=region_name)

    net = region_data.get("networking", {})
    compute = region_data.get("compute", {})
    storage = region_data.get("storage", {})
    security = region_data.get("security", {})

    subnets = net.get("subnets", [])
    route_tables = net.get("route_tables", [])
    nfws = net.get("network_firewalls", []) or security.get("network_firewalls", [])

    nfw_subnet_ids: set[str] = set()
    for fw in nfws:
        nfw_subnet_ids.update(fw.get("subnet_mappings", []))

    igw_vpc: dict[str, str] = {}
    for gw in net.get("internet_gateways", []):
        for att in gw.get("attachments", []):
            vpc_id = att.get("vpc_id", att.get("VpcId", ""))
            if vpc_id:
                igw_vpc[gw.get("resource_id", "")] = vpc_id

    vgw_vpc: dict[str, str] = {}
    for gw in net.get("vpn_gateways", []):
        for att in gw.get("vpc_attachments", gw.get("attachments", [])):
            vpc_id = att.get("vpc_id", att.get("VpcId", ""))
            if vpc_id:
                vgw_vpc[gw.get("resource_id", "")] = vpc_id

    # ── VPCs, AZs, subnets ──────────────────────────────────────────
    for vpc_raw in net.get("vpcs", []):
        vpc_id = vpc_raw.get("resource_id", vpc_raw.get("vpc_id", ""))
        vpc_model = VPCModel(
            id=vpc_id,
            name=_safe_label(vpc_raw.get("name", "") or vpc_id),
            cidr=vpc_raw.get("cidr_block", ""),
            is_default=vpc_raw.get("is_default", False),
        )
        for gw_id, gw_vpc in igw_vpc.items():
            if gw_vpc == vpc_id:
                vpc_model.igw_id = gw_id
        for gw_id, gw_vpc in vgw_vpc.items():
            if gw_vpc == vpc_id:
                vpc_model.vgw_id = gw_id

        for subnet_raw in subnets:
            if subnet_raw.get("vpc_id", "") != vpc_id:
                continue
            sid = subnet_raw.get("resource_id", subnet_raw.get("subnet_id", ""))
            az = subnet_raw.get("availability_zone", "")
            tier = classify_subnet_tier(subnet_raw, route_tables, nfw_subnet_ids)
            sm = SubnetModel(
                id=sid, name=_safe_label(subnet_raw.get("name", "") or sid),
                cidr=subnet_raw.get("cidr_block", ""), az=az, tier=tier, vpc_id=vpc_id,
            )
            az_model = vpc_model.azs.setdefault(az, AZModel(name=az))
            key, n = tier, 2
            while key in az_model.subnets:
                key = f"{tier}#{n}"
                n += 1
            az_model.subnets[key] = sm

        for ep in net.get("vpc_endpoints", []):
            if ep.get("vpc_id") != vpc_id:
                continue
            svc_name = ep.get("service_name", "")
            ep_node = _register(model, DiagramNode(
                id=_node_id("vpc_endpoint", ep.get("resource_id", "")),
                resource_type="vpc_endpoint",
                label=svc_name.rsplit(".", 1)[-1] if "." in svc_name else svc_name,
                container_id=vpc_id,
                sublabel=ep.get("endpoint_type") or ep.get("vpc_endpoint_type", ""),
                tooltip=svc_name,
            ))
            vpc_model.endpoints.append(ep_node)

        region.vpcs[vpc_id] = vpc_model

    # ── Resources ───────────────────────────────────────────────────
    _place_ec2(model, region, compute, storage, net)
    _place_nat_gateways(model, region, net)
    _place_load_balancers(model, region, net)
    _place_rds(model, region, storage)
    _place_ecs_services(model, region, compute)
    _place_eks_clusters(model, region, compute)
    _place_asgs(model, region, compute)
    _place_lambda_vpc(model, region, compute)
    _place_elasticache(model, region, storage)
    _place_opensearch(model, region, storage)
    _place_redshift(model, region, storage)
    _place_efs(model, region, storage)
    _place_nfw(model, region, nfws)

    for vpc_model in region.vpcs.values():
        vpc_model.has_workloads = bool(vpc_model.groups) or any(
            sm.nodes for az in vpc_model.azs.values() for sm in az.subnets.values()
        )

    for vpc_id in [v for v, m in region.vpcs.items() if m.is_default and not m.has_workloads]:
        del region.vpcs[vpc_id]
        model.hidden_default_vpcs.append(f"{vpc_id} ({region_name})")

    _build_gutter(model, region, net, security)
    _build_tiles(region, region_data, global_data, is_first_region)
    return region


def _gutter(model: DiagramModel, region: RegionModel, node: DiagramNode) -> None:
    region.gutter_nodes.append(_register(model, node))


def _build_gutter(model: DiagramModel, region: RegionModel, net: dict, security: dict) -> None:
    """Region-level connectivity and edge services, outside VPCs."""
    gutter_id = f"gutter:{region.name}"

    for tgw in net.get("transit_gateways", []):
        tgw_id = tgw.get("resource_id", "")
        n_att = sum(1 for a in net.get("transit_gateway_attachments", [])
                    if a.get("transit_gateway_id") == tgw_id)
        _gutter(model, region, DiagramNode(
            id=_node_id("transit_gateway", tgw_id), resource_type="transit_gateway",
            label=_safe_label(tgw.get("name", "") or tgw_id), container_id=gutter_id,
            sublabel=f"{n_att} attachments" if n_att else "",
        ))

    for cgw in net.get("customer_gateways", []):
        _gutter(model, region, DiagramNode(
            id=_node_id("customer_gateway", cgw.get("resource_id", "")),
            resource_type="customer_gateway",
            label=_safe_label(cgw.get("name", "") or cgw.get("resource_id", "") or "CGW"),
            container_id=gutter_id, sublabel=cgw.get("ip_address", ""),
        ))

    for vpn in net.get("vpn_connections", []):
        tunnels = vpn.get("tunnels", [])
        up = sum(1 for t in tunnels if (t.get("status") or "").upper() == "UP")
        _gutter(model, region, DiagramNode(
            id=_node_id("vpn_connection", vpn.get("resource_id", "")),
            resource_type="vpn_connection",
            label=_safe_label(vpn.get("name", "") or vpn.get("resource_id", "") or "VPN"),
            container_id=gutter_id,
            sublabel=f"{up}/{len(tunnels)} tunnels up" if tunnels else "",
        ))

    for dx in net.get("direct_connect_connections", []):
        _gutter(model, region, DiagramNode(
            id=_node_id("direct_connect", dx.get("resource_id", "")),
            resource_type="direct_connect",
            label=_safe_label(dx.get("name", "") or "DX"), container_id=gutter_id,
            sublabel=dx.get("bandwidth", ""),
        ))

    for apigw in net.get("api_gateway_rest_apis", []):
        _gutter(model, region, DiagramNode(
            id=_node_id("api_gateway_rest", apigw.get("resource_id", "")),
            resource_type="api_gateway_rest",
            label=_safe_label(apigw.get("name", "")), container_id=gutter_id,
            sublabel=", ".join(apigw.get("endpoint_types", [])),
        ))

    for apigw in net.get("api_gateway_http_apis", []):
        node = DiagramNode(
            id=_node_id("api_gateway_http", apigw.get("resource_id", "")),
            resource_type="api_gateway_http",
            label=_safe_label(apigw.get("name", "")), container_id=gutter_id,
            sublabel=apigw.get("protocol_type", ""),
        )
        _gutter(model, region, node)
        if apigw.get("api_endpoint"):
            host = apigw["api_endpoint"].split("://", 1)[-1].split("/", 1)[0]
            model.dns_index[_normalize_dns(host)] = node.id

    for waf in net.get("waf_web_acls", []) or security.get("waf_web_acls", []):
        n_res = len(waf.get("associated_resources", []))
        _gutter(model, region, DiagramNode(
            id=_node_id("waf_web_acl", waf.get("resource_id", "")),
            resource_type="waf_web_acl",
            label=_safe_label(waf.get("name", "") or "WAF"), container_id=gutter_id,
            sublabel=f"protects {n_res}" if n_res else "unassociated",
        ))


# ── Placement helpers ───────────────────────────────────────────────

def _find_subnet(region: RegionModel, subnet_id: str) -> SubnetModel | None:
    for vpc in region.vpcs.values():
        for az in vpc.azs.values():
            for sm in az.subnets.values():
                if sm.id == subnet_id:
                    return sm
    return None


def _add_to_subnet(region: RegionModel, subnet_id: str, node_id: str) -> bool:
    sm = _find_subnet(region, subnet_id)
    if sm is None:
        return False
    sm.nodes.append(node_id)
    return True


def _add_group_to_vpc(region: RegionModel, subnet_ids: list[str], group: DiagramGroup) -> bool:
    """Attach a group to the VPC that contains its subnets."""
    for vpc in region.vpcs.values():
        for az in vpc.azs.values():
            for sm in az.subnets.values():
                if sm.id in subnet_ids:
                    vpc.groups.append(group)
                    return True
    return False


def _place_ec2(model: DiagramModel, region: RegionModel, compute: dict, storage: dict, net: dict) -> None:
    """Place EC2 instances with their EBS volumes and Elastic IPs attached."""
    volumes_by_instance: dict[str, list[dict]] = {}
    for vol in storage.get("ebs_volumes", []):
        for att in vol.get("attachments", []):
            if att.get("instance_id"):
                volumes_by_instance.setdefault(att["instance_id"], []).append(vol)

    eips_by_instance: dict[str, list[dict]] = {}
    for eip in net.get("elastic_ips", []):
        if eip.get("instance_id"):
            eips_by_instance.setdefault(eip["instance_id"], []).append(eip)

    for inst in compute.get("ec2_instances", []):
        if inst.get("state", "") == "terminated":
            continue
        subnet_id = inst.get("subnet_id", "")
        if not subnet_id:
            continue
        iid = inst.get("resource_id", "")
        attachments: list[tuple[str, str]] = []
        tip = [f"{inst.get('name') or iid} ({iid})", f"{inst.get('instance_type', '')} · {inst.get('state', '')}"]
        for vol in volumes_by_instance.get(iid, []):
            label = f"{vol.get('size_gb', '?')}G {vol.get('volume_type', '')}".strip()
            attachments.append(("ebs_volume", label))
            dev = next((a.get("device") for a in vol.get("attachments", [])
                        if a.get("instance_id") == iid), "")
            tip.append(f"EBS {vol.get('resource_id', '')} {label} {dev or ''}".rstrip())
        for eip in eips_by_instance.get(iid, []):
            attachments.append(("elastic_ip", eip.get("public_ip", "EIP")))
            tip.append(f"EIP {eip.get('public_ip', '')}")
        if inst.get("security_groups"):
            tip.append("SG " + ", ".join(sg.get("name") or sg.get("id", "") for sg in inst["security_groups"]))

        node = _register(model, DiagramNode(
            id=_node_id("ec2_instance", iid),
            resource_type="ec2_spot" if inst.get("lifecycle") == "spot" else "ec2_instance",
            label=_safe_label(inst.get("name", "") or iid),
            container_id=subnet_id,
            sublabel=inst.get("instance_type", ""),
            attachments=attachments,
            tooltip="\n".join(tip),
        ))
        _add_to_subnet(region, subnet_id, node.id)


def _place_nat_gateways(model: DiagramModel, region: RegionModel, net: dict) -> None:
    for nat in net.get("nat_gateways", []):
        subnet_id = nat.get("subnet_id", "")
        if not subnet_id:
            continue
        attachments = [("elastic_ip", nat["public_ip"])] if nat.get("public_ip") else []
        node = _register(model, DiagramNode(
            id=_node_id("nat_gateway", nat.get("resource_id", "")),
            resource_type="nat_gateway",
            label=_safe_label(nat.get("name", "") or "NAT"),
            container_id=subnet_id,
            sublabel=nat.get("connectivity_type", "") if nat.get("connectivity_type") == "private" else "",
            attachments=attachments,
            tooltip=f"{nat.get('resource_id', '')}\npublic {nat.get('public_ip') or '-'} · private {nat.get('private_ip') or '-'}",
        ))
        _add_to_subnet(region, subnet_id, node.id)


def _place_load_balancers(model: DiagramModel, region: RegionModel, net: dict) -> None:
    """ALB/NLB groups containing their target groups; CLB groups."""
    tgs_by_lb: dict[str, list[dict]] = {}
    for tg in net.get("target_groups", []):
        lbs = tg.get("load_balancer_arns", [])
        if lbs:
            tgs_by_lb.setdefault(lbs[0], []).append(tg)

    for lb in net.get("load_balancers_v2", []):
        subnet_ids = lb.get("subnet_ids", [])
        if not subnet_ids:
            continue
        arn = lb.get("resource_id", "")
        members: list[str] = []
        for tg in tgs_by_lb.get(arn, []):
            targets = tg.get("targets", [])
            healthy = sum(1 for t in targets if t.get("state") == "healthy")
            member = _register(model, DiagramNode(
                id=_node_id("target_group", tg.get("resource_id", "")),
                resource_type="target_group",
                label=_safe_label(tg.get("name", "")),
                container_id="group",
                sublabel=f"{tg.get('protocol') or ''}:{tg.get('port') or ''} · {healthy}/{len(targets)}",
                tooltip=f"{tg.get('name', '')} ({tg.get('target_type', '')})\n"
                        f"{healthy}/{len(targets)} healthy targets",
            ))
            members.append(member.id)
        listeners = ", ".join(
            f"{l.get('protocol')}:{l.get('port')}" for l in lb.get("listeners", [])
        )
        group = DiagramGroup(
            id=_node_id("load_balancer_v2", arn),
            label=_safe_label(lb.get("name", "")),
            category="networking",
            subnet_ids=subnet_ids,
            members=_members_with_overflow(model, _node_id("load_balancer_v2", arn), members),
            sublabel=" ".join(x for x in [
                {"application": "ALB", "network": "NLB", "gateway": "GWLB"}.get(lb.get("type", ""), "ELB"),
                lb.get("scheme", "") or "", listeners,
            ] if x),
            icon="load_balancer_v2",
        )
        if _add_group_to_vpc(region, subnet_ids, group) and lb.get("dns_name"):
            model.dns_index[_normalize_dns(lb["dns_name"])] = group.id

    for lb in net.get("load_balancers_classic", []):
        subnet_ids = lb.get("subnet_ids", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id("load_balancer_classic", lb.get("resource_id", "")),
            label=_safe_label(lb.get("name", "")),
            category="networking",
            subnet_ids=subnet_ids,
            sublabel=f"CLB · {len(lb.get('instances', []))} instances",
            icon="load_balancer_classic",
        )
        if _add_group_to_vpc(region, subnet_ids, group) and lb.get("dns_name"):
            model.dns_index[_normalize_dns(lb["dns_name"])] = group.id


def _place_rds(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    """Standalone RDS instances in subnets; Aurora clusters as groups containing their instances."""
    instances = storage.get("rds_instances", [])
    by_name = {db.get("name", ""): db for db in instances}
    clustered: set[str] = set()

    for cluster in storage.get("rds_clusters", []):
        members: list[str] = []
        subnet_ids: list[str] = []
        for m in cluster.get("members", []):
            db = by_name.get(m.get("instance_id", ""))
            if not db:
                continue
            clustered.add(db.get("name", ""))
            role = "writer" if m.get("is_writer") else "reader"
            node = _register(model, DiagramNode(
                id=_node_id("rds_instance", db.get("resource_id", "")),
                resource_type="rds_instance",
                label=_safe_label(db.get("name", "")),
                container_id="group",
                sublabel=f"{role} · {db.get('availability_zone') or ''}",
                tooltip=f"{db.get('name', '')} {db.get('instance_class', '')}",
            ))
            members.append(node.id)
            if db.get("subnet_id"):
                subnet_ids.append(db["subnet_id"])
            elif not subnet_ids:
                subnet_ids.extend(db.get("subnet_ids", []))
        if not subnet_ids:
            continue
        gid = _node_id("rds_cluster", cluster.get("resource_id", ""))
        group = DiagramGroup(
            id=gid,
            label=_safe_label(cluster.get("name", "") or "Aurora"),
            category="database",
            subnet_ids=sorted(set(subnet_ids)),
            members=_members_with_overflow(model, gid, members),
            sublabel=f"{cluster.get('engine', '')} {cluster.get('engine_mode') or ''}".strip(),
            icon="rds_cluster",
        )
        if _add_group_to_vpc(region, group.subnet_ids, group):
            for ep in (cluster.get("endpoint"), cluster.get("reader_endpoint")):
                if ep:
                    model.dns_index[_normalize_dns(ep)] = gid

    for db in instances:
        if db.get("name", "") in clustered:
            continue
        subnet_id = db.get("subnet_id", "")
        if not subnet_id:
            continue
        node = _register(model, DiagramNode(
            id=_node_id("rds_instance", db.get("resource_id", "")),
            resource_type="rds_instance",
            label=_safe_label(db.get("name", "") or db.get("resource_id", "")),
            container_id=subnet_id,
            sublabel=db.get("engine", ""),
            attachments=[("rds_instance", f"standby {db['secondary_availability_zone']}")]
            if db.get("multi_az") and db.get("secondary_availability_zone") else [],
            tooltip=f"{db.get('name', '')} {db.get('instance_class', '')} "
                    f"{db.get('allocated_storage_gb') or ''}G {db.get('storage_type') or ''}",
        ))
        _add_to_subnet(region, subnet_id, node.id)
        if db.get("endpoint"):
            model.dns_index[_normalize_dns(db["endpoint"])] = node.id


def _place_ecs_services(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    for svc in compute.get("ecs_services", []):
        subnet_ids = svc.get("subnet_ids", [])
        if not subnet_ids:
            continue  # non-awsvpc → ECS tile
        _add_group_to_vpc(region, subnet_ids, DiagramGroup(
            id=_node_id("ecs_service", svc.get("resource_id", "")),
            label=_safe_label(svc.get("name", "")),
            category="compute",
            subnet_ids=subnet_ids,
            sublabel=f"{svc.get('cluster', '')} · {svc.get('launch_type', '')} "
                     f"{svc.get('running_count', 0)}/{svc.get('desired_count', 0)}",
            icon="ecs_service",
        ))


def _place_eks_clusters(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    """EKS clusters as groups with their managed node groups (and Fargate) inside."""
    for cluster in compute.get("eks_clusters", []):
        all_subnets: set[str] = set()
        members: list[str] = []
        cname = cluster.get("name", "")

        for ng in cluster.get("node_groups", []):
            all_subnets.update(ng.get("subnet_ids", []))
            scaling = ng.get("scaling", {}) or {}
            desired = scaling.get("desiredSize", scaling.get("desired_size", "?"))
            types = ", ".join(ng.get("instance_types", []) or [])
            members.append(_register(model, DiagramNode(
                id=_node_id("eks_nodegroup", f"{cname}/{ng.get('name', '')}"),
                resource_type="eks_nodegroup",
                label=_safe_label(ng.get("name", "")),
                container_id="group",
                sublabel=f"{ng.get('capacity_type') or ''} ×{desired}".strip(),
                tooltip=f"{ng.get('name', '')}: {types}\n"
                        f"min {scaling.get('minSize', '?')} / max {scaling.get('maxSize', '?')}",
            )).id)

        if cluster.get("fargate_profile_count"):
            members.append(_register(model, DiagramNode(
                id=_node_id("eks_fargate", cname),
                resource_type="fargate",
                label="Fargate",
                container_id="group",
                sublabel=f"{cluster['fargate_profile_count']} profiles",
            )).id)

        if not all_subnets:
            all_subnets = set(cluster.get("subnet_ids", []))
        if not all_subnets:
            continue

        gid = _node_id("eks_cluster", cluster.get("resource_id", ""))
        _add_group_to_vpc(region, sorted(all_subnets), DiagramGroup(
            id=gid,
            label=_safe_label(cname),
            category="compute",
            subnet_ids=sorted(all_subnets),
            members=_members_with_overflow(model, gid, members),
            sublabel=f"EKS {cluster.get('version', '')}"
                     + (" · public API" if cluster.get("endpoint_public_access") else ""),
            icon="eks_cluster",
        ))


def _place_asgs(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    """ASG outline around the subnets its instances live in (instances stay in their subnets)."""
    for asg in compute.get("auto_scaling_groups", []):
        subnet_ids = asg.get("subnet_ids", [])
        if not subnet_ids:
            continue
        instances = asg.get("instances", [])
        in_service = sum(1 for i in instances if i.get("state") == "InService")
        _add_group_to_vpc(region, subnet_ids, DiagramGroup(
            id=_node_id("auto_scaling_group", asg.get("resource_id", asg.get("name", ""))),
            label=_safe_label(asg.get("name", "")),
            category="compute",
            subnet_ids=subnet_ids,
            sublabel=f"ASG {in_service}/{asg.get('desired_capacity', 0)} "
                     f"(min {asg.get('min_size', 0)} max {asg.get('max_size', 0)})",
            icon="auto_scaling_group",
        ))


def _place_lambda_vpc(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    """VPC-attached Lambdas grouped by subnet set, functions listed inside."""
    by_subnets: dict[tuple, list[dict]] = {}
    for fn in compute.get("lambda_functions", []):
        subnet_ids = (fn.get("vpc_config") or {}).get("SubnetIds", [])
        if subnet_ids:
            by_subnets.setdefault(tuple(sorted(subnet_ids)), []).append(fn)

    for subnet_tuple, fns in by_subnets.items():
        gid = f"lambda_group:{'_'.join(subnet_tuple[:3])}"
        members = [
            _register(model, DiagramNode(
                id=_node_id("lambda_function", fn.get("resource_id", fn.get("name", ""))),
                resource_type="lambda_function",
                label=_safe_label(fn.get("name", "")),
                container_id="group",
                sublabel=fn.get("runtime", "") or fn.get("package_type", ""),
            )).id
            for fn in fns
        ]
        _add_group_to_vpc(region, list(subnet_tuple), DiagramGroup(
            id=gid,
            label=f"VPC Lambda ×{len(fns)}",
            category="compute",
            subnet_ids=list(subnet_tuple),
            members=_members_with_overflow(model, gid, members),
            icon="lambda_function",
        ))


def _place_elasticache(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    """Replication groups containing their member cache clusters; standalone clusters in subnets."""
    clusters = storage.get("elasticache_clusters", [])
    by_id = {c.get("name", ""): c for c in clusters}
    grouped: set[str] = set()

    for rg in storage.get("elasticache_replication_groups", []):
        members: list[str] = []
        subnet_ids: list[str] = list(rg.get("subnet_ids", []))
        for cid in rg.get("member_clusters", []):
            c = by_id.get(cid)
            if not c:
                continue
            grouped.add(cid)
            members.append(_register(model, DiagramNode(
                id=_node_id("elasticache_cluster", c.get("resource_id", cid)),
                resource_type="elasticache_cluster",
                label=_safe_label(cid),
                container_id="group",
                sublabel=c.get("availability_zone") or c.get("node_type", ""),
            )).id)
            if c.get("subnet_id"):
                subnet_ids.append(c["subnet_id"])
        if not subnet_ids:
            continue
        gid = _node_id("elasticache_replication_group", rg.get("resource_id", ""))
        _add_group_to_vpc(region, sorted(set(subnet_ids)), DiagramGroup(
            id=gid,
            label=_safe_label(rg.get("name", "") or "ElastiCache"),
            category="database",
            subnet_ids=sorted(set(subnet_ids)),
            members=_members_with_overflow(model, gid, members),
            sublabel=" ".join(x for x in [
                rg.get("engine") or "", rg.get("node_type") or "",
                "cluster-mode" if rg.get("cluster_mode") else "",
            ] if x),
            icon="elasticache_replication_group",
        ))

    for c in clusters:
        if c.get("name", "") in grouped or c.get("replication_group_id"):
            continue
        subnet_id = c.get("subnet_id", "")
        if not subnet_id:
            continue
        node = _register(model, DiagramNode(
            id=_node_id("elasticache_cluster", c.get("resource_id", "")),
            resource_type="elasticache_cluster",
            label=_safe_label(c.get("name", "")),
            container_id=subnet_id,
            sublabel=f"{c.get('engine', '')} ×{c.get('num_nodes', 1)}",
        ))
        _add_to_subnet(region, subnet_id, node.id)


def _place_opensearch(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    for domain in storage.get("opensearch_domains", []):
        subnet_ids = domain.get("subnet_ids", [])
        if not subnet_ids:
            continue
        _add_group_to_vpc(region, subnet_ids, DiagramGroup(
            id=_node_id("opensearch_domain", domain.get("resource_id", "")),
            label=_safe_label(domain.get("name", "") or "OpenSearch"),
            category="database",
            subnet_ids=subnet_ids,
            sublabel=f"{domain.get('instance_type') or ''} ×{domain.get('instance_count') or '?'}",
            icon="opensearch_domain",
        ))


def _place_redshift(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    for cluster in storage.get("redshift_clusters", []):
        subnet_id = cluster.get("subnet_id", "")
        if not subnet_id:
            continue
        node = _register(model, DiagramNode(
            id=_node_id("redshift_cluster", cluster.get("resource_id", "")),
            resource_type="redshift_cluster",
            label=_safe_label(cluster.get("name", "") or "Redshift"),
            container_id=subnet_id,
            sublabel=f"{cluster.get('node_type') or ''} ×{cluster.get('number_of_nodes') or 1}",
        ))
        _add_to_subnet(region, subnet_id, node.id)


def _place_efs(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    """EFS group spanning its mount-target subnets, one mount-target node per subnet."""
    for fs in storage.get("efs_file_systems", []):
        mount_targets = [mt for mt in fs.get("mount_targets", []) if mt.get("subnet_id")]
        subnet_ids = [mt["subnet_id"] for mt in mount_targets]
        if not subnet_ids:
            continue
        fs_short = fs.get("file_system_id") or fs.get("resource_id", "")
        for mt in mount_targets:
            node = _register(model, DiagramNode(
                id=_node_id("efs_mount_target", mt.get("mount_target_id") or f"{fs_short}-{mt['subnet_id']}"),
                resource_type="efs_filesystem",
                label="mount target",
                container_id=mt["subnet_id"],
                sublabel=mt.get("ip_address", "") or "",
            ))
            _add_to_subnet(region, mt["subnet_id"], node.id)
        _add_group_to_vpc(region, subnet_ids, DiagramGroup(
            id=_node_id("efs_filesystem", fs.get("resource_id", "")),
            label=_safe_label(fs.get("name", "") or fs_short or "EFS"),
            category="storage",
            subnet_ids=subnet_ids,
            sublabel=f"EFS {fs.get('performance_mode') or ''}".strip(),
            icon="efs_filesystem",
        ))


def _place_nfw(model: DiagramModel, region: RegionModel, nfws: list[dict]) -> None:
    """Network Firewall group with its per-AZ endpoint in each firewall subnet."""
    for fw in nfws:
        subnet_ids = fw.get("subnet_mappings", [])
        if not subnet_ids:
            continue
        for sid in subnet_ids:
            ep_id = (fw.get("subnet_to_endpoint") or {}).get(sid, "")
            node = _register(model, DiagramNode(
                id=_node_id("nfw_endpoint", ep_id or f"{fw.get('name', '')}-{sid}"),
                resource_type="network_firewall",
                label="FW endpoint",
                container_id=sid,
                sublabel=ep_id,
            ))
            _add_to_subnet(region, sid, node.id)
        _add_group_to_vpc(region, subnet_ids, DiagramGroup(
            id=_node_id("network_firewall", fw.get("resource_id", "")),
            label=_safe_label(fw.get("name", "") or "NFW"),
            category="security",
            subnet_ids=subnet_ids,
            sublabel=fw.get("status", "") or "",
            icon="network_firewall",
        ))


# ── Tiles ───────────────────────────────────────────────────────────

def _build_tiles(region: RegionModel, region_data: dict, global_data: dict, is_first_region: bool) -> None:
    """Aggregated managed-service tiles for the region's right panel."""
    tiles: dict[str, tuple[str, int, list[str]]] = {}

    def _count(display: str, icon: str, resources: list[dict]) -> None:
        if not resources:
            return
        _, count, names = tiles.get(display, (icon, 0, []))
        tiles[display] = (icon, count + len(resources),
                          names + [r.get("name", "") for r in resources[:5]])

    for category_data in region_data.values():
        if not isinstance(category_data, dict):
            continue
        for key, rlist in category_data.items():
            if key in TILE_SERVICES and isinstance(rlist, list):
                display, icon = TILE_SERVICES[key]
                _count(display, icon, rlist)

    # EBS volumes not attached to any instance (attached ones are drawn under their EC2)
    vols = region_data.get("storage", {}).get("ebs_volumes", [])
    _count("EBS unattached", "ebs_volume", [v for v in vols if not v.get("attachments")])

    # Unassociated Elastic IPs
    eips = region_data.get("networking", {}).get("elastic_ips", [])
    _count("EIP unused", "elastic_ip", [e for e in eips if not e.get("association_id")])

    if is_first_region:
        _count("S3", "s3_bucket", global_data.get("s3", {}).get("s3_buckets", []))

    lambdas = region_data.get("compute", {}).get("lambda_functions", [])
    _count("Lambda", "lambda_function",
           [f for f in lambdas if not (f.get("vpc_config") or {}).get("SubnetIds")])

    for display in sorted(tiles):
        icon, count, names = tiles[display]
        region.tiles.append(ServiceTile(service=display, icon=icon, count=count, names=names[:5]))


# ── Edges ───────────────────────────────────────────────────────────

def _build_edges(model: DiagramModel, account_data: dict) -> None:
    """Build edges from inventory relationships. Unresolvable endpoints are dropped at layout."""
    global_data = account_data.get("global", {})
    regions_data = account_data.get("regions", {})

    # Route 53 alias → LB / CloudFront / API GW / RDS
    for zone in global_data.get("route53", {}).get("route53_hosted_zones", []):
        for alias in zone.get("alias_targets", []):
            target_id = model.dns_index.get(_normalize_dns(alias.get("dns_name", "")))
            if target_id:
                model.edges.append(DiagramEdge(
                    "global:route53", target_id, "traffic", alias.get("name", ""),
                ))

    for region_name, region_data in regions_data.items():
        net = region_data.get("networking", {})
        compute = region_data.get("compute", {})
        region_model = model.regions.get(region_name)

        # Target group → EC2 targets
        for tg in net.get("target_groups", []):
            tg_id = _node_id("target_group", tg.get("resource_id", ""))
            for t in tg.get("targets", []):
                tid = t.get("id") or ""
                if tid.startswith("i-"):
                    model.edges.append(DiagramEdge(tg_id, _node_id("ec2_instance", tid), "traffic"))

        # Target group → ECS service
        for svc in compute.get("ecs_services", []):
            for lb in svc.get("load_balancers", []):
                if lb.get("target_group_arn"):
                    model.edges.append(DiagramEdge(
                        _node_id("target_group", lb["target_group_arn"]),
                        _node_id("ecs_service", svc.get("resource_id", "")),
                        "traffic",
                    ))

        # CLB → registered instances
        for lb in net.get("load_balancers_classic", []):
            for iid in lb.get("instances", []):
                model.edges.append(DiagramEdge(
                    _node_id("load_balancer_classic", lb.get("resource_id", "")),
                    _node_id("ec2_instance", iid), "traffic",
                ))

        # NAT → IGW
        for nat in net.get("nat_gateways", []):
            if region_model is None:
                continue
            sm = _find_subnet(region_model, nat.get("subnet_id", ""))
            vpc_model = region_model.vpcs.get(nat.get("vpc_id") or (sm.vpc_id if sm else ""))
            if vpc_model and vpc_model.igw_id:
                model.edges.append(DiagramEdge(
                    _node_id("nat_gateway", nat.get("resource_id", "")),
                    f"igw:{vpc_model.igw_id}", "egress",
                ))

        # TGW → attached VPCs
        for att in net.get("transit_gateway_attachments", []):
            if (att.get("resource_type_attached") or "").lower() == "vpc":
                model.edges.append(DiagramEdge(
                    _node_id("transit_gateway", att.get("transit_gateway_id", "")),
                    f"vpc:{att.get('resource_id_attached', '')}", "network",
                ))

        # Site-to-site VPN: CGW → VPN → VGW / TGW
        for vpn in net.get("vpn_connections", []):
            vpn_id = _node_id("vpn_connection", vpn.get("resource_id", ""))
            if vpn.get("customer_gateway_id"):
                model.edges.append(DiagramEdge(
                    _node_id("customer_gateway", vpn["customer_gateway_id"]), vpn_id, "network",
                ))
            if vpn.get("vpn_gateway_id"):
                model.edges.append(DiagramEdge(vpn_id, f"vgw:{vpn['vpn_gateway_id']}", "network"))
            elif vpn.get("transit_gateway_id"):
                model.edges.append(DiagramEdge(
                    vpn_id, _node_id("transit_gateway", vpn["transit_gateway_id"]), "network",
                ))

        # VPC peering
        for peer in net.get("vpc_peering_connections", []):
            req, acc = peer.get("requester_vpc_id", ""), peer.get("accepter_vpc_id", "")
            if req and acc:
                model.edges.append(DiagramEdge(f"vpc:{req}", f"vpc:{acc}", "network", "Peering"))

        # WAF → protected LB / API Gateway
        for waf in net.get("waf_web_acls", []):
            waf_id = _node_id("waf_web_acl", waf.get("resource_id", ""))
            for arn in waf.get("associated_resources", []):
                target = None
                if ":loadbalancer/" in arn:
                    target = _node_id("load_balancer_v2", arn)
                elif "/restapis/" in arn:
                    target = f"api_gateway_rest:{arn.split('/restapis/', 1)[1].split('/', 1)[0]}"
                if target:
                    model.edges.append(DiagramEdge(waf_id, target, "security"))

        # Gateway endpoints → S3 / DynamoDB tiles
        for ep in net.get("vpc_endpoints", []):
            svc = (ep.get("service_name") or "").rsplit(".", 1)[-1]
            tile = {"s3": "S3", "dynamodb": "DynamoDB"}.get(svc)
            if tile:
                model.edges.append(DiagramEdge(
                    _node_id("vpc_endpoint", ep.get("resource_id", "")),
                    f"tile:{region_name}:{tile}", "endpoint",
                ))

    _build_replication_edges(model, account_data)


def _build_replication_edges(model: DiagramModel, account_data: dict) -> None:
    """Cross-region replication arrows between service tiles."""
    regions_data = account_data.get("regions", {})

    for region_name, region_data in regions_data.items():
        for table in region_data.get("storage", {}).get("dynamodb_tables", []):
            for replica_region in table.get("replica_regions", []):
                if replica_region != region_name:
                    model.edges.append(DiagramEdge(
                        f"tile:{region_name}:DynamoDB", f"tile:{replica_region}:DynamoDB",
                        "replication", "Global Table",
                    ))

        for key in region_data.get("identity", {}).get("kms_keys", []):
            if key.get("multi_region") and key.get("multi_region_type") == "PRIMARY":
                for replica_region in key.get("replica_regions", []):
                    model.edges.append(DiagramEdge(
                        f"tile:{region_name}:KMS", f"tile:{replica_region}:KMS",
                        "replication", "Multi-Region Key",
                    ))

        for dest in region_data.get("compute", {}).get("_ecr_replication", []):
            dest_region = dest.get("region", "")
            if dest_region and dest_region != region_name:
                model.edges.append(DiagramEdge(
                    f"tile:{region_name}:ECR", f"tile:{dest_region}:ECR",
                    "replication", "ECR Replication",
                ))
