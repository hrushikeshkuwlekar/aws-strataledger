# Changelog

All notable changes to **AWS StrataLedger** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.1] - 2026-10-02

### 🐛 Critical Bug Fixes
- **Dashboard Script Initialization (TDZ ReferenceError)**: Resolved JavaScript runtime crash (`ReferenceError: Cannot access 'cy' before initialization`) caused by hoisting Temporal Dead Zone when evaluating theme initialization before the Cytoscape graph variable declaration.
  - Hoisted `let cy = null;` to the global script scope header.
  - Restored full functionality to:
    - **Resource Category Metric Tiles**: Correctly rendered percentage bars and breakdown tags on the Overview dashboard.
    - **Inventory Explorer**: Restored instant multi-filter search, column sorting, pagination, and CSV data export.
    - **Interactive AWS Reference Architecture Topology**: Canvas now initializes immediately with official AWS SVG icons, hierarchical tiered layouts, and node inspector cards.
    - **Security & Compliance Tab**: Restored per-account posture checks (GuardDuty, Security Hub, CloudTrail multi-region, IAM MFA, public S3 buckets).
    - **Tab Navigation**: Restored seamless switching between Overview, Inventory, Topology, and Security views.

## [1.0.0] - 2026-10-02

### 🏛️ AWS Reference Architecture Topology & Official Icons
- **Official AWS Vector SVG Icon Library**: Embedded crisp vector SVG icons adhering to official AWS architecture specifications:
  - **Compute (`#FF9900`)**: Amazon EC2, Amazon EKS Cluster, AWS Lambda, EC2 Auto Scaling Groups.
  - **Networking & Content Delivery (`#8C4FFF`)**: AWS Transit Gateway, Internet Gateway, NAT Gateway, Elastic Load Balancing (ALB/NLB), VPC Endpoints, Site-to-Site VPN, AWS VPC.
  - **Database (`#2E73B8`)**: Amazon Aurora Clusters, Amazon RDS Instances, Amazon DynamoDB Tables.
  - **Storage (`#3F8624`)**: Amazon S3 Buckets, Amazon EFS File Systems.
  - **Security, Identity & Compliance (`#DD344C`)**: AWS WAF Web ACLs, AWS Network Firewall, AWS KMS Keys, AWS Secrets Manager.
  - **Management & Monitoring (`#E05243` / `#B00889`)**: Amazon CloudWatch Alarms, Amazon EventBridge Rules.
- **Deterministic 3-Tier Landscape Flow**: Replaced chaotic force-directed physics with an architectural tiered positioning engine:
  - **Ingress Tier (Top)**: Transit Gateway, Internet Gateway, and WAF Web ACLs.
  - **VPC Boundary Boxes**: Dashed `#8C4FFF` container boundaries labeled with VPC Name and CIDR block.
  - **Subnet Tier Boxes**: Color-coded container frames for Public Subnets (Teal `#10B981`), Private App Subnets (Blue `#3B82F6`), and Private Database Subnets (Purple `#A855F7`).
  - **AWS Regional & Managed Services Panel**: Dedicated cloud services panel for S3, DynamoDB, KMS, Secrets Manager, and CloudWatch alarms.
- **Orthogonal (Taxi) CAD-Style Flow Lines**: Implemented 90-degree orthogonal connectors (`curve-style: 'taxi'`) with color-coded relationships:
  - Sky Blue (`#38BDF8`): Ingress / HTTP Traffic Flow.
  - Emerald Green Dashed (`#10B981`): Outbound NAT Internet Egress.
  - AWS Purple Solid (`#8C4FFF`): Transit Gateway Attachment Backbone.
  - Royal Blue Solid (`#3B82F6`): Compute-to-Database SQL Access.
  - Amber Dashed (`#F97316`): VPC Peering Connections.
- **Eliminated Route Table Spiderwebs**: Route tables (`rtb-*`) are no longer rendered as noisy graph nodes with dozens of diagonal lines; route tables are analyzed programmatically to classify subnets into their true architectural tiers (`public`, `app`, `db`).
- **Interactive Architecture Toolbar**: Added dedicated controls for `🏛️ AWS Architecture` (Default), `📐 Hierarchical Flow`, `🌐 Force-Directed`, `🎯 Reset View`, `🔍 Fit`, `➕ Zoom In`, and `➖ Zoom Out`.

### 🌓 UI/UX & Dashboard Features
- **Dark Mode & Light Mode Toggle**: Added a theme switcher in the top navigation bar with persistent preference storage via `localStorage` and real-time canvas re-styling.
- **Interactive Resource Metric Tiles**: Replaced static category progress bars on the Overview tab with rich, interactive KPI tiles showing counts, percentage share, and sub-resource breakdowns.
- **Per-Account Summary Metrics**: Added dedicated columns to the Account Summary table for:
  - **EKS Clusters**: Total active Kubernetes clusters per account.
  - **Subnets**: Total VPC subnets provisioned.
  - **Active Firewalls**: Combined count of AWS Network Firewalls and AWS WAF Web ACLs.

### 🚀 Core Platform & 70+ Resource Collectors
- **AWS SSO / IAM Identity Center Native**: Reads `~/.aws/config` directly. Zero static IAM credentials needed.
- **70+ AWS Resource Types**: Full discovery across Compute, Networking, Storage, Databases, Identity, Security, and Monitoring.
- **Concurrent Engine**: Multi-threaded execution across accounts and regions with rate-limiting and pagination.
- **Single-File Self-Contained Deliverable**: Generates air-gapped HTML dashboard with zero external server dependencies.
