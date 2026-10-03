"""
Diagram layout engine.

Computes deterministic positions and sizes for all containers, nodes,
groups, and edges. The layout follows the AWS architecture diagram
conventions: left-to-right request flow within regions, top-to-bottom
stacking of regions.

Inside a VPC, every multi-subnet construct (ALB, EKS, Aurora, …) gets a
header card stacked at the top of its tier column. The card holds the
parent's icon and its child resources; the construct's dashed outline
joins the card to the subnets it spans.

Layout units are in SVG user units (≈ pixels at 96 DPI).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .model import DiagramModel, RegionModel, VPCModel, DiagramNode, DiagramGroup

# ── Layout constants ────────────────────────────────────────────────

PAD = 20
ICON_SIZE = 32
ICON_GAP = 12
LABEL_H = 16
HEADER_H = 28

# Icon cell (icon + label + sublabel) inside subnets and group cards
CELL_W = 88
CELL_H = ICON_SIZE + 30
ATTACH_H = 18           # extra row for attached mini icons (EBS, EIP)

SUBNET_MIN_W = 120
SUBNET_MIN_H = 80
SUBNET_PAD = 10
MAX_ICONS_PER_SUBNET = 8
MAX_SUBNET_COLS = 4

AZ_PAD = 8
AZ_LABEL_H = 18

TIER_ORDER = ["firewall", "public", "app", "data"]
TIER_MIN_W = 140

CARD_HEADER_H = 34
CARD_PAD = 8
CARD_GAP = 10

VPC_PAD = 12
VPC_ENDPOINT_COL_W = 80
IGW_COL_W = 36

REGION_PAD = 16
TILE_W = 140
TILE_H = 48
TILE_GAP = 8
GUTTER_W = 80

GLOBAL_W = 120
GLOBAL_PAD = 16

CLOUD_PAD = 24


@dataclass
class Rect:
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
    attachments: list[tuple[str, str]] = field(default_factory=list)
    tooltip: str = ""


@dataclass
class LayoutMember:
    """A child node rendered inside a group card."""
    id: str
    rect: Rect
    resource_type: str
    label: str
    sublabel: str = ""
    tooltip: str = ""


@dataclass
class LayoutGroup:
    """A positioned multi-subnet construct: dashed outline + header card."""
    id: str
    rect: Rect
    label: str
    category: str
    sublabel: str = ""
    members: list[LayoutMember] = field(default_factory=list)
    card: Rect | None = None
    icon: str = ""
    outline: bool = True  # False when the card's tier column already conveys the span


@dataclass
class LayoutEdge:
    source: str
    target: str
    kind: str
    label: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class LayoutContainer:
    """A positioned container (Cloud, Region, VPC, AZ, Subnet)."""
    id: str
    kind: str
    rect: Rect
    label: str = ""
    sublabel: str = ""


@dataclass
class LayoutTile:
    service: str
    icon: str
    count: int
    rect: Rect
    names: list[str] = field(default_factory=list)
    id: str = ""


@dataclass
class LayoutResult:
    width: float = 0
    height: float = 0
    containers: list[LayoutContainer] = field(default_factory=list)
    nodes: list[LayoutNode] = field(default_factory=list)
    groups: list[LayoutGroup] = field(default_factory=list)
    edges: list[LayoutEdge] = field(default_factory=list)
    tiles: list[LayoutTile] = field(default_factory=list)
    global_nodes: list[LayoutNode] = field(default_factory=list)


def _layout_node(node: DiagramNode, rect: Rect) -> LayoutNode:
    return LayoutNode(
        id=node.id, rect=rect, resource_type=node.resource_type,
        label=node.label, sublabel=node.sublabel,
        attachments=list(node.attachments), tooltip=node.tooltip,
    )


def compute_layout(model: DiagramModel) -> LayoutResult:
    """Compute the full layout for a DiagramModel."""
    result = LayoutResult()

    global_x = CLOUD_PAD
    global_y = CLOUD_PAD + HEADER_H + PAD
    step = ICON_SIZE + LABEL_H + ICON_GAP * 2
    for i, gn in enumerate(model.global_nodes):
        result.global_nodes.append(_layout_node(
            gn, Rect(global_x + (GLOBAL_W - ICON_SIZE) / 2, global_y + i * step, ICON_SIZE, ICON_SIZE),
        ))
    global_col_h = len(model.global_nodes) * step + PAD

    region_x = CLOUD_PAD + GLOBAL_W + GLOBAL_PAD
    region_y = CLOUD_PAD + HEADER_H + PAD
    max_region_right = region_x

    for region_name, region_model in model.regions.items():
        rr = _layout_region(result, region_model, region_x, region_y, model)
        result.containers.append(LayoutContainer(
            id=f"region:{region_name}", kind="region", rect=rr, label=region_name,
        ))
        max_region_right = max(max_region_right, rr.right)
        region_y = rr.bottom + REGION_PAD

    cloud_w = max(max_region_right + CLOUD_PAD, GLOBAL_W + 400)
    cloud_h = max(region_y, global_col_h + CLOUD_PAD + HEADER_H) + CLOUD_PAD
    result.containers.insert(0, LayoutContainer(
        id="aws_cloud", kind="aws_cloud", rect=Rect(0, 0, cloud_w, cloud_h),
        label=f"AWS Cloud · {model.account_alias} ({model.account_id})",
    ))
    result.width = cloud_w
    result.height = cloud_h

    _layout_edges(result, model)
    return result


def _layout_region(
    result: LayoutResult, region: RegionModel, rx: float, ry: float, model: DiagramModel,
) -> Rect:
    inner_x = rx + REGION_PAD
    inner_y = ry + HEADER_H + REGION_PAD

    gutter_step = ICON_SIZE + LABEL_H + ICON_GAP + 8
    for i, gn in enumerate(region.gutter_nodes):
        result.nodes.append(_layout_node(
            gn, Rect(inner_x + (GUTTER_W - ICON_SIZE) / 2, inner_y + i * gutter_step, ICON_SIZE, ICON_SIZE),
        ))
    gutter_bottom = inner_y + len(region.gutter_nodes) * gutter_step
    vpc_x = inner_x + GUTTER_W + PAD if region.gutter_nodes else inner_x

    vpc_y = inner_y
    max_vpc_right = vpc_x
    for vpc_id, vpc_model in region.vpcs.items():
        vr = _layout_vpc(result, vpc_model, vpc_x, vpc_y, model)
        result.containers.append(LayoutContainer(
            id=f"vpc:{vpc_id}", kind="vpc", rect=vr,
            label=f"{vpc_model.name} {vpc_model.cidr}",
        ))
        max_vpc_right = max(max_vpc_right, vr.right)
        vpc_y = vr.bottom + VPC_PAD

    tiles_x = max_vpc_right + PAD
    for i, tile in enumerate(region.tiles):
        result.tiles.append(LayoutTile(
            service=tile.service, icon=tile.icon, count=tile.count,
            rect=Rect(tiles_x, inner_y + i * (TILE_H + TILE_GAP), TILE_W, TILE_H),
            names=tile.names, id=f"tile:{region.name}:{tile.service}",
        ))
    tiles_bottom = inner_y + len(region.tiles) * (TILE_H + TILE_GAP)

    region_w = (tiles_x + TILE_W + REGION_PAD) - rx
    region_h = max(vpc_y, tiles_bottom, gutter_bottom) + REGION_PAD - ry
    return Rect(rx, ry, region_w, region_h)


def _subnet_size(sm_nodes: list[str], model: DiagramModel) -> tuple[float, float, int, float]:
    """Return (width, height, cols, cell_height) for a subnet's icon grid."""
    shown = sm_nodes[:MAX_ICONS_PER_SUBNET]
    n = len(shown)
    cols = max(1, min(n, MAX_SUBNET_COLS))
    rows = max(1, (n + cols - 1) // cols) if n else 0
    has_attach = any(model.all_nodes.get(nid) and model.all_nodes[nid].attachments for nid in shown)
    cell_h = CELL_H + (ATTACH_H if has_attach else 0)
    overflow_h = LABEL_H + 4 if len(sm_nodes) > MAX_ICONS_PER_SUBNET else 0
    w = max(SUBNET_MIN_W, cols * CELL_W + SUBNET_PAD * 2)
    h = max(SUBNET_MIN_H, HEADER_H + SUBNET_PAD + rows * cell_h + overflow_h + SUBNET_PAD)
    return w, h, cols, cell_h


def _group_home_tier(group: DiagramGroup, tier_of: dict[str, str], present: list[str]) -> str:
    tiers = [tier_of[s] for s in group.subnet_ids if s in tier_of]
    if not tiers:
        return present[0]
    counts = Counter(tiers)
    return max(present, key=lambda t: (counts.get(t, 0), -present.index(t)))


def _card_min_width(group: DiagramGroup) -> float:
    header = 40 + 5.5 * max(len(group.label), len(group.sublabel))
    members = min(len(group.members), 3) * CELL_W + CARD_PAD * 2
    return max(TIER_MIN_W, min(header, 3 * CELL_W + CARD_PAD * 2), members)


def _card_height(n_members: int, width: float) -> float:
    if not n_members:
        return CARD_HEADER_H
    cols = max(1, int((width - CARD_PAD * 2) // CELL_W))
    rows = (n_members + cols - 1) // cols
    return CARD_HEADER_H + rows * CELL_H + CARD_PAD


def _layout_vpc(
    result: LayoutResult, vpc: VPCModel, vx: float, vy: float, model: DiagramModel,
) -> Rect:
    inner_x = vx + VPC_PAD
    inner_y = vy + HEADER_H + VPC_PAD

    if vpc.igw_id:
        result.nodes.append(LayoutNode(
            id=f"igw:{vpc.igw_id}", rect=Rect(inner_x, inner_y, ICON_SIZE, ICON_SIZE),
            resource_type="igw", label="IGW", tooltip=vpc.igw_id,
        ))
    if vpc.vgw_id:
        result.nodes.append(LayoutNode(
            id=f"vgw:{vpc.vgw_id}",
            rect=Rect(inner_x, inner_y + ICON_SIZE + LABEL_H + ICON_GAP * 2, ICON_SIZE, ICON_SIZE),
            resource_type="vpn_gateway", label="VGW", tooltip=vpc.vgw_id,
        ))

    # ── Sizing pass ─────────────────────────────────────────────────
    tier_of: dict[str, str] = {}
    sizes: dict[str, tuple[float, float, int, float]] = {}
    present_tiers: list[str] = []
    for az in vpc.azs.values():
        for sm in az.subnets.values():
            tier_of[sm.id] = sm.tier
            sizes[sm.id] = _subnet_size(sm.nodes, model)
    for tier in TIER_ORDER:
        if tier in tier_of.values():
            present_tiers.append(tier)
    if not present_tiers:
        present_tiers = ["app"]

    tier_w: dict[str, float] = {t: TIER_MIN_W for t in present_tiers}
    for sid, (w, _h, _c, _ch) in sizes.items():
        tier_w[tier_of[sid]] = max(tier_w[tier_of[sid]], w)

    home: dict[str, str] = {}
    for g in vpc.groups:
        home[g.id] = _group_home_tier(g, tier_of, present_tiers)
        tier_w[home[g.id]] = max(tier_w[home[g.id]], _card_min_width(g))

    tier_x_start = inner_x + IGW_COL_W + PAD
    tier_x: dict[str, float] = {}
    x = tier_x_start
    for tier in present_tiers:
        tier_x[tier] = x
        x += tier_w[tier] + PAD
    tiers_right = x

    # ── Group cards strip ───────────────────────────────────────────
    strip_y = inner_y
    stack_y = {t: strip_y for t in present_tiers}
    cards: dict[str, Rect] = {}
    order_in_tier: dict[str, list[str]] = {t: [] for t in present_tiers}
    for g in vpc.groups:
        t = home[g.id]
        ch = _card_height(len(g.members), tier_w[t])
        cards[g.id] = Rect(tier_x[t], stack_y[t], tier_w[t], ch)
        stack_y[t] += ch + CARD_GAP
        order_in_tier[t].append(g.id)
    strip_h = max(stack_y.values()) - strip_y
    if strip_h:
        strip_h += 6

    # ── AZ rows ─────────────────────────────────────────────────────
    subnet_rects: dict[str, Rect] = {}
    az_y = inner_y + strip_h
    for az_name in sorted(vpc.azs):
        az_model = vpc.azs[az_name]
        by_tier: dict[str, list] = {}
        for sm in az_model.subnets.values():
            by_tier.setdefault(sm.tier, []).append(sm)
        row_top = az_y + AZ_LABEL_H

        col_bottom = row_top
        for tier in present_tiers:
            sy = row_top
            for sm in by_tier.get(tier, []):
                _w, sh, cols, cell_h = sizes[sm.id]
                sx = tier_x[tier]
                sw = tier_w[tier]
                kind = "subnet_private" if tier == "app" else f"subnet_{tier}"
                result.containers.append(LayoutContainer(
                    id=f"subnet:{sm.id}", kind=kind, rect=Rect(sx, sy, sw, sh),
                    label=sm.name, sublabel=sm.cidr,
                ))
                subnet_rects[sm.id] = Rect(sx, sy, sw, sh)

                icon_x0 = sx + SUBNET_PAD + (CELL_W - ICON_SIZE) / 2
                icon_y0 = sy + HEADER_H + SUBNET_PAD
                for j, node_id in enumerate(sm.nodes[:MAX_ICONS_PER_SUBNET]):
                    node = model.all_nodes.get(node_id)
                    if node is None:
                        continue
                    result.nodes.append(_layout_node(node, Rect(
                        icon_x0 + (j % cols) * CELL_W,
                        icon_y0 + (j // cols) * cell_h,
                        ICON_SIZE, ICON_SIZE,
                    )))

                overflow = len(sm.nodes) - MAX_ICONS_PER_SUBNET
                if overflow > 0:
                    result.nodes.append(LayoutNode(
                        id=f"overflow:{sm.id}",
                        rect=Rect(sx + SUBNET_PAD, sy + sh - LABEL_H - SUBNET_PAD,
                                  sw - SUBNET_PAD * 2, LABEL_H),
                        resource_type="generic", label=f"+{overflow} more",
                    ))
                sy += sh + AZ_PAD
            col_bottom = max(col_bottom, sy - AZ_PAD)

        az_h = max(SUBNET_MIN_H, col_bottom - row_top) + AZ_LABEL_H + AZ_PAD
        result.containers.append(LayoutContainer(
            id=f"az:{vpc.id}:{az_name}", kind="az",
            rect=Rect(tier_x_start - AZ_PAD, az_y, tiers_right - tier_x_start, az_h),
            label=az_name,
        ))
        az_y += az_h + AZ_PAD

    # ── Groups: outline (card ∪ subnets) + members in card ─────────
    # An outline is only drawn when the span isn't simply "every subnet of the card's tier".
    needs: set[str] = set()
    for g in vpc.groups:
        local = {s for s in g.subnet_ids if s in subnet_rects}
        if local and local != {s for s, tr in tier_of.items() if tr == home[g.id]}:
            needs.add(g.id)
    for g in vpc.groups:
        card = cards[g.id]
        needs_outline = g.id in needs
        outlined = [gid for gid in order_in_tier[home[g.id]] if gid in needs]
        rank = outlined.index(g.id) if needs_outline else 0
        margin = 4 + 4 * (len(outlined) - 1 - rank)
        x1, y1, x2, y2 = card.x, card.y, card.right, card.bottom
        for sid in g.subnet_ids:
            r = subnet_rects.get(sid)
            if r:
                x1, y1 = min(x1, r.x), min(y1, r.y)
                x2, y2 = max(x2, r.right), max(y2, r.bottom)
        outline = Rect(x1 - margin, y1 - margin, x2 - x1 + margin * 2, y2 - y1 + margin * 2)

        members: list[LayoutMember] = []
        cols = max(1, int((card.w - CARD_PAD * 2) // CELL_W))
        mx0 = card.x + CARD_PAD + (CELL_W - ICON_SIZE) / 2
        my0 = card.y + CARD_HEADER_H
        for j, mid in enumerate(g.members):
            node = model.all_nodes.get(mid)
            if node is None:
                continue
            members.append(LayoutMember(
                id=mid,
                rect=Rect(mx0 + (j % cols) * CELL_W, my0 + (j // cols) * CELL_H, ICON_SIZE, ICON_SIZE),
                resource_type=node.resource_type, label=node.label,
                sublabel=node.sublabel, tooltip=node.tooltip,
            ))

        result.groups.append(LayoutGroup(
            id=g.id, rect=outline, label=g.label, category=g.category,
            sublabel=g.sublabel, members=members, card=card, icon=g.icon,
            outline=needs_outline,
        ))

    # ── Endpoint column ─────────────────────────────────────────────
    ep_x = tiers_right + PAD
    ep_y = inner_y
    ep_step = ICON_SIZE + LABEL_H + ICON_GAP + 8
    for i, ep in enumerate(vpc.endpoints[:12]):
        result.nodes.append(_layout_node(ep, Rect(ep_x, ep_y + i * ep_step, ICON_SIZE, ICON_SIZE)))

    vpc_w = (ep_x + VPC_ENDPOINT_COL_W + VPC_PAD) - vx
    vpc_h = max(az_y, ep_y + len(vpc.endpoints[:12]) * ep_step) + VPC_PAD - vy
    return Rect(vx, vy, vpc_w, vpc_h)


def _layout_edges(result: LayoutResult, model: DiagramModel) -> None:
    """Orthogonal routing between any resolvable endpoints."""
    rects: dict[str, Rect] = {}
    for c in result.containers:
        if c.kind == "vpc":
            rects[c.id] = c.rect
    for t in result.tiles:
        rects[t.id] = t.rect
    for g in result.groups:
        rects[g.id] = g.card or g.rect
        for m in g.members:
            rects[m.id] = m.rect
    for n in result.nodes + result.global_nodes:
        rects[n.id] = n.rect

    seen: set[tuple[str, str, str]] = set()
    for edge in model.edges:
        key = (edge.source, edge.target, edge.kind)
        if key in seen or edge.source == edge.target:
            continue
        src, tgt = rects.get(edge.source), rects.get(edge.target)
        if not src or not tgt:
            continue
        seen.add(key)

        if tgt.x >= src.right:
            sx, sy, tx, ty = src.right, src.cy, tgt.x, tgt.cy
            mx = (sx + tx) / 2
            points = [(sx, sy), (mx, sy), (mx, ty), (tx, ty)]
        elif tgt.right <= src.x:
            sx, sy, tx, ty = src.x, src.cy, tgt.right, tgt.cy
            mx = (sx + tx) / 2
            points = [(sx, sy), (mx, sy), (mx, ty), (tx, ty)]
        else:
            down = tgt.y >= src.cy
            sx, sy = src.cx, (src.bottom if down else src.y)
            tx, ty = tgt.cx, (tgt.y if down else tgt.bottom)
            my = (sy + ty) / 2
            points = [(sx, sy), (sx, my), (tx, my), (tx, ty)]

        result.edges.append(LayoutEdge(
            source=edge.source, target=edge.target, kind=edge.kind,
            label=edge.label, points=points,
        ))
