"""
AWS Architecture Diagram — deterministic, server-side SVG rendering.

Modules:
    model   — transforms scan inventory into a structured diagram model
    layout  — computes geometry (positions, sizes) for every element
    svg     — renders the laid-out model as an SVG string
    icons   — AWS architecture icon symbol library (inline SVG paths)
"""

from .model import build_diagram_model
from .layout import compute_layout
from .svg import render_svg

__all__ = ["build_diagram_model", "compute_layout", "render_svg"]
