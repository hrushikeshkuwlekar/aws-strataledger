"""
AWS Architecture Icon symbol library.

Each icon is a dict with:
  - path: SVG path data (viewBox 0 0 24 24)
  - fill: default fill colour (AWS 2023 palette)
  - category: service category for group colouring

Icons are referenced as <symbol> definitions and instantiated with <use>.
"""

from __future__ import annotations

# AWS 2023 Architecture Icon palette
PALETTE = {
    "compute": "#ED7100",       # orange
    "container": "#ED7100",
    "database": "#C925D1",      # purple/magenta
    "storage": "#3F8624",       # green
    "networking": "#8C4FFF",    # purple
    "security": "#DD344C",      # red
    "identity": "#DD344C",
    "management": "#E7157B",    # pink
    "integration": "#E7157B",
    "analytics": "#8C4FFF",
    "global": "#232F3E",        # dark
    "generic": "#879196",       # grey
}

# Container / group styles
CONTAINER_STYLES = {
    "aws_cloud": {"stroke": "#232F3E", "stroke_width": 2, "fill": "none", "dash": ""},
    "region": {"stroke": "#00A4A6", "stroke_width": 1.5, "fill": "none", "dash": "8 4"},
    "vpc": {"stroke": "#7AA116", "stroke_width": 1.5, "fill": "none", "dash": ""},
    "az": {"stroke": "#879196", "stroke_width": 1, "fill": "none", "dash": "6 3"},
    "subnet_public": {"stroke": "#7AA116", "stroke_width": 1, "fill": "rgba(122,161,22,0.06)", "dash": ""},
    "subnet_private": {"stroke": "#00A4A6", "stroke_width": 1, "fill": "rgba(0,164,166,0.06)", "dash": ""},
    "subnet_firewall": {"stroke": "#DD344C", "stroke_width": 1, "fill": "rgba(221,52,76,0.06)", "dash": ""},
    "group_compute": {"stroke": "#ED7100", "stroke_width": 1, "fill": "none", "dash": "5 3"},
    "group_database": {"stroke": "#C925D1", "stroke_width": 1, "fill": "none", "dash": "5 3"},
    "group_networking": {"stroke": "#8C4FFF", "stroke_width": 1, "fill": "none", "dash": "5 3"},
    "group_storage": {"stroke": "#3F8624", "stroke_width": 1, "fill": "none", "dash": "5 3"},
    "group_security": {"stroke": "#DD344C", "stroke_width": 1, "fill": "none", "dash": "5 3"},
}

# Edge styles by kind/layer
EDGE_STYLES = {
    "traffic": {"stroke": "#38BDF8", "stroke_width": 1.5, "dash": ""},
    "data": {"stroke": "#C925D1", "stroke_width": 1.5, "dash": ""},
    "network": {"stroke": "#8C4FFF", "stroke_width": 1.5, "dash": ""},
    "endpoint": {"stroke": "#7AA116", "stroke_width": 1.2, "dash": ""},
    "egress": {"stroke": "#10B981", "stroke_width": 1, "dash": "6 3"},
    "replication": {"stroke": "#E7157B", "stroke_width": 1.5, "dash": "6 3"},
    "security": {"stroke": "#DD344C", "stroke_width": 1, "dash": "3 3"},
}

# Simplified AWS icons as SVG paths (viewBox 0 0 24 24)
# These are stylised representations, not official AWS assets.
ICONS: dict[str, dict] = {
    # ── Compute ──
    "ec2_instance": {
        "path": "M3 5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5zm4 2v2h2V7H7zm4 0v2h2V7h-2zm4 0v2h2V7h-2zM7 11v2h2v-2H7zm4 0v2h2v-2h-2zm4 0v2h2v-2h-2zM7 15v2h10v-2H7z",
        "fill": PALETTE["compute"],
        "category": "compute",
    },
    "ec2_spot": {
        "path": "M3 5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5zm9 1l-1.5 4H7l3.5 3-1.5 4.5L13 14l4 3.5-1.5-4.5 3.5-3h-3.5L12 6z",
        "fill": PALETTE["compute"],
        "category": "compute",
    },
    "lambda_function": {
        "path": "M3 20l4-8 2.5 5H14l-5-10 2-4h3l5 10 2 4H3zm6.5-3l-2-4-2 4h4z",
        "fill": PALETTE["compute"],
        "category": "compute",
    },
    "auto_scaling_group": {
        "path": "M4 4h7v7H4V4zm9 0h7v7h-7V4zm-9 9h7v7H4v-7zm9 0h7v7h-7v-7zm-5-6v3h3V7H8zm9 0v3h3V7h-3zM8 16v3h3v-3H8zm9 0v3h3v-3h-3z",
        "fill": PALETTE["compute"],
        "category": "compute",
    },
    "launch_template": {
        "path": "M4 3h16a1 1 0 011 1v16a1 1 0 01-1 1H4a1 1 0 01-1-1V4a1 1 0 011-1zm2 3v2h12V6H6zm0 4v2h8v-2H6zm0 4v2h10v-2H6z",
        "fill": PALETTE["compute"],
        "category": "compute",
    },
    # ── Containers ──
    "ecs_cluster": {
        "path": "M12 2L3 7v10l9 5 9-5V7l-9-5zm0 2.2L18.5 7.5 12 10.8 5.5 7.5 12 4.2zM5 9l7 3.5V19l-7-3.5V9zm14 0v6.5L12 19v-6.5L19 9z",
        "fill": PALETTE["container"],
        "category": "compute",
    },
    "ecs_service": {
        "path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08s5.97 1.09 6 3.08C16.71 17.72 14.5 19 12 19z",
        "fill": PALETTE["container"],
        "category": "compute",
    },
    "eks_cluster": {
        "path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 2c4.42 0 8 3.58 8 8s-3.58 8-8 8-8-3.58-8-8 3.58-8 8-8zm-1 3v4H7v2h4v4h2v-4h4v-2h-4V7h-2z",
        "fill": PALETTE["container"],
        "category": "compute",
    },
    "ecr_repository": {
        "path": "M4 3h16a1 1 0 011 1v16a1 1 0 01-1 1H4a1 1 0 01-1-1V4a1 1 0 011-1zm8 3a6 6 0 100 12 6 6 0 000-12zm0 2a4 4 0 110 8 4 4 0 010-8zm0 2a2 2 0 100 4 2 2 0 000-4z",
        "fill": PALETTE["container"],
        "category": "compute",
    },
    # ── Networking ──
    "vpc": {
        "path": "M12 2l10 5.5v9L12 22 2 16.5v-9L12 2zm0 2.2L4 8.6v7.8l8 4.4 8-4.4V8.6L12 4.2z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "subnet": {
        "path": "M3 4h18v16H3V4zm2 2v12h14V6H5zm2 2h4v3H7V8zm6 0h4v3h-4V8zm-6 5h4v3H7v-3zm6 0h4v3h-4v-3z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "igw": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 2a8 8 0 100 16 8 8 0 000-16zm-1 3h2v4h3l-4 5-4-5h3V7z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "nat_gateway": {
        "path": "M12 2l8 4.5v11L12 22l-8-4.5v-11L12 2zm0 2.5L6 7.5v9l6 3 6-3v-9l-6-3zM11 9h2v3h2.5L12 16l-3.5-4H11V9z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "load_balancer_v2": {
        "path": "M4 4h16v16H4V4zm8 2a6 6 0 100 12 6 6 0 000-12zm-3 5h6v2H9v-2z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "load_balancer_classic": {
        "path": "M4 4h16v16H4V4zm8 2a6 6 0 100 12 6 6 0 000-12zm-3 5h6v2H9v-2z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "target_group": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4a6 6 0 100 12 6 6 0 000-12zm0 2a4 4 0 110 8 4 4 0 010-8zm0 2a2 2 0 100 4 2 2 0 000-4z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "api_gateway_rest": {
        "path": "M4 4l4 8-4 8h3l4-8-4-8H4zm9 0l4 8-4 8h3l4-8-4-8h-3z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "api_gateway_http": {
        "path": "M4 4l4 8-4 8h3l4-8-4-8H4zm9 0l4 8-4 8h3l4-8-4-8h-3z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "cloudfront": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 2a8 8 0 100 16 8 8 0 000-16zm0 2c3.31 0 6 2.69 6 6s-2.69 6-6 6c-1.1 0-2-.9-2-2s.9-2 2-2 2-.9 2-2-.9-2-2-2-2 .9-2 2H8c0-3.31 2.69-6 6-6z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "route53": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 2a8 8 0 100 16 8 8 0 000-16zM8 7h3v2H8V7zm5 0h3v2h-3V7zM8 11h8v2H8v-2zm0 4h3v2H8v-2zm5 0h3v2h-3v-2z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "transit_gateway": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4a6 6 0 100 12 6 6 0 000-12zm-1 2h2v3h3v2h-3v3h-2v-3H8v-2h3V8z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "vpc_endpoint": {
        "path": "M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2zm7 3l-5 6h3v6h4v-6h3l-5-6z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "vpn_gateway": {
        "path": "M12 2L3 7v10l9 5 9-5V7l-9-5zm0 4l5 3v6l-5 3-5-3V9l5-3zm-2 4v4h4v-4h-4z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "direct_connect": {
        "path": "M2 12h4m12 0h4M8 8h8v8H8V8zm2 2v4h4v-4h-4z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    "network_firewall": {
        "path": "M3 3h18v18H3V3zm2 2v14h14V5H5zm4 3h6l-3 4 3 4H9l3-4-3-4z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    "waf_web_acl": {
        "path": "M12 2L3 6v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V6l-9-4zm0 2.18l7 3.12v5.7c0 4.47-3.07 8.67-7 9.82V4.18z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    # ── Storage ──
    "s3_bucket": {
        "path": "M12 2C7 2 3 3.5 3 5.5v13C3 20.5 7 22 12 22s9-1.5 9-3.5v-13C21 3.5 17 2 12 2zm0 2c4.42 0 7 1.12 7 1.5S16.42 7 12 7 5 5.88 5 5.5 7.58 4 12 4zM5 8c1.38.83 4.14 1.5 7 1.5s5.62-.67 7-1.5v3c0 .38-2.58 1.5-7 1.5S5 11.38 5 11V8zm0 5.5c1.38.83 4.14 1.5 7 1.5s5.62-.67 7-1.5V17c0 .38-2.58 1.5-7 1.5S5 17.38 5 17v-3.5z",
        "fill": PALETTE["storage"],
        "category": "storage",
    },
    # ── Database ──
    "rds_instance": {
        "path": "M12 2C7.58 2 4 3.34 4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5c0-1.66-3.58-3-8-3zm0 2c3.87 0 6 1.12 6 1s-2.13 1-6 1-6-.12-6-1 2.13-1 6-1zM6 7.54C7.38 8.23 9.57 8.7 12 8.7s4.62-.47 6-1.16V11c0 .88-2.13 2-6 2s-6-1.12-6-2V7.54zm0 6C7.38 14.23 9.57 14.7 12 14.7s4.62-.47 6-1.16V17c0 .88-2.13 2-6 2s-6-1.12-6-2v-3.46z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "rds_cluster": {
        "path": "M12 2C7.58 2 4 3.34 4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5c0-1.66-3.58-3-8-3zm0 2c3.87 0 6 1.12 6 1s-2.13 1-6 1-6-.12-6-1 2.13-1 6-1zM6 7.54C7.38 8.23 9.57 8.7 12 8.7s4.62-.47 6-1.16V11c0 .88-2.13 2-6 2s-6-1.12-6-2V7.54zm0 6C7.38 14.23 9.57 14.7 12 14.7s4.62-.47 6-1.16V17c0 .88-2.13 2-6 2s-6-1.12-6-2v-3.46z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "dynamodb_table": {
        "path": "M4 4h16v4H4V4zm0 6h6v10H4V10zm8 0h8v10h-8V10zM6 6v0m4 0v0m4 0v0m4 0v0M6 13h2v2H6v-2zm8 0h4v2h-4v-2zM6 17h2v2H6v-2zm8 0h4v2h-4v-2z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "elasticache_cluster": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4a6 6 0 100 12 6 6 0 000-12zm-2 3l5 3-5 3V9z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "elasticache_replication_group": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4a6 6 0 100 12 6 6 0 000-12zm-2 3l5 3-5 3V9z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "opensearch_domain": {
        "path": "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "redshift_cluster": {
        "path": "M4 4h16v16H4V4zm2 2v12h12V6H6zm3 2h6v2H9V8zm0 4h6v2H9v-2zm0 4h4v2H9v-2z",
        "fill": PALETTE["database"],
        "category": "database",
    },
    "efs_filesystem": {
        "path": "M3 5v14h18V5H3zm2 2h14v10H5V7zm2 2v2h10V9H7zm0 4v2h6v-2H7z",
        "fill": PALETTE["storage"],
        "category": "storage",
    },
    # ── Security / Identity ──
    "kms_key": {
        "path": "M12 2a4 4 0 00-4 4c0 1.86 1.28 3.41 3 3.86V22h2V9.86c1.72-.45 3-2 3-3.86a4 4 0 00-4-4zm0 2a2 2 0 110 4 2 2 0 010-4z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    "secret": {
        "path": "M18 8h-1V6A5 5 0 007 6v2H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V10a2 2 0 00-2-2zM9 6a3 3 0 016 0v2H9V6zm3 10a2 2 0 110-4 2 2 0 010 4z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    "iam_user": {
        "path": "M12 4a4 4 0 100 8 4 4 0 000-8zm0 10c-4.42 0-8 1.79-8 4v2h16v-2c0-2.21-3.58-4-8-4z",
        "fill": PALETTE["identity"],
        "category": "identity",
    },
    "shield": {
        "path": "M12 2L3 6v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V6l-9-4z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    "guardduty": {
        "path": "M12 2L3 6v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V6l-9-4zm-1 6h2v5h-2V8zm0 7h2v2h-2v-2z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    # ── Integration / Management ──
    "sqs_queue": {
        "path": "M3 4h18v16H3V4zm2 2v12h14V6H5zm3 3h8v2H8V9zm0 4h6v2H8v-2z",
        "fill": PALETTE["integration"],
        "category": "integration",
    },
    "sns_topic": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4l-6 4 6 4 6-4-6-4zm-6 6v2l6 4 6-4v-2l-6 4-6-4z",
        "fill": PALETTE["integration"],
        "category": "integration",
    },
    "cloudwatch": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm-1 5h2v5.41l3.3 3.3-1.42 1.41L11 13.83V7z",
        "fill": PALETTE["management"],
        "category": "management",
    },
    "eventbridge": {
        "path": "M12 2a10 10 0 110 20 10 10 0 010-20zm0 4a6 6 0 100 12 6 6 0 000-12zm0 2a4 4 0 110 8 4 4 0 010-8z",
        "fill": PALETTE["integration"],
        "category": "integration",
    },
    # ── Global / edge ──
    "users": {
        "path": "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
        "fill": PALETTE["generic"],
        "category": "global",
    },
    "internet": {
        "path": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z",
        "fill": PALETTE["generic"],
        "category": "global",
    },
    # ── Additional Networking ──
    "customer_gateway": {
        "path": "M12 2L3 7v10l9 5 9-5V7l-9-5zm0 4l5 3v6l-5 3-5-3V9l5-3zm-1 4v2h2v-2h-2z",
        "fill": PALETTE["networking"],
        "category": "networking",
    },
    # ── Additional Compute ──
    "eks_nodegroup": {
        "path": "M4 4h7v7H4V4zm9 0h7v7h-7V4zm-9 9h7v7H4v-7zm9 0h7v7h-7v-7zM6 6v3h3V6H6zm9 0v3h3V6h-3zM6 15v3h3v-3H6zm9 0v3h3v-3h-3z",
        "fill": PALETTE["container"],
        "category": "compute",
    },
    # ── Additional Storage ──
    "ebs_volume": {
        "path": "M12 2C7.58 2 4 3.34 4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5c0-1.66-3.58-3-8-3zm6 17c0 .55-2.69 1-6 1s-6-.45-6-1v-3.07c1.38.63 3.52 1.07 6 1.07s4.62-.44 6-1.07V19zm0-6c0 .55-2.69 1-6 1s-6-.45-6-1v-3.07c1.38.63 3.52 1.07 6 1.07s4.62-.44 6-1.07V13zm0-6c0 .55-2.69 1-6 1s-6-.45-6-1V5c0-.55 2.69-1 6-1s6 .45 6 1v2z",
        "fill": PALETTE["storage"],
        "category": "storage",
    },
    "backup": {
        "path": "M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14l-5-5h3V8h4v4h3l-5 5z",
        "fill": PALETTE["storage"],
        "category": "storage",
    },
    # ── Additional Security / Identity ──
    "acm": {
        "path": "M12 2L3 6v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V6l-9-4zm0 4l5 2.5v5c0 3.33-2.13 6.44-5 7.41V6z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    "cloudhsm": {
        "path": "M18 8h-1V6A5 5 0 007 6v2H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V10a2 2 0 00-2-2zM9 6a3 3 0 016 0v2H9V6zm3 12a3 3 0 110-6 3 3 0 010 6z",
        "fill": PALETTE["security"],
        "category": "security",
    },
    # ── Generic ──
    "generic": {
        "path": "M4 4h16v16H4V4zm2 2v12h12V6H6z",
        "fill": PALETTE["generic"],
        "category": "generic",
    },
}


def get_icon(resource_type: str) -> dict:
    """Return icon data for a resource type, falling back to generic."""
    return ICONS.get(resource_type, ICONS["generic"])


def get_category_colour(category: str) -> str:
    """Return the palette colour for a service category."""
    return PALETTE.get(category, PALETTE["generic"])
