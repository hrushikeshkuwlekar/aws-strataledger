"""
Diagram model builder.

Transforms one account's scan inventory into a layout-agnostic model that
follows AWS reference-architecture conventions:

  - External:   Users / Internet, corporate data center (customer gateways)
  - Global:     Route 53, CloudFront, Global Accelerator, IAM, Organizations
  - Region:     connectivity gutter (API Gateway, WAF, TGW, VPN, DX),
                VPCs, and a categorised regional-services panel
  - VPC:        AZ columns × subnet-tier rows; single-subnet resources are
                nodes inside subnets, multi-AZ constructs (ALB, EKS, Aurora,
                MSK, …) are groups that span AZ columns and hold their children
  - Edges:      real relationships only (aliases, origins, targets, VPN, TGW…)

Instances owned by an Auto Scaling group, EKS node group, Elastic Beanstalk
environment or EMR cluster are collapsed into one node per subnet so large
fleets stay readable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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
    """A resource icon. ``resource_type`` is the icon key (see aws_icons.ICON_PNG)."""
    id: str
    resource_type: str
    label: str
    container_id: str = ""
    sublabel: str = ""
    tooltip: str = ""
    # Child resources drawn as mini icons under the parent (EC2 → EBS, EIP)
    attachments: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DiagramGroup:
    """A multi-subnet construct drawn as an AWS group box spanning AZ columns."""
    id: str
    label: str
    category: str  # compute, container, database, networking, storage, analytics, integration, security
    subnet_ids: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    sublabel: str = ""
    icon: str = ""
    tooltip: str = ""
    dashed: bool = False  # AWS convention: Auto Scaling groups are dashed


@dataclass
class DiagramEdge:
    source: str
    target: str
    kind: str  # traffic, network, security, endpoint, replication
    label: str = ""


@dataclass
class ServiceTile:
    """One managed service in the regional-services panel."""
    service: str
    icon: str
    count: int
    names: list[str] = field(default_factory=list)
    category: str = "Other"


@dataclass
class SubnetModel:
    id: str
    name: str
    cidr: str
    az: str
    tier: str
    vpc_id: str
    nodes: list[str] = field(default_factory=list)


@dataclass
class AZModel:
    name: str
    # Keyed by tier; extra subnets of the same tier get "tier#2", "tier#3"…
    subnets: dict[str, SubnetModel] = field(default_factory=dict)


@dataclass
class VPCModel:
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

    def subnet(self, subnet_id: str) -> SubnetModel | None:
        for az in self.azs.values():
            for sm in az.subnets.values():
                if sm.id == subnet_id:
                    return sm
        return None


@dataclass
class RegionModel:
    name: str
    vpcs: dict[str, VPCModel] = field(default_factory=dict)
    tiles: list[ServiceTile] = field(default_factory=list)
    gutter_nodes: list[DiagramNode] = field(default_factory=list)
    empty_vpcs: list[str] = field(default_factory=list)  # "name (cidr)" of VPCs with no resources


@dataclass
class DiagramModel:
    account_id: str
    account_alias: str
    regions: dict[str, RegionModel] = field(default_factory=dict)
    global_nodes: list[DiagramNode] = field(default_factory=list)
    external_nodes: list[DiagramNode] = field(default_factory=list)  # Users / Internet
    onprem_nodes: list[DiagramNode] = field(default_factory=list)    # customer gateways
    edges: list[DiagramEdge] = field(default_factory=list)
    all_nodes: dict[str, DiagramNode] = field(default_factory=dict)
    hidden_default_vpcs: list[str] = field(default_factory=list)
    skipped_regions: list[str] = field(default_factory=list)
    dns_index: dict[str, str] = field(default_factory=dict)       # dns name → node/group id
    instance_index: dict[str, str] = field(default_factory=dict)  # EC2 instance id → node id
    fleet_owner: dict[str, str] = field(default_factory=dict)     # fleet node id → "eks:<cluster>" / "asg:<name>"
    owner_groups: dict[str, str] = field(default_factory=dict)    # "eks:<cluster>" / "asg:<name>" → group id


# ── Regional services catalogue ─────────────────────────────────────

SERVICE_CATEGORIES = [
    "Compute", "Database", "Storage", "Application Integration", "Analytics",
    "Security & Identity", "Management",
]

# inventory list key → (display name, icon key, category)
TILE_SERVICES: dict[str, tuple[str, str, str]] = {
    "ecr_repositories": ("ECR", "ecr", "Compute"),
    "beanstalk_environments": ("Elastic Beanstalk", "beanstalk", "Compute"),
    "dynamodb_tables": ("DynamoDB", "dynamodb", "Database"),
    "ebs_snapshots": ("EBS snapshots", "ebs_snapshot", "Storage"),
    "backup_vaults": ("AWS Backup", "backup", "Storage"),
    "sqs_queues": ("SQS", "sqs", "Application Integration"),
    "sns_topics": ("SNS", "sns", "Application Integration"),
    "eventbridge_rules": ("EventBridge", "eventbridge", "Application Integration"),
    "step_functions": ("Step Functions", "step_functions", "Application Integration"),
    "kinesis_streams": ("Kinesis Data Streams", "kinesis", "Analytics"),
    "firehose_streams": ("Data Firehose", "firehose", "Analytics"),
    "kms_keys": ("KMS", "kms", "Security & Identity"),
    "secrets": ("Secrets Manager", "secrets_manager", "Security & Identity"),
    "acm_certificates": ("ACM", "acm", "Security & Identity"),
    "cognito_user_pools": ("Cognito", "cognito", "Security & Identity"),
    "guardduty_detectors": ("GuardDuty", "guardduty", "Security & Identity"),
    "security_hub": ("Security Hub", "security_hub", "Security & Identity"),
    "cloudhsm_clusters": ("CloudHSM", "cloudhsm", "Security & Identity"),
    "cloudwatch_alarms": ("CloudWatch alarms", "cloudwatch", "Management"),
    "cloudwatch_log_groups": ("CloudWatch Logs", "cloudwatch", "Management"),
    "cloudtrail_trails": ("CloudTrail", "cloudtrail", "Management"),
    "config_recorders": ("AWS Config", "config", "Management"),
    "ssm_parameters": ("Parameter Store", "ssm", "Management"),
}

MAX_GROUP_MEMBERS = 6

RDS_ENGINE_ICONS = [
    ("aurora", "aurora_instance"), ("docdb", "documentdb"), ("neptune", "neptune"),
    ("postgres", "rds_postgres"), ("mariadb", "rds_mariadb"), ("mysql", "rds_mysql"),
    ("oracle", "rds_oracle"), ("sqlserver", "rds_sqlserver"),
]


def _rds_icon(engine: str | None) -> str:
    engine = (engine or "").lower()
    return next((icon for token, icon in RDS_ENGINE_ICONS if token in engine), "rds_instance")


def _cluster_icon(engine: str | None) -> str:
    engine = (engine or "").lower()
    if "docdb" in engine:
        return "documentdb"
    if "neptune" in engine:
        return "neptune"
    return "aurora"


def _cache_icon(engine: str | None) -> str:
    return "elasticache_memcached" if "memcached" in (engine or "").lower() else "elasticache_redis"


def _node_id(resource_type: str, resource_id: str) -> str:
    """
    Type-prefixed node ID. ARNs keep their region so same-named resources in two
    regions (typical for DR) never collide: ``rds_cluster:eu-west-1:orders``.
    """
    if resource_id.startswith("arn:"):
        parts = resource_id.split(":", 5)
        short = resource_id.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
        region = parts[3] if len(parts) > 3 else ""
        return f"{resource_type}:{region}:{short}" if region else f"{resource_type}:{short}"
    return f"{resource_type}:{resource_id}"


def _safe_label(name: str, max_len: int = 30) -> str:
    name = name or ""
    return name if len(name) <= max_len else name[:max_len - 1] + "…"


def _normalize_dns(dns: str) -> str:
    dns = (dns or "").lower().rstrip(".")
    return dns[len("dualstack."):] if dns.startswith("dualstack.") else dns


def _words(*parts: object) -> str:
    """Join the non-empty parts with spaces."""
    return " ".join(str(p) for p in parts if p not in (None, "", []))


def _register(model: DiagramModel, node: DiagramNode) -> DiagramNode:
    model.all_nodes[node.id] = node
    return node


def _capped(model: DiagramModel, group_id: str, ids: list[str]) -> list[str]:
    """Cap group members, replacing the tail with a '+N more' chip."""
    if len(ids) <= MAX_GROUP_MEMBERS:
        return ids
    keep = ids[:MAX_GROUP_MEMBERS - 1]
    chip = _register(model, DiagramNode(
        id=f"overflow:{group_id}", resource_type="generic",
        label=f"+{len(ids) - len(keep)} more", container_id="group",
    ))
    return keep + [chip.id]


# ── Builder ─────────────────────────────────────────────────────────

def build_diagram_model(account_id: str, account_alias: str, account_data: dict) -> DiagramModel:
    """Build a DiagramModel from one account's scan data ({"global":…, "regions":…})."""
    model = DiagramModel(account_id=account_id, account_alias=account_alias)
    global_data = account_data.get("global", {}) or {}
    regions_data = account_data.get("regions", {}) or {}

    buckets_by_region: dict[str, list[dict]] = {}
    for b in global_data.get("s3", {}).get("s3_buckets", []):
        buckets_by_region.setdefault(b.get("location") or "us-east-1", []).append(b)
    first_region = next(iter(regions_data), "")
    # Buckets whose region was not scanned are shown in the first scanned region.
    orphan = [b for r, bs in buckets_by_region.items() if r not in regions_data for b in bs]

    for region_name, region_data in regions_data.items():
        buckets = list(buckets_by_region.get(region_name, []))
        if region_name == first_region:
            buckets += orphan
        region = _build_region(model, region_name, region_data or {}, buckets)
        if region.vpcs or region.tiles or region.gutter_nodes:
            model.regions[region_name] = region
        else:
            model.skipped_regions.append(region_name)

    _build_global(model, global_data)
    _build_edges(model, account_data)
    return model


def _build_global(model: DiagramModel, global_data: dict) -> None:
    """Global column (Route 53, CloudFront, GA, IAM, Organizations) and external actors."""
    zones = global_data.get("route53", {}).get("route53_hosted_zones", [])
    if zones:
        public = sum(1 for z in zones if not z.get("is_private"))
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:route53", resource_type="route53", label="Route 53", container_id="global",
            sublabel=f"{len(zones)} hosted zones",
            tooltip=f"{public} public / {len(zones) - public} private\n"
                    + "\n".join(z.get("name", "") for z in zones[:15]),
        )))

    edge = global_data.get("edge", {}) or {}
    dists = edge.get("cloudfront_distributions", [])
    if dists:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:cloudfront", resource_type="cloudfront", label="CloudFront", container_id="global",
            sublabel=f"{len(dists)} distributions",
            tooltip="\n".join(f"{d.get('name', '')} → {', '.join(o.get('domain_name', '') for o in d.get('origins', []))}"
                              for d in dists[:15]),
        )))
        for d in dists:
            for dns in [d.get("domain_name", "")] + list(d.get("aliases", [])):
                if dns:
                    model.dns_index[_normalize_dns(dns)] = "global:cloudfront"

    accelerators = edge.get("global_accelerators", [])
    if accelerators:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:global_accelerator", resource_type="global_accelerator",
            label="Global Accelerator", container_id="global",
            sublabel=f"{len(accelerators)} accelerators",
            tooltip="\n".join(a.get("name", "") for a in accelerators[:15]),
        )))
        for a in accelerators:
            if a.get("dns_name"):
                model.dns_index[_normalize_dns(a["dns_name"])] = "global:global_accelerator"

    iam = global_data.get("iam", {}) or {}
    users, roles = iam.get("iam_users", []), iam.get("iam_roles", [])
    if users or roles:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:iam", resource_type="iam", label="IAM", container_id="global",
            sublabel=f"{len(users)} users · {len(roles)} roles",
        )))

    accounts = (global_data.get("organizations", {}) or {}).get("organization_accounts", [])
    if accounts:
        model.global_nodes.append(_register(model, DiagramNode(
            id="global:organizations", resource_type="organizations", label="Organizations",
            container_id="global", sublabel=f"{len(accounts)} accounts",
        )))

    model.external_nodes.append(_register(model, DiagramNode(
        id="global:users", resource_type="users", label="Users", container_id="external",
        sublabel="Internet",
    )))


def _build_region(model: DiagramModel, region_name: str, region_data: dict, buckets: list[dict]) -> RegionModel:
    region = RegionModel(name=region_name)
    net = region_data.get("networking", {}) or {}
    compute = region_data.get("compute", {}) or {}
    storage = region_data.get("storage", {}) or {}
    analytics = region_data.get("analytics", {}) or {}
    integration = region_data.get("integration", {}) or {}
    security = region_data.get("security", {}) or {}

    subnets = net.get("subnets", [])
    route_tables = net.get("route_tables", [])
    nfws = net.get("network_firewalls", []) or security.get("network_firewalls", [])
    nfw_subnet_ids = {sid for fw in nfws for sid in fw.get("subnet_mappings", [])}

    igw_vpc = {
        gw.get("resource_id", ""): att.get("vpc_id", att.get("VpcId", ""))
        for gw in net.get("internet_gateways", []) for att in gw.get("attachments", [])
        if att.get("vpc_id") or att.get("VpcId")
    }
    vgw_vpc = {
        gw.get("resource_id", ""): att.get("vpc_id", att.get("VpcId", ""))
        for gw in net.get("vpn_gateways", [])
        for att in gw.get("vpc_attachments", gw.get("attachments", []))
        if att.get("vpc_id") or att.get("VpcId")
    }

    for vpc_raw in net.get("vpcs", []):
        vpc_id = vpc_raw.get("resource_id", vpc_raw.get("vpc_id", ""))
        vpc = VPCModel(
            id=vpc_id, name=_safe_label(vpc_raw.get("name", "") or vpc_id),
            cidr=vpc_raw.get("cidr_block", ""), is_default=vpc_raw.get("is_default", False),
        )
        vpc.igw_id = next((g for g, v in igw_vpc.items() if v == vpc_id), None)
        vpc.vgw_id = next((g for g, v in vgw_vpc.items() if v == vpc_id), None)

        for s in subnets:
            if s.get("vpc_id") != vpc_id:
                continue
            sid = s.get("resource_id", s.get("subnet_id", ""))
            tier = classify_subnet_tier(s, route_tables, nfw_subnet_ids)
            sm = SubnetModel(
                id=sid, name=_safe_label(s.get("name", "") or sid, 26), cidr=s.get("cidr_block", ""),
                az=s.get("availability_zone", ""), tier=tier, vpc_id=vpc_id,
            )
            az = vpc.azs.setdefault(sm.az, AZModel(name=sm.az))
            key, n = tier, 2
            while key in az.subnets:
                key, n = f"{tier}#{n}", n + 1
            az.subnets[key] = sm

        for ep in net.get("vpc_endpoints", []):
            if ep.get("vpc_id") != vpc_id:
                continue
            svc = ep.get("service_name", "")
            vpc.endpoints.append(_register(model, DiagramNode(
                id=_node_id("vpc_endpoint", ep.get("resource_id", "")), resource_type="vpc_endpoint",
                label=svc.split(".", 3)[-1] if svc.count(".") >= 3 else svc, container_id=vpc_id,
                sublabel=ep.get("endpoint_type") or ep.get("vpc_endpoint_type", ""), tooltip=svc,
            )))
        region.vpcs[vpc_id] = vpc

    _place_ec2(model, region, compute, storage, net)
    _place_nat_gateways(model, region, net)
    _place_load_balancers(model, region, net)
    _place_eks(model, region, compute)
    _place_asgs(model, region, compute)
    _place_ecs(model, region, compute)
    _place_lambda_vpc(model, region, compute)
    _place_rds(model, region, storage)
    _place_elasticache(model, region, storage)
    _place_simple_groups(model, region, storage, analytics, integration)
    _place_single_subnet_nodes(model, region, storage, analytics)
    _place_nfw(model, region, nfws)

    for vpc_id in list(region.vpcs):
        vpc = region.vpcs[vpc_id]
        vpc.has_workloads = bool(vpc.groups) or any(
            sm.nodes for az in vpc.azs.values() for sm in az.subnets.values()
        )
        if vpc.has_workloads:
            continue
        del region.vpcs[vpc_id]
        if vpc.is_default:
            model.hidden_default_vpcs.append(f"{vpc_id} ({region_name})")
        else:
            region.empty_vpcs.append(f"{vpc.name} ({vpc.cidr})" if vpc.name != vpc_id else f"{vpc_id} ({vpc.cidr})")

    _build_gutter(model, region, net, security)
    _build_tiles(region, region_data, buckets)
    return region


# ── Placement helpers ───────────────────────────────────────────────

def _find_subnet(region: RegionModel, subnet_id: str) -> SubnetModel | None:
    for vpc in region.vpcs.values():
        sm = vpc.subnet(subnet_id)
        if sm:
            return sm
    return None


def _add_to_subnet(region: RegionModel, subnet_id: str, node_id: str) -> bool:
    sm = _find_subnet(region, subnet_id)
    if sm is None:
        return False
    sm.nodes.append(node_id)
    return True


def _add_group(region: RegionModel, group: DiagramGroup) -> bool:
    """Attach a group to the VPC that owns its subnets (subnets outside that VPC are dropped)."""
    for vpc in region.vpcs.values():
        local = [s for s in group.subnet_ids if vpc.subnet(s)]
        if local:
            group.subnet_ids = sorted(set(local))
            vpc.groups.append(group)
            return True
    return False


def _instance_owner(inst: dict, asg_by_instance: dict[str, str]) -> tuple[str, str] | None:
    """(owner kind, owner name) for instances managed by a fleet construct."""
    tags = inst.get("tags") or {}
    if tags.get("eks:nodegroup-name"):
        return "eks", tags["eks:nodegroup-name"]
    if tags.get("karpenter.sh/nodepool") or tags.get("karpenter.sh/provisioner-name"):
        return "eks", tags.get("karpenter.sh/nodepool") or tags["karpenter.sh/provisioner-name"]
    if tags.get("elasticbeanstalk:environment-name"):
        return "beanstalk", tags["elasticbeanstalk:environment-name"]
    if tags.get("aws:elasticmapreduce:job-flow-id"):
        return "emr", tags["aws:elasticmapreduce:job-flow-id"]
    asg = tags.get("aws:autoscaling:groupName") or asg_by_instance.get(inst.get("resource_id", ""))
    if asg:
        return "asg", asg
    return None


def _place_ec2(model: DiagramModel, region: RegionModel, compute: dict, storage: dict, net: dict) -> None:
    """Standalone instances get their own icon (with EBS/EIP); fleet instances are collapsed per subnet."""
    volumes_by_instance: dict[str, list[dict]] = {}
    for vol in storage.get("ebs_volumes", []):
        for att in vol.get("attachments", []):
            if att.get("instance_id"):
                volumes_by_instance.setdefault(att["instance_id"], []).append(vol)
    eips_by_instance: dict[str, list[dict]] = {}
    for eip in net.get("elastic_ips", []):
        if eip.get("instance_id"):
            eips_by_instance.setdefault(eip["instance_id"], []).append(eip)
    asg_by_instance = {
        i.get("id", ""): asg.get("name", "")
        for asg in compute.get("auto_scaling_groups", []) for i in asg.get("instances", [])
    }

    fleets: dict[tuple[str, str, str], list[dict]] = {}
    for inst in compute.get("ec2_instances", []):
        if inst.get("state") in ("terminated", "shutting-down"):
            continue
        subnet_id = inst.get("subnet_id", "")
        if not subnet_id:
            continue
        owner = _instance_owner(inst, asg_by_instance)
        if owner:
            fleets.setdefault((subnet_id, *owner), []).append(inst)
            continue

        iid = inst.get("resource_id", "")
        tip = [f"{inst.get('name') or iid} ({iid})",
               f"{inst.get('instance_type', '')} · {inst.get('state', '')} · {inst.get('private_ip') or ''}"]
        attachments: list[tuple[str, str]] = []
        for vol in volumes_by_instance.get(iid, []):
            label = f"{vol.get('size_gb', '?')} GiB {vol.get('volume_type', '')}".strip()
            attachments.append(("ebs_volume", f"EBS {label}"))
            dev = next((a.get("device") for a in vol.get("attachments", []) if a.get("instance_id") == iid), "")
            tip.append(f"EBS {vol.get('resource_id', '')} {label} {dev or ''}".rstrip())
        for eip in eips_by_instance.get(iid, []):
            attachments.append(("elastic_ip", f"Elastic IP {eip.get('public_ip', '')}"))
            tip.append(f"Elastic IP {eip.get('public_ip', '')}")
        if inst.get("security_groups"):
            tip.append("SG: " + ", ".join(sg.get("name") or sg.get("id", "") for sg in inst["security_groups"]))
        if inst.get("state") and inst["state"] != "running":
            tip.append(f"state: {inst['state']}")

        node = _register(model, DiagramNode(
            id=_node_id("ec2_instance", iid),
            resource_type="ec2_spot" if inst.get("lifecycle") == "spot" else "ec2_instance",
            label=_safe_label(inst.get("name", "") or iid), container_id=subnet_id,
            sublabel=inst.get("instance_type", "") + ("" if inst.get("state") in (None, "running") else " (stopped)"),
            attachments=attachments, tooltip="\n".join(tip),
        ))
        model.instance_index[iid] = node.id
        _add_to_subnet(region, subnet_id, node.id)

    for (subnet_id, kind, owner), insts in fleets.items():
        types = sorted({i.get("instance_type") or "" for i in insts} - {""})
        node = _register(model, DiagramNode(
            id=f"ec2_fleet:{subnet_id}:{kind}:{owner}", resource_type="ec2_instances",
            label=_safe_label(owner, 24), container_id=subnet_id,
            sublabel=f"{len(insts)} × {types[0] if len(types) == 1 else 'mixed'}",
            tooltip=f"{len(insts)} instances ({ {'eks': 'EKS node group', 'asg': 'Auto Scaling group', 'beanstalk': 'Elastic Beanstalk', 'emr': 'EMR'}[kind] } {owner})\n"
                    + "\n".join(f"{i.get('resource_id')} {i.get('name') or ''} {i.get('instance_type') or ''}"
                                for i in insts[:15]),
        ))
        for i in insts:
            model.instance_index[i.get("resource_id", "")] = node.id
        _add_to_subnet(region, subnet_id, node.id)
        tags = insts[0].get("tags") or {}
        if kind == "eks" and tags.get("eks:cluster-name"):
            model.fleet_owner[node.id] = f"{region.name}:eks:{tags['eks:cluster-name']}"
        elif kind == "asg":
            model.fleet_owner[node.id] = f"{region.name}:asg:{owner}"


def _place_nat_gateways(model: DiagramModel, region: RegionModel, net: dict) -> None:
    for nat in net.get("nat_gateways", []):
        subnet_id = nat.get("subnet_id", "")
        if not subnet_id:
            continue
        node = _register(model, DiagramNode(
            id=_node_id("nat_gateway", nat.get("resource_id", "")), resource_type="nat_gateway",
            label=_safe_label(nat.get("name", "") or "NAT gateway", 24), container_id=subnet_id,
            sublabel="private" if nat.get("connectivity_type") == "private" else (nat.get("public_ip") or ""),
            tooltip=f"{nat.get('resource_id', '')}\npublic {nat.get('public_ip') or '-'} · private {nat.get('private_ip') or '-'}",
        ))
        _add_to_subnet(region, subnet_id, node.id)


def _place_load_balancers(model: DiagramModel, region: RegionModel, net: dict) -> None:
    tgs_by_lb: dict[str, list[dict]] = {}
    for tg in net.get("target_groups", []):
        lbs = tg.get("load_balancer_arns", [])
        if lbs:
            tgs_by_lb.setdefault(lbs[0], []).append(tg)

    for lb in net.get("load_balancers_v2", []):
        if not lb.get("subnet_ids"):
            continue
        arn = lb.get("resource_id", "")
        gid = _node_id("load_balancer_v2", arn)
        members = []
        for tg in tgs_by_lb.get(arn, []):
            targets = tg.get("targets", [])
            healthy = sum(1 for t in targets if t.get("state") == "healthy")
            members.append(_register(model, DiagramNode(
                id=_node_id("target_group", tg.get("resource_id", "")), resource_type="target_group",
                label=_safe_label(tg.get("name", ""), 22), container_id="group",
                sublabel=f"{tg.get('protocol') or ''}:{tg.get('port') or ''} · {healthy}/{len(targets)} up",
                tooltip=_words("Target group", tg.get("name"), f"({tg['target_type']})" if tg.get("target_type") else ""),
            )).id)
        lb_type = lb.get("type", "application")
        icon = {"application": "alb", "network": "nlb"}.get(lb_type, "elb")
        listeners = ", ".join(f"{l.get('protocol')}:{l.get('port')}" for l in lb.get("listeners", []))
        group = DiagramGroup(
            id=gid, label=_safe_label(lb.get("name", ""), 34), category="networking",
            subnet_ids=list(lb["subnet_ids"]), members=_capped(model, gid, members), icon=icon,
            sublabel=" · ".join(x for x in [
                {"application": "ALB", "network": "NLB", "gateway": "GWLB"}.get(lb_type, "ELB"),
                lb.get("scheme") or "", listeners] if x),
            tooltip=lb.get("dns_name", ""),
        )
        if _add_group(region, group) and lb.get("dns_name"):
            model.dns_index[_normalize_dns(lb["dns_name"])] = gid

    for lb in net.get("load_balancers_classic", []):
        if not lb.get("subnet_ids"):
            continue
        group = DiagramGroup(
            id=f"load_balancer_classic:{region.name}:{lb.get('resource_id', '')}",
            label=_safe_label(lb.get("name", ""), 34), category="networking",
            subnet_ids=list(lb["subnet_ids"]), icon="clb",
            sublabel=f"CLB · {lb.get('scheme') or ''} · {len(lb.get('instances', []))} instances",
        )
        if _add_group(region, group) and lb.get("dns_name"):
            model.dns_index[_normalize_dns(lb["dns_name"])] = group.id


def _place_eks(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    for cluster in compute.get("eks_clusters", []):
        cname = cluster.get("name", "")
        gid = _node_id("eks_cluster", cluster.get("resource_id", ""))
        subnets: set[str] = set()
        members = []
        for ng in cluster.get("node_groups", []):
            subnets.update(ng.get("subnet_ids", []))
            scaling = ng.get("scaling") or {}
            desired = scaling.get("desiredSize", scaling.get("desired_size", "?"))
            members.append(_register(model, DiagramNode(
                id=f"eks_nodegroup:{region.name}:{cname}/{ng.get('name', '')}", resource_type="ec2_instances",
                label=_safe_label(ng.get("name", ""), 22), container_id="group",
                sublabel=f"{(ng.get('capacity_type') or 'node group').replace('_', '-').lower()} ×{desired}",
                tooltip=_words(f"{ng.get('name', '')}:", ", ".join(ng.get("instance_types") or []))
                        + f"\nmin {scaling.get('minSize', '?')} / desired {desired} / max {scaling.get('maxSize', '?')}",
            )).id)
        if cluster.get("fargate_profile_count"):
            members.append(_register(model, DiagramNode(
                id=f"eks_fargate:{region.name}:{cname}", resource_type="fargate", label="Fargate",
                container_id="group", sublabel=f"{cluster['fargate_profile_count']} profiles",
            )).id)
        subnets = subnets or set(cluster.get("subnet_ids", []))
        if not subnets:
            continue
        model.owner_groups[f"{region.name}:eks:{cname}"] = gid
        _add_group(region, DiagramGroup(
            id=gid, label=_safe_label(cname, 34), category="container", subnet_ids=sorted(subnets),
            members=_capped(model, gid, members), icon="eks_cluster",
            sublabel=f"Amazon EKS {cluster.get('version') or ''}"
                     + (" · public endpoint" if cluster.get("endpoint_public_access") else " · private endpoint"),
        ))


def _place_asgs(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    """Auto Scaling groups (EKS-managed ones are already represented by their node group)."""
    for asg in compute.get("auto_scaling_groups", []):
        tags = asg.get("tags") or {}
        if not asg.get("subnet_ids") or tags.get("eks:nodegroup-name") or tags.get("eks:cluster-name") \
                or any(k.startswith("kubernetes.io/cluster/") for k in tags):
            continue
        instances = asg.get("instances", [])
        in_service = sum(1 for i in instances if i.get("state") == "InService")
        env = tags.get("elasticbeanstalk:environment-name")
        gid = _node_id("auto_scaling_group", asg.get("resource_id", asg.get("name", "")))
        model.owner_groups[f"{region.name}:asg:{asg.get('name', '')}"] = gid
        _add_group(region, DiagramGroup(
            id=gid,
            label=_safe_label(asg.get("name", ""), 34), category="compute",
            subnet_ids=list(asg["subnet_ids"]), icon="auto_scaling_group", dashed=True,
            sublabel=(f"Beanstalk {env} · " if env else "Auto Scaling · ")
                     + f"{in_service}/{asg.get('desired_capacity', 0)} in service"
                       f" (min {asg.get('min_size', 0)}, max {asg.get('max_size', 0)})",
        ))


def _place_ecs(model: DiagramModel, region: RegionModel, compute: dict) -> None:
    """One group per ECS cluster holding its awsvpc services."""
    by_cluster: dict[str, list[dict]] = {}
    for svc in compute.get("ecs_services", []):
        if svc.get("subnet_ids"):
            by_cluster.setdefault(svc.get("cluster") or "ecs", []).append(svc)
    for cluster, services in by_cluster.items():
        gid = f"ecs_cluster:{region.name}:{cluster}"
        members = [
            _register(model, DiagramNode(
                id=_node_id("ecs_service", s.get("resource_id", "")), resource_type="ecs_service",
                label=_safe_label(s.get("name", ""), 22), container_id="group",
                sublabel=f"{s.get('launch_type') or ''} {s.get('running_count', 0)}/{s.get('desired_count', 0)}".strip(),
                tooltip=_words("task definition", s.get("task_definition")) if s.get("task_definition") else "",
            )).id
            for s in services
        ]
        _add_group(region, DiagramGroup(
            id=gid, label=_safe_label(cluster, 34), category="container",
            subnet_ids=sorted({sid for s in services for sid in s["subnet_ids"]}),
            members=_capped(model, gid, members), icon="ecs_cluster",
            sublabel=f"Amazon ECS · {len(services)} services",
        ))


def _place_lambda_vpc(model: DiagramModel, region: RegionModel, compute: dict) -> None:
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
                resource_type="lambda_function", label=_safe_label(fn.get("name", ""), 22),
                container_id="group", sublabel=fn.get("runtime", "") or fn.get("package_type", ""),
            )).id
            for fn in fns
        ]
        _add_group(region, DiagramGroup(
            id=gid, label="Lambda (VPC)", category="compute", subnet_ids=list(subnet_tuple),
            members=_capped(model, gid, members), icon="lambda",
            sublabel=f"{len(fns)} function{'s' if len(fns) != 1 else ''}",
        ))


def _place_rds(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    """Standalone instances in their subnet; Aurora / DocumentDB / Neptune clusters as groups."""
    instances = storage.get("rds_instances", [])
    by_name = {db.get("name", ""): db for db in instances}
    clustered: set[str] = set()

    for cluster in storage.get("rds_clusters", []):
        gid = _node_id("rds_cluster", cluster.get("resource_id", ""))
        members, subnet_ids = [], []
        for m in cluster.get("members", []):
            db = by_name.get(m.get("instance_id", ""))
            if not db:
                continue
            clustered.add(db.get("name", ""))
            members.append(_register(model, DiagramNode(
                id=_node_id("rds_instance", db.get("resource_id", "")),
                resource_type=_rds_icon(db.get("engine") or cluster.get("engine")),
                label=_safe_label(db.get("name", ""), 22), container_id="group",
                sublabel=f"{'writer' if m.get('is_writer') else 'reader'} · {db.get('availability_zone') or ''}",
                tooltip=_words(db.get("name"), db.get("instance_class")),
            )).id)
            if db.get("subnet_id"):
                subnet_ids.append(db["subnet_id"])
            else:
                subnet_ids.extend(db.get("subnet_ids", []))
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=gid, label=_safe_label(cluster.get("name", ""), 34), category="database",
            subnet_ids=subnet_ids, members=_capped(model, gid, members),
            icon=_cluster_icon(cluster.get("engine")),
            sublabel=" ".join(x for x in [cluster.get("engine") or "", cluster.get("engine_version") or "",
                                          cluster.get("engine_mode") if cluster.get("engine_mode") not in (None, "provisioned") else ""] if x),
        )
        if _add_group(region, group):
            for ep in (cluster.get("endpoint"), cluster.get("reader_endpoint")):
                if ep:
                    model.dns_index[_normalize_dns(ep)] = gid

    for db in instances:
        if db.get("name", "") in clustered or db.get("cluster_identifier"):
            continue
        subnet_id = db.get("subnet_id", "")
        if not subnet_id:
            continue
        node = _register(model, DiagramNode(
            id=_node_id("rds_instance", db.get("resource_id", "")), resource_type=_rds_icon(db.get("engine")),
            label=_safe_label(db.get("name", "") or db.get("resource_id", "")), container_id=subnet_id,
            sublabel=" ".join(x for x in [db.get("engine") or "", "Multi-AZ" if db.get("multi_az") else ""] if x),
            attachments=[(_rds_icon(db.get("engine")), f"standby in {db['secondary_availability_zone']}")]
            if db.get("multi_az") and db.get("secondary_availability_zone") else [],
            tooltip=_words(db.get("name"), db.get("instance_class"),
                           f"{db['allocated_storage_gb']} GiB" if db.get("allocated_storage_gb") else "",
                           db.get("storage_type")),
        ))
        _add_to_subnet(region, subnet_id, node.id)
        if db.get("endpoint"):
            model.dns_index[_normalize_dns(db["endpoint"])] = node.id


def _place_elasticache(model: DiagramModel, region: RegionModel, storage: dict) -> None:
    clusters = storage.get("elasticache_clusters", [])
    by_id = {c.get("name", ""): c for c in clusters}
    grouped: set[str] = set()

    for rg in storage.get("elasticache_replication_groups", []):
        gid = _node_id("elasticache_replication_group", rg.get("resource_id", ""))
        members, subnet_ids = [], list(rg.get("subnet_ids", []))
        for cid in rg.get("member_clusters", []):
            c = by_id.get(cid)
            if not c:
                continue
            grouped.add(cid)
            members.append(_register(model, DiagramNode(
                id=_node_id("elasticache_cluster", c.get("resource_id", cid)), resource_type="cache_node",
                label=_safe_label(cid, 22), container_id="group",
                sublabel=c.get("availability_zone") or c.get("node_type", ""),
            )).id)
            if c.get("subnet_id"):
                subnet_ids.append(c["subnet_id"])
        if not subnet_ids:
            continue
        _add_group(region, DiagramGroup(
            id=gid, label=_safe_label(rg.get("name", ""), 34), category="database", subnet_ids=subnet_ids,
            members=_capped(model, gid, members), icon=_cache_icon(rg.get("engine")),
            sublabel=" · ".join(x for x in [
                f"ElastiCache {rg.get('engine') or ''}".strip(), rg.get("node_type") or "",
                "cluster mode" if rg.get("cluster_mode") else ""] if x),
        ))

    for c in clusters:
        if c.get("name", "") in grouped or c.get("replication_group_id") or not c.get("subnet_id"):
            continue
        node = _register(model, DiagramNode(
            id=_node_id("elasticache_cluster", c.get("resource_id", "")), resource_type=_cache_icon(c.get("engine")),
            label=_safe_label(c.get("name", "")), container_id=c["subnet_id"],
            sublabel=f"{c.get('engine') or ''} × {c.get('num_nodes') or 1}",
        ))
        _add_to_subnet(region, c["subnet_id"], node.id)


def _place_simple_groups(model: DiagramModel, region: RegionModel, storage: dict,
                         analytics: dict, integration: dict) -> None:
    """Multi-AZ managed services without child resources."""
    specs = []
    for c in storage.get("elasticache_serverless_caches", []):
        specs.append(("elasticache_serverless", c, _cache_icon(c.get("engine")), "database",
                      f"ElastiCache Serverless · {c.get('engine') or ''}"))
    for c in storage.get("memorydb_clusters", []):
        specs.append(("memorydb", c, "elasticache_redis", "database",
                      f"MemoryDB · {c.get('node_type') or ''} · {c.get('shards') or '?'} shards"))
    for d in storage.get("opensearch_domains", []):
        specs.append(("opensearch_domain", d, "opensearch", "analytics",
                      f"OpenSearch · {d.get('instance_type') or ''} × {d.get('instance_count') or '?'}"))
    for fs in storage.get("efs_file_systems", []):
        fs = dict(fs, subnet_ids=[mt["subnet_id"] for mt in fs.get("mount_targets", []) if mt.get("subnet_id")])
        specs.append(("efs_filesystem", fs, "efs", "storage",
                      f"Amazon EFS · {fs.get('performance_mode') or ''}"))
    for fs in storage.get("fsx_file_systems", []):
        specs.append(("fsx", fs, "fsx", "storage",
                      f"FSx {fs.get('file_system_type') or ''} · {fs.get('storage_capacity_gb') or '?'} GiB"))
    for c in analytics.get("msk_clusters", []):
        parts = ["Amazon MSK",
                 f"{c.get('broker_count')} × {c.get('instance_type')}" if c.get("broker_count")
                 else (c.get("cluster_type") or "").title(),
                 f"Kafka {c['kafka_version']}" if c.get("kafka_version") else ""]
        specs.append(("msk_cluster", c, "msk", "analytics", " · ".join(p for p in parts if p)))
    for b in integration.get("mq_brokers", []):
        specs.append(("mq_broker", b, "mq", "integration",
                      f"Amazon MQ {b.get('engine') or ''} · {b.get('deployment_mode') or ''}"))

    for kind, res, icon, category, sublabel in specs:
        subnet_ids = res.get("subnet_ids", [])
        if not subnet_ids:
            continue
        group = DiagramGroup(
            id=_node_id(kind, res.get("resource_id", "") or res.get("name", "")),
            label=_safe_label(res.get("name", "") or res.get("file_system_id", "") or kind, 34),
            category=category, subnet_ids=list(subnet_ids), icon=icon, sublabel=sublabel,
        )
        if _add_group(region, group):
            for key in ("endpoint", "dns_name"):
                if res.get(key):
                    model.dns_index[_normalize_dns(res[key])] = group.id


def _place_single_subnet_nodes(model: DiagramModel, region: RegionModel, storage: dict, analytics: dict) -> None:
    for c in storage.get("redshift_clusters", []):
        if c.get("subnet_id"):
            node = _register(model, DiagramNode(
                id=_node_id("redshift_cluster", c.get("resource_id", "")), resource_type="redshift",
                label=_safe_label(c.get("name", "") or "Redshift"), container_id=c["subnet_id"],
                sublabel=f"{c.get('node_type') or ''} × {c.get('number_of_nodes') or 1}",
            ))
            _add_to_subnet(region, c["subnet_id"], node.id)
    for c in analytics.get("emr_clusters", []):
        if c.get("subnet_ids"):
            node = _register(model, DiagramNode(
                id=_node_id("emr_cluster", c.get("cluster_id") or c.get("resource_id", "")), resource_type="emr",
                label=_safe_label(c.get("name", "")), container_id=c["subnet_ids"][0],
                sublabel=c.get("release_label") or "", tooltip=", ".join(c.get("applications") or []),
            ))
            _add_to_subnet(region, c["subnet_ids"][0], node.id)


def _place_nfw(model: DiagramModel, region: RegionModel, nfws: list[dict]) -> None:
    """Network Firewall group plus its endpoint in every firewall subnet."""
    for fw in nfws:
        subnet_ids = fw.get("subnet_mappings", [])
        if not subnet_ids:
            continue
        for sid in subnet_ids:
            ep_id = (fw.get("subnet_to_endpoint") or {}).get(sid, "")
            node = _register(model, DiagramNode(
                id=_node_id("nfw_endpoint", ep_id or f"{fw.get('name', '')}-{sid}"), resource_type="network_firewall",
                label="Firewall endpoint", container_id=sid, sublabel=ep_id,
            ))
            _add_to_subnet(region, sid, node.id)
        _add_group(region, DiagramGroup(
            id=_node_id("network_firewall", fw.get("resource_id", "")),
            label=_safe_label(fw.get("name", "") or "Network Firewall", 34), category="security",
            subnet_ids=list(subnet_ids), icon="network_firewall",
            sublabel=f"AWS Network Firewall · {fw.get('status') or ''}",
        ))


# ── Gutter, tiles ───────────────────────────────────────────────────

def _build_gutter(model: DiagramModel, region: RegionModel, net: dict, security: dict) -> None:
    """Region-level entry points and connectivity, drawn left of the VPCs."""
    gid = f"gutter:{region.name}"

    def add(node: DiagramNode) -> DiagramNode:
        region.gutter_nodes.append(_register(model, node))
        return node

    for api in net.get("api_gateway_rest_apis", []):
        add(DiagramNode(
            id=_node_id("api_gateway_rest", api.get("resource_id", "")), resource_type="api_gateway",
            label=_safe_label(api.get("name", ""), 22), container_id=gid,
            sublabel="REST · " + ", ".join(api.get("endpoint_types", [])),
        ))
        if api.get("resource_id"):
            model.dns_index[f"{api['resource_id']}.execute-api.{region.name}.amazonaws.com"] = \
                _node_id("api_gateway_rest", api["resource_id"])
    for api in net.get("api_gateway_http_apis", []):
        node = add(DiagramNode(
            id=_node_id("api_gateway_http", api.get("resource_id", "")), resource_type="api_gateway",
            label=_safe_label(api.get("name", ""), 22), container_id=gid, sublabel=api.get("protocol_type") or "HTTP",
        ))
        if api.get("api_endpoint"):
            model.dns_index[_normalize_dns(api["api_endpoint"].split("://", 1)[-1].split("/", 1)[0])] = node.id

    for waf in net.get("waf_web_acls", []) or security.get("waf_web_acls", []):
        n_res = len(waf.get("associated_resources", []))
        add(DiagramNode(
            id=_node_id("waf_web_acl", waf.get("resource_id", "")), resource_type="waf",
            label=_safe_label(waf.get("name", "") or "AWS WAF", 22), container_id=gid,
            sublabel=f"protects {n_res}" if n_res else "not associated",
        ))

    for tgw in net.get("transit_gateways", []):
        tid = tgw.get("resource_id", "")
        n_att = sum(1 for a in net.get("transit_gateway_attachments", []) if a.get("transit_gateway_id") == tid)
        add(DiagramNode(
            id=_node_id("transit_gateway", tid), resource_type="transit_gateway",
            label=_safe_label(tgw.get("name", "") or tid, 22), container_id=gid,
            sublabel=f"{n_att} attachments" if n_att else "Transit Gateway",
        ))

    for vpn in net.get("vpn_connections", []):
        tunnels = vpn.get("tunnels", [])
        up = sum(1 for t in tunnels if (t.get("status") or "").upper() == "UP")
        add(DiagramNode(
            id=_node_id("vpn_connection", vpn.get("resource_id", "")), resource_type="vpn_connection",
            label=_safe_label(vpn.get("name", "") or vpn.get("resource_id", "") or "VPN", 22), container_id=gid,
            sublabel=f"Site-to-Site VPN · {up}/{len(tunnels)} up" if tunnels else "Site-to-Site VPN",
        ))

    for dx in net.get("direct_connect_connections", []):
        add(DiagramNode(
            id=_node_id("direct_connect", dx.get("resource_id", "")), resource_type="direct_connect",
            label=_safe_label(dx.get("name", "") or "Direct Connect", 22), container_id=gid,
            sublabel=" · ".join(x for x in [dx.get("bandwidth") or "", dx.get("location") or ""] if x),
        ))

    for cgw in net.get("customer_gateways", []):
        model.onprem_nodes.append(_register(model, DiagramNode(
            id=_node_id("customer_gateway", cgw.get("resource_id", "")), resource_type="customer_gateway",
            label=_safe_label(cgw.get("name", "") or cgw.get("resource_id", "") or "Customer gateway", 22),
            container_id="onprem", sublabel=cgw.get("ip_address") or "",
        )))


def _build_tiles(region: RegionModel, region_data: dict, buckets: list[dict]) -> None:
    tiles: dict[str, ServiceTile] = {}

    def count(display: str, icon: str, category: str, resources: list[dict]) -> None:
        if not resources:
            return
        tile = tiles.setdefault(display, ServiceTile(service=display, icon=icon, count=0, category=category))
        tile.count += len(resources)
        tile.names.extend(r.get("name", "") for r in resources[:10] if len(tile.names) < 10)

    for category_data in region_data.values():
        if isinstance(category_data, dict):
            for key, rlist in category_data.items():
                if key in TILE_SERVICES and isinstance(rlist, list):
                    count(*TILE_SERVICES[key], rlist)

    storage = region_data.get("storage", {}) or {}
    compute = region_data.get("compute", {}) or {}
    count("S3", "s3", "Storage", buckets)
    count("EBS (unattached)", "ebs_volume", "Storage",
          [v for v in storage.get("ebs_volumes", []) if not v.get("attachments")])
    count("Idle Elastic IPs", "elastic_ip", "Compute",
          [e for e in (region_data.get("networking", {}) or {}).get("elastic_ips", []) if not e.get("association_id")])
    count("Lambda", "lambda", "Compute",
          [f for f in compute.get("lambda_functions", []) if not (f.get("vpc_config") or {}).get("SubnetIds")])
    count("OpenSearch", "opensearch", "Analytics",
          [d for d in storage.get("opensearch_domains", []) if not d.get("subnet_ids")])
    count("ECS (non-VPC)", "ecs_cluster", "Compute",
          [s for s in compute.get("ecs_services", []) if not s.get("subnet_ids")])

    order = {c: i for i, c in enumerate(SERVICE_CATEGORIES)}
    region.tiles = sorted(tiles.values(), key=lambda t: (order.get(t.category, 99), t.service))


# ── Edges ───────────────────────────────────────────────────────────

def _build_edges(model: DiagramModel, account_data: dict) -> None:
    global_data = account_data.get("global", {}) or {}
    regions_data = account_data.get("regions", {}) or {}
    edges = model.edges

    # Users → front door
    zones = global_data.get("route53", {}).get("route53_hosted_zones", [])
    if "global:route53" in model.all_nodes and any(not z.get("is_private") for z in zones):
        edges.append(DiagramEdge("global:users", "global:route53", "traffic"))
    elif "global:cloudfront" in model.all_nodes:
        edges.append(DiagramEdge("global:users", "global:cloudfront", "traffic"))

    # Route 53 alias → CloudFront / LB / API GW / GA
    for zone in zones:
        for alias in zone.get("alias_targets", []):
            target = model.dns_index.get(_normalize_dns(alias.get("dns_name", "")))
            if target:
                edges.append(DiagramEdge("global:route53", target, "traffic"))

    # CloudFront → origins (ALB, API GW, S3)
    bucket_region = {b.get("name", ""): (b.get("location") or "us-east-1")
                     for b in global_data.get("s3", {}).get("s3_buckets", [])}
    for d in (global_data.get("edge", {}) or {}).get("cloudfront_distributions", []):
        for origin in d.get("origins", []):
            host = _normalize_dns(origin.get("domain_name", ""))
            target = model.dns_index.get(host)
            if not target and ".s3" in host:
                bucket = host.split(".s3", 1)[0]
                region = bucket_region.get(bucket)
                if region not in model.regions:
                    region = next(iter(model.regions), "")
                target = f"tile:{region}:S3"
            if target and target != "global:cloudfront":
                edges.append(DiagramEdge("global:cloudfront", target, "traffic"))

    for region_name, region_data in regions_data.items():
        region_data = region_data or {}
        net = region_data.get("networking", {}) or {}
        compute = region_data.get("compute", {}) or {}

        # Target group → targets (individual instance or collapsed fleet)
        for tg in net.get("target_groups", []):
            tg_id = _node_id("target_group", tg.get("resource_id", ""))
            for t in tg.get("targets", []):
                target = model.instance_index.get(t.get("id") or "")
                owner = model.owner_groups.get(model.fleet_owner.get(target or "", ""), "")
                if owner:
                    target = owner
                if target:
                    edges.append(DiagramEdge(tg_id, target, "traffic"))
        for svc in compute.get("ecs_services", []):
            for lb in svc.get("load_balancers", []):
                if lb.get("target_group_arn"):
                    edges.append(DiagramEdge(_node_id("target_group", lb["target_group_arn"]),
                                             _node_id("ecs_service", svc.get("resource_id", "")), "traffic"))
        for lb in net.get("load_balancers_classic", []):
            for iid in lb.get("instances", []):
                if model.instance_index.get(iid):
                    edges.append(DiagramEdge(f"load_balancer_classic:{region_name}:{lb.get('resource_id', '')}",
                                             model.instance_index[iid], "traffic"))

        # Transit Gateway → attached VPCs
        for att in net.get("transit_gateway_attachments", []):
            if (att.get("resource_type_attached") or "").lower() == "vpc":
                edges.append(DiagramEdge(_node_id("transit_gateway", att.get("transit_gateway_id", "")),
                                         f"vpc:{att.get('resource_id_attached', '')}", "network"))

        # Site-to-Site VPN: CGW → VPN → VGW / TGW
        for vpn in net.get("vpn_connections", []):
            vid = _node_id("vpn_connection", vpn.get("resource_id", ""))
            if vpn.get("customer_gateway_id"):
                edges.append(DiagramEdge(_node_id("customer_gateway", vpn["customer_gateway_id"]), vid, "network"))
            if vpn.get("vpn_gateway_id"):
                edges.append(DiagramEdge(vid, f"vgw:{vpn['vpn_gateway_id']}", "network"))
            elif vpn.get("transit_gateway_id"):
                edges.append(DiagramEdge(vid, _node_id("transit_gateway", vpn["transit_gateway_id"]), "network"))

        for peer in net.get("vpc_peering_connections", []):
            req, acc = peer.get("requester_vpc_id", ""), peer.get("accepter_vpc_id", "")
            if req and acc:
                edges.append(DiagramEdge(f"vpc:{req}", f"vpc:{acc}", "network", "peering"))

        # WAF → protected ALB / API Gateway
        for waf in net.get("waf_web_acls", []):
            wid = _node_id("waf_web_acl", waf.get("resource_id", ""))
            for arn in waf.get("associated_resources", []):
                if ":loadbalancer/" in arn:
                    edges.append(DiagramEdge(wid, _node_id("load_balancer_v2", arn), "security"))
                elif "/restapis/" in arn:
                    api_id = arn.split("/restapis/", 1)[1].split("/", 1)[0]
                    edges.append(DiagramEdge(wid, f"api_gateway_rest:{api_id}", "security"))

        # Cross-region replication between service tiles
        for table in (region_data.get("storage", {}) or {}).get("dynamodb_tables", []):
            for replica in table.get("replica_regions", []):
                # Global tables list every replica in every region: draw one line per region pair.
                if replica != region_name and (replica not in regions_data or region_name < replica):
                    edges.append(DiagramEdge(f"tile:{region_name}:DynamoDB", f"tile:{replica}:DynamoDB",
                                             "replication", "global table"))
        for dest in compute.get("_ecr_replication", []):
            if dest.get("region") and dest["region"] != region_name:
                edges.append(DiagramEdge(f"tile:{region_name}:ECR", f"tile:{dest['region']}:ECR",
                                         "replication", "replication"))
