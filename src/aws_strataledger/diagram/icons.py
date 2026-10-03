"""
Icon symbols and AWS diagram styles.

Service/resource icons are the official AWS Architecture Icons embedded in
``aws_icons.ICON_PNG``. A few concepts AWS publishes no icon for (target
group, region flag, generic) use small vector glyphs.

Colours follow the AWS Architecture Icons group guidelines.
"""

from __future__ import annotations

import base64
import struct

from .aws_icons import ICON_PNG

INK = "#232F3E"        # AWS squid ink — primary text
INK_SOFT = "#545B64"   # secondary text
CANVAS = "#FFFFFF"

# kind → (stroke, fill, dash, header icon)
CONTAINER_STYLES: dict[str, dict] = {
    "aws_cloud": {"stroke": INK, "fill": "none", "dash": "", "icon": "aws_logo", "width": 1.5},
    "region": {"stroke": "#00A4A6", "fill": "none", "dash": "7 4", "icon": "region_flag", "width": 1.2},
    "vpc": {"stroke": "#8C4FFF", "fill": "none", "dash": "", "icon": "vpc", "width": 1.5},
    "az": {"stroke": "#147EBA", "fill": "none", "dash": "6 4", "icon": "", "width": 1},
    "subnet_public": {"stroke": "#7AA116", "fill": "#F2F6E8", "dash": "", "icon": "public_subnet", "width": 1},
    "subnet_private": {"stroke": "#00A4A6", "fill": "#E6F6F7", "dash": "", "icon": "private_subnet", "width": 1},
    "subnet_data": {"stroke": "#00A4A6", "fill": "#E6F6F7", "dash": "", "icon": "private_subnet", "width": 1},
    "subnet_firewall": {"stroke": "#DD344C", "fill": "#FBEDEF", "dash": "", "icon": "private_subnet", "width": 1},
    "onprem": {"stroke": "#7D8998", "fill": "none", "dash": "", "icon": "corporate_dc", "width": 1.2},
    "services": {"stroke": "#D5DBDB", "fill": "#FAFAFA", "dash": "", "icon": "", "width": 1},
}

CATEGORY_COLOURS = {
    "compute": "#ED7100",
    "container": "#ED7100",
    "database": "#C925D1",
    "networking": "#8C4FFF",
    "storage": "#7AA116",
    "analytics": "#8C4FFF",
    "integration": "#E7157B",
    "security": "#DD344C",
}

EDGE_STYLES = {
    "traffic": {"stroke": INK, "width": 1.4, "dash": ""},
    "network": {"stroke": "#8C4FFF", "width": 1.4, "dash": ""},
    "security": {"stroke": "#DD344C", "width": 1.2, "dash": "5 3"},
    "endpoint": {"stroke": "#7AA116", "width": 1.2, "dash": "5 3"},
    "replication": {"stroke": "#E7157B", "width": 1.3, "dash": "6 3"},
}

# Vector glyphs (viewBox 0 0 24 24) for concepts without an official icon.
GLYPHS: dict[str, tuple[str, str]] = {
    "target_group": (
        "M12 3a9 9 0 110 18 9 9 0 010-18zm0 2a7 7 0 100 14 7 7 0 000-14zm0 3a4 4 0 110 8 4 4 0 010-8zm0 2a2 2 0 100 4 2 2 0 000-4z",
        "#8C4FFF"),
    "region_flag": ("M5 3h2v18H5V3zm3 1h11l-2.5 4L19 12H8V4z", "#00A4A6"),
    "generic": ("M4 4h16v16H4V4zm2 2v12h12V6H6z", "#7D8998"),
}


def has_icon(key: str) -> bool:
    return key in ICON_PNG or key in GLYPHS


def icon_key(key: str) -> str:
    return key if has_icon(key) else "generic"


def _png_size(b64: str) -> tuple[int, int]:
    head = base64.b64decode(b64[:44])
    return struct.unpack(">II", head[16:24])


def symbol(key: str) -> str:
    """SVG <symbol> for one icon key, referenced as #awsi-<key>."""
    key = icon_key(key)
    if key in ICON_PNG:
        w, h = _png_size(ICON_PNG[key])
        return (f'<symbol id="awsi-{key}" viewBox="0 0 {w} {h}">'
                f'<image width="{w}" height="{h}" href="data:image/png;base64,{ICON_PNG[key]}"/></symbol>')
    path, fill = GLYPHS[key]
    return f'<symbol id="awsi-{key}" viewBox="0 0 24 24"><path d="{path}" fill="{fill}"/></symbol>'
