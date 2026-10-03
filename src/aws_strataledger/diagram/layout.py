"""
Diagram layout engine.

Computes deterministic positions and sizes for all containers, nodes,
groups, and edges. The layout follows the AWS architecture diagram
conventions: left-to-right request flow within regions, top-to-bottom
stacking of regions.

Layout units are in SVG user units (≈ pixels at 96 DPI).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    DiagramModel, RegionModel, VPCModel, AZModel, SubnetModel,
    DiagramNode, DiagramGroup, DiagramEdge, ServiceTile,
)

# ── Layout constants ────────────────────────────────────────────────

PAD = 20            # general padding
ICON_SIZE = 32      # icon width/height
ICON_GAP = 12       # gap between icons
LABEL_H = 16        # label text height
HEADER_H = 28       # container header height

# Subnet cell
SUBNET_MIN_W = 120
SUBNET_MIN_H = 80
SUBNET_PAD = 10
MAX_ICONS_PER_SUBNET = 8

# AZ row
AZ_PAD = 8

# Tier columns
TIER_ORDER = ["firewall", "public", "app", "data"]
TIER_MIN_W = 140

# VPC
VPC_PAD = 12
VPC_ENDPOINT_COL_W = 80  # endpoint column on right edge
IGW_COL_W = 36           # IGW/VGW gutter on left edge

# Region
REGION_PAD = 16
TILE_W = 140
TILE_H = 48
TILE_GAP = 8
GUTTER_W = 80

# Global column
GLOBAL_W = 120
GLOBAL_PAD = 16

# Cloud
CLOUD_PAD = 24


@dataclass
class Rect:
    """A positioned rectangle."""
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class LayoutNode:
    """A positioned resource icon."""
    id: str
    rect: Rect
    resource_type: str
    label: str
    sublabel: str = ""


@dataclass
class LayoutMember:
    """A member node rendered inside a group."""
    id: str
    rect: Rect
    resource_type: str
    label: str
    sublabel: str = ""


@dataclass
class LayoutGroup:
    """A positioned multi-AZ group."""
    id: str
    rect: Rect
    label: str
    category: str
    sublabel: str = ""
    members: list[LayoutMember] = field(default_factory=list)


@dataclass
class LayoutEdge:
    """A positioned edge with waypoints."""
    source: str
    target: str
    kind: str
    label: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class LayoutContainer:
    """A positioned container (Cloud, Region, VPC, AZ, Subnet)."""
    id: str
    kind: str  # aws_cloud, region, vpc, az, subnet_public, subnet_private, etc.
    rect: Rect
    label: str = ""
    sublabel: str = ""


@dataclass
class LayoutTile:
    """A positioned service tile."""
    service: str
    icon: str
    count: int
    rect: Rect
    names: list[str] = field(default_factory=list)


@dataclass
class LayoutResult:
    """Complete layout output."""
    width: float = 0
    height: float = 0
    containers: list[LayoutContainer] = field(default_factory=list)
    nodes: list[LayoutNode] = field(default_factory=list)
    groups: list[LayoutGroup] = field(default_factory=list)
    edges: list[LayoutEdge] = field(default_factory=list)
    tiles: list[LayoutTile] = field(default_factory=list)
    global_nodes: list[LayoutNode] = field(default_factory=list)


def compute_layout(model: DiagramModel) -> LayoutResult:
    """
    Compute the full layout for a DiagramModel.

    Returns a LayoutResult with positioned elements ready for SVG rendering.
    """
    result = LayoutResult()

    # ── Global column ───────────────────────────────────────────────
    global_x = CLOUD_PAD
    global_y = CLOUD_PAD + HEADER_H + PAD
    for i, gn in enumerate(model.global_nodes):
        ny = global_y + i * (ICON_SIZE + LABEL_H + ICON_GAP * 2)
        result.global_nodes.append(LayoutNode(
            id=gn.id,
            rect=Rect(global_x + (GLOBAL_W - ICON_SIZE) / 2, ny, ICON_SIZE, ICON_SIZE),
            resource_type=gn.resource_type,
            label=gn.label,
            sublabel=gn.sublabel,
        ))
    global_col_h = len(model.global_nodes) * (ICON_SIZE + LABEL_H + ICON_GAP * 2) + PAD

    # ── Regions ─────────────────────────────────────────────────────
    region_x = CLOUD_PAD + GLOBAL_W + GLOBAL_PAD
    region_y = CLOUD_PAD + HEADER_H + PAD
    max_region_right = region_x

    for region_name, region_model in model.regions.items():
        rr, region_h = _layout_region(result, region_model, region_x, region_y, model)
        result.containers.append(LayoutContainer(
            id=f"region:{region_name}",
            kind="region",
            rect=rr,
            label=region_name,
        ))
        max_region_right = max(max_region_right, rr.right)
        region_y = rr.bottom + REGION_PAD

    # ── AWS Cloud container ─────────────────────────────────────────
    cloud_w = max(max_region_right + CLOUD_PAD - CLOUD_PAD, GLOBAL_W + 400)
    cloud_h = max(region_y, global_col_h + CLOUD_PAD + HEADER_H) + CLOUD_PAD
    result.containers.insert(0, LayoutContainer(
        id="aws_cloud",
        kind="aws_cloud",
        rect=Rect(0, 0, cloud_w, cloud_h),
        label=f"AWS Cloud · {model.account_alias} ({model.account_id})",
    ))

    result.width = cloud_w
    result.height = cloud_h

    # ── Edges ───────────────────────────────────────────────────────
    _layout_edges(result, model)

    return result


def _layout_region(
    result: LayoutResult,
    region: RegionModel,
    rx: float, ry: float,
    model: DiagramModel,
) -> tuple[Rect, float]:
    """Layout one region. Returns (region_rect, height)."""
    inner_x = rx + REGION_PAD
    inner_y = ry + HEADER_H + REGION_PAD

    # Gutter (left side: TGW, VPN, API GW)
    gutter_x = inner_x
    if region.gutter_nodes:
        for i, gn in enumerate(region.gutter_nodes):
            ny = inner_y + i * (ICON_SIZE + LABEL_H + ICON_GAP)
            result.nodes.append(LayoutNode(
                id=gn.id,
                rect=Rect(gutter_x + (GUTTER_W - ICON_SIZE) / 2, ny, ICON_SIZE, ICON_SIZE),
                resource_type=gn.resource_type,
                label=gn.label,
            ))
        vpc_x = gutter_x + GUTTER_W + PAD
    else:
        vpc_x = inner_x

    # VPCs
    vpc_y = inner_y
    max_vpc_right = vpc_x
    for vpc_id, vpc_model in region.vpcs.items():
        vr = _layout_vpc(result, vpc_model, vpc_x, vpc_y, model)
        result.containers.append(LayoutContainer(
            id=f"vpc:{vpc_id}",
            kind="vpc",
            rect=vr,
            label=f"{vpc_model.name} {vpc_model.cidr}",
        ))
        max_vpc_right = max(max_vpc_right, vr.right)
        vpc_y = vr.bottom + VPC_PAD

    # Tiles (right side panel)
    tiles_x = max_vpc_right + PAD
    tiles_y = inner_y
    if region.tiles:
        for i, tile in enumerate(region.tiles):
            ty = tiles_y + i * (TILE_H + TILE_GAP)
            result.tiles.append(LayoutTile(
                service=tile.service,
                icon=tile.icon,
                count=tile.count,
                rect=Rect(tiles_x, ty, TILE_W, TILE_H),
                names=tile.names,
            ))
        tiles_bottom = tiles_y + len(region.tiles) * (TILE_H + TILE_GAP)
    else:
        tiles_bottom = inner_y

    region_w = (tiles_x + TILE_W + REGION_PAD) - rx
    region_h = max(vpc_y, tiles_bottom) + REGION_PAD - ry
    rr = Rect(rx, ry, region_w, region_h)

    return rr, region_h


def _layout_vpc(
    result: LayoutResult,
    vpc: VPCModel,
    vx: float, vy: float,
    model: DiagramModel,
) -> Rect:
    """Layout one VPC container. Returns its bounding Rect."""
    inner_x = vx + VPC_PAD
    inner_y = vy + HEADER_H + VPC_PAD

    # IGW/VGW gutter
    if vpc.igw_id:
        result.nodes.append(LayoutNode(
            id=f"igw:{vpc.igw_id}",
            rect=Rect(inner_x, inner_y, ICON_SIZE, ICON_SIZE),
            resource_type="igw",
            label="IGW",
        ))
        model.all_nodes[f"igw:{vpc.igw_id}"] = DiagramNode(
            id=f"igw:{vpc.igw_id}", resource_type="igw", label="IGW",
            container_id=vpc.id,
        )
    if vpc.vgw_id:
        result.nodes.append(LayoutNode(
            id=f"vgw:{vpc.vgw_id}",
            rect=Rect(inner_x, inner_y + ICON_SIZE + ICON_GAP, ICON_SIZE, ICON_SIZE),
            resource_type="vpn_gateway",
            label="VGW",
        ))

    tier_x_start = inner_x + IGW_COL_W + PAD

    # Determine which tiers are present
    present_tiers: list[str] = []
    for tier in TIER_ORDER:
        for az in vpc.azs.values():
            if tier in az.subnets:
                if tier not in present_tiers:
                    present_tiers.append(tier)

    if not present_tiers:
        present_tiers = ["app"]

    # Tier header row
    tier_x = tier_x_start
    tier_positions: dict[str, float] = {}
    for tier in present_tiers:
        tier_positions[tier] = tier_x
        tier_x += TIER_MIN_W + PAD

    # AZ rows
    az_y = inner_y + HEADER_H  # below tier headers
    sorted_azs = sorted(vpc.azs.keys())
    for az_name in sorted_azs:
        az_model = vpc.azs[az_name]
        az_h = SUBNET_MIN_H + AZ_PAD * 2

        # Layout subnets in tier columns
        for tier in present_tiers:
            if tier in az_model.subnets:
                sm = az_model.subnets[tier]
                sx = tier_positions[tier]
                sy = az_y + AZ_PAD

                # Compute subnet size from icon count
                num_icons = min(len(sm.nodes), MAX_ICONS_PER_SUBNET)
                cols = max(1, min(num_icons, 4))
                rows = max(1, (num_icons + cols - 1) // cols)
                sw = max(SUBNET_MIN_W, cols * (ICON_SIZE + ICON_GAP) + SUBNET_PAD * 2)
                sh = max(SUBNET_MIN_H, rows * (ICON_SIZE + ICON_GAP) + HEADER_H + SUBNET_PAD * 2)
                az_h = max(az_h, sh + AZ_PAD * 2)

                tier_kind = f"subnet_{tier}" if tier != "app" else "subnet_private"
                result.containers.append(LayoutContainer(
                    id=f"subnet:{sm.id}",
                    kind=tier_kind,
                    rect=Rect(sx, sy, sw, sh),
                    label=sm.name,
                    sublabel=sm.cidr,
                ))

                # Place icons in subnet
                icon_x = sx + SUBNET_PAD
                icon_y = sy + HEADER_H + SUBNET_PAD
                for j, node_id in enumerate(sm.nodes[:MAX_ICONS_PER_SUBNET]):
                    if node_id in model.all_nodes:
                        node_data = model.all_nodes[node_id]
                        col = j % cols
                        row = j // cols
                        result.nodes.append(LayoutNode(
                            id=node_id,
                            rect=Rect(
                                icon_x + col * (ICON_SIZE + ICON_GAP),
                                icon_y + row * (ICON_SIZE + ICON_GAP),
                                ICON_SIZE, ICON_SIZE,
                            ),
                            resource_type=node_data.resource_type,
                            label=node_data.label,
                            sublabel=node_data.sublabel,
                        ))

                # "+N more" chip
                overflow = len(sm.nodes) - MAX_ICONS_PER_SUBNET
                if overflow > 0:
                    result.nodes.append(LayoutNode(
                        id=f"overflow:{sm.id}",
                        rect=Rect(icon_x, sy + sh - LABEL_H - SUBNET_PAD, sw - SUBNET_PAD * 2, LABEL_H),
                        resource_type="generic",
                        label=f"+{overflow} more",
                    ))

        # AZ container
        az_w = tier_x - tier_x_start + PAD
        result.containers.append(LayoutContainer(
            id=f"az:{az_name}",
            kind="az",
            rect=Rect(tier_x_start - AZ_PAD, az_y, az_w + AZ_PAD * 2, az_h),
            label=az_name,
        ))
        az_y += az_h + AZ_PAD

    # Groups (multi-AZ constructs)
    for group in vpc.groups:
        # Find bounding box of the group's subnets
        gx1 = float("inf")
        gy1 = float("inf")
        gx2 = 0.0
        gy2 = 0.0
        for c in result.containers:
            for sid in group.subnet_ids:
                if c.id == f"subnet:{sid}":
                    gx1 = min(gx1, c.rect.x)
                    gy1 = min(gy1, c.rect.y)
                    gx2 = max(gx2, c.rect.right)
                    gy2 = max(gy2, c.rect.bottom)
        if gx1 < float("inf"):
            margin = 6
            gr = Rect(gx1 - margin, gy1 - margin, gx2 - gx1 + margin * 2, gy2 - gy1 + margin * 2)

            # Position member nodes inside the group
            layout_members: list[LayoutMember] = []
            if group.members:
                member_y = gr.y + HEADER_H + 4
                member_x = gr.x + 10
                for mid in group.members:
                    node_data = model.all_nodes.get(mid)
                    if not node_data:
                        continue
                    layout_members.append(LayoutMember(
                        id=mid,
                        rect=Rect(member_x, member_y, ICON_SIZE, ICON_SIZE),
                        resource_type=node_data.resource_type,
                        label=node_data.label,
                        sublabel=node_data.sublabel,
                    ))
                    member_x += ICON_SIZE + ICON_GAP + 60
                # Expand group rect to fit members
                members_bottom = member_y + ICON_SIZE + LABEL_H + 8
                if members_bottom > gr.bottom:
                    gr.h = members_bottom - gr.y
                members_right = member_x
                if members_right > gr.right:
                    gr.w = members_right - gr.x

            result.groups.append(LayoutGroup(
                id=group.id,
                rect=gr,
                label=group.label,
                category=group.category,
                sublabel=group.sublabel,
                members=layout_members,
            ))

    # Endpoint column (right edge of VPC)
    ep_x = tier_x + PAD
    ep_y = inner_y + HEADER_H
    for i, ep in enumerate(vpc.endpoints[:12]):
        ey = ep_y + i * (ICON_SIZE + ICON_GAP)
        result.nodes.append(LayoutNode(
            id=ep.id,
            rect=Rect(ep_x, ey, ICON_SIZE, ICON_SIZE),
            resource_type=ep.resource_type,
            label=ep.label,
            sublabel=ep.sublabel,
        ))

    vpc_w = (ep_x + VPC_ENDPOINT_COL_W + VPC_PAD) - vx
    vpc_h = max(az_y, ep_y + len(vpc.endpoints[:12]) * (ICON_SIZE + ICON_GAP)) + VPC_PAD - vy
    return Rect(vx, vy, vpc_w, vpc_h)


def _layout_edges(result: LayoutResult, model: DiagramModel) -> None:
    """Compute edge waypoints using simple orthogonal routing."""
    node_rects: dict[str, Rect] = {}
    for n in result.nodes + result.global_nodes:
        node_rects[n.id] = n.rect

    for edge in model.edges:
        src_rect = node_rects.get(edge.source)
        tgt_rect = node_rects.get(edge.target)
        if not src_rect or not tgt_rect:
            continue  # skip edges to nodes we don't have layout for

        # Simple L-shaped routing: source right → bend → target left
        sx = src_rect.right
        sy = src_rect.cy
        tx = tgt_rect.x
        ty = tgt_rect.cy
        mx = (sx + tx) / 2

        result.edges.append(LayoutEdge(
            source=edge.source,
            target=edge.target,
            kind=edge.kind,
            label=edge.label,
            points=[(sx, sy), (mx, sy), (mx, ty), (tx, ty)],
        ))
