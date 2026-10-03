"""
Diagram layout engine (AWS reference-architecture conventions).

    [Users]        ┌ AWS Cloud ───────────────────────────────────────────────┐
    [Corporate     │ [Route 53]   ┌ Region ───────────────────────────────────┐ │
     data center]  │ [CloudFront] │ [API GW]  ┌ VPC ───────────────┐ ┌ Regional│ │
                   │ [IAM]        │ [TGW]    [IGW]  AZ a     AZ b   │ │ services│ │
                   │              │ [VPN]     │ Public  ▭▭▭    ▭▭▭  │ │ by      │ │
                   │              │           │ Private ▭▭▭    ▭▭▭  │ │ category│ │
                   │              │           │ Data    ▭▭▭    ▭▭▭  │ │         │ │

Inside a VPC, Availability Zones are columns and subnet tiers are rows.
Multi-AZ constructs (ALB, EKS, Aurora, MSK …) are group boxes placed in a
lane above the subnets of their tier, spanning exactly the AZ columns they
occupy, with their child resources inside.

All geometry is deterministic; units are SVG user units (≈ px).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import ceil

from .model import DiagramModel, DiagramNode, RegionModel, SubnetModel, VPCModel

# ── Layout constants ────────────────────────────────────────────────

MARGIN = 24
GAP = 44                 # between major columns (external | cloud | global | regions | panel)

ICON = 40                # resource icon size
CELL_W = 104             # icon cell: icon + 2 label lines
CELL_H = ICON + 34
ATTACH_H = 18            # extra row for attached mini icons (EBS, EIP)

SUBNET_HDR = 34
SUBNET_PAD = 10
SUBNET_GAP = 10
SUBNET_COLS = 3
MAX_ICONS_PER_SUBNET = 6
COMPACT_SUBNET_H = 34
EMPTY_SUBNET_MERGE = 2   # more empty subnets than this in one cell are merged into one box

COL_MIN_W = 250
AZ_PAD = 12
AZ_HDR = 30
COL_GAP = 16
ROW_GAP = 18
ROWHDR_W = 26

GROUP_HDR = 48
GROUP_SLIM_H = 36        # groups without children are a one-line bar
GROUP_PAD = 10
LANE_GAP = 12

VPC_HDR = 42
VPC_PAD = 18
VPC_GAP = 28

REGION_HDR = 44
REGION_PAD = 22
GUTTER_W = 132
GUTTER_STEP = 92
GUTTER_TO_VPC = 100      # room for the IGW/VGW straddling the VPC border and their labels

TILE_W = 164
TILE_H = 50
TILE_GAP = 8
PANEL_PAD = 12
PANEL_HDR = 34
CAT_H = 22
PANEL_W = 2 * TILE_W + TILE_GAP + 2 * PANEL_PAD

GLOBAL_W = 140
GLOBAL_STEP = 96
EXT_W = 160
CLOUD_HDR = 44
CLOUD_PAD = 24

TIER_ORDER = ["firewall", "public", "app", "data"]
TIER_TITLES = {
    "firewall": "Firewall subnets", "public": "Public subnets",
    "app": "Private subnets", "data": "Data subnets",
}
SUBNET_KIND = {
    "firewall": "subnet_firewall", "public": "subnet_public",
    "app": "subnet_private", "data": "subnet_data",
}
MAX_ENDPOINTS = 12


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

    def union(self, other: "Rect") -> "Rect":
        x1, y1 = min(self.x, other.x), min(self.y, other.y)
        return Rect(x1, y1, max(self.right, other.right) - x1, max(self.bottom, other.bottom) - y1)


@dataclass
class LayoutNode:
    id: str
    rect: Rect               # the icon box
    resource_type: str
    label: str
    sublabel: str = ""
    attachments: list[tuple[str, str]] = field(default_factory=list)
    tooltip: str = ""


LayoutMember = LayoutNode


@dataclass
class LayoutGroup:
    id: str
    rect: Rect               # the group box (header + members)
    label: str
    category: str
    sublabel: str = ""
    members: list[LayoutNode] = field(default_factory=list)
    icon: str = ""
    dashed: bool = False
    outline: Rect | None = None  # dashed span when the group also covers other tiers
    tooltip: str = ""


@dataclass
class LayoutEdge:
    source: str
    target: str
    kind: str
    label: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class LayoutContainer:
    id: str
    kind: str
    rect: Rect
    label: str = ""
    sublabel: str = ""
    tooltip: str = ""


@dataclass
class LayoutTile:
    service: str
    icon: str
    count: int
    rect: Rect
    names: list[str] = field(default_factory=list)
    id: str = ""
    category: str = ""


@dataclass
class LayoutLabel:
    x: float
    y: float
    text: str
    kind: str = "note"       # note, row, category
    tooltip: str = ""


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
    external_nodes: list[LayoutNode] = field(default_factory=list)
    labels: list[LayoutLabel] = field(default_factory=list)


def _lnode(node: DiagramNode, x: float, y: float) -> LayoutNode:
    return LayoutNode(
        id=node.id, rect=Rect(x, y, ICON, ICON), resource_type=node.resource_type,
        label=node.label, sublabel=node.sublabel, attachments=list(node.attachments),
        tooltip=node.tooltip,
    )


# ── Top level ───────────────────────────────────────────────────────

def compute_layout(model: DiagramModel) -> LayoutResult:
    res = LayoutResult()
    has_external = bool(model.external_nodes or model.onprem_nodes)
    cloud_x = MARGIN + EXT_W + GAP if has_external else MARGIN
    cloud_y = MARGIN
    inner_top = cloud_y + CLOUD_HDR + CLOUD_PAD

    gx = cloud_x + CLOUD_PAD
    y = inner_top
    for n in model.global_nodes:
        res.global_nodes.append(_lnode(n, gx + (GLOBAL_W - ICON) / 2, y))
        y += GLOBAL_STEP
    global_bottom = y

    regions_x = gx + GLOBAL_W + GAP if model.global_nodes else gx
    ry = inner_top
    right = regions_x + 360
    for region in model.regions.values():
        rr = _layout_region(res, model, region, regions_x, ry)
        right = max(right, rr.right)
        ry = rr.bottom + GAP
    content_bottom = max(ry - GAP, global_bottom, inner_top + 120)

    cloud = Rect(cloud_x, cloud_y, right + CLOUD_PAD - cloud_x, content_bottom + CLOUD_PAD - cloud_y)
    res.containers.insert(0, LayoutContainer(
        id="aws_cloud", kind="aws_cloud", rect=cloud,
        label=f"AWS Cloud  ·  {model.account_alias} ({model.account_id})",
    ))

    # External actors (outside the AWS Cloud)
    ext_bottom = inner_top
    for n in model.external_nodes:
        res.external_nodes.append(_lnode(n, MARGIN + (EXT_W - ICON) / 2, ext_bottom))
        ext_bottom += GLOBAL_STEP
    if model.onprem_nodes:
        box_y = ext_bottom + 20
        ny = box_y + 50
        for n in model.onprem_nodes:
            res.external_nodes.append(_lnode(n, MARGIN + (EXT_W - ICON) / 2, ny))
            ny += GLOBAL_STEP
        res.containers.insert(1, LayoutContainer(
            id="onprem", kind="onprem", rect=Rect(MARGIN, box_y, EXT_W, ny - box_y - 20),
            label="Corporate data center",
        ))
        ext_bottom = ny

    res.width = cloud.right + MARGIN
    res.height = max(cloud.bottom, ext_bottom) + MARGIN
    _layout_edges(res, model)
    return res


# ── Region ──────────────────────────────────────────────────────────

def _layout_region(res: LayoutResult, model: DiagramModel, region: RegionModel, rx: float, ry: float) -> Rect:
    idx = len(res.containers)
    x0 = rx + REGION_PAD
    y0 = ry + REGION_HDR

    gutter_bottom = y0
    for i, n in enumerate(region.gutter_nodes):
        res.nodes.append(_lnode(n, x0 + (GUTTER_W - ICON) / 2, y0 + i * GUTTER_STEP))
        gutter_bottom = y0 + (i + 1) * GUTTER_STEP
    vpc_x = x0 + GUTTER_W + GUTTER_TO_VPC if region.gutter_nodes else x0 + ICON

    vy = y0
    right = vpc_x
    for vpc in region.vpcs.values():
        vr = _layout_vpc(res, model, vpc, vpc_x, vy)
        right = max(right, vr.right)
        vy = vr.bottom + VPC_GAP
    if region.empty_vpcs:
        shown = region.empty_vpcs[:4]
        more = len(region.empty_vpcs) - len(shown)
        res.labels.append(LayoutLabel(
            vpc_x, vy + 12,
            f"VPCs with no resources: {', '.join(shown)}" + (f" +{more} more" if more else ""),
            tooltip="\n".join(region.empty_vpcs),
        ))
        vy += 30
    vpcs_bottom = vy - (VPC_GAP if region.vpcs and not region.empty_vpcs else 0)

    panel_x = right + GAP if region.vpcs else vpc_x
    panel_bottom = _layout_panel(res, region, panel_x, y0)
    if region.tiles:
        right = panel_x + PANEL_W

    rect = Rect(rx, ry, right + REGION_PAD - rx, max(vpcs_bottom, panel_bottom, gutter_bottom) + REGION_PAD - ry)
    res.containers.insert(idx, LayoutContainer(id=f"region:{region.name}", kind="region", rect=rect,
                                               label=f"Region  ·  {region.name}"))
    return rect


def _layout_panel(res: LayoutResult, region: RegionModel, px: float, py: float) -> float:
    if not region.tiles:
        return py
    idx = len(res.containers)
    y = py + PANEL_HDR
    by_cat: dict[str, list] = defaultdict(list)
    for t in region.tiles:
        by_cat[t.category].append(t)
    for category, tiles in by_cat.items():
        res.labels.append(LayoutLabel(px + PANEL_PAD, y + 14, category.upper(), "category"))
        y += CAT_H
        for i, t in enumerate(tiles):
            res.tiles.append(LayoutTile(
                service=t.service, icon=t.icon, count=t.count, names=list(t.names),
                rect=Rect(px + PANEL_PAD + (i % 2) * (TILE_W + TILE_GAP),
                          y + (i // 2) * (TILE_H + TILE_GAP), TILE_W, TILE_H),
                id=f"tile:{region.name}:{t.service}", category=category,
            ))
        y += ceil(len(tiles) / 2) * (TILE_H + TILE_GAP) + 6
    rect = Rect(px, py, PANEL_W, y - py + PANEL_PAD - 6)
    res.containers.insert(idx, LayoutContainer(id=f"services:{region.name}", kind="services", rect=rect,
                                               label="Regional services"))
    return rect.bottom


# ── VPC ─────────────────────────────────────────────────────────────

@dataclass
class _Entry:
    """One box in an (tier, AZ) cell: a subnet, or several empty subnets merged."""
    subnets: list[SubnetModel]
    w: float
    h: float
    cols: int = 1
    cell_h: float = CELL_H


def _subnet_entry(sm: SubnetModel, model: DiagramModel) -> _Entry:
    shown = sm.nodes[:MAX_ICONS_PER_SUBNET]
    if not shown:
        return _Entry([sm], COL_MIN_W, COMPACT_SUBNET_H)
    cols = min(len(shown), SUBNET_COLS)
    rows = ceil(len(shown) / cols)
    has_attach = any(model.all_nodes.get(n) and model.all_nodes[n].attachments for n in shown)
    cell_h = CELL_H + (ATTACH_H if has_attach else 0)
    overflow_h = 18 if len(sm.nodes) > MAX_ICONS_PER_SUBNET else 0
    return _Entry([sm], cols * CELL_W + 2 * SUBNET_PAD,
                  SUBNET_HDR + rows * cell_h + overflow_h + SUBNET_PAD / 2, cols, cell_h)


def _group_height(n_members: int, width: float) -> float:
    if not n_members:
        return GROUP_SLIM_H
    cols = max(1, int((width - 2 * GROUP_PAD) // CELL_W))
    return GROUP_HDR + ceil(n_members / cols) * CELL_H + GROUP_PAD / 2


def _layout_vpc(res: LayoutResult, model: DiagramModel, vpc: VPCModel, vx: float, vy: float) -> Rect:
    vpc_idx = len(res.containers)
    azs = sorted(vpc.azs)
    az_index = {az: i for i, az in enumerate(azs)}
    tiers = [t for t in TIER_ORDER
             if any(sm.tier == t for az in vpc.azs.values() for sm in az.subnets.values())] or ["app"]

    # ── Cells ───────────────────────────────────────────────────────
    cells: dict[tuple[str, str], list[_Entry]] = {}
    for az in azs:
        by_tier: dict[str, list[SubnetModel]] = defaultdict(list)
        for sm in vpc.azs[az].subnets.values():
            by_tier[sm.tier].append(sm)
        for tier, sms in by_tier.items():
            busy = sorted((s for s in sms if s.nodes), key=lambda s: s.name)
            empty = sorted((s for s in sms if not s.nodes), key=lambda s: s.name)
            entries = [_subnet_entry(s, model) for s in busy]
            if len(empty) > EMPTY_SUBNET_MERGE:
                entries.append(_Entry(empty, COL_MIN_W, COMPACT_SUBNET_H))
            else:
                entries += [_subnet_entry(s, model) for s in empty]
            cells[(tier, az)] = entries

    col_w = {az: max([COL_MIN_W] + [e.w for t in tiers for e in cells.get((t, az), [])]) for az in azs}

    # ── Groups: home tier and AZ-column span ────────────────────────
    spans = {}
    for g in vpc.groups:
        sms = [s for s in (vpc.subnet(sid) for sid in g.subnet_ids) if s]
        if not sms:
            continue
        counts = Counter(s.tier for s in sms)
        home = max(tiers, key=lambda t: (counts.get(t, 0), -tiers.index(t)))
        cols = [az_index[s.az] for s in sms if s.tier == home and s.az in az_index]
        if not cols:
            continue
        spans[g.id] = (home, min(cols), max(cols), len(counts) > 1)

    # Widen a column when a single-column group needs more room than the subnets do.
    for g in vpc.groups:
        if g.id in spans and spans[g.id][1] == spans[g.id][2]:
            az = azs[spans[g.id][1]]
            need = 2 * GROUP_PAD + min(len(g.members), 2) * CELL_W
            col_w[az] = max(col_w[az], need)

    colx: dict[str, float] = {}
    x = vx + VPC_PAD + ROWHDR_W
    for az in azs:
        colx[az] = x + AZ_PAD
        x += col_w[az] + 2 * AZ_PAD + COL_GAP
    cols_right = x - COL_GAP

    def span_rect_x(c1: int, c2: int) -> tuple[float, float]:
        return colx[azs[c1]], colx[azs[c2]] + col_w[azs[c2]] - colx[azs[c1]]

    # ── Rows ────────────────────────────────────────────────────────
    az_top = vy + VPC_HDR
    y = az_top + AZ_HDR
    az_idx = len(res.containers)
    subnet_rects: dict[str, Rect] = {}
    group_rects: dict[str, Rect] = {}
    row_mid: dict[str, float] = {}

    for tier in tiers:
        row_top = y
        tier_groups = sorted((g for g in vpc.groups if spans.get(g.id, ("",))[0] == tier),
                             key=lambda g: (spans[g.id][1], -(spans[g.id][2] - spans[g.id][1])))
        lanes: list[list] = []
        for g in tier_groups:
            _, c1, c2, _ = spans[g.id]
            for lane in lanes:
                if all(c2 < a or c1 > b for _, a, b in lane):
                    lane.append((g, c1, c2))
                    break
            else:
                lanes.append([(g, c1, c2)])
        for lane in lanes:
            lane_h = 0.0
            for g, c1, c2 in lane:
                gx, gw = span_rect_x(c1, c2)
                gh = _group_height(len(g.members), gw)
                group_rects[g.id] = Rect(gx, y, gw, gh)
                lane_h = max(lane_h, gh)
            y += lane_h + LANE_GAP

        row_h = 0.0
        for az in azs:
            sy = y
            for e in cells.get((tier, az), []):
                rect = Rect(colx[az], sy, col_w[az], e.h)
                _place_entry(res, model, e, rect, vpc.id, tier, az)
                for s in e.subnets:
                    subnet_rects[s.id] = rect
                sy += e.h + SUBNET_GAP
            row_h = max(row_h, sy - SUBNET_GAP - y)
        y += row_h + ROW_GAP
        row_mid[tier] = (row_top + y - ROW_GAP) / 2
        res.labels.append(LayoutLabel(vx + VPC_PAD + ROWHDR_W / 2, row_mid[tier], TIER_TITLES[tier], "row"))
    rows_bottom = y - ROW_GAP

    # AZ boxes go behind subnets: insert at the index reserved before the rows were laid out.
    for i, az in enumerate(azs):
        res.containers.insert(az_idx + i, LayoutContainer(
            id=f"az:{vpc.id}:{az}", kind="az",
            rect=Rect(colx[az] - AZ_PAD, az_top, col_w[az] + 2 * AZ_PAD, rows_bottom + AZ_PAD - az_top),
            label=f"Availability Zone  {az}",
        ))

    # ── Groups ──────────────────────────────────────────────────────
    for g in vpc.groups:
        if g.id not in group_rects:
            continue
        gr = group_rects[g.id]
        members = []
        mcols = max(1, int((gr.w - 2 * GROUP_PAD) // CELL_W))
        used = min(len(g.members), mcols)
        mx0 = gr.x + (gr.w - used * CELL_W) / 2 + (CELL_W - ICON) / 2
        for j, mid in enumerate(g.members):
            node = model.all_nodes.get(mid)
            if node:
                members.append(_lnode(node, mx0 + (j % mcols) * CELL_W, gr.y + GROUP_HDR + (j // mcols) * CELL_H))
        outline = None
        if spans[g.id][3]:
            outline = gr
            for sid in g.subnet_ids:
                if sid in subnet_rects:
                    outline = outline.union(subnet_rects[sid])
            outline = Rect(outline.x - 5, outline.y - 5, outline.w + 10, outline.h + 10)
        res.groups.append(LayoutGroup(
            id=g.id, rect=gr, label=g.label, category=g.category, sublabel=g.sublabel,
            members=members, icon=g.icon, dashed=g.dashed, outline=outline, tooltip=g.tooltip,
        ))

    # ── Gateways straddling the VPC's left border ───────────────────
    gw_x = vx - ICON / 2
    igw_y = row_mid.get("public", row_mid[tiers[0]]) - ICON / 2
    if vpc.igw_id:
        res.nodes.append(LayoutNode(id=f"igw:{vpc.igw_id}", rect=Rect(gw_x, igw_y, ICON, ICON),
                                    resource_type="igw", label="Internet gateway", tooltip=vpc.igw_id))
    if vpc.vgw_id:
        vgw_y = row_mid.get("app", row_mid[tiers[-1]]) - ICON / 2
        if vpc.igw_id and abs(vgw_y - igw_y) < ICON + 40:
            vgw_y = igw_y + ICON + 44
        res.nodes.append(LayoutNode(id=f"vgw:{vpc.vgw_id}", rect=Rect(gw_x, vgw_y, ICON, ICON),
                                    resource_type="vpn_gateway", label="Virtual private gateway",
                                    tooltip=vpc.vgw_id))

    # ── VPC endpoints strip ─────────────────────────────────────────
    bottom = rows_bottom + AZ_PAD
    if vpc.endpoints:
        ex0 = vx + VPC_PAD + ROWHDR_W
        res.labels.append(LayoutLabel(ex0, bottom + 22, "VPC ENDPOINTS", "category"))
        per_row = max(1, int((cols_right - ex0) // CELL_W))
        eps = vpc.endpoints[:MAX_ENDPOINTS]
        ey0 = bottom + 34
        for i, ep in enumerate(eps):
            res.nodes.append(_lnode(ep, ex0 + (i % per_row) * CELL_W + (CELL_W - ICON) / 2,
                                    ey0 + (i // per_row) * CELL_H))
        bottom = ey0 + ceil(len(eps) / per_row) * CELL_H
        if len(vpc.endpoints) > MAX_ENDPOINTS:
            res.labels.append(LayoutLabel(ex0, bottom + 4, f"+{len(vpc.endpoints) - MAX_ENDPOINTS} more endpoints",
                                          tooltip="\n".join(e.tooltip for e in vpc.endpoints[MAX_ENDPOINTS:])))
            bottom += 16

    rect = Rect(vx, vy, cols_right + VPC_PAD - vx, bottom + VPC_PAD - vy)
    res.containers.insert(vpc_idx, LayoutContainer(
        id=f"vpc:{vpc.id}", kind="vpc", rect=rect,
        label=f"VPC  ·  {vpc.name}", sublabel=vpc.cidr, tooltip=vpc.id,
    ))
    return rect


def _place_entry(res: LayoutResult, model: DiagramModel, e: _Entry, rect: Rect,
                 vpc_id: str, tier: str, az: str) -> None:
    kind = SUBNET_KIND[tier]
    if len(e.subnets) > 1:
        res.containers.append(LayoutContainer(
            id=f"subnets:{vpc_id}:{tier}:{az}", kind=kind, rect=rect,
            label=f"{len(e.subnets)} more subnets", sublabel="no resources",
            tooltip="\n".join(f"{s.name} {s.cidr}" for s in e.subnets),
        ))
        return
    sm = e.subnets[0]
    res.containers.append(LayoutContainer(
        id=f"subnet:{sm.id}", kind=kind, rect=rect, label=sm.name, sublabel=sm.cidr, tooltip=sm.id,
    ))
    shown = sm.nodes[:MAX_ICONS_PER_SUBNET]
    x0 = rect.x + (rect.w - e.cols * CELL_W) / 2 + (CELL_W - ICON) / 2
    for j, nid in enumerate(shown):
        node = model.all_nodes.get(nid)
        if node:
            res.nodes.append(_lnode(node, x0 + (j % e.cols) * CELL_W, rect.y + SUBNET_HDR + (j // e.cols) * e.cell_h))
    overflow = len(sm.nodes) - len(shown)
    if overflow > 0:
        hidden = [model.all_nodes[n].label for n in sm.nodes[len(shown):] if n in model.all_nodes]
        res.nodes.append(LayoutNode(
            id=f"overflow:{sm.id}", rect=Rect(rect.x + SUBNET_PAD, rect.bottom - 20, rect.w - 2 * SUBNET_PAD, 14),
            resource_type="generic", label=f"+{overflow} more", tooltip="\n".join(hidden),
        ))


# ── Edges ───────────────────────────────────────────────────────────

def _layout_edges(res: LayoutResult, model: DiagramModel) -> None:
    rects: dict[str, Rect] = {}
    vpcs = {c.id: c.rect for c in res.containers if c.kind == "vpc"}
    rects.update(vpcs)
    for t in res.tiles:
        rects[t.id] = t.rect
    for g in res.groups:
        rects[g.id] = g.rect
        for m in g.members:
            rects[m.id] = m.rect
    for n in res.nodes + res.global_nodes + res.external_nodes:
        rects[n.id] = n.rect
    icons = {n.id for n in res.nodes + res.global_nodes + res.external_nodes} | {
        m.id for g in res.groups for m in g.members}

    base = [g.rect for g in res.groups] + [t.rect for t in res.tiles] + [
        c.rect for c in res.containers if c.kind.startswith("subnet_")
    ] + [n.rect for n in res.nodes + res.global_nodes + res.external_nodes]

    seen: set[tuple[str, str]] = set()
    for edge in model.edges:
        key = (edge.source, edge.target)
        if key in seen or edge.source == edge.target:
            continue
        src, tgt = rects.get(edge.source), rects.get(edge.target)
        if not src or not tgt:
            continue
        seen.add(key)
        # Only boxes near the line matter; a line should not run through a VPC it has nothing to do with.
        area = src.union(tgt)
        near = [r for r in base if r.right > area.x - ROUTE_MARGIN and r.x < area.right + ROUTE_MARGIN
                and r.bottom > area.y - ROUTE_MARGIN and r.y < area.bottom + ROUTE_MARGIN]
        foreign = [v for vid, v in vpcs.items() if vid not in key and not _encloses(v, [src, tgt])]
        obstacles = [(r, CROSSING_COST) for r in near] + [(v, VPC_CROSSING_COST) for v in foreign]
        targets = [tgt]
        if edge.target in vpcs:
            # Enter the VPC border at the best of a few heights.
            ys = [min(max(src.cy, tgt.y + 30), tgt.bottom - 30), tgt.y + 60, tgt.cy, tgt.bottom - 60]
            targets = [Rect(tgt.x, y - 1, tgt.w, 2) for y in ys]
        pads = (LABEL_PAD if edge.source in icons else 0, LABEL_PAD if edge.target in icons else 0)
        best = min((_route(src, t, obstacles, pads) for t in targets), key=lambda r: r[0])
        res.edges.append(LayoutEdge(edge.source, edge.target, edge.kind, edge.label, best[1]))


ROUTE_MARGIN = 400        # boxes farther than this from a line's bounding box are ignored
LABEL_PAD = 28            # labels under an icon: vertical lines leave/enter below them
CROSSING_COST = 300       # px of extra length worth paying to avoid crossing one box
VPC_CROSSING_COST = 3000  # …and to avoid cutting through an unrelated VPC


def _encloses(r: Rect, inner: list[Rect]) -> bool:
    return any(r is i or (r.x <= i.cx <= r.right and r.y <= i.cy <= r.bottom) for i in inner)


def _crossing_cost(points: list[tuple[float, float]], obstacles: list[tuple[Rect, float]]) -> float:
    cost = 0.0
    for r, weight in obstacles:
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if (y1 == y2 and r.y + 1 < y1 < r.bottom - 1 and min(x1, x2) < r.right - 1 and max(x1, x2) > r.x + 1) or \
               (x1 == x2 and r.x + 1 < x1 < r.right - 1 and min(y1, y2) < r.bottom - 1 and max(y1, y2) > r.y + 1):
                cost += weight
                break
    return cost


def _length(points: list[tuple[float, float]]) -> float:
    return sum(abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in zip(points, points[1:]))


def _route(src: Rect, tgt: Rect, weighted: list[tuple[Rect, float]] | None = None,
           pads: tuple[float, float] = (0, 0)) -> tuple[float, list[tuple[float, float]]]:
    """
    Orthogonal route between two boxes. Candidates (straight, elbows, detours
    around blocking boxes) are scored by length plus the weight of every box
    crossed. Returns (score, points).
    """
    weighted = [(r, w) for r, w in (weighted or []) if not _encloses(r, [src, tgt])]
    obstacles = [r for r, _ in weighted]
    candidates: list[list[tuple[float, float]]] = []
    if tgt.x >= src.right + 8 or tgt.right <= src.x - 8:
        rightward = tgt.x >= src.right + 8
        sx, tx = (src.right, tgt.x) if rightward else (src.x, tgt.right)
        lo_y, hi_y = max(src.y, tgt.y) + 6, min(src.bottom, tgt.bottom) - 6
        if lo_y <= hi_y:
            y = min(max(src.cy, lo_y), hi_y)
            candidates.append([(sx, y), (tx, y)])
        sy, ty = src.cy, tgt.cy
        step = 14 if rightward else -14
        for mx in ((sx + tx) / 2, sx + step, tx - step):
            candidates.append([(sx, sy), (mx, sy), (mx, ty), (tx, ty)] if abs(sy - ty) > 1 else [(sx, sy), (tx, ty)])
        lo, hi = min(sx, tx), max(sx, tx)
        band = [r for r in obstacles if r.right > lo and r.x < hi and r.bottom > min(sy, ty) and r.y < max(sy, ty)]
        if band:
            for cy in (min(r.y for r in band) - 12, max(r.bottom for r in band) + 12):
                candidates.append([(sx, sy), (sx + step, sy), (sx + step, cy), (tx - step, cy), (tx - step, ty), (tx, ty)])
    else:
        down = tgt.cy >= src.cy
        sy, ty = (src.bottom + pads[0], tgt.y) if down else (src.y, tgt.bottom + pads[1])
        lo_x, hi_x = max(src.x, tgt.x) + 8, min(src.right, tgt.right) - 8
        if lo_x <= hi_x:
            x = min(max(src.cx, lo_x), hi_x)
            candidates.append([(x, sy), (x, ty)])
        sx, tx = src.cx, tgt.cx
        step = 12 if down else -12
        for my in ((sy + ty) / 2, sy + step, ty - step):
            candidates.append([(sx, sy), (tx, ty)] if abs(sx - tx) < 1 else [(sx, sy), (sx, my), (tx, my), (tx, ty)])
        lo, hi = min(sy, ty), max(sy, ty)
        band = [r for r in obstacles if r.bottom > lo and r.y < hi and r.right > min(sx, tx) - 1 and r.x < max(sx, tx) + 1]
        if band:
            for cx in (min(r.x for r in band) - 12, max(r.right for r in band) + 12):
                candidates.append([(sx, sy), (sx, sy + step), (cx, sy + step), (cx, ty - step), (tx, ty - step), (tx, ty)])
    scored = [(_crossing_cost(p, weighted) + _length(p), p) for p in candidates]
    return min(scored, key=lambda sp: sp[0])
