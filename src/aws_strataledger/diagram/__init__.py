"""
AWS Architecture Diagram — deterministic, server-side SVG rendering.

Modules:
    model   — transforms scan inventory into a structured diagram model
    layout  — computes geometry (positions, sizes) for every element
    svg     — renders the laid-out model as an SVG string
    icons   — diagram styles and icon <symbol> builder
    aws_icons — official AWS Architecture Icons (generated, base64 PNG)
"""

from .model import build_diagram_model
from .layout import compute_layout
from .svg import render_svg, shared_defs_svg, used_icon_keys

__all__ = ["build_diagram_model", "compute_layout", "render_svg", "shared_defs_svg", "used_icon_keys"]
