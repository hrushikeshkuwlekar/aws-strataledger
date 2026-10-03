"""
SVG renderer for the AWS architecture diagram.

Takes a LayoutResult and produces a self-contained SVG string.
All icons are defined as <symbol> elements and referenced with <use>.
Colours use CSS custom properties so the diagram follows the report theme.
"""

from __future__ import annotations

import html
from io import StringIO

from .icons import ICONS, CONTAINER_STYLES, EDGE_STYLES, get_icon
from .layout import (
    LayoutResult, LayoutContainer, LayoutNode, LayoutGroup,
    LayoutEdge, LayoutTile, LayoutMember,
)


_CONTAINER_ICONS = {
    "vpc": "vpc",
    "region": "generic",
    "aws_cloud": "internet",
}


def render_svg(layout: LayoutResult, theme: str = "dark") -> str:
    """
    Render a LayoutResult as an SVG string.

    Args:
        layout: The computed layout from compute_layout()
        theme: "dark" or "light"

    Returns:
        A complete SVG string ready for embedding in HTML or saving to a file.
    """
    buf = StringIO()
    w = layout.width + 40  # margin
    h = layout.height + 40

    buf.write(f'<svg xmlns="http://www.w3.org/2000/svg" '
              f'viewBox="0 0 {w} {h}" '
              f'width="{w}" height="{h}" '
              f'style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', '
              f'Roboto, Helvetica, Arial, sans-serif; font-size: 11px;">\n')

    # ── CSS custom properties for theme ─────────────────────────────
    _write_styles(buf, theme)

    # ── Icon symbol definitions ─────────────────────────────────────
    _write_symbols(buf)

    # ── Translate for margin ────────────────────────────────────────
    buf.write('<g transform="translate(20, 20)">\n')

    # ── Containers (back to front: cloud → region → vpc → az → subnet)
    for c in layout.containers:
        _draw_container(buf, c)

    # ── Groups (multi-AZ dashed boxes) ──────────────────────────────
    for g in layout.groups:
        _draw_group(buf, g)

    # ── Service tiles ───────────────────────────────────────────────
    for t in layout.tiles:
        _draw_tile(buf, t)

    # ── Edges (behind icons, above containers) ──────────────────────
    for e in layout.edges:
        _draw_edge(buf, e)

    # ── Group children, then nodes (icons with labels) ──────────────
    for g in layout.groups:
        colour = CONTAINER_STYLES.get(f"group_{g.category}", CONTAINER_STYLES["group_compute"])["stroke"]
        for m in g.members:
            _draw_member(buf, m, colour)
    for n in layout.global_nodes:
        _draw_node(buf, n)
    for n in layout.nodes:
        _draw_node(buf, n)

    buf.write('</g>\n')
    buf.write('</svg>\n')

    return buf.getvalue()


def _write_styles(buf: StringIO, theme: str) -> None:
    """Write CSS styles using custom properties for theme support."""
    dark = theme == "dark"
    buf.write('<style>\n')
    buf.write(f':root {{\n')
    buf.write(f'  --diagram-bg: {"#0a0e1a" if dark else "#ffffff"};\n')
    buf.write(f'  --diagram-text: {"#e2e8f0" if dark else "#1a202c"};\n')
    buf.write(f'  --diagram-text-muted: {"#94a3b8" if dark else "#718096"};\n')
    buf.write(f'  --diagram-text-label: {"#cbd5e1" if dark else "#4a5568"};\n')
    buf.write(f'  --diagram-container-text: {"#94a3b8" if dark else "#4a5568"};\n')
    buf.write(f'  --diagram-node-bg: {"rgba(30,41,59,0.8)" if dark else "rgba(255,255,255,0.9)"};\n')
    buf.write(f'  --diagram-tile-bg: {"rgba(30,41,59,0.6)" if dark else "rgba(247,250,252,0.9)"};\n')
    buf.write(f'  --diagram-group-bg: {"rgba(30,41,59,0.3)" if dark else "rgba(247,250,252,0.5)"};\n')
    buf.write(f'}}\n')
    buf.write('.container-label { font-size: 11px; font-weight: 600; }\n')
    buf.write('.node-label { font-size: 9px; font-weight: 500; text-anchor: middle; }\n')
    buf.write('.node-sublabel { font-size: 8px; font-weight: 400; text-anchor: middle; }\n')
    buf.write('.tile-label { font-size: 10px; font-weight: 600; }\n')
    buf.write('.tile-count { font-size: 10px; font-weight: 400; }\n')
    buf.write('.group-label { font-size: 9px; font-weight: 500; }\n')
    buf.write('.edge-label { font-size: 8px; font-weight: 400; }\n')
    buf.write('</style>\n')


def _write_symbols(buf: StringIO) -> None:
    """Write <symbol> definitions for all icons."""
    buf.write('<defs>\n')
    for icon_id, icon_data in ICONS.items():
        buf.write(f'  <symbol id="icon-{_esc_attr(icon_id)}" viewBox="0 0 24 24">\n')
        buf.write(f'    <path d="{icon_data["path"]}" fill="{icon_data["fill"]}"/>\n')
        buf.write(f'  </symbol>\n')

    # Arrow marker for edges
    for kind, style in EDGE_STYLES.items():
        buf.write(f'  <marker id="arrow-{kind}" viewBox="0 0 10 10" '
                  f'refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">\n')
        buf.write(f'    <path d="M 0 0 L 10 5 L 0 10 z" fill="{style["stroke"]}"/>\n')
        buf.write(f'  </marker>\n')

    buf.write('</defs>\n')


def _draw_container(buf: StringIO, c: LayoutContainer) -> None:
    """Draw a container rectangle with header."""
    style = CONTAINER_STYLES.get(c.kind, CONTAINER_STYLES.get("region"))
    if style is None:
        return

    r = c.rect
    stroke = style["stroke"]
    sw = style["stroke_width"]
    fill = style.get("fill", "none")
    dash = style.get("dash", "")

    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    rx = 6 if c.kind != "aws_cloud" else 8

    buf.write(f'<rect x="{r.x}" y="{r.y}" width="{r.w}" height="{r.h}" '
              f'rx="{rx}" '
              f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash_attr}/>\n')

    # Container icon + header label
    icon_key = _CONTAINER_ICONS.get(c.kind)
    icon_offset = 0
    if icon_key and c.label:
        icon_size = 18
        ix = r.x + 8
        iy = r.y + 6
        buf.write(f'<use href="#icon-{_esc_attr(icon_key)}" '
                  f'x="{ix}" y="{iy}" width="{icon_size}" height="{icon_size}"/>\n')
        icon_offset = icon_size + 4

    if c.label:
        lx = r.x + 12 + icon_offset
        ly = r.y + 18
        buf.write(f'<text x="{lx}" y="{ly}" class="container-label" '
                  f'fill="{stroke}">{_esc(c.label)}</text>\n')

    # Sublabel (CIDR for VPCs, etc.)
    if c.sublabel:
        lx = r.x + 12 + icon_offset
        ly = r.y + 30
        buf.write(f'<text x="{lx}" y="{ly}" class="node-sublabel" '
                  f'fill="var(--diagram-text-muted)" style="text-anchor:start">{_esc(c.sublabel)}</text>\n')


def _icon_ref(resource_type: str) -> str:
    return f"#icon-{_esc_attr(resource_type if resource_type in ICONS else 'generic')}"


def _fit(text: str, max_chars: int = 16) -> str:
    return text if len(text) <= max_chars else text[:max_chars - 1] + "\u2026"


def _title(text: str) -> str:
    return f'<title>{_esc(text)}</title>' if text else ""


def _draw_icon_with_labels(buf: StringIO, r, resource_type: str, label: str, sublabel: str,
                           tooltip: str, stroke: str = "none") -> None:
    full = tooltip or "\n".join(x for x in (label, sublabel) if x)
    buf.write(f'<g>{_title(full)}\n')
    buf.write(f'<rect x="{r.x - 2}" y="{r.y - 2}" width="{r.w + 4}" height="{r.h + 4}" '
              f'rx="4" fill="var(--diagram-node-bg)" stroke="{stroke}" stroke-width="0.75"/>\n')
    buf.write(f'<use href="{_icon_ref(resource_type)}" '
              f'x="{r.x}" y="{r.y}" width="{r.w}" height="{r.h}"/>\n')
    if label:
        buf.write(f'<text x="{r.cx}" y="{r.bottom + 12}" class="node-label" '
                  f'fill="var(--diagram-text-label)">{_esc(_fit(label))}</text>\n')
    if sublabel:
        buf.write(f'<text x="{r.cx}" y="{r.bottom + 22}" class="node-sublabel" '
                  f'fill="var(--diagram-text-muted)">{_esc(_fit(sublabel, 20))}</text>\n')
    buf.write('</g>\n')


def _draw_node(buf: StringIO, n: LayoutNode) -> None:
    """Draw a resource icon with label, plus attached child resources as mini icons."""
    r = n.rect
    if n.id.startswith("overflow:"):
        buf.write(f'<text x="{r.x}" y="{r.y + 11}" class="node-sublabel" style="text-anchor:start" '
                  f'fill="var(--diagram-text-muted)">{_esc(n.label)}</text>\n')
        return
    _draw_icon_with_labels(buf, r, n.resource_type, n.label, n.sublabel, n.tooltip)
    if n.attachments:
        _draw_attachments(buf, n)


def _draw_attachments(buf: StringIO, n: LayoutNode) -> None:
    """Child resources (EBS volumes, Elastic IPs…) as a row of mini icons under the parent."""
    mini = 12
    shown = n.attachments[:3]
    extra = len(n.attachments) - len(shown)
    total_w = len(shown) * (mini + 2) + (14 if extra else 0)
    x = n.rect.cx - total_w / 2
    y = n.rect.bottom + 27
    # connector from parent to its children
    buf.write(f'<line x1="{n.rect.cx}" y1="{n.rect.bottom + 24}" x2="{n.rect.cx}" y2="{y}" '
              f'stroke="var(--diagram-text-muted)" stroke-width="0.75"/>\n')
    for rtype, label in shown:
        buf.write(f'<g>{_title(label)}<use href="{_icon_ref(rtype)}" x="{x}" y="{y}" '
                  f'width="{mini}" height="{mini}"/></g>\n')
        x += mini + 2
    if extra:
        buf.write(f'<text x="{x}" y="{y + 9}" class="node-sublabel" style="text-anchor:start" '
                  f'fill="var(--diagram-text-muted)">+{extra}</text>\n')


def _draw_group(buf: StringIO, g: LayoutGroup) -> None:
    """Draw a group's dashed outline and its header card (parent icon + name)."""
    style = CONTAINER_STYLES.get(f"group_{g.category}", CONTAINER_STYLES["group_compute"])
    colour = style["stroke"]
    r = g.rect
    if g.outline:
        buf.write(f'<rect x="{r.x}" y="{r.y}" width="{r.w}" height="{r.h}" '
                  f'rx="6" fill="none" stroke="{colour}" stroke-width="{style["stroke_width"]}" '
                  f'stroke-dasharray="{style.get("dash", "5 3")}" opacity="0.8"/>\n')

    c = g.card
    if c is None:
        if g.label:
            buf.write(f'<text x="{r.x + 6}" y="{r.y - 4}" class="group-label" fill="{colour}">'
                      f'{_esc(g.label)}{" · " + _esc(g.sublabel) if g.sublabel else ""}</text>\n')
        return

    buf.write(f'<g>{_title(f"{g.label} {g.sublabel}".strip())}\n')
    buf.write(f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="5" '
              f'fill="var(--diagram-group-bg)" stroke="{colour}" stroke-width="1"/>\n')
    buf.write(f'<rect x="{c.x}" y="{c.y}" width="4" height="{c.h}" rx="2" fill="{colour}"/>\n')
    icon_size = 20
    if g.icon:
        buf.write(f'<use href="{_icon_ref(g.icon)}" x="{c.x + 10}" y="{c.y + 7}" '
                  f'width="{icon_size}" height="{icon_size}"/>\n')
    tx = c.x + 10 + (icon_size + 6 if g.icon else 0)
    max_chars = max(8, int((c.right - tx - 6) / 5.5))
    buf.write(f'<text x="{tx}" y="{c.y + 16}" class="container-label" fill="{colour}">'
              f'{_esc(_fit(g.label, max_chars))}</text>\n')
    if g.sublabel:
        buf.write(f'<text x="{tx}" y="{c.y + 28}" class="node-sublabel" style="text-anchor:start" '
                  f'fill="var(--diagram-text-muted)">{_esc(_fit(g.sublabel, max_chars + 4))}</text>\n')
    if g.members:
        buf.write(f'<line x1="{c.x + 8}" y1="{c.y + 33}" x2="{c.right - 8}" y2="{c.y + 33}" '
                  f'stroke="{colour}" stroke-width="0.5" opacity="0.5"/>\n')
    buf.write('</g>\n')


def _draw_member(buf: StringIO, m: LayoutMember, group_colour: str) -> None:
    """Draw a child resource inside its parent's group card."""
    if m.id.startswith("overflow:"):
        r = m.rect
        buf.write(f'<text x="{r.cx}" y="{r.cy + 4}" class="node-label" '
                  f'fill="var(--diagram-text-muted)">{_esc(m.label)}</text>\n')
        return
    _draw_icon_with_labels(buf, m.rect, m.resource_type, m.label, m.sublabel, m.tooltip,
                           stroke=group_colour)


def _draw_tile(buf: StringIO, t: LayoutTile) -> None:
    """Draw a service tile (icon + name + count)."""
    r = t.rect
    icon = get_icon(t.icon)

    # Background
    buf.write(f'<rect x="{r.x}" y="{r.y}" width="{r.w}" height="{r.h}" '
              f'rx="6" fill="var(--diagram-tile-bg)" '
              f'stroke="{icon["fill"]}" stroke-width="1" opacity="0.7"/>\n')

    # Icon
    icon_size = 24
    if t.names:
        buf.write(_title(f"{t.service}: " + ", ".join(n for n in t.names if n)))
    buf.write(f'<use href="{_icon_ref(t.icon)}" '
              f'x="{r.x + 8}" y="{r.y + (r.h - icon_size) / 2}" '
              f'width="{icon_size}" height="{icon_size}"/>\n')

    # Service name
    buf.write(f'<text x="{r.x + 40}" y="{r.y + 20}" class="tile-label" '
              f'fill="var(--diagram-text)">{_esc(t.service)}</text>\n')

    # Count
    buf.write(f'<text x="{r.x + 40}" y="{r.y + 34}" class="tile-count" '
              f'fill="var(--diagram-text-muted)">×{t.count}</text>\n')


def _draw_edge(buf: StringIO, e: LayoutEdge) -> None:
    """Draw an edge as an orthogonal polyline with an arrowhead."""
    if not e.points or len(e.points) < 2:
        return

    style = EDGE_STYLES.get(e.kind, EDGE_STYLES["traffic"])
    points_str = " ".join(f"{x},{y}" for x, y in e.points)
    dash_attr = f' stroke-dasharray="{style["dash"]}"' if style.get("dash") else ""

    buf.write(f'<polyline points="{points_str}" '
              f'fill="none" stroke="{style["stroke"]}" '
              f'stroke-width="{style["stroke_width"]}"{dash_attr} '
              f'marker-end="url(#arrow-{e.kind})" opacity="0.7"/>\n')

    # Edge label at midpoint
    if e.label and len(e.points) >= 2:
        (x1, y1), (x2, y2) = e.points[-2], e.points[-1]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        buf.write(f'<text x="{mx}" y="{my - 4}" class="edge-label" '
                  f'fill="{style["stroke"]}" text-anchor="middle">{_esc(e.label)}</text>\n')


def _esc(text: str) -> str:
    """Escape text for SVG/XML content."""
    return html.escape(str(text), quote=False)


def _esc_attr(text: str) -> str:
    """Escape text for SVG/XML attribute values."""
    return html.escape(str(text), quote=True)
