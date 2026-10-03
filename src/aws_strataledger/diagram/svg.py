"""
SVG renderer for the AWS architecture diagram.

Draws a LayoutResult on a white canvas in the style of AWS reference
architectures. Icons are <symbol>s (official AWS Architecture Icons) used via
<use href="#awsi-…">. CSS classes are prefixed ``sl-`` because inline SVG
styles apply to the whole host document.

``render_svg(layout, embed_defs=False)`` omits icon symbols and arrow markers
so a report with several accounts can share one copy (see ``shared_defs_svg``);
definitions inside a hidden (display:none) panel would not render.
"""

from __future__ import annotations

import html
from io import StringIO

from .icons import CATEGORY_COLOURS, CONTAINER_STYLES, EDGE_STYLES, INK, INK_SOFT, icon_key, symbol
from .layout import LayoutContainer, LayoutEdge, LayoutGroup, LayoutLabel, LayoutNode, LayoutResult, LayoutTile

# Longest label that fits an icon cell with a gap to its neighbour; full text is in the tooltip.
CELL_LABEL_CHARS = 15

FONT = "'Amazon Ember', 'Helvetica Neue', Roboto, Arial, sans-serif"

STYLE = f"""
.sl-root text {{ font-family: {FONT}; fill: {INK}; }}
.sl-title {{ font-size: 14px; font-weight: 700; }}
.sl-head {{ font-size: 12.5px; font-weight: 700; }}
.sl-sub {{ font-size: 10.5px; fill: {INK_SOFT} !important; }}
.sl-cidr {{ font-size: 10.5px; fill: {INK_SOFT} !important; text-anchor: end; }}
.sl-label {{ font-size: 11px; font-weight: 600; text-anchor: middle; }}
.sl-small {{ font-size: 10px; fill: {INK_SOFT} !important; text-anchor: middle; }}
.sl-row {{ font-size: 10.5px; font-weight: 700; letter-spacing: .6px; fill: {INK_SOFT} !important;
           text-anchor: middle; text-transform: uppercase; }}
.sl-cat {{ font-size: 9.5px; font-weight: 700; letter-spacing: .8px; fill: {INK_SOFT} !important; }}
.sl-note {{ font-size: 11px; font-style: italic; fill: {INK_SOFT} !important; }}
.sl-edge-label {{ font-size: 9.5px; text-anchor: middle; }}
.sl-item.sl-dim {{ opacity: .15; }}
.sl-item.sl-hit use {{ filter: drop-shadow(0 0 4px #FF9900); }}
"""


def used_icon_keys(layout: LayoutResult) -> set[str]:
    keys = {"generic"}
    for c in layout.containers:
        icon = CONTAINER_STYLES.get(c.kind, {}).get("icon")
        if icon:
            keys.add(icon)
    for n in layout.nodes + layout.global_nodes + layout.external_nodes:
        keys.add(n.resource_type)
        keys.update(a[0] for a in n.attachments)
    for g in layout.groups:
        if g.icon:
            keys.add(g.icon)
        for m in g.members:
            keys.add(m.resource_type)
    keys.update(t.icon for t in layout.tiles)
    return {icon_key(k) for k in keys}


def defs(keys: set[str]) -> str:
    """Icon symbols for ``keys`` plus the edge arrow markers."""
    markers = "".join(
        f'<marker id="sl-arrow-{kind}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{s["stroke"]}"/></marker>'
        for kind, s in EDGE_STYLES.items()
    )
    return "<defs>" + markers + "".join(symbol(k) for k in sorted(keys)) + "</defs>"


def shared_defs_svg(keys: set[str]) -> str:
    """A zero-size (not display:none) SVG holding definitions shared by every diagram in a page."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" id="sl-defs" width="0" height="0" aria-hidden="true" '
            f'style="position:absolute;width:0;height:0;overflow:hidden">{defs(keys)}</svg>')


def render_svg(layout: LayoutResult, embed_defs: bool = True) -> str:
    buf = StringIO()
    w, h = round(layout.width), round(layout.height)
    buf.write(f'<svg xmlns="http://www.w3.org/2000/svg" class="sl-root" viewBox="0 0 {w} {h}" '
              f'width="{w}" height="{h}" role="img" aria-label="AWS architecture diagram">\n')
    buf.write(f"<style>{STYLE}</style>\n")
    if embed_defs:
        buf.write(defs(used_icon_keys(layout)) + "\n")
    buf.write(f'<rect class="sl-bg" width="{w}" height="{h}" fill="#FFFFFF"/>\n')

    for c in layout.containers:
        _container(buf, c)
    for lbl in layout.labels:
        _label(buf, lbl)
    for g in layout.groups:
        _group(buf, g)
    for t in layout.tiles:
        _tile(buf, t)

    buf.write('<g class="sl-edges">\n')
    for e in layout.edges:
        _edge(buf, e)
    buf.write("</g>\n")

    for g in layout.groups:
        for m in g.members:
            _node(buf, m, max_label=CELL_LABEL_CHARS)
    for n in layout.nodes:
        _node(buf, n, max_label=CELL_LABEL_CHARS)
    for n in layout.global_nodes + layout.external_nodes:
        _node(buf, n, max_label=22)

    buf.write("</svg>\n")
    return buf.getvalue()


# ── Primitives ──────────────────────────────────────────────────────

def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _fit(text: str, max_chars: int) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[:max(1, max_chars - 1)] + "…"


def _title(text: str) -> str:
    return f"<title>{_esc(text)}</title>" if text else ""


def _use(key: str, x: float, y: float, w: float, h: float) -> str:
    return f'<use href="#awsi-{_esc(icon_key(key))}" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}"/>'


def _container(buf: StringIO, c: LayoutContainer) -> None:
    s = CONTAINER_STYLES.get(c.kind, CONTAINER_STYLES["services"])
    r = c.rect
    dash = f' stroke-dasharray="{s["dash"]}"' if s["dash"] else ""
    buf.write(f'<g class="sl-c sl-c-{c.kind}">{_title(c.tooltip)}'
              f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" '
              f'fill="{s["fill"]}" stroke="{s["stroke"]}" stroke-width="{s["width"]}"{dash}/>')
    kind = c.kind
    if kind == "aws_cloud":
        buf.write(_use("aws_logo", r.x + 12, r.y + 9, 40, 27))
        buf.write(f'<text class="sl-title" x="{r.x + 62:.1f}" y="{r.y + 28:.1f}">{_esc(c.label)}</text>')
    elif kind in ("region", "vpc", "onprem"):
        size = 24 if kind == "vpc" else 22
        buf.write(_use(s["icon"], r.x + 8, r.y + 8, size, size))
        buf.write(f'<text class="sl-head" x="{r.x + 40:.1f}" y="{r.y + 24:.1f}" '
                  f'style="fill:{s["stroke"] if kind != "onprem" else INK}">{_esc(c.label)}</text>')
        if c.sublabel:
            buf.write(f'<text class="sl-sub" x="{r.x + 40:.1f}" y="{r.y + 37:.1f}">{_esc(c.sublabel)}</text>')
    elif kind == "az":
        buf.write(f'<text class="sl-head" x="{r.x + 10:.1f}" y="{r.y + 19:.1f}" '
                  f'style="fill:{s["stroke"]};font-weight:600;font-size:11.5px">{_esc(c.label)}</text>')
    elif kind == "services":
        buf.write(f'<text class="sl-head" x="{r.x + 12:.1f}" y="{r.y + 22:.1f}">{_esc(c.label)}</text>')
    elif kind.startswith("subnet_"):
        buf.write(_use(s["icon"], r.x, r.y, 26, 26))
        cidr_chars = len(c.sublabel)
        name_chars = max(8, int((r.w - 36 - cidr_chars * 6.2 - 12) / 6.4))
        buf.write(f'<text class="sl-head" x="{r.x + 32:.1f}" y="{r.y + 17:.1f}" '
                  f'style="font-size:11.5px;fill:{s["stroke"]}">{_esc(_fit(c.label, name_chars))}</text>')
        if c.sublabel:
            buf.write(f'<text class="sl-cidr" x="{r.right - 8:.1f}" y="{r.y + 17:.1f}">{_esc(c.sublabel)}</text>')
    buf.write("</g>\n")


def _label(buf: StringIO, lbl: LayoutLabel) -> None:
    tip = _title(lbl.tooltip)
    if lbl.kind == "row":
        buf.write(f'<text class="sl-row" x="{lbl.x:.1f}" y="{lbl.y:.1f}" '
                  f'transform="rotate(-90 {lbl.x:.1f} {lbl.y:.1f})">{_esc(lbl.text)}</text>\n')
    elif lbl.kind == "category":
        buf.write(f'<text class="sl-cat" x="{lbl.x:.1f}" y="{lbl.y:.1f}">{_esc(lbl.text)}</text>\n')
    else:
        buf.write(f'<text class="sl-note" x="{lbl.x:.1f}" y="{lbl.y:.1f}">{tip}{_esc(lbl.text)}</text>\n')


def _group(buf: StringIO, g: LayoutGroup) -> None:
    colour = CATEGORY_COLOURS.get(g.category, INK_SOFT)
    if g.outline:
        o = g.outline
        buf.write(f'<rect x="{o.x:.1f}" y="{o.y:.1f}" width="{o.w:.1f}" height="{o.h:.1f}" fill="none" '
                  f'stroke="{colour}" stroke-width="1.2" stroke-dasharray="4 3" opacity=".8"/>\n')
    r = g.rect
    dash = ' stroke-dasharray="7 4"' if g.dashed else ""
    name = f"{g.label} {g.sublabel}".lower()
    buf.write(f'<g class="sl-item sl-group" data-name="{_esc(name)}">'
              f'{_title(chr(10).join(x for x in (g.label, g.sublabel, g.tooltip) if x))}'
              f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="2" '
              f'fill="#FFFFFF" stroke="{colour}" stroke-width="1.4"{dash}/>')
    if not g.members:
        # One-line bar: icon, bold name, grey details.
        if g.icon:
            buf.write(_use(g.icon, r.x + 7, r.y + 6, 24, 24))
        chars = max(12, int((r.w - 50) / 6.3))
        label = _fit(g.label, max(8, chars // 2))
        detail = _fit(g.sublabel, max(0, chars - len(label) - 3))
        buf.write(f'<text class="sl-head" x="{r.x + 40:.1f}" y="{r.y + 22:.1f}">{_esc(label)}'
                  f'<tspan class="sl-sub" dx="10">{_esc(detail)}</tspan></text>')
        buf.write("</g>\n")
        return
    if g.icon:
        buf.write(_use(g.icon, r.x + 9, r.y + 9, 30, 30))
    chars = max(10, int((r.w - 56) / 7))
    buf.write(f'<text class="sl-head" x="{r.x + 48:.1f}" y="{r.y + 22:.1f}">{_esc(_fit(g.label, chars))}</text>')
    if g.sublabel:
        buf.write(f'<text class="sl-sub" x="{r.x + 48:.1f}" y="{r.y + 37:.1f}">'
                  f'{_esc(_fit(g.sublabel, int(chars * 1.25)))}</text>')
    buf.write("</g>\n")


def _tile(buf: StringIO, t: LayoutTile) -> None:
    r = t.rect
    names = ", ".join(n for n in t.names if n)
    buf.write(f'<g class="sl-item sl-tile" data-name="{_esc((t.service + " " + names).lower())}">'
              f'{_title(f"{t.service} × {t.count}" + (chr(10) + names if names else ""))}'
              f'<rect x="{r.x:.1f}" y="{r.y:.1f}" width="{r.w:.1f}" height="{r.h:.1f}" rx="3" '
              f'fill="#FFFFFF" stroke="#D5DBDB"/>')
    buf.write(_use(t.icon, r.x + 8, r.y + 9, 32, 32))
    buf.write(f'<text class="sl-head" x="{r.x + 48:.1f}" y="{r.y + 22:.1f}" style="font-size:11.5px">'
              f'{_esc(_fit(t.service, 17))}</text>')
    buf.write(f'<text class="sl-sub" x="{r.x + 48:.1f}" y="{r.y + 37:.1f}">{t.count:,}</text>')
    buf.write("</g>\n")


def _edge(buf: StringIO, e: LayoutEdge) -> None:
    if len(e.points) < 2:
        return
    s = EDGE_STYLES.get(e.kind, EDGE_STYLES["traffic"])
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in e.points)
    dash = f' stroke-dasharray="{s["dash"]}"' if s["dash"] else ""
    buf.write(f'<polyline class="sl-edge sl-edge-{e.kind}" points="{pts}" fill="none" stroke="{s["stroke"]}" '
              f'stroke-width="{s["width"]}" stroke-linejoin="round"{dash} marker-end="url(#sl-arrow-{e.kind})"/>')
    if e.label:
        (x1, y1), (x2, y2) = e.points[len(e.points) // 2 - 1], e.points[len(e.points) // 2]
        buf.write(f'<text class="sl-edge-label" x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" '
                  f'style="fill:{s["stroke"]}">{_esc(e.label)}</text>')
    buf.write("\n")


def _node(buf: StringIO, n: LayoutNode, max_label: int) -> None:
    r = n.rect
    if n.id.startswith("overflow:"):
        anchor_x = r.cx if r.w <= 60 else r.x + 4
        cls = "sl-small" if r.w <= 60 else "sl-sub"
        buf.write(f'<text class="{cls}" x="{anchor_x:.1f}" y="{r.y + 11:.1f}">{_title(n.tooltip)}{_esc(n.label)}</text>\n')
        return
    tip = n.tooltip or "\n".join(x for x in (n.label, n.sublabel) if x)
    buf.write(f'<g class="sl-item" data-name="{_esc((n.label + " " + n.sublabel + " " + n.tooltip).lower())}">'
              f'{_title(tip)}')
    buf.write(_use(n.resource_type, r.x, r.y, r.w, r.h))
    if n.id.startswith(("igw:", "vgw:")):
        # Gateways straddle the VPC border: label them on the outside.
        words = n.label.split(" ", 1)
        for i, line in enumerate(words):
            buf.write(f'<text class="sl-label" style="text-anchor:end" x="{r.x - 6:.1f}" '
                      f'y="{r.cy - 2 + i * 13 - (len(words) - 1) * 4:.1f}">{_esc(line)}</text>')
        buf.write("</g>\n")
        return
    if n.label:
        buf.write(f'<text class="sl-label" x="{r.cx:.1f}" y="{r.bottom + 13:.1f}">{_esc(_fit(n.label, max_label))}</text>')
    if n.sublabel:
        buf.write(f'<text class="sl-small" x="{r.cx:.1f}" y="{r.bottom + 25:.1f}">'
                  f'{_esc(_fit(n.sublabel, max_label + 2))}</text>')
    if n.attachments:
        mini = 14
        shown = n.attachments[:4]
        extra = len(n.attachments) - len(shown)
        total = len(shown) * (mini + 3) + (16 if extra else 0)
        x = r.cx - total / 2
        y = r.bottom + 30
        for key, label in shown:
            buf.write(f'<g>{_title(label)}{_use(key, x, y, mini, mini)}</g>')
            x += mini + 3
        if extra:
            buf.write(f'<text class="sl-small" x="{x + 7:.1f}" y="{y + 11:.1f}">+{extra}</text>')
    buf.write("</g>\n")
