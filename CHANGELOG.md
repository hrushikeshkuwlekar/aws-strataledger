# Changelog

All notable changes to **AWS StrataLedger** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-10-03

### 🏗️ Server-Side Architecture Diagrams (Replaces Cytoscape)
- **Pure SVG Diagram Engine**: Replaced client-side Cytoscape.js with a deterministic server-side SVG renderer (`diagram/` package). Diagrams are generated at report time, not in the browser.
  - `model.py` — transforms scan inventory into a structured diagram model with containers (Cloud → Region → VPC → AZ → Subnet), nodes, groups, edges, and tiles.
  - `layout.py` — deterministic geometry engine computing positions following AWS architecture conventions (left-to-right request flow, top-to-bottom stacking).
  - `svg.py` — renders LayoutResult as self-contained SVG with dark/light theme support via CSS custom properties.
  - `icons.py` — AWS 2023 palette with simplified SVG icon paths for all resource types.
- **Route-Table-Based Subnet Tier Classification**: Subnets classified by their effective route table destination (IGW → public, NAT/TGW → app, local-only → data), with tag override via `strataledger:tier`.
- **Removed Cytoscape.js & Topology Tab**: Eliminated ~800 lines of Cytoscape JS code and the Topology tab. The Architecture tab now shows the server-side SVG diagrams.

### 🔒 Security Hardening
- **Jinja2 Autoescape ON**: All user-controlled strings are HTML-escaped by default.
- **Script-Safe JSON**: `_script_safe_json()` escapes `</script>` and `<!--` inside embedded JSON to prevent script injection.
- **XSS-Safe innerHTML**: Client-side `esc()` helper used for all dynamic HTML interpolation.
- **Air-Gapped Reports**: Removed all CDN URLs (Cytoscape, Google Fonts). System font stack, inline SVG.

### ⚡ Scan Engine Improvements
- **Thread-Safe ClientFactory**: `ClientFactory` serializes boto3 client creation behind a lock; clients are shared across worker threads.
- **Adaptive Retry**: botocore adaptive retry mode (`max_attempts=10`) handles throttling automatically.
- **Structured Issue Recording**: Every collector failure is classified (error/denied/unavailable) and surfaced in the Coverage tab.
- **Parallel Region Scanning**: Regions scanned concurrently via `ThreadPoolExecutor`.
- **Account De-duplication**: Multiple profiles pointing to the same account are detected and skipped.
- **CloudTrail De-duplication**: Multi-region shadow trails removed by ARN.
- **Dynamic Region Discovery**: `--regions all` now queries `ec2:DescribeRegions` for the account's enabled regions.
- **Service Alias Mapping**: `--services ec2,s3,iam` correctly resolves to collector categories.

### 📊 Report Enhancements
- **Status Filter**: Inventory tab now has a Status dropdown filter.
- **Enhanced CSV Export**: Exported CSV includes ARN, Account ID columns.
- **Custom Report Title**: `--title` flag on `scan` and `report` commands sets the HTML `<title>`.
- **Coverage Tab**: Grouped issue display by collector and region with level indicators.
- **SVG Diagram Bug Fix**: SVG output is now wrapped in `Markup` so Jinja2 autoescape doesn't entity-escape diagram tags.

### 🧪 Quality
- **pytest Test Suite**: 74 unit tests covering diagram model, layout, report generation, XSS prevention, collector helpers, scanner utilities, and CLI.
- **GitHub Actions CI**: Matrix testing (Python 3.9/3.11/3.12) with ruff lint and pytest on push/PR.

### 🔧 Collectors
- All collectors rewritten with ClientFactory, pagination, and issue recording.
- S3 public access: account-level + bucket-level Block Public Access + policy + ACL.
- KMS key rotation status via separate API call.
- ECS, ElastiCache, OpenSearch, Redshift, ECR replication, DynamoDB replicas.
- ELBv2 with target health, Classic ELB, API Gateway REST/HTTP, Network Firewall, WAF regional.

## [1.0.3] - 2026-10-02

### 🔇 Quiet Discovery by Default & Verbose-Only Logging Control
- **Silent Discovery Output**: Completely eliminated console line spam during active AWS discovery.
  - Enabled global `logging.disable(logging.CRITICAL)` by default, completely silencing client errors (`AccessDeniedException`, `UnauthorizedOperation`, unsupported regional endpoints) and framework logging from `botocore`, `boto3`, `urllib3`, and `requests`.
  - Replaced `logger.warning` / `logger.error` in base collectors and scanner with `logger.debug`, ensuring unexpected or expected service errors are stored in collector metadata and never break the Rich progress bar.
- **Dedicated `--verbose` / `-v` Flag**:
  - Full discovery logs, debug messages, and detailed timestamps (`%(asctime)s [%(levelname)s] ...`) are only printed to stderr when `--verbose` (or `-v`) is explicitly passed to `aws-strataledger` or `aws-strataledger scan`.
- **Clean Profile Validation Summary**:
  - Consolidated multi-profile validation into a single concise line (e.g., `✔ Validated 4 profile(s): dev, staging, prod, sand`) when running without `--verbose`, avoiding terminal line scrolling.
  - Preserved critical SSO token expiration warnings (`aws sso login --profile ...`) so users are immediately alerted if authentication is required.
- **Dynamic Package Versioning**: Bound CLI banners and scan metadata outputs directly to `aws_strataledger.__version__`.

## [1.0.2] - 2026-10-02

### 🛡️ AWS Network Firewall Detection Algorithm Verification & Hardening
- **API Pagination on Discovery**: Enabled `_safe_paginate` on `nfw.list_firewalls()` across `Firewalls` to guarantee all firewalls are discovered across all pages without truncating at default page limits.
- **Robust Detail Retrieval & IAM Fallback**:
  - Replaced parameter-binding lambda in `describe_firewall` with direct keyword arguments targeting `FirewallArn` (exact match) and `FirewallName`.
  - Added graceful fallback: if `DescribeFirewall` fails (e.g. IAM permission boundary restricting describe actions), the firewall metadata discovered via `ListFirewalls` is retained as an active resource rather than being silently dropped.
- **Accurate Lifecycle Status Decoding**: Directly inspects `FirewallStatus.Status` (`READY`, `PROVISIONING`, `DELETING`) instead of false default assumptions.
- **VPC Endpoint & AZ Mapping**: Extracted all Availability Zone VPC Endpoint IDs (`vpce-*`) and attachments generated by AWS Network Firewall.
- **Transit Gateway Attachment Support**: Added discovery of `TransitGatewayId` for centralized inspection firewalls attached to AWS Transit Gateways.
- **VPC Route Table Endpoint Target Resolution**: Added `VpcEndpointId` (as well as `CarrierGatewayId`, `LocalGatewayId`, and `CoreNetworkArn`) to the route table collector target parser, preventing routes pointed to Network Firewall endpoints from being misclassified as local routes.
- **Architectural Placement & Flow Lines**:
  - In the topology engine, automatically maps Network Firewalls into their dedicated `[Firewall Subnet]` containers.
  - Generates bidirectional inspection edges (`Inspects VPC`, `Ingress Inspection`, `TGW Inspection`).
  - Resolved compound parent distortion in Cytoscape layout.
- **Per-Account Summary Metrics Clarity**:
  - Updated the Account Summary table header to `Firewalls (NFW / WAF)` with separate indicators (e.g. `1 NFW / 2 WAF`, or `1 WAF`), preventing Web Application Firewalls (WAF) from being misread as AWS Network Firewalls.

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
